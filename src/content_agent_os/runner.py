from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .approval_gate import (
    APPROVAL_NOT_REQUIRED,
    APPROVAL_PENDING,
    latest_repair_for_step,
    normalize_repair_log,
    repair_is_approved,
    repair_needs_human_approval,
)
from .failure import classify_failure, failure_message
from .state_store import WorkflowStateStore
from .agents import AgentExecutionContext, AgentResult, run_agent, supports_agent
from .retry_policy import build_retry_event, build_retry_policy_config, decide_retry
from .stale_detector import assess_task_health
from .supervision import write_supervision_outputs
from .workflow import Workflow, WorkflowStep, load_workflow, workflow_from_dict


DEFAULT_PLATFORMS = ["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"]
VIDEO_PLATFORMS = {"douyin", "shipinhao", "bilibili"}
DEFAULT_OUTPUT_ROOT = Path("outputs/runs")


def run_workflow(
    workflow_path: Path,
    topic: str,
    platforms: list[str] | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    input_attachments: list[dict[str, Any]] | None = None,
) -> Path:
    workflow = load_workflow(workflow_path)
    selected_platforms = platforms or DEFAULT_PLATFORMS
    run_id = "run_" + _utc_now_compact()
    run_dir = output_root / run_id
    (run_dir / "logs/tasks").mkdir(parents=True, exist_ok=True)
    store = WorkflowStateStore(_state_db_path(output_root))

    context = RunContext(
        workflow=workflow,
        workflow_path=workflow_path,
        run_id=run_id,
        run_dir=run_dir,
        topic=topic,
        platforms=selected_platforms,
        input_attachments=input_attachments or [],
    )
    result = WorkflowExecutor(context, store).execute()
    return run_dir


def resume_workflow(
    run_id: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    store = WorkflowStateStore(_state_db_path(output_root))
    persisted = store.load_workflow_run(run_id)
    if persisted is None:
        raise FileNotFoundError(f"Workflow run not found in state store: {run_id}")
    if persisted["status"] == "DONE":
        return Path(persisted["run_dir"])

    workflow = workflow_from_dict(persisted["workflow"])
    run_dir = Path(persisted["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs/tasks").mkdir(parents=True, exist_ok=True)
    context = RunContext(
        workflow=workflow,
        workflow_path=Path(persisted["workflow_path"]),
        run_id=run_id,
        run_dir=run_dir,
        topic=str(persisted["topic"]),
        platforms=list(persisted["platforms"]),
        created_at=str(persisted["created_at"]),
        input_attachments=list(persisted.get("input_attachments") or []),
    )
    executor = WorkflowExecutor(context, store, resume_state=persisted)
    executor.resume()
    return run_dir


class RunContext:
    def __init__(
        self,
        workflow: Workflow,
        workflow_path: Path,
        run_id: str,
        run_dir: Path,
        topic: str,
        platforms: list[str],
        created_at: str | None = None,
        input_attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        self.workflow = workflow
        self.workflow_path = workflow_path
        self.run_id = run_id
        self.run_dir = run_dir
        self.topic = topic
        self.platforms = platforms
        self.created_at = created_at or _utc_now_iso()
        self.input_attachments = list(input_attachments or [])


class WorkflowExecutor:
    def __init__(
        self,
        context: RunContext,
        store: WorkflowStateStore,
        resume_state: dict[str, Any] | None = None,
    ) -> None:
        self.context = context
        self.store = store
        self.steps_by_id = {step.id: step for step in self.context.workflow.steps}
        self.task_specs = [self._task_spec(step) for step in self.context.workflow.steps]
        self.task_runs_by_step: dict[str, dict[str, Any]] = {}
        self.artifacts_by_path: dict[str, dict[str, Any]] = {}
        self.final_artifact_paths: list[str] = []
        self.completed: set[str] = set()
        self.skipped: set[str] = set()
        self.failures: list[dict[str, Any]] = []
        self.repair_log: list[dict[str, Any]] = normalize_repair_log(list((resume_state or {}).get("repair_log", [])))
        self.retry_events: list[dict[str, Any]] = list((resume_state or {}).get("retry_events", []))
        self.retry_policy_config = build_retry_policy_config()
        self.pending_retry_decisions: dict[str, dict[str, Any]] = {}
        self.retry_blocked_steps: set[str] = set()
        self.repair_blocked_steps: set[str] = set()
        self.workflow_status = str((resume_state or {}).get("status", "PENDING"))
        self.current_step_id: str | None = None
        self.current_failure: dict[str, Any] | None = None

        if resume_state is not None:
            self._load_resume_state(resume_state)

        self._sync_state()

    def resume(self) -> dict[str, Any]:
        return self.execute()

    def execute(self) -> dict[str, Any]:
        blocked_steps = self.retry_blocked_steps | self.repair_blocked_steps
        if blocked_steps:
            blocked = ", ".join(sorted(blocked_steps))
            if any(self._pending_manual_repair_for_step(step_id) for step_id in blocked_steps):
                self.workflow_status = "NEEDS_HUMAN"
                message = f"Human approval is required before replaying repair plan(s) for step(s): {blocked}"
            else:
                self.workflow_status = "FAILED"
                message = f"Automatic replay is blocked pending repair for step(s): {blocked}"
            self._sync_state()
            raise RuntimeError(message)

        if self.workflow_status != "DONE":
            self.workflow_status = "RUNNING"
            self._sync_state()

        try:
            for step in self.context.workflow.steps:
                if self._step_is_complete(step):
                    continue

                if self._should_skip(step):
                    self._record_skipped(step)
                    continue

                if not self._deps_satisfied(step):
                    blocked = {step.id: step.depends_on}
                    raise RuntimeError(f"Workflow is blocked by unsatisfied dependencies: {blocked}")

                self._run_step(step)

            if not self._all_steps_complete():
                raise RuntimeError("Workflow finished without completing all required steps")

            self.workflow_status = "VALIDATING"
            self.current_step_id = None
            self._sync_state()
            self._write_final_outputs()
            self.workflow_status = "DONE"
            self.current_failure = None
            self.failures = []
            self._sync_state()
            return self._workflow_run()
        except Exception as exc:
            if self.workflow_status == "NEEDS_HUMAN" and self.current_step_id and self._pending_manual_repair_for_step(self.current_step_id):
                self._sync_state()
                raise
            if self.workflow_status != "FAILED":
                self._record_workflow_failure(
                    exc,
                    self.current_step_id or self._first_incomplete_step_id(),
                )
            self._sync_state()
            raise

    def _load_resume_state(self, resume_state: dict[str, Any]) -> None:
        latest_attempts = self.store.load_latest_task_attempts(self.context.run_id)
        all_attempts = self.store.load_task_attempts(self.context.run_id)
        for step in self.context.workflow.steps:
            attempt = latest_attempts.get(step.id)
            if attempt is None:
                continue

            task_run = self._task_run_from_attempt(step, attempt)
            if task_run["status"] == "RUNNING":
                task_run = self._convert_running_attempt_to_failed(step, attempt, resume_state)

            if task_run["status"] == "PASSED":
                self.task_runs_by_step[step.id] = task_run
                self.completed.add(step.id)
                self.current_step_id = None
                for artifact_path in task_run.get("artifact_paths", []):
                    self._upsert_artifact(self._artifact_record(step, artifact_path, task_run))
                continue

            if task_run["status"] == "SKIPPED":
                self.task_runs_by_step[step.id] = task_run
                self.skipped.add(step.id)
                continue

            if task_run["status"] == "FAILED":
                current_failure = {
                    "task_id": task_run["task_id"],
                    "step_id": step.id,
                    "agent": step.agent,
                    "failure_type": task_run.get("failure_category") or "ENV_ERROR",
                    "message": task_run.get("failure_message") or "Previous attempt failed before resume.",
                    "recoverable": bool(task_run.get("recoverable")),
                    "recovery_state": task_run.get("recovery_state"),
                    "stale_reason": task_run.get("stale_reason"),
                }
                prior_attempts = [item for item in all_attempts if item.get("step_id") == step.id]
                retry_decision = decide_retry(
                    task_run=task_run,
                    prior_attempts=prior_attempts,
                    config=self.retry_policy_config,
                )
                if retry_decision.get("should_retry"):
                    self.pending_retry_decisions[step.id] = retry_decision
                    self.retry_events.append(
                        build_retry_event(
                            task_run=task_run,
                            decision=retry_decision,
                            attempt=None,
                            stage="scheduled",
                        )
                    )
                    self.current_step_id = step.id
                    self.current_failure = None
                    self.failures = []
                    continue

                self.retry_events.append(
                    build_retry_event(
                        task_run=task_run,
                        decision=retry_decision,
                        attempt=attempt.get("attempt"),
                        stage="blocked",
                    )
                )
                task_run["retry_decision"] = retry_decision

                self.task_runs_by_step[step.id] = task_run
                self.current_step_id = step.id
                self.current_failure = current_failure | {"retry_decision": retry_decision}
                self.failures = [self.current_failure]
                repair_entry = self._record_repair_plan(
                    step,
                    self.current_failure,
                    retry_decision=retry_decision,
                    source="retry_policy_blocked",
                )
                if repair_needs_human_approval(repair_entry):
                    if task_run.get("recoverable"):
                        self.retry_blocked_steps.add(step.id)
                    self.repair_blocked_steps.add(step.id)
                    self.workflow_status = "NEEDS_HUMAN"
                    continue
                if repair_entry and repair_is_approved(repair_entry):
                    self.retry_blocked_steps.discard(step.id)
                    self.repair_blocked_steps.discard(step.id)
                    self.current_failure = None
                    self.failures = []
                    continue
                if task_run.get("recoverable"):
                    self.retry_blocked_steps.add(step.id)
                self.repair_blocked_steps.add(step.id)
                self.workflow_status = "FAILED"

        if resume_state.get("status") == "DONE":
            self.workflow_status = "DONE"

    def _should_skip(self, step: WorkflowStep) -> bool:
        return self._skip_reason(step) is not None

    def _skip_reason(self, step: WorkflowStep) -> str | None:
        if step.platform and step.platform not in self.context.platforms:
            return f"platform {step.platform} not selected"
        required = step.requires_any_platform or []
        if required and not any(platform in self.context.platforms for platform in required):
            return f"requires one of {', '.join(required)}"
        return None

    def _deps_satisfied(self, step: WorkflowStep) -> bool:
        return all(self._step_is_complete(self.steps_by_id[dep]) for dep in step.depends_on)

    def _all_steps_complete(self) -> bool:
        return all(self._step_is_complete(step) for step in self.context.workflow.steps)

    def _step_is_complete(self, step: WorkflowStep) -> bool:
        task_run = self.task_runs_by_step.get(step.id)
        if not task_run:
            return False
        if task_run["status"] == "SKIPPED":
            return True
        if task_run["status"] != "PASSED":
            return False
        return all((self.context.run_dir / output_path).exists() for output_path in self._expected_outputs(step))

    def _expected_outputs(self, step: WorkflowStep) -> list[str]:
        return [output_path for output_path in step.outputs if self._output_applies(output_path)]

    def _output_applies(self, output_path: str) -> bool:
        for platform in DEFAULT_PLATFORMS:
            platform_paths = (
                f"{platform}/",
                f"assets/{platform}/",
                f"artifact_store/downloads/{platform}_project_bundle.zip",
            )
            if output_path.startswith(platform_paths):
                return platform in self.context.platforms
        return True

    def _first_incomplete_step_id(self) -> str | None:
        for step in self.context.workflow.steps:
            if not self._step_is_complete(step):
                return step.id
        return None

    def _record_skipped(self, step: WorkflowStep) -> None:
        now = _utc_now_iso()
        task_spec = self._task_spec(step)
        reason = self._skip_reason(step) or "step is not applicable"
        task_run = {
            "task_id": task_spec["task_id"],
            "step_id": step.id,
            "agent": step.agent,
            "status": "SKIPPED",
            "started_at": now,
            "ended_at": now,
            "artifact_paths": [],
            "log_path": None,
            "execution_mode": "skipped",
            "reason": reason,
        }
        record = {
            "task_spec": task_spec,
            "task_run": task_run,
            "agent_result": {"metadata": {"execution_mode": "skipped", "agent_interface": "n/a"}, "notes": []},
            "note": reason,
        }
        self._persist_task_attempt(step, task_spec, task_run, record, attempt=0)
        self.task_runs_by_step[step.id] = task_run
        self.skipped.add(step.id)
        self._sync_state()

    def _task_run_from_attempt(self, step: WorkflowStep, attempt_row: dict[str, Any]) -> dict[str, Any]:
        task_run = {
            "task_id": attempt_row["task_id"],
            "step_id": step.id,
            "agent": step.agent,
            "status": attempt_row["status"],
            "started_at": attempt_row["started_at"],
            "ended_at": attempt_row.get("ended_at"),
            "artifact_paths": attempt_row.get("artifact_paths", []),
            "log_path": attempt_row.get("log_path"),
            "execution_mode": attempt_row.get("execution_mode", "template"),
        }
        if attempt_row["status"] == "SKIPPED":
            task_run["reason"] = attempt_row.get("record", {}).get("task_run", {}).get(
                "reason",
                f"platform {step.platform} not selected",
            )
        if attempt_row["status"] == "FAILED":
            task_run["failure_category"] = attempt_row.get("failure_category")
            task_run["failure_message"] = attempt_row.get("failure_message")
            stale_detector = attempt_row.get("record", {}).get("stale_detector", {})
            health = stale_detector.get("health", {}) if isinstance(stale_detector, dict) else {}
            if isinstance(stale_detector, dict) and stale_detector.get("recoverable"):
                task_run["recoverable"] = True
                task_run["recovery_state"] = health.get("state")
                task_run["stale_reason"] = health.get("reason")
        return task_run

    def _run_step(self, step: WorkflowStep) -> None:
        self.current_step_id = step.id
        self.current_failure = None
        task_spec = self._task_spec(step)
        attempt = self.store.next_attempt(self.context.run_id, step.id)
        retry_decision = self.pending_retry_decisions.pop(step.id, None)
        started_at = _utc_now_iso()
        task_log_path = Path("logs/tasks") / f"{step.id}.json"
        running_task_run = self._task_run_template(step, task_spec, "RUNNING", started_at, None, [], str(task_log_path))
        running_record = self._task_log_payload(
            task_spec,
            running_task_run,
            agent_result=None,
            note="Task running.",
        )
        if retry_decision is not None:
            running_record["retry_policy"] = {
                "auto_retry": True,
                "decision": retry_decision,
                "retry_attempt": attempt,
            }
            self.retry_events.append(
                build_retry_event(
                    task_run=running_task_run,
                    decision=retry_decision,
                    attempt=attempt,
                    stage="started",
                )
            )
        self._persist_task_attempt(step, task_spec, running_task_run, running_record, attempt=attempt)
        self._clear_step_outputs(step)

        try:
            agent_result = self._execute_step(step, task_spec)
            artifact_paths: list[str] = []
            artifact_records: list[dict[str, Any]] = []
            for output_path, content in agent_result.outputs.items():
                artifact = self._write_step_output(step, output_path, content, agent_result.metadata)
                artifact_paths.append(artifact["path"])
                artifact_records.append(artifact)

            for artifact in artifact_records:
                self._upsert_artifact(artifact)

            ended_at = _utc_now_iso()
            finished_task_run = self._task_run_template(
                step,
                task_spec,
                "PASSED",
                started_at,
                ended_at,
                artifact_paths,
                str(task_log_path),
                execution_mode=agent_result.metadata.get("execution_mode", "template"),
            )
            finished_record = self._task_log_payload(
                task_spec,
                finished_task_run,
                agent_result=agent_result,
                note="No login, upload, cookie refresh, or publishing actions were performed.",
            )
            if retry_decision is not None:
                finished_record["retry_policy"] = {
                    "auto_retry": True,
                    "decision": retry_decision,
                    "retry_attempt": attempt,
                    "result": "PASSED",
                }
                self.retry_events.append(
                    build_retry_event(
                        task_run=finished_task_run,
                        decision=retry_decision,
                        attempt=attempt,
                        stage="passed",
                    )
                )
            self._persist_task_attempt(step, task_spec, finished_task_run, finished_record, attempt=attempt)
            self.task_runs_by_step[step.id] = finished_task_run
            self.completed.add(step.id)
            self.failures = []
            self.current_failure = None
            self.current_step_id = None
            self._sync_state()
        except Exception as exc:
            self._clear_step_outputs(step)
            ended_at = _utc_now_iso()
            failure_category = classify_failure(exc, step_id=step.id, agent_id=step.agent, task_spec=task_spec)
            failure_msg = failure_message(exc, step_id=step.id, agent_id=step.agent, task_spec=task_spec)
            failed_task_run = self._task_run_template(
                step,
                task_spec,
                "FAILED",
                started_at,
                ended_at,
                [],
                str(task_log_path),
                execution_mode=task_spec["metadata"]["execution_mode"],
            )
            failure_record = {
                "task_id": task_spec["task_id"],
                "step_id": step.id,
                "agent": step.agent,
                "failure_type": failure_category,
                "message": failure_msg,
            }
            failed_record = self._task_log_payload(
                task_spec,
                failed_task_run,
                agent_result=None,
                note=f"Failure category: {failure_category}.",
            )
            if retry_decision is not None:
                failed_record["retry_policy"] = {
                    "auto_retry": True,
                    "decision": retry_decision,
                    "retry_attempt": attempt,
                    "result": "FAILED",
                }
                self.retry_events.append(
                    build_retry_event(
                        task_run=failed_task_run,
                        decision=retry_decision,
                        attempt=attempt,
                        stage="failed",
                    )
                )
            self._persist_task_attempt(
                step,
                task_spec,
                failed_task_run,
                failed_record,
                attempt=attempt,
                failure_category=failure_category,
                failure_message=failure_msg,
            )
            self.task_runs_by_step[step.id] = failed_task_run
            self.failures = [failure_record]
            self.current_failure = failure_record
            repair_entry = self._record_repair_plan(
                step,
                failure_record,
                retry_decision=None,
                source="task_failure",
            )
            self.workflow_status = "NEEDS_HUMAN" if repair_needs_human_approval(repair_entry) else "FAILED"
            self._sync_state()
            raise

    def _execute_step(self, step: WorkflowStep, task_spec: dict[str, Any]) -> AgentResult:
        if supports_agent(step.agent):
            result = run_agent(
                task_spec,
                AgentExecutionContext(
                    run_dir=self.context.run_dir,
                    topic=self.context.topic,
                    platforms=self.context.platforms,
                    produced_artifacts=self._artifact_records_for_agent(),
                    input_attachments=self.context.input_attachments,
                ),
            )
            self._validate_agent_outputs(step, result)
            return result

        outputs = {
            output_path: render_artifact(step, output_path, self.context, self._artifact_records_for_agent())
            for output_path in step.outputs
        }
        return AgentResult(
            outputs=outputs,
            metadata={
                "execution_mode": "template",
                "agent_interface": "render_artifact",
            },
            notes=["No run_agent handler is registered for this agent yet; template fallback was used."],
        )

    def _validate_agent_outputs(self, step: WorkflowStep, result: AgentResult) -> None:
        expected_outputs = self._expected_outputs(step)
        missing = [output_path for output_path in expected_outputs if output_path not in result.outputs]
        extra = [output_path for output_path in result.outputs if output_path not in step.outputs]
        if missing or extra:
            raise RuntimeError(
                f"Agent {step.agent} returned outputs that do not match workflow step {step.id}: "
                f"missing={missing}, extra={extra}"
            )

    def _task_spec(self, step: WorkflowStep) -> dict[str, Any]:
        return {
            "task_id": f"task_{self.context.run_id}_{step.id}",
            "workflow_id": self.context.workflow.id,
            "agent": step.agent,
            "goal": f"Execute workflow step {step.id} for topic: {self.context.topic}",
            "inputs": {
                "topic": self.context.topic,
                "platforms": self.context.platforms,
                "input_attachments": self.context.input_attachments,
                "depends_on": step.depends_on,
                "workflow_path": str(self.context.workflow_path),
            },
            "outputs": self._expected_outputs(step),
            "acceptance_criteria": [
                "All declared output files exist.",
                "No publishing, upload, login, or cookie refresh action is performed.",
                "Task log is written under the run directory.",
            ],
            "permissions": ["read_artifacts", "write_artifacts"],
            "max_retries": 0,
            "requires_human_approval": step.requires_human_approval,
            "metadata": {
                "step_id": step.id,
                "platform": step.platform,
                "requires_any_platform": step.requires_any_platform or [],
                "parallel_group": step.parallel_group,
                "execution_mode": "agent" if supports_agent(step.agent) else "template",
            },
        }

    def _task_run_template(
        self,
        step: WorkflowStep,
        task_spec: dict[str, Any],
        status: str,
        started_at: str,
        ended_at: str | None,
        artifact_paths: list[str],
        log_path: str | None,
        *,
        execution_mode: str | None = None,
    ) -> dict[str, Any]:
        task_run = {
            "task_id": task_spec["task_id"],
            "step_id": step.id,
            "agent": step.agent,
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "artifact_paths": artifact_paths,
            "log_path": log_path,
            "execution_mode": execution_mode or task_spec["metadata"]["execution_mode"],
        }
        if status == "SKIPPED":
            task_run["reason"] = self._skip_reason(step) or "step is not applicable"
        return task_run

    def _task_log_payload(
        self,
        task_spec: dict[str, Any],
        task_run: dict[str, Any],
        *,
        agent_result: AgentResult | None,
        note: str,
    ) -> dict[str, Any]:
        return {
            "task_spec": task_spec,
            "task_run": task_run,
            "agent_result": {
                "metadata": agent_result.metadata if agent_result is not None else {},
                "notes": agent_result.notes if agent_result is not None else [],
            },
            "note": note,
        }

    def _persist_task_attempt(
        self,
        step: WorkflowStep,
        task_spec: dict[str, Any],
        task_run: dict[str, Any],
        record: dict[str, Any],
        *,
        attempt: int,
        failure_category: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        self.store.save_task_attempt(
            {
                "run_id": self.context.run_id,
                "step_id": step.id,
                "attempt": attempt,
                "task_id": task_spec["task_id"],
                "agent": step.agent,
                "status": task_run["status"],
                "started_at": task_run["started_at"],
                "ended_at": task_run.get("ended_at"),
                "execution_mode": task_run.get("execution_mode"),
                "log_path": task_run.get("log_path"),
                "artifact_paths": task_run.get("artifact_paths", []),
                "failure_category": failure_category,
                "failure_message": failure_message,
                "record": record,
                "created_at": task_run["started_at"],
                "updated_at": task_run.get("ended_at") or task_run["started_at"],
            }
        )
        if task_run.get("log_path"):
            _write_json(self.context.run_dir / str(task_run["log_path"]), record)

    def _artifact_records_for_agent(self) -> list[dict[str, Any]]:
        return list(self.artifacts_by_path.values())

    def _artifact_record(self, step: WorkflowStep, output_path: str, result_task_run: dict[str, Any]) -> dict[str, Any]:
        return {
            "path": output_path,
            "kind": _artifact_kind(output_path),
            "producer": step.agent,
            "platform": step.platform or "shared",
            "created_at": _utc_now_iso(),
            "execution_mode": result_task_run.get("execution_mode", "template"),
        }

    def _upsert_artifact(self, artifact: dict[str, Any]) -> None:
        self.artifacts_by_path[artifact["path"]] = artifact

    def _clear_step_outputs(self, step: WorkflowStep) -> None:
        for output_path in step.outputs:
            destination = self.context.run_dir / output_path
            if destination.exists():
                destination.unlink()

    def _record_repair_plan(
        self,
        step: WorkflowStep,
        failure: dict[str, Any],
        *,
        retry_decision: dict[str, Any] | None,
        source: str,
    ) -> dict[str, Any] | None:
        dedupe_key = {
            "step_id": step.id,
            "task_id": failure.get("task_id"),
            "message": failure.get("message"),
            "source": source,
        }
        for entry in self.repair_log:
            if entry.get("dedupe_key") == dedupe_key:
                return entry

        repair_dir = self.context.run_dir / "repair"
        repair_dir.mkdir(parents=True, exist_ok=True)
        task_spec = self._task_spec(step)
        repair_task_spec = {
            "task_id": f"task_{self.context.run_id}_repair_{step.id}_{len(self.repair_log) + 1}",
            "workflow_id": self.context.workflow.id,
            "agent": "repair-agent",
            "goal": f"Diagnose failed workflow step {step.id} and propose safe repair actions.",
            "inputs": {
                "topic": self.context.topic,
                "platforms": self.context.platforms,
                "failure": failure,
                "failed_task_spec": task_spec,
                "retry_decision": retry_decision or {},
                "source": source,
            },
            "outputs": [
                f"repair/{step.id}_repair_plan.md",
                f"repair/{step.id}_repair_plan.json",
            ],
            "acceptance_criteria": [
                "Root cause hypothesis is recorded.",
                "Recommended repair actions are explicit.",
                "No task inputs, artifacts, cookies, browser state, upload state, or publishing state are modified.",
            ],
            "permissions": ["read_artifacts", "write_repair_log"],
            "max_retries": 0,
            "requires_human_approval": False,
            "metadata": {
                "step_id": f"repair_{step.id}",
                "failed_step_id": step.id,
                "execution_mode": "agent",
            },
        }
        try:
            result = run_agent(
                repair_task_spec,
                AgentExecutionContext(
                    run_dir=self.context.run_dir,
                    topic=self.context.topic,
                    platforms=self.context.platforms,
                    produced_artifacts=self._artifact_records_for_agent(),
                    input_attachments=self.context.input_attachments,
                ),
            )
        except Exception as exc:
            self.repair_log.append(
                {
                    "repair_id": f"repair_{len(self.repair_log) + 1}",
                    "source": source,
                    "created_at": _utc_now_iso(),
                    "failed_step_id": step.id,
                    "failed_agent": step.agent,
                    "task_id": failure.get("task_id"),
                    "failure_category": failure.get("failure_type") or failure.get("category"),
                    "failure_message": failure.get("message"),
                    "repair_agent": "repair-agent",
                    "status": "FAILED",
                    "repair_error": str(exc),
                    "dedupe_key": dedupe_key,
                }
            )
            _write_json(repair_dir / "repair_log.json", self.repair_log)
            return self.repair_log[-1]
        plan_md_path = Path(f"repair/{step.id}_repair_plan.md")
        plan_json_path = Path(f"repair/{step.id}_repair_plan.json")
        (self.context.run_dir / plan_md_path).parent.mkdir(parents=True, exist_ok=True)
        (self.context.run_dir / plan_md_path).write_text(str(result.outputs["repair_plan.md"]), encoding="utf-8")
        _write_json(self.context.run_dir / plan_json_path, result.outputs["repair_plan.json"])
        manual_required = bool(result.outputs["repair_plan.json"].get("manual_required"))
        entry = {
            "repair_id": f"repair_{len(self.repair_log) + 1}",
            "source": source,
            "created_at": _utc_now_iso(),
            "failed_step_id": step.id,
            "failed_agent": step.agent,
            "task_id": failure.get("task_id"),
            "failure_category": failure.get("failure_type") or failure.get("category"),
            "failure_message": failure.get("message"),
            "retry_decision": retry_decision or {},
            "repair_agent": "repair-agent",
            "plan_path": str(plan_md_path),
            "plan_json_path": str(plan_json_path),
            "manual_required": manual_required,
            "approval_status": APPROVAL_PENDING if manual_required else APPROVAL_NOT_REQUIRED,
            "can_auto_patch": bool(result.outputs["repair_plan.json"].get("can_auto_patch")),
            "status": "PROPOSED",
            "dedupe_key": dedupe_key,
        }
        self.repair_log.append(entry)
        _write_json(repair_dir / "repair_log.json", self.repair_log)
        return entry

    def _convert_running_attempt_to_failed(
        self,
        step: WorkflowStep,
        attempt_row: dict[str, Any],
        resume_state: dict[str, Any],
    ) -> dict[str, Any]:
        task_spec = self._task_spec(step)
        health = assess_task_health(
            workflow_run=resume_state,
            task_view={
                "task_id": attempt_row.get("task_id"),
                "step_id": step.id,
                "agent": step.agent,
                "status": "RUNNING",
                "started_at": attempt_row.get("started_at"),
                "ended_at": attempt_row.get("ended_at"),
                "log_path": attempt_row.get("log_path"),
            },
            mode="resume",
        )
        failure_category = "ENV_ERROR"
        failure_msg = (
            health.get("failure_message")
            or health.get("reason")
            or f"Previous attempt for {step.id} was interrupted before completion."
        )
        task_run = self._task_run_template(
            step,
            task_spec,
            "FAILED",
            attempt_row["started_at"],
            _utc_now_iso(),
            [],
            attempt_row.get("log_path"),
            execution_mode=attempt_row.get("execution_mode"),
        )
        record = self._task_log_payload(
            task_spec,
            task_run,
            agent_result=None,
            note=f"Failure category: {failure_category}. Stale detector state: {health.get('state')}.",
        )
        record["stale_detector"] = {
            "mode": "resume",
            "health": health,
            "recoverable": bool(health.get("recoverable")),
        }
        previous_retry_policy = attempt_row.get("record", {}).get("retry_policy")
        if isinstance(previous_retry_policy, dict):
            record["retry_policy"] = previous_retry_policy
        self._persist_task_attempt(
            step,
            task_spec,
            task_run,
            record,
            attempt=attempt_row["attempt"],
            failure_category=failure_category,
            failure_message=failure_msg,
        )
        return task_run | {
            "failure_category": failure_category,
            "failure_message": failure_msg,
            "recoverable": bool(health.get("recoverable")),
            "recovery_state": health.get("state"),
            "stale_reason": health.get("reason"),
        }

    def _record_workflow_failure(self, exc: Exception, step_id: str | None) -> None:
        step = self.steps_by_id.get(step_id) if step_id else None
        if step is None:
            failure_task_id = f"task_{self.context.run_id}_workflow"
            failure_type = classify_failure(
                exc,
                step_id=step_id or "workflow",
                agent_id="global-orchestrator",
                task_spec={"task_id": failure_task_id},
            )
            message = failure_message(
                exc,
                step_id=step_id or "workflow",
                agent_id="global-orchestrator",
                task_spec={"task_id": failure_task_id},
            )
        else:
            task_spec = self._task_spec(step)
            failure_task_id = task_spec["task_id"]
            failure_type = classify_failure(exc, step_id=step.id, agent_id=step.agent, task_spec=task_spec)
            message = failure_message(exc, step_id=step.id, agent_id=step.agent, task_spec=task_spec)

        self.workflow_status = "FAILED"
        self.current_failure = {"task_id": failure_task_id, "failure_type": failure_type, "message": message}
        if step is not None:
            self.current_failure["step_id"] = step.id
            self.current_failure["agent"] = step.agent
        self.failures = [self.current_failure]
        if step is not None:
            repair_entry = self._record_repair_plan(
                step,
                self.current_failure,
                retry_decision=None,
                source="workflow_failure",
            )
            if repair_needs_human_approval(repair_entry):
                self.workflow_status = "NEEDS_HUMAN"

    def _sync_state(self) -> None:
        snapshot = self._workflow_run()
        _write_json(self.context.run_dir / "workflow_run.json", snapshot)
        current_step_id = self.current_step_id
        failure_task_id = self.current_failure["task_id"] if self.current_failure else None
        failure_category = self.current_failure["failure_type"] if self.current_failure else None
        failure_message_value = self.current_failure["message"] if self.current_failure else None
        self.store.save_workflow_run(
            snapshot,
            workflow_path=str(self.context.workflow_path),
            run_dir=str(self.context.run_dir),
            current_step_id=current_step_id,
            failure_task_id=failure_task_id,
            failure_category=failure_category,
            failure_message=failure_message_value,
        )
        write_supervision_outputs(
            self.context.run_dir,
            snapshot,
            self.store.load_task_attempts(self.context.run_id),
        )

    def _pending_manual_repair_for_step(self, step_id: str) -> bool:
        entry = latest_repair_for_step(self.repair_log, step_id=step_id)
        return repair_needs_human_approval(entry)

    def _write_step_output(
        self,
        step: WorkflowStep,
        output_path: str,
        content: Any,
        result_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        destination = self.context.run_dir / output_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            destination.write_bytes(content)
        elif isinstance(content, (dict, list)):
            _write_json(destination, content)
        else:
            destination.write_text(str(content), encoding="utf-8")

        return {
            "path": output_path,
            "kind": _artifact_kind(output_path),
            "producer": step.agent,
            "platform": step.platform or "shared",
            "created_at": _utc_now_iso(),
            "execution_mode": result_metadata.get("execution_mode", "template"),
        }

    def _write_final_outputs(self) -> None:
        final_dir = self.context.run_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        video_platforms = [platform for platform in self.context.platforms if platform in VIDEO_PLATFORMS]
        has_video_platforms = bool(video_platforms)

        artifact_manifest = {
            "run_id": self.context.run_id,
            "artifacts": [
                {
                    "path": item["path"],
                    "kind": item["kind"],
                    "producer": item["producer"],
                    "description": f"Produced by {item['producer']}",
                    "created_at": item["created_at"],
                    "execution_mode": item.get("execution_mode", "template"),
                }
                for item in self.artifacts_by_path.values()
            ],
        }
        _write_json(self.context.run_dir / "artifact_manifest.json", artifact_manifest)

        video_production_package = self._build_video_production_package()
        materialization_manifest = self._build_materialization_manifest(video_production_package)
        licensed_media_ingest_manifest = self._build_licensed_media_ingest_manifest(video_production_package)
        licensed_media_proxy_manifest = self._build_licensed_media_proxy_manifest(video_production_package)
        editor_replacement_instruction_manifest = self._build_editor_replacement_instruction_manifest(video_production_package)
        editor_replacement_execution_manifest = self._build_editor_replacement_execution_manifest(video_production_package)
        editor_project_mutation_manifest = self._build_editor_project_mutation_manifest(video_production_package)
        editor_software_import_manifest = self._build_editor_software_import_manifest(video_production_package)
        editor_software_real_runner_manifest = self._build_editor_software_real_runner_manifest(video_production_package)
        editor_software_run_evidence_manifest = self._build_editor_software_run_evidence_manifest(video_production_package)
        edit_project_manifest = self._build_edit_project_manifest(video_production_package)
        export_project_manifest = self._build_export_project_manifest(video_production_package)
        project_bundle_manifest = self._build_project_bundle_manifest(video_production_package)

        content_package = {
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "package_type": "content_package",
            "platforms": self.context.platforms,
            "artifacts": [
                {
                    "platform": item["platform"],
                    "path": item["path"],
                    "kind": item["kind"],
                }
                for item in self.artifacts_by_path.values()
                if item["platform"] in self.context.platforms
            ],
            "review_required": True,
        }
        if has_video_platforms:
            content_package.update(
                {
                    "video_production_package": "final/video_production_package.json",
                    "materialization_manifest": "final/materialization_manifest.json",
                    "licensed_media_ingest_manifest": "final/licensed_media_ingest_manifest.json",
                    "licensed_media_proxy_manifest": "final/licensed_media_proxy_manifest.json",
                    "editor_replacement_instruction_manifest": "final/editor_replacement_instruction_manifest.json",
                    "editor_replacement_execution_manifest": "final/editor_replacement_execution_manifest.json",
                    "editor_project_mutation_manifest": "final/editor_project_mutation_manifest.json",
                    "editor_software_import_manifest": "final/editor_software_import_manifest.json",
                    "editor_software_real_runner_manifest": "final/editor_software_real_runner_manifest.json",
                    "editor_software_run_evidence_manifest": "final/editor_software_run_evidence_manifest.json",
                    "edit_project_manifest": "final/edit_project_manifest.json",
                    "export_project_manifest": "final/export_project_manifest.json",
                    "project_bundle_manifest": "final/project_bundle_manifest.json",
                    "delivery_index": "final/delivery_index.json",
                    "delivery_readme": "final/delivery_readme.md",
                    "artifact_store_manifest": "artifact_store/artifact_store_manifest.json",
                    "artifact_store_readme": "artifact_store/README.md",
                    "artifact_store_download_index": "artifact_store/download_index.md",
                    "artifact_store_checksums": "artifact_store/checksums.sha256",
                    "external_mirror_plan": "artifact_store/external_mirror_plan.json",
                    "external_mirror_sync_command_preview": "artifact_store/sync_command_preview.md",
                    "external_mirror_approval_request": "artifact_store/human_distribution_approval_request.md",
                    "external_mirror_readme": "artifact_store/external_mirror_readme.md",
                }
            )
        _write_json(final_dir / "content_package_manifest.json", content_package)
        if has_video_platforms:
            _write_json(final_dir / "video_production_package.json", video_production_package)
            _write_json(final_dir / "materialization_manifest.json", materialization_manifest)
            _write_json(final_dir / "licensed_media_ingest_manifest.json", licensed_media_ingest_manifest)
            _write_json(final_dir / "licensed_media_proxy_manifest.json", licensed_media_proxy_manifest)
            _write_json(final_dir / "editor_replacement_instruction_manifest.json", editor_replacement_instruction_manifest)
            _write_json(final_dir / "editor_replacement_execution_manifest.json", editor_replacement_execution_manifest)
            _write_json(final_dir / "editor_project_mutation_manifest.json", editor_project_mutation_manifest)
            _write_json(final_dir / "editor_software_import_manifest.json", editor_software_import_manifest)
            _write_json(final_dir / "editor_software_real_runner_manifest.json", editor_software_real_runner_manifest)
            _write_json(final_dir / "editor_software_run_evidence_manifest.json", editor_software_run_evidence_manifest)
            _write_json(final_dir / "edit_project_manifest.json", edit_project_manifest)
            _write_json(final_dir / "export_project_manifest.json", export_project_manifest)
            _write_json(final_dir / "project_bundle_manifest.json", project_bundle_manifest)

        execution_mode = self._execution_mode_summary()
        review_lines = [
            "# Final Review Report",
            "",
            f"- Run ID: {self.context.run_id}",
            f"- Topic: {self.context.topic}",
            f"- Platforms: {', '.join(self.context.platforms)}",
            "- Status: DONE",
            f"- Execution mode: {execution_mode}",
            "- Publishing: not performed",
        ]
        if has_video_platforms:
            review_lines.extend(
                [
                "- Video production package: final/video_production_package.json",
                "- Materialization manifest: final/materialization_manifest.json",
                "- Licensed media ingest manifest: final/licensed_media_ingest_manifest.json",
                "- Licensed media proxy manifest: final/licensed_media_proxy_manifest.json",
                "- Editor replacement instruction manifest: final/editor_replacement_instruction_manifest.json",
                "- Editor replacement execution manifest: final/editor_replacement_execution_manifest.json",
                "- Editor project mutation manifest: final/editor_project_mutation_manifest.json",
                "- Editor software import manifest: final/editor_software_import_manifest.json",
                "- Editor software real runner manifest: final/editor_software_real_runner_manifest.json",
                "- Editor software run evidence manifest: final/editor_software_run_evidence_manifest.json",
                "- Edit project manifest: final/edit_project_manifest.json",
                "- Export project manifest: final/export_project_manifest.json",
                "- Project bundle manifest: final/project_bundle_manifest.json",
                "- Delivery index: final/delivery_index.json",
                "- Artifact store: artifact_store/artifact_store_manifest.json",
                "- External mirror plan: artifact_store/external_mirror_plan.json",
                "",
                "Phase 4 upgrades the run from text drafts to a video production package with asset plan, cover prompts, generated covers, storyboard keyframe previews, local B-roll reference materials, licensed-media review handoffs, proxy replacement suggestions, editor replacement import templates with a human confirmation gate, editor execution adapter preflight plans blocked pending explicit approval, mutation sandbox patched project copies blocked pending explicit approval, editor software import executor isolation plans blocked pending explicit approval, real-runner sandbox launch packages blocked pending explicit approval, post-launch evidence ingest packages blocked pending human real-run result, timed subtitles, draft voiceover audio, edit timelines, shot lists, B-roll lists, export manifest, project bundles, a local delivery index, a local artifact store for downloadable handoff files, and a plan-only external mirror handoff.",
                ]
            )
        else:
            review_lines.extend(
                [
                    "",
                    "The run selected no video platforms, so video production, bundle, delivery index, artifact store, and external mirror steps were skipped.",
                ]
            )
        review_report = "\n".join(review_lines)
        (final_dir / "review_report.md").write_text(review_report + "\n", encoding="utf-8")
        video_final_artifact_paths = [
            "final/video_production_package.json",
            "final/materialization_manifest.json",
            "final/licensed_media_ingest_manifest.json",
            "final/licensed_media_proxy_manifest.json",
            "final/editor_replacement_instruction_manifest.json",
            "final/editor_replacement_execution_manifest.json",
            "final/editor_project_mutation_manifest.json",
            "final/editor_software_import_manifest.json",
            "final/editor_software_real_runner_manifest.json",
            "final/editor_software_run_evidence_manifest.json",
            "final/edit_project_manifest.json",
            "final/export_project_manifest.json",
            "final/project_bundle_manifest.json",
        ]
        self.final_artifact_paths = [
            "artifact_manifest.json",
            "final/content_package_manifest.json",
            *(video_final_artifact_paths if has_video_platforms else []),
            "final/review_report.md",
        ]

    def _build_video_production_package(self) -> dict[str, Any]:
        video_platforms = [platform for platform in self.context.platforms if platform in VIDEO_PLATFORMS]
        asset_plan = _read_json_if_exists(self.context.run_dir / "asset_plan.json")
        asset_tasks = _read_json_if_exists(self.context.run_dir / "assets/asset_generation_tasks.json")
        media_asset_manifest = _read_json_if_exists(self.context.run_dir / "assets/media_asset_manifest.json")
        platform_plans = _asset_platform_plans(asset_plan)
        platform_packages = []
        generated_assets: list[dict[str, Any]] = []
        for platform in video_platforms:
            plan = platform_plans.get(platform, {})
            platform_materialized_assets = _materialized_assets_for_platform(self.context.run_dir, platform)
            platform_generated_assets = _generated_assets_for_platform(self.context.run_dir, platform)
            platform_generated_assets.extend(platform_materialized_assets)
            generated_assets.extend(platform_generated_assets)
            platform_packages.append(
                {
                    "platform": platform,
                    "platform_label": _platform_label(platform),
                    "aspect_ratio": plan.get("aspect_ratio") or _default_aspect_ratio(platform),
                    "recommended_duration_seconds": _platform_duration_seconds(self.context.run_dir, platform, plan),
                    "deliverables": _video_deliverables_for_platform(self.context.run_dir, platform),
                    "asset_plan": {
                        "cover_prompt": plan.get("cover_prompt"),
                        "shot_list": plan.get("shot_list", []),
                        "broll_list": plan.get("broll_list", []),
                        "asset_clearance": plan.get("asset_clearance", {}),
                    },
                    "asset_tasks": _asset_tasks_for_platform(asset_tasks, platform),
                    "media_assets": _media_assets_for_platform(media_asset_manifest, platform),
                    "materialized_assets": _materialized_assets_summary_for_platform(self.context.run_dir, platform),
                    "licensed_media_ingest": _licensed_media_ingest_summary_for_platform(self.context.run_dir, platform),
                    "licensed_media_proxy": _licensed_media_proxy_summary_for_platform(self.context.run_dir, platform),
                    "editor_replacement_instructions": _editor_replacement_instruction_summary_for_platform(
                        self.context.run_dir,
                        platform,
                    ),
                    "editor_replacement_execution": _editor_replacement_execution_summary_for_platform(
                        self.context.run_dir,
                        platform,
                    ),
                    "editor_project_mutation_sandbox": _editor_project_mutation_summary_for_platform(
                        self.context.run_dir,
                        platform,
                    ),
                    "editor_software_import_executor": _editor_software_import_summary_for_platform(
                        self.context.run_dir,
                        platform,
                    ),
                    "editor_software_real_runner_sandbox": _editor_software_real_runner_summary_for_platform(
                        self.context.run_dir,
                        platform,
                    ),
                    "editor_software_run_evidence": _editor_software_run_evidence_summary_for_platform(
                        self.context.run_dir,
                        platform,
                    ),
                    "generated_assets": platform_generated_assets,
                    "timed_subtitles": _timed_subtitles_summary_for_platform(self.context.run_dir, platform),
                    "voiceover_tts": _voiceover_tts_summary_for_platform(self.context.run_dir, platform),
                    "edit_project": _edit_project_summary_for_platform(self.context.run_dir, platform),
                    "export_project": _export_project_summary_for_platform(self.context.run_dir, platform),
                    "project_bundle": _project_bundle_summary_for_platform(self.context.run_dir, platform),
                    "production_checklist": [
                        "Review script and voiceover against platform tone.",
                        "Confirm storyboard timing, subtitle timing, voiceover pacing, edit timeline, export project, and shot list are executable.",
                        "Confirm generated cover images, storyboard keyframes, B-roll, and other assets are self-created, licensed, or human-reviewed.",
                        "Export only after human review; no login, upload, sync, or publish action is automated.",
                    ],
                    "review_required": True,
                }
            )
        return {
            "schema_version": "phase4.video_production_package.v1",
            "package_type": "video_production_package",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "platforms": self.context.platforms,
            "video_platforms": video_platforms,
            "source_artifacts": [
                path
                for path in [
                    "asset_plan.json",
                    "cover_prompts.md",
                    "assets/asset_generation_tasks.json",
                    "assets/media_asset_manifest.json",
                    "assets/asset_ingest_guide.md",
                    "angle_pack.json",
                    "master_outline.md",
                ]
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _generated_media_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _materialized_asset_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _licensed_media_ingest_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _licensed_media_proxy_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _editor_replacement_instruction_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _editor_replacement_execution_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _editor_project_mutation_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _editor_software_import_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _editor_software_real_runner_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _editor_software_run_evidence_source_paths(self.context.run_dir, platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _timed_subtitle_source_paths(platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _voiceover_tts_source_paths(platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _edit_project_source_paths(platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _export_project_source_paths(platform)
                if (self.context.run_dir / path).exists()
            ]
            + [
                path
                for platform in video_platforms
                for path in _project_bundle_source_paths(platform)
                if (self.context.run_dir / path).exists()
            ],
            "asset_generation_tasks": "assets/asset_generation_tasks.json",
            "media_asset_manifest": "assets/media_asset_manifest.json",
            "materialization_manifest": "final/materialization_manifest.json",
            "licensed_media_ingest_manifest": "final/licensed_media_ingest_manifest.json",
            "licensed_media_proxy_manifest": "final/licensed_media_proxy_manifest.json",
            "editor_replacement_instruction_manifest": "final/editor_replacement_instruction_manifest.json",
            "editor_replacement_execution_manifest": "final/editor_replacement_execution_manifest.json",
            "editor_project_mutation_manifest": "final/editor_project_mutation_manifest.json",
            "editor_software_import_manifest": "final/editor_software_import_manifest.json",
            "editor_software_real_runner_manifest": "final/editor_software_real_runner_manifest.json",
            "editor_software_run_evidence_manifest": "final/editor_software_run_evidence_manifest.json",
            "edit_project_manifest": "final/edit_project_manifest.json",
            "export_project_manifest": "final/export_project_manifest.json",
            "project_bundle_manifest": "final/project_bundle_manifest.json",
            "generated_assets": generated_assets,
            "platform_packages": platform_packages,
            "export_boundary": {
                "cover_image_generation": "performed_locally_pending_human_review",
                "storyboard_preview_generation": "performed_locally_pending_human_review",
                "asset_materialization": "performed_locally_reference_only",
                "licensed_media_ingest": "review_handoff_only_pending_human_supplied_media",
                "licensed_media_proxy": "performed_locally_from_human_registered_media_only",
                "editor_replacement_instructions": "performed_locally_template_and_instruction_only",
                "editor_replacement_execution": "blocked_pending_explicit_human_approval",
                "editor_project_mutation_sandbox": "blocked_pending_explicit_human_mutation_approval",
                "editor_software_import_executor": "blocked_pending_explicit_human_software_import_approval",
                "editor_software_real_runner_sandbox": "blocked_pending_explicit_human_real_run_approval",
                "editor_software_run_evidence": _aggregate_editor_software_run_evidence_boundary(platform_packages),
                "subtitle_timing_correction": "performed_locally_deterministic_no_tts",
                "voiceover_tts_generation": _aggregate_voiceover_tts_boundary(platform_packages),
                "edit_project_generation": "performed_locally_draft_no_editing_software",
                "export_project_generation": "performed_locally_draft_no_editing_software",
                "project_bundle_generation": "performed_locally_draft_no_editing_software",
                "publishing": "not_performed",
                "upload": "not_performed",
                "login_or_cookie_refresh": "not_performed",
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
            },
            "review_required": True,
        }

    def _build_materialization_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_materials = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        materialized_count = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            materialized_assets = package.get("materialized_assets", {})
            if not isinstance(materialized_assets, dict):
                materialized_assets = {}
            reference_paths = materialized_assets.get("reference_paths", [])
            if not isinstance(reference_paths, list):
                reference_paths = []
            material_sources = [
                path
                for path in [
                    materialized_assets.get("manifest_path"),
                    materialized_assets.get("readme_path"),
                    *reference_paths,
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(material_sources)
            validation_status = materialized_assets.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            count = int(materialized_assets.get("materialized_count") or 0)
            materialized_count += count
            platform_materials.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "manifest_path": materialized_assets.get("manifest_path"),
                    "readme_path": materialized_assets.get("readme_path"),
                    "materialized_count": count,
                    "reference_paths": reference_paths,
                    "validation": {
                        "status": validation_status,
                        "licensed_final_media_required": materialized_assets.get("licensed_final_media_required") is True,
                    },
                    "source_artifacts": material_sources,
                    "review_required": True,
                }
            )

        return {
            "schema_version": "phase4.materialization_bundle_manifest.v1",
            "artifact_type": "materialization_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/materialization_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": _dedupe(source_artifacts),
            "platform_materials": platform_materials,
            "export_boundary": {
                "asset_materialization": "performed_locally_reference_only",
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
                "editing_software": "not_opened",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_materials) and materialized_count > 0 else "NEEDS_REVIEW",
                "platform_count": len(platform_materials),
                "passed_platform_count": passed_platforms,
                "materialized_count": materialized_count,
                "licensed_final_media_required": True,
            },
            "generation_status": "generated_local_materialization_bundle_pending_human_review",
            "manual_review_required": True,
            "review_required": True,
        }

    def _build_licensed_media_ingest_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_ingests = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        required_count = 0
        pending_count = 0
        candidate_count = 0
        ready_count = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            ingest = package.get("licensed_media_ingest", {})
            if not isinstance(ingest, dict):
                ingest = {}
            media_paths = ingest.get("licensed_media_paths", [])
            proof_paths = ingest.get("license_proof_paths", [])
            if not isinstance(media_paths, list):
                media_paths = []
            if not isinstance(proof_paths, list):
                proof_paths = []
            ingest_sources = [
                path
                for path in [
                    ingest.get("manifest_path"),
                    ingest.get("readme_path"),
                    ingest.get("review_handoff_path"),
                    ingest.get("human_media_registry_path") if ingest.get("human_media_registry_exists") is True else None,
                    *media_paths,
                    *proof_paths,
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(ingest_sources)
            validation_status = ingest.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            required = int(ingest.get("required_final_media_count") or 0)
            pending = int(ingest.get("pending_human_media_count") or 0)
            candidate = int(ingest.get("candidate_media_count") or 0)
            ready = int(ingest.get("ready_for_editor_replacement_count") or 0)
            required_count += required
            pending_count += pending
            candidate_count += candidate
            ready_count += ready
            platform_ingests.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "manifest_path": ingest.get("manifest_path"),
                    "readme_path": ingest.get("readme_path"),
                    "review_handoff_path": ingest.get("review_handoff_path"),
                    "human_media_registry_path": ingest.get("human_media_registry_path"),
                    "human_media_registry_exists": ingest.get("human_media_registry_exists") is True,
                    "required_final_media_count": required,
                    "pending_human_media_count": pending,
                    "candidate_media_count": candidate,
                    "ready_for_editor_replacement_count": ready,
                    "licensed_media_paths": media_paths,
                    "license_proof_paths": proof_paths,
                    "validation": {
                        "status": validation_status,
                        "intake_complete": ingest.get("intake_complete") is True,
                        "licensed_final_media_required": ingest.get("licensed_final_media_required") is True,
                    },
                    "source_artifacts": ingest_sources,
                    "review_required": True,
                }
            )

        return {
            "schema_version": "phase4.licensed_media_ingest_bundle_manifest.v1",
            "artifact_type": "licensed_media_ingest_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/licensed_media_ingest_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": _dedupe(source_artifacts),
            "platform_ingests": platform_ingests,
            "export_boundary": {
                "licensed_media_ingest": "review_handoff_only_pending_human_supplied_media",
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
                "editing_software": "not_opened",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_ingests) and required_count > 0 else "NEEDS_REVIEW",
                "platform_count": len(platform_ingests),
                "passed_platform_count": passed_platforms,
                "required_final_media_count": required_count,
                "pending_human_media_count": pending_count,
                "candidate_media_count": candidate_count,
                "ready_for_editor_replacement_count": ready_count,
                "intake_complete": ready_count == required_count and required_count > 0,
                "licensed_final_media_required": True,
            },
            "generation_status": "generated_local_licensed_media_ingest_bundle_pending_human_review",
            "manual_review_required": True,
            "review_required": True,
        }

    def _build_licensed_media_proxy_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_proxies = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        required_count = 0
        ready_source_count = 0
        copied_count = 0
        pending_count = 0
        candidate_count = 0
        blocked_count = 0
        editor_ready_count = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            proxy = package.get("licensed_media_proxy", {})
            if not isinstance(proxy, dict):
                proxy = {}
            proxy_paths = proxy.get("proxy_media_paths", [])
            source_paths = proxy.get("licensed_media_paths", [])
            proof_paths = proxy.get("license_proof_paths", [])
            if not isinstance(proxy_paths, list):
                proxy_paths = []
            if not isinstance(source_paths, list):
                source_paths = []
            if not isinstance(proof_paths, list):
                proof_paths = []
            proxy_sources = [
                path
                for path in [
                    proxy.get("manifest_path"),
                    proxy.get("replacement_suggestions_path"),
                    proxy.get("readme_path"),
                    *proxy_paths,
                    *source_paths,
                    *proof_paths,
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(proxy_sources)
            validation_status = proxy.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            required = int(proxy.get("required_final_media_count") or 0)
            ready_source = int(proxy.get("ready_source_media_count") or 0)
            copied = int(proxy.get("proxy_copied_count") or 0)
            pending = int(proxy.get("pending_human_media_count") or 0)
            candidate = int(proxy.get("candidate_pending_review_count") or 0)
            blocked = int(proxy.get("blocked_proxy_count") or 0)
            editor_ready = int(proxy.get("editor_replacement_ready_count") or 0)
            required_count += required
            ready_source_count += ready_source
            copied_count += copied
            pending_count += pending
            candidate_count += candidate
            blocked_count += blocked
            editor_ready_count += editor_ready
            platform_proxies.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "manifest_path": proxy.get("manifest_path"),
                    "replacement_suggestions_path": proxy.get("replacement_suggestions_path"),
                    "readme_path": proxy.get("readme_path"),
                    "proxy_dir": proxy.get("proxy_dir"),
                    "required_final_media_count": required,
                    "ready_source_media_count": ready_source,
                    "proxy_copied_count": copied,
                    "pending_human_media_count": pending,
                    "candidate_pending_review_count": candidate,
                    "blocked_proxy_count": blocked,
                    "editor_replacement_ready_count": editor_ready,
                    "proxy_media_paths": proxy_paths,
                    "licensed_media_paths": source_paths,
                    "license_proof_paths": proof_paths,
                    "ready_asset_ids": proxy.get("ready_asset_ids", []),
                    "pending_asset_ids": proxy.get("pending_asset_ids", []),
                    "candidate_asset_ids": proxy.get("candidate_asset_ids", []),
                    "blocked_asset_ids": proxy.get("blocked_asset_ids", []),
                    "validation": {
                        "status": validation_status,
                        "proxy_copy_complete_for_ready_media": proxy.get("proxy_copy_complete_for_ready_media") is True,
                        "editor_replacement_ready_count": editor_ready,
                    },
                    "source_artifacts": proxy_sources,
                    "review_required": True,
                }
            )

        return {
            "schema_version": "phase4.licensed_media_proxy_bundle_manifest.v1",
            "artifact_type": "licensed_media_proxy_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/licensed_media_proxy_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": _dedupe(source_artifacts),
            "platform_proxies": platform_proxies,
            "export_boundary": {
                "licensed_media_proxy": "performed_locally_from_human_registered_media_only",
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
                "license_purchase": "not_performed",
                "editing_software": "not_opened",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_proxies) and required_count > 0 else "NEEDS_REVIEW",
                "platform_count": len(platform_proxies),
                "passed_platform_count": passed_platforms,
                "required_final_media_count": required_count,
                "ready_source_media_count": ready_source_count,
                "proxy_copied_count": copied_count,
                "pending_human_media_count": pending_count,
                "candidate_pending_review_count": candidate_count,
                "blocked_proxy_count": blocked_count,
                "editor_replacement_ready_count": editor_ready_count,
                "proxy_copy_complete_for_ready_media": copied_count == ready_source_count,
            },
            "generation_status": "generated_local_proxy_bundle_pending_editor_review",
            "manual_review_required": True,
            "review_required": True,
        }

    def _build_editor_replacement_instruction_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_instructions = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        instruction_count = 0
        ready_count = 0
        pending_count = 0
        blocked_count = 0
        executable_count = 0
        confirmation_required_count = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            instructions = package.get("editor_replacement_instructions", {})
            if not isinstance(instructions, dict):
                instructions = {}
            instruction_sources = [
                path
                for path in [
                    instructions.get("manifest_path"),
                    instructions.get("replacement_commands_path"),
                    instructions.get("editor_import_template_path"),
                    instructions.get("human_confirmation_checklist_path"),
                    instructions.get("readme_path"),
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(instruction_sources)
            validation_status = instructions.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            count = int(instructions.get("instruction_count") or 0)
            ready = int(instructions.get("ready_pending_human_confirmation_count") or 0)
            pending = int(instructions.get("pending_human_media_count") or 0)
            blocked = int(instructions.get("blocked_instruction_count") or 0)
            executable = int(instructions.get("executable_after_human_confirmation_count") or 0)
            confirmation_required = int(instructions.get("human_confirmation_required_count") or 0)
            instruction_count += count
            ready_count += ready
            pending_count += pending
            blocked_count += blocked
            executable_count += executable
            confirmation_required_count += confirmation_required
            platform_instructions.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "manifest_path": instructions.get("manifest_path"),
                    "replacement_commands_path": instructions.get("replacement_commands_path"),
                    "editor_import_template_path": instructions.get("editor_import_template_path"),
                    "human_confirmation_checklist_path": instructions.get("human_confirmation_checklist_path"),
                    "readme_path": instructions.get("readme_path"),
                    "instruction_count": count,
                    "ready_pending_human_confirmation_count": ready,
                    "pending_human_media_count": pending,
                    "blocked_instruction_count": blocked,
                    "executable_after_human_confirmation_count": executable,
                    "human_confirmation_required_count": confirmation_required,
                    "validation": {
                        "status": validation_status,
                        "human_confirmation_gate_active": instructions.get("human_confirmation_gate_active") is True,
                        "replacement_execution_performed": instructions.get("replacement_execution_performed") is True,
                    },
                    "source_artifacts": instruction_sources,
                    "review_required": True,
                    "human_confirmation_required": True,
                }
            )

        return {
            "schema_version": "phase4.editor_replacement_instruction_bundle_manifest.v1",
            "artifact_type": "editor_replacement_instruction_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/editor_replacement_instruction_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": _dedupe(source_artifacts),
            "platform_instructions": platform_instructions,
            "export_boundary": {
                "editor_replacement_instructions": "performed_locally_template_and_instruction_only",
                "replacement_execution": "not_performed",
                "editing_software": "not_opened",
                "project_file_mutation": "not_performed",
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
                "license_purchase": "not_performed",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_instructions) and instruction_count > 0 else "NEEDS_REVIEW",
                "platform_count": len(platform_instructions),
                "passed_platform_count": passed_platforms,
                "instruction_count": instruction_count,
                "ready_pending_human_confirmation_count": ready_count,
                "pending_human_media_count": pending_count,
                "blocked_instruction_count": blocked_count,
                "executable_after_human_confirmation_count": executable_count,
                "human_confirmation_required_count": confirmation_required_count,
                "human_confirmation_gate_active": confirmation_required_count == instruction_count and instruction_count > 0,
                "replacement_execution_performed": False,
                "editing_software_opened": False,
            },
            "generation_status": "generated_local_editor_replacement_instruction_bundle_pending_human_confirmation",
            "manual_review_required": True,
            "human_confirmation_required": True,
            "review_required": True,
        }

    def _build_editor_replacement_execution_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_executions = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        command_count = 0
        ready_after_instruction_gate_count = 0
        approved_count = 0
        blocked_count = 0
        blocked_pending_count = 0
        missing_proxy_count = 0
        executable_after_approval_count = 0
        executed_count = 0
        approval_present_count = 0
        approval_valid_count = 0
        approved_boundary_count = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            execution = package.get("editor_replacement_execution", {})
            if not isinstance(execution, dict):
                execution = {}
            execution_sources = [
                path
                for path in [
                    execution.get("manifest_path"),
                    execution.get("execution_plan_path"),
                    execution.get("audit_log_path"),
                    execution.get("approval_request_path"),
                    execution.get("readme_path"),
                    execution.get("human_execution_approval_path")
                    if execution.get("human_execution_approval_present") is True
                    else None,
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(execution_sources)
            validation_status = execution.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            count = int(execution.get("command_count") or 0)
            ready = int(execution.get("ready_after_instruction_gate_count") or 0)
            approved = int(execution.get("human_execution_approved_count") or 0)
            blocked = int(execution.get("blocked_execution_count") or 0)
            blocked_pending = int(execution.get("blocked_pending_approval_count") or 0)
            missing_proxy = int(execution.get("blocked_proxy_media_missing_count") or 0)
            executable = int(execution.get("executable_after_approval_count") or 0)
            executed = int(execution.get("executed_count") or 0)
            approval_present = execution.get("human_execution_approval_present") is True
            approval_valid = execution.get("human_execution_approval_valid") is True
            boundary_state = execution.get("editor_replacement_execution")
            if boundary_state == "approved_but_not_executed_by_default":
                approved_boundary_count += 1
            command_count += count
            ready_after_instruction_gate_count += ready
            approved_count += approved
            blocked_count += blocked
            blocked_pending_count += blocked_pending
            missing_proxy_count += missing_proxy
            executable_after_approval_count += executable
            executed_count += executed
            approval_present_count += 1 if approval_present else 0
            approval_valid_count += 1 if approval_valid else 0
            platform_executions.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "manifest_path": execution.get("manifest_path"),
                    "execution_plan_path": execution.get("execution_plan_path"),
                    "audit_log_path": execution.get("audit_log_path"),
                    "approval_request_path": execution.get("approval_request_path"),
                    "readme_path": execution.get("readme_path"),
                    "human_execution_approval_path": execution.get("human_execution_approval_path"),
                    "human_execution_approval_present": approval_present,
                    "human_execution_approval_valid": approval_valid,
                    "command_count": count,
                    "ready_after_instruction_gate_count": ready,
                    "human_execution_approved_count": approved,
                    "blocked_execution_count": blocked,
                    "blocked_pending_approval_count": blocked_pending,
                    "blocked_proxy_media_missing_count": missing_proxy,
                    "executable_after_approval_count": executable,
                    "executed_count": executed,
                    "ready_asset_ids": execution.get("ready_asset_ids", []),
                    "approved_asset_ids": execution.get("approved_asset_ids", []),
                    "blocked_asset_ids": execution.get("blocked_asset_ids", []),
                    "executable_asset_ids": execution.get("executable_asset_ids", []),
                    "validation": {
                        "status": validation_status,
                        "human_execution_approval_required": execution.get("human_execution_approval_required") is True,
                        "human_execution_approval_present": approval_present,
                        "human_execution_approval_valid": approval_valid,
                        "replacement_execution_performed": execution.get("replacement_execution_performed") is True,
                        "editing_software_opened": execution.get("editing_software_opened") is True,
                        "project_file_mutation_performed": execution.get("project_file_mutation_performed") is True,
                    },
                    "source_artifacts": execution_sources,
                    "review_required": True,
                    "human_execution_approval_required": True,
                }
            )

        boundary_state = (
            "approved_but_not_executed_by_default"
            if approved_boundary_count == len(platform_executions) and platform_executions
            else "blocked_pending_explicit_human_approval"
        )
        return {
            "schema_version": "phase4.editor_replacement_execution_bundle_manifest.v1",
            "artifact_type": "editor_replacement_execution_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/editor_replacement_execution_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": _dedupe(source_artifacts),
            "platform_executions": platform_executions,
            "export_boundary": {
                "editor_replacement_execution": boundary_state,
                "replacement_execution": "not_performed",
                "editing_software": "not_opened",
                "project_file_mutation": "not_performed",
                "requires_explicit_human_approval": True,
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
                "license_purchase": "not_performed",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_executions) and command_count > 0 else "NEEDS_REVIEW",
                "platform_count": len(platform_executions),
                "passed_platform_count": passed_platforms,
                "command_count": command_count,
                "ready_after_instruction_gate_count": ready_after_instruction_gate_count,
                "human_execution_approved_count": approved_count,
                "blocked_execution_count": blocked_count,
                "blocked_pending_approval_count": blocked_pending_count,
                "blocked_proxy_media_missing_count": missing_proxy_count,
                "executable_after_approval_count": executable_after_approval_count,
                "executed_count": executed_count,
                "human_execution_approval_required": True,
                "human_execution_approval_present_count": approval_present_count,
                "human_execution_approval_valid_count": approval_valid_count,
                "replacement_execution_performed": False,
                "editing_software_opened": False,
                "project_file_mutation_performed": False,
            },
            "generation_status": "generated_local_execution_adapter_bundle_pending_explicit_human_approval",
            "manual_review_required": True,
            "human_execution_approval_required": True,
            "review_required": True,
        }

    def _build_editor_project_mutation_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_mutations = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        execution_item_count = 0
        mutation_applied_count = 0
        blocked_mutation_count = 0
        blocked_pending_approval_count = 0
        blocked_execution_not_ready_count = 0
        blocked_proxy_media_missing_count = 0
        target_missing_count = 0
        approval_present_count = 0
        approval_valid_count = 0
        sandbox_patch_boundary_count = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            mutation = package.get("editor_project_mutation_sandbox", {})
            if not isinstance(mutation, dict):
                mutation = {}
            mutation_sources = [
                path
                for path in [
                    mutation.get("manifest_path"),
                    mutation.get("patched_project_path"),
                    mutation.get("mutation_diff_path"),
                    mutation.get("rollback_manifest_path"),
                    mutation.get("audit_log_path"),
                    mutation.get("final_review_checklist_path"),
                    mutation.get("readme_path"),
                    mutation.get("human_mutation_approval_path")
                    if mutation.get("human_mutation_approval_present") is True
                    else None,
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(mutation_sources)
            validation_status = mutation.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            item_count = int(mutation.get("execution_item_count") or 0)
            applied = int(mutation.get("mutation_applied_count") or 0)
            blocked = int(mutation.get("blocked_mutation_count") or 0)
            blocked_pending = int(mutation.get("blocked_pending_approval_count") or 0)
            blocked_execution = int(mutation.get("blocked_execution_not_ready_count") or 0)
            blocked_proxy = int(mutation.get("blocked_proxy_media_missing_count") or 0)
            target_missing = int(mutation.get("target_missing_count") or 0)
            approval_present = mutation.get("human_mutation_approval_present") is True
            approval_valid = mutation.get("human_mutation_approval_valid") is True
            boundary_state = mutation.get("editor_project_mutation_sandbox")
            if boundary_state == "sandbox_patch_generated_from_explicit_human_approval":
                sandbox_patch_boundary_count += 1
            execution_item_count += item_count
            mutation_applied_count += applied
            blocked_mutation_count += blocked
            blocked_pending_approval_count += blocked_pending
            blocked_execution_not_ready_count += blocked_execution
            blocked_proxy_media_missing_count += blocked_proxy
            target_missing_count += target_missing
            approval_present_count += 1 if approval_present else 0
            approval_valid_count += 1 if approval_valid else 0
            platform_mutations.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "manifest_path": mutation.get("manifest_path"),
                    "patched_project_path": mutation.get("patched_project_path"),
                    "mutation_diff_path": mutation.get("mutation_diff_path"),
                    "rollback_manifest_path": mutation.get("rollback_manifest_path"),
                    "audit_log_path": mutation.get("audit_log_path"),
                    "final_review_checklist_path": mutation.get("final_review_checklist_path"),
                    "readme_path": mutation.get("readme_path"),
                    "source_execution_manifest_path": mutation.get("source_execution_manifest_path"),
                    "source_execution_plan_path": mutation.get("source_execution_plan_path"),
                    "source_export_manifest_path": mutation.get("source_export_manifest_path"),
                    "source_project_path": mutation.get("source_project_path"),
                    "human_mutation_approval_path": mutation.get("human_mutation_approval_path"),
                    "human_mutation_approval_present": approval_present,
                    "human_mutation_approval_valid": approval_valid,
                    "execution_item_count": item_count,
                    "mutation_applied_count": applied,
                    "blocked_mutation_count": blocked,
                    "blocked_pending_approval_count": blocked_pending,
                    "blocked_execution_not_ready_count": blocked_execution,
                    "blocked_proxy_media_missing_count": blocked_proxy,
                    "target_missing_count": target_missing,
                    "mutated_asset_ids": mutation.get("mutated_asset_ids", []),
                    "blocked_asset_ids": mutation.get("blocked_asset_ids", []),
                    "validation": {
                        "status": validation_status,
                        "human_mutation_approval_required": mutation.get("human_mutation_approval_required") is True,
                        "human_mutation_approval_present": approval_present,
                        "human_mutation_approval_valid": approval_valid,
                        "patched_copy_generated": mutation.get("patched_copy_generated") is True,
                        "original_project_mutated": mutation.get("original_project_mutated") is True,
                        "replacement_execution_performed": mutation.get("replacement_execution_performed") is True,
                        "editing_software_opened": mutation.get("editing_software_opened") is True,
                    },
                    "source_artifacts": mutation_sources,
                    "review_required": True,
                    "human_mutation_approval_required": True,
                }
            )

        boundary_state = (
            "sandbox_patch_generated_from_explicit_human_approval"
            if sandbox_patch_boundary_count == len(platform_mutations) and platform_mutations
            else "blocked_pending_explicit_human_mutation_approval"
        )
        return {
            "schema_version": "phase4.editor_project_mutation_bundle_manifest.v1",
            "artifact_type": "editor_project_mutation_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/editor_project_mutation_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": _dedupe(source_artifacts),
            "platform_mutations": platform_mutations,
            "export_boundary": {
                "editor_project_mutation_sandbox": boundary_state,
                "original_project_mutation": "not_performed",
                "sandbox_project_mutation": "performed_on_patched_copy_only"
                if mutation_applied_count > 0
                else "not_performed",
                "replacement_execution": "not_performed",
                "editing_software": "not_opened",
                "project_file_mutation": "patched_copy_only_original_not_mutated",
                "requires_explicit_human_mutation_approval": True,
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
                "license_purchase": "not_performed",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_mutations) and execution_item_count > 0 else "NEEDS_REVIEW",
                "platform_count": len(platform_mutations),
                "passed_platform_count": passed_platforms,
                "execution_item_count": execution_item_count,
                "mutation_applied_count": mutation_applied_count,
                "blocked_mutation_count": blocked_mutation_count,
                "blocked_pending_approval_count": blocked_pending_approval_count,
                "blocked_execution_not_ready_count": blocked_execution_not_ready_count,
                "blocked_proxy_media_missing_count": blocked_proxy_media_missing_count,
                "target_missing_count": target_missing_count,
                "human_mutation_approval_required": True,
                "human_mutation_approval_present_count": approval_present_count,
                "human_mutation_approval_valid_count": approval_valid_count,
                "patched_copy_generated": passed_platforms == len(platform_mutations) and bool(platform_mutations),
                "original_project_mutated": False,
                "replacement_execution_performed": False,
                "editing_software_opened": False,
            },
            "generation_status": "generated_local_project_mutation_bundle_pending_final_human_review",
            "manual_review_required": True,
            "human_mutation_approval_required": True,
            "review_required": True,
        }

    def _build_editor_software_import_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_imports = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        import_item_count = 0
        ready_count = 0
        blocked_count = 0
        blocked_pending_approval_count = 0
        blocked_no_sandbox_patch_count = 0
        blocked_patched_project_missing_count = 0
        approval_present_count = 0
        approval_valid_count = 0
        approved_boundary_count = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            software_import = package.get("editor_software_import_executor", {})
            if not isinstance(software_import, dict):
                software_import = {}
            import_sources = [
                path
                for path in [
                    software_import.get("manifest_path"),
                    software_import.get("import_plan_path"),
                    software_import.get("import_commands_path"),
                    software_import.get("audit_log_path"),
                    software_import.get("rollback_safety_report_path"),
                    software_import.get("execution_request_path"),
                    software_import.get("readme_path"),
                    software_import.get("human_software_import_approval_path")
                    if software_import.get("human_software_import_approval_present") is True
                    else None,
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(import_sources)
            validation_status = software_import.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            item_count = int(software_import.get("import_item_count") or 0)
            ready = int(software_import.get("ready_for_isolated_manual_import_count") or 0)
            blocked = int(software_import.get("blocked_import_count") or 0)
            blocked_pending = int(software_import.get("blocked_pending_approval_count") or 0)
            blocked_no_patch = int(software_import.get("blocked_no_sandbox_patch_count") or 0)
            blocked_missing_project = int(software_import.get("blocked_patched_project_missing_count") or 0)
            approval_present = software_import.get("human_software_import_approval_present") is True
            approval_valid = software_import.get("human_software_import_approval_valid") is True
            boundary_state = software_import.get("editor_software_import_executor")
            if boundary_state == "approved_for_isolated_manual_import_not_executed":
                approved_boundary_count += 1
            import_item_count += item_count
            ready_count += ready
            blocked_count += blocked
            blocked_pending_approval_count += blocked_pending
            blocked_no_sandbox_patch_count += blocked_no_patch
            blocked_patched_project_missing_count += blocked_missing_project
            approval_present_count += 1 if approval_present else 0
            approval_valid_count += 1 if approval_valid else 0
            platform_imports.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "manifest_path": software_import.get("manifest_path"),
                    "import_plan_path": software_import.get("import_plan_path"),
                    "import_commands_path": software_import.get("import_commands_path"),
                    "audit_log_path": software_import.get("audit_log_path"),
                    "rollback_safety_report_path": software_import.get("rollback_safety_report_path"),
                    "execution_request_path": software_import.get("execution_request_path"),
                    "readme_path": software_import.get("readme_path"),
                    "source_mutation_manifest_path": software_import.get("source_mutation_manifest_path"),
                    "source_mutation_diff_path": software_import.get("source_mutation_diff_path"),
                    "source_rollback_manifest_path": software_import.get("source_rollback_manifest_path"),
                    "source_patched_project_path": software_import.get("source_patched_project_path"),
                    "human_software_import_approval_path": software_import.get("human_software_import_approval_path"),
                    "human_software_import_approval_present": approval_present,
                    "human_software_import_approval_valid": approval_valid,
                    "target_editor": software_import.get("target_editor"),
                    "import_item_count": item_count,
                    "ready_for_isolated_manual_import_count": ready,
                    "blocked_import_count": blocked,
                    "blocked_pending_approval_count": blocked_pending,
                    "blocked_no_sandbox_patch_count": blocked_no_patch,
                    "blocked_patched_project_missing_count": blocked_missing_project,
                    "executed_count": int(software_import.get("executed_count") or 0),
                    "editing_software_opened_count": int(software_import.get("editing_software_opened_count") or 0),
                    "ready_asset_ids": software_import.get("ready_asset_ids", []),
                    "blocked_asset_ids": software_import.get("blocked_asset_ids", []),
                    "validation": {
                        "status": validation_status,
                        "human_software_import_approval_required": software_import.get(
                            "human_software_import_approval_required"
                        )
                        is True,
                        "human_software_import_approval_present": approval_present,
                        "human_software_import_approval_valid": approval_valid,
                        "software_import_execution_performed": software_import.get(
                            "software_import_execution_performed"
                        )
                        is True,
                        "editing_software_opened": software_import.get("editing_software_opened") is True,
                        "project_file_mutation_performed": software_import.get(
                            "project_file_mutation_performed"
                        )
                        is True,
                        "original_project_mutated": software_import.get("original_project_mutated") is True,
                        "replacement_execution_performed": software_import.get(
                            "replacement_execution_performed"
                        )
                        is True,
                        "isolated_manual_launch_required": software_import.get(
                            "isolated_manual_launch_required"
                        )
                        is True,
                    },
                    "source_artifacts": import_sources,
                    "review_required": True,
                    "human_software_import_approval_required": True,
                }
            )

        boundary_state = (
            "approved_for_isolated_manual_import_not_executed"
            if approved_boundary_count == len(platform_imports) and platform_imports
            else "blocked_pending_explicit_human_software_import_approval"
        )
        return {
            "schema_version": "phase4.editor_software_import_bundle_manifest.v1",
            "artifact_type": "editor_software_import_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/editor_software_import_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": _dedupe(source_artifacts),
            "platform_imports": platform_imports,
            "export_boundary": {
                "editor_software_import_executor": boundary_state,
                "software_import_execution": "not_performed",
                "editing_software": "not_opened",
                "project_file_mutation": "not_performed_by_executor",
                "original_project_mutation": "not_performed",
                "replacement_execution": "not_performed",
                "requires_explicit_human_software_import_approval": True,
                "external_software_isolation": "required_before_manual_launch",
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
                "license_purchase": "not_performed",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_imports) and import_item_count > 0 else "NEEDS_REVIEW",
                "platform_count": len(platform_imports),
                "passed_platform_count": passed_platforms,
                "import_item_count": import_item_count,
                "ready_for_isolated_manual_import_count": ready_count,
                "blocked_import_count": blocked_count,
                "blocked_pending_approval_count": blocked_pending_approval_count,
                "blocked_no_sandbox_patch_count": blocked_no_sandbox_patch_count,
                "blocked_patched_project_missing_count": blocked_patched_project_missing_count,
                "human_software_import_approval_required": True,
                "human_software_import_approval_present_count": approval_present_count,
                "human_software_import_approval_valid_count": approval_valid_count,
                "software_import_execution_performed": False,
                "editing_software_opened": False,
                "project_file_mutation_performed": False,
                "original_project_mutated": False,
                "replacement_execution_performed": False,
                "isolated_manual_launch_required": True,
            },
            "generation_status": "generated_local_editor_software_import_bundle_pending_explicit_human_launch",
            "manual_review_required": True,
            "human_software_import_approval_required": True,
            "review_required": True,
        }

    def _build_editor_software_real_runner_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_runners = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        runner_item_count = 0
        ready_count = 0
        blocked_count = 0
        approval_present_count = 0
        approval_valid_count = 0
        approved_boundary_count = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            real_runner = package.get("editor_software_real_runner_sandbox", {})
            if not isinstance(real_runner, dict):
                real_runner = {}
            runner_sources = [
                path
                for path in [
                    real_runner.get("manifest_path"),
                    real_runner.get("environment_snapshot_path"),
                    real_runner.get("launch_plan_path"),
                    real_runner.get("command_preview_path"),
                    real_runner.get("audit_log_path"),
                    real_runner.get("evidence_manifest_path"),
                    real_runner.get("approval_request_path"),
                    real_runner.get("readme_path"),
                    real_runner.get("human_real_run_approval_path")
                    if real_runner.get("human_real_run_approval_present") is True
                    else None,
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(runner_sources)
            validation_status = real_runner.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            item_count = int(real_runner.get("runner_item_count") or 0)
            ready = int(real_runner.get("ready_for_manual_external_sandbox_launch_count") or 0)
            blocked = int(real_runner.get("blocked_runner_count") or 0)
            approval_present = real_runner.get("human_real_run_approval_present") is True
            approval_valid = real_runner.get("human_real_run_approval_valid") is True
            boundary_state = real_runner.get("editor_software_real_runner_sandbox")
            if boundary_state == "approved_for_manual_external_sandbox_launch_not_executed":
                approved_boundary_count += 1
            runner_item_count += item_count
            ready_count += ready
            blocked_count += blocked
            approval_present_count += 1 if approval_present else 0
            approval_valid_count += 1 if approval_valid else 0
            platform_runners.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "manifest_path": real_runner.get("manifest_path"),
                    "environment_snapshot_path": real_runner.get("environment_snapshot_path"),
                    "launch_plan_path": real_runner.get("launch_plan_path"),
                    "command_preview_path": real_runner.get("command_preview_path"),
                    "audit_log_path": real_runner.get("audit_log_path"),
                    "evidence_manifest_path": real_runner.get("evidence_manifest_path"),
                    "approval_request_path": real_runner.get("approval_request_path"),
                    "readme_path": real_runner.get("readme_path"),
                    "source_import_manifest_path": real_runner.get("source_import_manifest_path"),
                    "source_import_plan_path": real_runner.get("source_import_plan_path"),
                    "source_import_commands_path": real_runner.get("source_import_commands_path"),
                    "source_rollback_safety_report_path": real_runner.get(
                        "source_rollback_safety_report_path"
                    ),
                    "source_patched_project_path": real_runner.get("source_patched_project_path"),
                    "human_real_run_approval_path": real_runner.get("human_real_run_approval_path"),
                    "human_real_run_approval_present": approval_present,
                    "human_real_run_approval_valid": approval_valid,
                    "target_editor": real_runner.get("target_editor"),
                    "runner_item_count": item_count,
                    "ready_for_manual_external_sandbox_launch_count": ready,
                    "blocked_runner_count": blocked,
                    "launched_count": int(real_runner.get("launched_count") or 0),
                    "process_spawned_count": int(real_runner.get("process_spawned_count") or 0),
                    "editing_software_opened_count": int(real_runner.get("editing_software_opened_count") or 0),
                    "ready_asset_ids": real_runner.get("ready_asset_ids", []),
                    "blocked_asset_ids": real_runner.get("blocked_asset_ids", []),
                    "validation": {
                        "status": validation_status,
                        "human_real_run_approval_required": real_runner.get("human_real_run_approval_required")
                        is True,
                        "human_real_run_approval_present": approval_present,
                        "human_real_run_approval_valid": approval_valid,
                        "real_software_launch_performed": real_runner.get("real_software_launch_performed")
                        is True,
                        "software_import_execution_performed": real_runner.get(
                            "software_import_execution_performed"
                        )
                        is True,
                        "editing_software_opened": real_runner.get("editing_software_opened") is True,
                        "project_file_mutation_performed": real_runner.get(
                            "project_file_mutation_performed"
                        )
                        is True,
                        "process_spawned": real_runner.get("process_spawned") is True,
                        "manual_external_launch_required": real_runner.get("manual_external_launch_required")
                        is True,
                    },
                    "source_artifacts": runner_sources,
                    "review_required": True,
                    "human_real_run_approval_required": True,
                }
            )

        boundary_state = (
            "approved_for_manual_external_sandbox_launch_not_executed"
            if approved_boundary_count == len(platform_runners) and platform_runners
            else "blocked_pending_explicit_human_real_run_approval"
        )
        return {
            "schema_version": "phase4.editor_software_real_runner_bundle_manifest.v1",
            "artifact_type": "editor_software_real_runner_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/editor_software_real_runner_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": _dedupe(source_artifacts),
            "platform_runners": platform_runners,
            "export_boundary": {
                "editor_software_real_runner_sandbox": boundary_state,
                "real_software_launch": "not_performed",
                "software_import_execution": "not_performed",
                "editing_software": "not_opened",
                "project_file_mutation": "not_performed_by_runner",
                "original_project_mutation": "not_performed",
                "replacement_execution": "not_performed",
                "requires_explicit_human_real_run_approval": True,
                "external_process_isolation": "required_before_human_launch",
                "process_spawn": "not_performed",
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
                "license_purchase": "not_performed",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_runners) and runner_item_count > 0 else "NEEDS_REVIEW",
                "platform_count": len(platform_runners),
                "passed_platform_count": passed_platforms,
                "runner_item_count": runner_item_count,
                "ready_for_manual_external_sandbox_launch_count": ready_count,
                "blocked_runner_count": blocked_count,
                "human_real_run_approval_required": True,
                "human_real_run_approval_present_count": approval_present_count,
                "human_real_run_approval_valid_count": approval_valid_count,
                "real_software_launch_performed": False,
                "software_import_execution_performed": False,
                "editing_software_opened": False,
                "project_file_mutation_performed": False,
                "process_spawned": False,
                "manual_external_launch_required": True,
                "external_process_isolation_required": True,
            },
            "generation_status": "generated_local_editor_software_real_runner_bundle_pending_explicit_human_launch",
            "manual_review_required": True,
            "human_real_run_approval_required": True,
            "review_required": True,
        }

    def _build_editor_software_run_evidence_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_evidence = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        evidence_item_count = 0
        ingested_count = 0
        blocked_count = 0
        result_present_count = 0
        result_valid_count = 0
        rollback_required_count = 0
        ingested_boundary_count = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            evidence = package.get("editor_software_run_evidence", {})
            if not isinstance(evidence, dict):
                evidence = {}
            evidence_sources = [
                path
                for path in [
                    evidence.get("manifest_path"),
                    evidence.get("validation_report_path"),
                    evidence.get("rollback_decision_report_path"),
                    evidence.get("checklist_path"),
                    evidence.get("readme_path"),
                    evidence.get("human_real_run_result_path")
                    if evidence.get("human_real_run_result_present") is True
                    else None,
                    *evidence.get("evidence_files", []),
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(evidence_sources)
            validation_status = evidence.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            item_count = int(evidence.get("evidence_item_count") or 0)
            ingested = int(evidence.get("human_real_run_evidence_ingested_count") or 0)
            blocked = int(evidence.get("blocked_evidence_count") or 0)
            result_present = evidence.get("human_real_run_result_present") is True
            result_valid = evidence.get("human_real_run_result_valid") is True
            rollback_required = bool(evidence.get("rollback_required_count"))
            boundary_state = evidence.get("editor_software_run_evidence")
            if boundary_state == "human_evidence_ingested_no_automation_execution":
                ingested_boundary_count += 1
            evidence_item_count += item_count
            ingested_count += ingested
            blocked_count += blocked
            result_present_count += 1 if result_present else 0
            result_valid_count += 1 if result_valid else 0
            rollback_required_count += 1 if rollback_required else 0
            platform_evidence.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "manifest_path": evidence.get("manifest_path"),
                    "validation_report_path": evidence.get("validation_report_path"),
                    "rollback_decision_report_path": evidence.get("rollback_decision_report_path"),
                    "checklist_path": evidence.get("checklist_path"),
                    "readme_path": evidence.get("readme_path"),
                    "source_runner_manifest_path": evidence.get("source_runner_manifest_path"),
                    "source_launch_plan_path": evidence.get("source_launch_plan_path"),
                    "source_command_preview_path": evidence.get("source_command_preview_path"),
                    "source_runner_evidence_manifest_path": evidence.get("source_runner_evidence_manifest_path"),
                    "human_real_run_result_path": evidence.get("human_real_run_result_path"),
                    "human_real_run_result_present": result_present,
                    "human_real_run_result_valid": result_valid,
                    "editor_software_run_evidence": boundary_state,
                    "evidence_item_count": item_count,
                    "human_real_run_evidence_ingested_count": ingested,
                    "blocked_evidence_count": blocked,
                    "evidence_file_count": int(evidence.get("evidence_file_count") or 0),
                    "existing_evidence_file_count": int(evidence.get("existing_evidence_file_count") or 0),
                    "missing_evidence_file_count": int(evidence.get("missing_evidence_file_count") or 0),
                    "rollback_required_count": int(evidence.get("rollback_required_count") or 0),
                    "rollback_decision": evidence.get("rollback_decision"),
                    "evidence_files": evidence.get("evidence_files", []),
                    "missing_evidence_files": evidence.get("missing_evidence_files", []),
                    "validation": {
                        "status": validation_status,
                        "human_real_run_result_required": evidence.get("human_real_run_result_required") is True,
                        "human_real_run_result_present": result_present,
                        "human_real_run_result_valid": result_valid,
                        "real_software_launch_performed_by_automation": evidence.get(
                            "real_software_launch_performed_by_automation"
                        )
                        is True,
                        "software_import_execution_performed_by_automation": evidence.get(
                            "software_import_execution_performed_by_automation"
                        )
                        is True,
                        "editing_software_opened_by_automation": evidence.get(
                            "editing_software_opened_by_automation"
                        )
                        is True,
                        "project_file_mutation_performed_by_automation": evidence.get(
                            "project_file_mutation_performed_by_automation"
                        )
                        is True,
                        "process_spawned_by_automation": evidence.get("process_spawned_by_automation") is True,
                        "upload_performed": evidence.get("upload_performed") is True,
                        "publishing_performed": evidence.get("publishing_performed") is True,
                    },
                    "source_artifacts": evidence_sources,
                    "review_required": True,
                    "human_real_run_result_required": True,
                }
            )

        boundary_state = (
            "human_evidence_ingested_no_automation_execution"
            if ingested_boundary_count == len(platform_evidence) and platform_evidence
            else "blocked_pending_human_real_run_result"
        )
        return {
            "schema_version": "phase4.editor_software_run_evidence_bundle_manifest.v1",
            "artifact_type": "editor_software_run_evidence_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/editor_software_run_evidence_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": _dedupe(source_artifacts),
            "platform_evidence": platform_evidence,
            "export_boundary": {
                "editor_software_run_evidence": boundary_state,
                "real_software_launch_by_automation": "not_performed",
                "software_import_execution_by_automation": "not_performed",
                "editing_software": "not_opened_by_automation",
                "project_file_mutation": "not_performed_by_evidence_ingest",
                "original_project_mutation": "not_performed",
                "replacement_execution_by_automation": "not_performed",
                "process_spawn": "not_performed",
                "evidence_ingest_only": True,
                "requires_human_real_run_result": True,
                "asset_download": "not_performed",
                "external_asset_search": "not_performed",
                "license_purchase": "not_performed",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_evidence) and evidence_item_count > 0 else "NEEDS_REVIEW",
                "platform_count": len(platform_evidence),
                "passed_platform_count": passed_platforms,
                "evidence_item_count": evidence_item_count,
                "human_real_run_evidence_ingested_count": ingested_count,
                "blocked_evidence_count": blocked_count,
                "human_real_run_result_required": True,
                "human_real_run_result_present_count": result_present_count,
                "human_real_run_result_valid_count": result_valid_count,
                "rollback_required_count": rollback_required_count,
                "real_software_launch_performed_by_automation": False,
                "software_import_execution_performed_by_automation": False,
                "editing_software_opened_by_automation": False,
                "project_file_mutation_performed_by_automation": False,
                "process_spawned_by_automation": False,
                "upload_performed": False,
                "publishing_performed": False,
            },
            "generation_status": "generated_local_editor_software_run_evidence_bundle_pending_human_result",
            "manual_review_required": True,
            "human_real_run_result_required": True,
            "review_required": True,
        }

    def _build_edit_project_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_projects = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            deliverables = package.get("deliverables", {})
            edit_project = package.get("edit_project", {})
            if not isinstance(deliverables, dict):
                deliverables = {}
            if not isinstance(edit_project, dict):
                edit_project = {}
            project_sources = [
                path
                for path in [
                    deliverables.get("edit_timeline"),
                    deliverables.get("edit_manifest"),
                    deliverables.get("draft_cut_edl"),
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(project_sources)
            validation_status = edit_project.get("validation_status")
            if validation_status == "PASSED":
                passed_platforms += 1
            platform_projects.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "aspect_ratio": package.get("aspect_ratio"),
                    "duration_seconds": edit_project.get("duration_seconds", 0),
                    "frame_rate": edit_project.get("frame_rate", 0),
                    "timeline_path": deliverables.get("edit_timeline"),
                    "manifest_path": deliverables.get("edit_manifest"),
                    "edl_path": deliverables.get("draft_cut_edl"),
                    "track_summary": edit_project.get("track_summary", {}),
                    "validation": {
                        "status": validation_status,
                        "video_duration_matches": edit_project.get("video_duration_matches") is True,
                        "audio_duration_matches": edit_project.get("audio_duration_matches") is True,
                        "subtitle_duration_matches": edit_project.get("subtitle_duration_matches") is True,
                    },
                    "source_artifacts": project_sources,
                    "review_required": True,
                }
            )

        return {
            "schema_version": "phase4.edit_project_bundle_manifest.v1",
            "artifact_type": "edit_project_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/edit_project_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": source_artifacts,
            "platform_projects": platform_projects,
            "export_boundary": {
                "edit_project_generation": "performed_locally_draft_no_editing_software",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_projects) else "NEEDS_REVIEW",
                "platform_count": len(platform_projects),
                "passed_platform_count": passed_platforms,
            },
            "generation_status": "generated_local_edit_timeline_bundle_pending_human_review",
            "manual_review_required": True,
            "review_required": True,
        }

    def _build_export_project_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_projects = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            export_project = package.get("export_project", {})
            if not isinstance(export_project, dict):
                export_project = {}
            project_sources = [
                path
                for path in [
                    export_project.get("project_path"),
                    export_project.get("readme_path"),
                    export_project.get("offline_report_path"),
                    export_project.get("manifest_path"),
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(project_sources)
            validation = export_project.get("validation")
            validation_status = validation.get("status") if isinstance(validation, dict) else None
            if validation_status == "PASSED":
                passed_platforms += 1
            platform_projects.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "project_format": export_project.get("project_format"),
                    "project_path": export_project.get("project_path"),
                    "readme_path": export_project.get("readme_path"),
                    "offline_report_path": export_project.get("offline_report_path"),
                    "manifest_path": export_project.get("manifest_path"),
                    "duration_seconds": export_project.get("duration_seconds", 0),
                    "track_summary": export_project.get("track_summary", {}),
                    "validation": validation if isinstance(validation, dict) else {},
                    "source_artifacts": project_sources,
                    "review_required": True,
                }
            )

        return {
            "schema_version": "phase4.export_project_bundle_manifest.v1",
            "artifact_type": "export_project_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/export_project_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": source_artifacts,
            "platform_projects": platform_projects,
            "export_boundary": {
                "export_project_generation": "performed_locally_draft_no_editing_software",
                "editing_software": "not_opened",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_projects) else "NEEDS_REVIEW",
                "platform_count": len(platform_projects),
                "passed_platform_count": passed_platforms,
            },
            "generation_status": "generated_local_export_project_bundle_pending_human_review",
            "manual_review_required": True,
            "review_required": True,
        }

    def _build_project_bundle_manifest(self, video_production_package: dict[str, Any]) -> dict[str, Any]:
        platform_bundles = []
        source_artifacts: list[str] = []
        passed_platforms = 0
        for package in video_production_package.get("platform_packages", []):
            if not isinstance(package, dict):
                continue
            platform = package.get("platform")
            if platform not in {"douyin", "shipinhao", "bilibili"}:
                continue
            project_bundle = package.get("project_bundle", {})
            if not isinstance(project_bundle, dict):
                project_bundle = {}
            bundle_sources = [
                path
                for path in [
                    project_bundle.get("bundle_path"),
                    project_bundle.get("manifest_path"),
                    project_bundle.get("file_manifest_path"),
                    project_bundle.get("readme_path"),
                ]
                if isinstance(path, str)
            ]
            source_artifacts.extend(bundle_sources)
            validation = project_bundle.get("validation")
            validation_status = validation.get("status") if isinstance(validation, dict) else None
            if validation_status == "PASSED":
                passed_platforms += 1
            platform_bundles.append(
                {
                    "platform": platform,
                    "platform_label": package.get("platform_label"),
                    "bundle_format": project_bundle.get("bundle_format"),
                    "bundle_path": project_bundle.get("bundle_path"),
                    "manifest_path": project_bundle.get("manifest_path"),
                    "file_manifest_path": project_bundle.get("file_manifest_path"),
                    "readme_path": project_bundle.get("readme_path"),
                    "bundle_summary": project_bundle.get("bundle_summary", {}),
                    "validation": validation if isinstance(validation, dict) else {},
                    "source_artifacts": bundle_sources,
                    "review_required": True,
                }
            )

        return {
            "schema_version": "phase4.project_bundle_bundle_manifest.v1",
            "artifact_type": "project_bundle_bundle",
            "run_id": self.context.run_id,
            "topic": self.context.topic,
            "manifest_path": "final/project_bundle_manifest.json",
            "video_production_package": "final/video_production_package.json",
            "platforms": video_production_package.get("video_platforms", []),
            "source_artifacts": source_artifacts,
            "platform_bundles": platform_bundles,
            "export_boundary": {
                "project_bundle_generation": "performed_locally_draft_no_editing_software",
                "editing_software": "not_opened",
                "publishing": "not_performed",
                "upload": "not_performed",
            },
            "validation": {
                "status": "PASSED" if passed_platforms == len(platform_bundles) else "NEEDS_REVIEW",
                "platform_count": len(platform_bundles),
                "passed_platform_count": passed_platforms,
            },
            "generation_status": "generated_local_project_bundle_bundle_pending_human_review",
            "manual_review_required": True,
            "review_required": True,
        }

    def _execution_mode_summary(self) -> str:
        modes = {item.get("execution_mode", "template") for item in self.task_runs_by_step.values()}
        if not modes:
            return "pending"
        if modes == {"agent-local"}:
            return "agent-local"
        if modes == {"template"}:
            return "template"
        return "mixed agent-local/template"

    def _workflow_run(self) -> dict[str, Any]:
        artifacts = [item["path"] for item in self.artifacts_by_path.values()] + list(self.final_artifact_paths)
        note = self._run_note()
        return {
            "run_id": self.context.run_id,
            "workflow_id": self.context.workflow.id,
            "workflow": asdict(self.context.workflow),
            "status": self.workflow_status,
            "created_at": self.context.created_at,
            "updated_at": _utc_now_iso(),
            "topic": self.context.topic,
            "platforms": self.context.platforms,
            "input_attachments": self.context.input_attachments,
            "tasks": self.task_specs,
            "task_runs": [self.task_runs_by_step[step.id] for step in self.context.workflow.steps if step.id in self.task_runs_by_step],
            "artifacts": artifacts,
            "failures": self.failures,
            "repair_log": self.repair_log,
            "retry_policy": self.retry_policy_config,
            "retry_events": self.retry_events,
            "note": note,
        }

    def _run_note(self) -> str:
        if self.workflow_status == "DONE":
            return "research-agent, topic-agent, outline-agent, asset-agent, cover-image-agent, storyboard-preview-agent, subtitle-timing-agent, voiceover-tts-agent, edit-project-agent, export-project-agent, project-bundle-agent, delivery-index-agent, artifact-store-agent, external-mirror-plan-agent, wechat-article-agent, xiaohongshu-note-agent, douyin-video-agent, shipinhao-video-agent, and bilibili-video-agent used run_agent(task_spec) when selected. No login, upload, or publishing actions were performed."
        if self.workflow_status == "FAILED" and self.current_failure is not None:
            return f"Workflow paused at {self.current_failure['task_id']} with {self.current_failure['failure_type']}."
        return "Workflow is running. State is persisted in the SQLite workflow ledger."


def render_artifact(
    step: WorkflowStep,
    output_path: str,
    context: RunContext,
    produced_artifacts: list[dict[str, Any]],
) -> Any:
    topic = context.topic
    if output_path == "research_report.md":
        return f"""# Research Report

Topic: {topic}

## Scope

This V1 step 1 runner creates a durable research placeholder for downstream agents.

## Findings

- The workflow can pass a shared topic into all downstream steps.
- External web research is not enabled in this step.
- Sources must be filled by a future research-agent implementation before production use.

## Source Policy

No external sources were fetched. Human review is required before publication.
"""

    if output_path == "sources.json":
        return {
            "topic": topic,
            "sources": [],
            "source_policy": "No external sources fetched in V1 step 1 template mode.",
            "review_required": True,
        }

    if output_path == "angle_pack.json":
        return {
            "topic": topic,
            "angles": [
                {
                    "name": "workflow-first content creation",
                    "audience": "content creators",
                    "hook": "Use a workflow to turn one topic into five platform-ready drafts.",
                }
            ],
            "review_required": True,
        }

    if output_path == "master_outline.md":
        return f"""# Master Outline

Topic: {topic}

## Core Claim

A unified content agent framework should share research and planning, then branch into platform-specific outputs.

## Sections

1. Why one framework is better than five separate systems.
2. What the global orchestrator controls.
3. How platform agents adapt the same idea for each channel.
4. Why validation and human approval matter before publishing.
"""

    if output_path == "wechat/article.md":
        return f"""# {topic}：为什么内容团队需要一个统一 Agent 框架

> 一套稳定的内容系统，不是让 agent 自由发挥，而是让流程负责边界，让专家负责产出。

## 先把生产线搭起来

同一个主题通常可以拆成公众号长文、小红书笔记、抖音短视频、视频号短视频和B站长视频。如果每个平台都单独做一套系统，研究、素材、审核和复盘都会重复。

## 总控负责节奏，平台负责表达

Global Orchestrator 先拆任务，再把研究、选题、大纲、平台改写和验证串起来。平台 Agent 只处理自己最擅长的表达方式。

## 发布前必须人工确认

当前内容为 V1 模板产物，没有真实来源抓取，也没有自动发布。正式发布前需要补充来源、事实核查和人工审核。
"""

    if output_path == "wechat/title_options.json":
        return {
            "platform": "wechat",
            "title_options": [
                f"{topic}：一套系统生成五个平台内容",
                "内容创作者为什么需要自己的 Agent 工作流",
                "从选题到视频脚本：统一内容生产线怎么搭",
            ],
            "review_required": True,
        }

    if output_path == "xiaohongshu/note.json":
        return {
            "title": "AI内容创作自动化",
            "content": "做自媒体最累的不是写一篇，而是同一个选题要反复改成公众号、小红书、抖音、视频号、B站五种形态。我的思路是先用一个总控 Agent 统一拆任务，再让不同平台 Agent 负责表达。研究、大纲、素材、审核都复用，平台差异最后再处理。当前是V1模板产物，发布前还要补真实来源和人工审核。",
            "tags": ["#内容创作", "#AI工具", "#自媒体运营", "#工作流", "#AI生成内容"],
            "cover_prompt": "A clean workspace showing a central workflow board branching into WeChat, Xiaohongshu, Douyin, WeChat Channels, and Bilibili content cards.",
            "best_time": "19:00-20:00",
            "cta": "你更想先自动化哪个平台？",
            "review_required": True,
        }

    if output_path == "xiaohongshu/cover_prompt.md":
        return f"# Cover Prompt\n\n主题：{topic}\n\n画面：一个中心控制台连接五个平台内容卡片，风格清晰、现代、适合小红书封面。\n"

    if output_path == "douyin/script.md":
        return f"""# Douyin Script

## Hook

你是不是也在把同一个选题反复改成五个平台版本？

## Voiceover

今天这个系统的关键不是多写几个 prompt，而是用一个总控 Agent 先拆任务，再让平台 Agent 分别生成公众号、小红书、抖音、视频号和B站内容。

## CTA

想看我下一步把它接成真实模型生成，评论区告诉我。
"""

    if output_path == "douyin/storyboard.json":
        return [
            {
                "scene": "opening",
                "visual": "Creator staring at five platform drafts.",
                "voiceover": "同一个选题，为什么要手动改五遍？",
                "duration_seconds": 3,
            },
            {
                "scene": "workflow",
                "visual": "Central orchestrator dispatches tasks.",
                "voiceover": "用一个总控 Agent 统一拆任务。",
                "duration_seconds": 6,
            },
        ]

    if output_path == "douyin/subtitles.srt":
        return "1\n00:00:00,000 --> 00:00:03,000\n同一个选题，为什么要手动改五遍？\n\n2\n00:00:03,000 --> 00:00:09,000\n用一个总控 Agent 统一拆任务，再分发给平台 Agent。\n"

    if output_path == "bilibili/script.md":
        return f"""# Bilibili Script

## Title

{topic}：从零搭一套多平台内容 Agent 工作流

## Opening

这一期我们不讲单个 prompt，而是讲一套能持续运行的内容生产系统。

## Main Sections

1. 总控 Agent 为什么必要。
2. 通用研究层如何复用。
3. 平台 Agent 如何适配不同内容形态。
4. validator 和人工审批为什么是底线。
"""

    if output_path == "bilibili/chapters.json":
        return [
            {"time": "00:00", "title": "为什么不要做五套系统"},
            {"time": "02:00", "title": "总控 Agent 的职责"},
            {"time": "05:00", "title": "平台插件化设计"},
            {"time": "08:00", "title": "下一步接入真实模型"},
        ]

    if output_path == "bilibili/description.md":
        return f"本期主题：{topic}\n\n内容为 V1 模板产物，用于验证 workflow runner，不代表最终发布稿。\n"

    if output_path == "review/fact_check.md":
        return "# Fact Check\n\n- Status: needs human review\n- External sources fetched: no\n- Unsupported factual claims: none in template claims beyond project architecture.\n"

    if output_path == "review/compliance.md":
        return "# Compliance Check\n\n- No publishing action performed.\n- No login or cookie refresh performed.\n- Human review required before platform use.\n"

    if output_path == "review/validation_report.json":
        return {
            "status": "PASSED",
            "mode": "template",
            "checked_artifacts": [item["path"] for item in produced_artifacts],
            "publish_actions_detected": False,
            "human_review_required": True,
            "notes": [
                "All declared step outputs before validation were produced.",
                "Semantic content quality is not validated in V1 step 1.",
            ],
        }

    return f"# {step.id}\n\nGenerated placeholder for `{output_path}`.\n"


def _artifact_kind(output_path: str) -> str:
    suffix = Path(output_path).suffix.lower()
    return {
        ".md": "markdown",
        ".json": "json",
        ".srt": "subtitle",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".webp": "image",
        ".wav": "audio",
        ".aiff": "audio",
        ".mp3": "audio",
        ".edl": "edit_decision_list",
        ".txt": "text",
    }.get(suffix, "file")


def _read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _asset_platform_plans(asset_plan: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(asset_plan, dict):
        return {}
    plans = asset_plan.get("platform_plans")
    if not isinstance(plans, list):
        return {}
    return {
        str(plan["platform"]): plan
        for plan in plans
        if isinstance(plan, dict) and plan.get("platform")
    }


def _asset_tasks_for_platform(asset_tasks: Any, platform: str) -> list[dict[str, Any]]:
    if not isinstance(asset_tasks, dict):
        return []
    tasks = asset_tasks.get("tasks")
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict) and task.get("platform") == platform]


def _media_assets_for_platform(media_asset_manifest: Any, platform: str) -> list[dict[str, Any]]:
    if not isinstance(media_asset_manifest, dict):
        return []
    assets = media_asset_manifest.get("assets")
    if not isinstance(assets, list):
        return []
    return [asset for asset in assets if isinstance(asset, dict) and asset.get("platform") == platform]


def _generated_assets_for_platform(run_dir: Path, platform: str) -> list[dict[str, Any]]:
    generated_assets: list[dict[str, Any]] = []

    cover_metadata_path = run_dir / "assets" / platform / "cover" / "cover_metadata.json"
    cover_metadata = _read_json_if_exists(cover_metadata_path)
    if isinstance(cover_metadata, dict):
        generated_assets.append(cover_metadata)

    storyboard_metadata_path = run_dir / "assets" / platform / "storyboard" / "storyboard_preview_metadata.json"
    storyboard_metadata = _read_json_if_exists(storyboard_metadata_path)
    if isinstance(storyboard_metadata, dict):
        preview_record = dict(storyboard_metadata)
        frames = preview_record.pop("frames", [])
        preview_record["metadata_path"] = f"assets/{platform}/storyboard/storyboard_preview_metadata.json"
        generated_assets.append(preview_record)
        if isinstance(frames, list):
            for frame in frames:
                if isinstance(frame, dict):
                    generated_assets.append(
                        frame
                        | {
                            "metadata_path": f"assets/{platform}/storyboard/storyboard_preview_metadata.json",
                            "preview_path": str(storyboard_metadata.get("path") or ""),
                        }
                    )

    return generated_assets


def _generated_media_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/cover/cover.png",
        f"assets/{platform}/cover/cover_metadata.json",
        f"assets/{platform}/storyboard/storyboard_preview.png",
        f"assets/{platform}/storyboard/storyboard_preview_metadata.json",
    ]
    storyboard_metadata = _read_json_if_exists(
        run_dir / "assets" / platform / "storyboard" / "storyboard_preview_metadata.json"
    )
    frames = storyboard_metadata.get("frames") if isinstance(storyboard_metadata, dict) else None
    if isinstance(frames, list):
        for frame in frames:
            if isinstance(frame, dict) and frame.get("path"):
                paths.append(str(frame["path"]))
    return paths


def _materialized_assets_for_platform(run_dir: Path, platform: str) -> list[dict[str, Any]]:
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "materials" / "material_manifest.json")
    if not isinstance(manifest, dict):
        return []
    assets = manifest.get("materialized_assets")
    if not isinstance(assets, list):
        return []
    enriched_assets = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        enriched_assets.append(
            asset
            | {
                "metadata_path": f"assets/{platform}/materials/material_manifest.json",
                "asset_family": "materialized_broll_reference",
            }
        )
    return enriched_assets


def _materialized_asset_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/materials/material_manifest.json",
        f"assets/{platform}/materials/README.md",
    ]
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "materials" / "material_manifest.json")
    assets = manifest.get("materialized_assets") if isinstance(manifest, dict) else None
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, dict) and asset.get("reference_path"):
                paths.append(str(asset["reference_path"]))
    return _dedupe(paths)


def _materialized_assets_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "materials" / "material_manifest.json")
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    summary = manifest.get("summary")
    assets = manifest.get("materialized_assets")
    reference_paths: list[str] = []
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, dict) and asset.get("reference_path"):
                reference_paths.append(str(asset["reference_path"]))
    return {
        "manifest_path": manifest.get("manifest_path"),
        "readme_path": manifest.get("readme_path"),
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "materialized_count": summary.get("materialized_count", 0) if isinstance(summary, dict) else 0,
        "broll_reference_count": summary.get("broll_reference_count", 0) if isinstance(summary, dict) else 0,
        "reference_paths": reference_paths,
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "licensed_final_media_required": validation.get("licensed_final_media_required") is True
        if isinstance(validation, dict)
        else True,
        "generation_status": manifest.get("generation_status"),
        "review_required": manifest.get("review_required") is True,
    }


def _licensed_media_ingest_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/licensed_media/ingest_manifest.json",
        f"assets/{platform}/licensed_media/README.md",
        f"assets/{platform}/licensed_media/review_handoff.md",
    ]
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json")
    if isinstance(manifest, dict):
        registry_path = manifest.get("human_media_registry_path")
        if manifest.get("human_media_registry_exists") is True and isinstance(registry_path, str):
            paths.append(registry_path)
        assets = manifest.get("licensed_media")
        if isinstance(assets, list):
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                for key in ["licensed_media_path", "license_proof_path"]:
                    path = asset.get(key)
                    if isinstance(path, str) and path:
                        paths.append(path)
    return _dedupe(paths)


def _licensed_media_ingest_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json")
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    summary = manifest.get("summary")
    assets = manifest.get("licensed_media")
    media_paths: list[str] = []
    proof_paths: list[str] = []
    pending_asset_ids: list[str] = []
    ready_asset_ids: list[str] = []
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_id = str(asset.get("asset_id") or "")
            media_path = asset.get("licensed_media_path")
            proof_path = asset.get("license_proof_path")
            if isinstance(media_path, str) and media_path:
                media_paths.append(media_path)
            if isinstance(proof_path, str) and proof_path:
                proof_paths.append(proof_path)
            if asset.get("intake_status") == "pending_human_media" and asset_id:
                pending_asset_ids.append(asset_id)
            if asset.get("ready_for_editor_replacement") is True and asset_id:
                ready_asset_ids.append(asset_id)
    return {
        "manifest_path": manifest.get("manifest_path"),
        "readme_path": manifest.get("readme_path"),
        "review_handoff_path": manifest.get("review_handoff_path"),
        "human_media_registry_path": manifest.get("human_media_registry_path"),
        "human_media_registry_exists": manifest.get("human_media_registry_exists") is True,
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "required_final_media_count": summary.get("required_final_media_count", 0) if isinstance(summary, dict) else 0,
        "pending_human_media_count": summary.get("pending_human_media_count", 0) if isinstance(summary, dict) else 0,
        "candidate_media_count": summary.get("candidate_media_count", 0) if isinstance(summary, dict) else 0,
        "ready_for_editor_replacement_count": summary.get("ready_for_editor_replacement_count", 0)
        if isinstance(summary, dict)
        else 0,
        "licensed_media_paths": media_paths,
        "license_proof_paths": proof_paths,
        "pending_asset_ids": pending_asset_ids,
        "ready_asset_ids": ready_asset_ids,
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "intake_complete": validation.get("intake_complete") is True if isinstance(validation, dict) else False,
        "licensed_final_media_required": validation.get("licensed_final_media_required") is True
        if isinstance(validation, dict)
        else True,
        "generation_status": manifest.get("generation_status"),
        "review_required": manifest.get("review_required") is True,
    }


def _licensed_media_proxy_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/licensed_media/proxy_manifest.json",
        f"assets/{platform}/licensed_media/replacement_suggestions.json",
        f"assets/{platform}/licensed_media/proxy/README.md",
    ]
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json")
    if isinstance(manifest, dict):
        source_artifacts = manifest.get("source_artifacts")
        if isinstance(source_artifacts, list):
            paths.extend([path for path in source_artifacts if isinstance(path, str)])
        assets = manifest.get("proxy_assets")
        if isinstance(assets, list):
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                for key in ["licensed_media_path", "license_proof_path", "proxy_media_path"]:
                    path = asset.get(key)
                    if isinstance(path, str) and path:
                        paths.append(path)
    return _dedupe(paths)


def _licensed_media_proxy_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json")
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    summary = manifest.get("summary")
    assets = manifest.get("proxy_assets")
    proxy_paths: list[str] = []
    media_paths: list[str] = []
    proof_paths: list[str] = []
    ready_asset_ids: list[str] = []
    pending_asset_ids: list[str] = []
    candidate_asset_ids: list[str] = []
    blocked_asset_ids: list[str] = []
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_id = str(asset.get("asset_id") or "")
            proxy_path = asset.get("proxy_media_path")
            media_path = asset.get("licensed_media_path")
            proof_path = asset.get("license_proof_path")
            replacement_status = str(asset.get("replacement_status") or "")
            if isinstance(proxy_path, str) and proxy_path:
                proxy_paths.append(proxy_path)
            if isinstance(media_path, str) and media_path:
                media_paths.append(media_path)
            if isinstance(proof_path, str) and proof_path:
                proof_paths.append(proof_path)
            if asset.get("editor_replacement_ready") is True and asset_id:
                ready_asset_ids.append(asset_id)
            if replacement_status == "pending_human_media" and asset_id:
                pending_asset_ids.append(asset_id)
            if replacement_status == "candidate_registered_pending_review" and asset_id:
                candidate_asset_ids.append(asset_id)
            if replacement_status.startswith("blocked_") and asset_id:
                blocked_asset_ids.append(asset_id)
    return {
        "manifest_path": manifest.get("manifest_path"),
        "replacement_suggestions_path": manifest.get("replacement_suggestions_path"),
        "readme_path": manifest.get("readme_path"),
        "proxy_dir": manifest.get("proxy_dir"),
        "licensed_media_ingest_manifest_path": manifest.get("licensed_media_ingest_manifest_path"),
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "required_final_media_count": summary.get("required_final_media_count", 0) if isinstance(summary, dict) else 0,
        "ready_source_media_count": summary.get("ready_source_media_count", 0) if isinstance(summary, dict) else 0,
        "proxy_copied_count": summary.get("proxy_copied_count", 0) if isinstance(summary, dict) else 0,
        "pending_human_media_count": summary.get("pending_human_media_count", 0) if isinstance(summary, dict) else 0,
        "candidate_pending_review_count": summary.get("candidate_pending_review_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_proxy_count": summary.get("blocked_proxy_count", 0) if isinstance(summary, dict) else 0,
        "editor_replacement_ready_count": summary.get("editor_replacement_ready_count", 0)
        if isinstance(summary, dict)
        else 0,
        "proxy_media_paths": proxy_paths,
        "licensed_media_paths": media_paths,
        "license_proof_paths": proof_paths,
        "ready_asset_ids": ready_asset_ids,
        "pending_asset_ids": pending_asset_ids,
        "candidate_asset_ids": candidate_asset_ids,
        "blocked_asset_ids": blocked_asset_ids,
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "proxy_copy_complete_for_ready_media": validation.get("proxy_copy_complete_for_ready_media") is True
        if isinstance(validation, dict)
        else False,
        "generation_status": manifest.get("generation_status"),
        "review_required": manifest.get("review_required") is True,
    }


def _editor_replacement_instruction_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/edit/replacement_instructions/instruction_manifest.json",
        f"assets/{platform}/edit/replacement_instructions/replacement_commands.json",
        f"assets/{platform}/edit/replacement_instructions/editor_import_template.fcpxml",
        f"assets/{platform}/edit/replacement_instructions/human_confirmation_checklist.md",
        f"assets/{platform}/edit/replacement_instructions/README.md",
    ]
    manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "replacement_instructions" / "instruction_manifest.json"
    )
    if isinstance(manifest, dict):
        source_artifacts = manifest.get("source_artifacts")
        if isinstance(source_artifacts, list):
            paths.extend([path for path in source_artifacts if isinstance(path, str)])
    return _dedupe(paths)


def _editor_replacement_instruction_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "replacement_instructions" / "instruction_manifest.json"
    )
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    summary = manifest.get("summary")
    instructions = manifest.get("instructions")
    ready_asset_ids: list[str] = []
    pending_asset_ids: list[str] = []
    blocked_asset_ids: list[str] = []
    if isinstance(instructions, list):
        for item in instructions:
            if not isinstance(item, dict):
                continue
            asset_id = str(item.get("asset_id") or "")
            instruction_status = str(item.get("instruction_status") or "")
            if item.get("can_execute_after_human_confirmation") is True and asset_id:
                ready_asset_ids.append(asset_id)
            if instruction_status == "pending_human_media" and asset_id:
                pending_asset_ids.append(asset_id)
            if instruction_status.startswith("blocked_") and asset_id:
                blocked_asset_ids.append(asset_id)
    return {
        "manifest_path": manifest.get("manifest_path"),
        "replacement_commands_path": manifest.get("replacement_commands_path"),
        "editor_import_template_path": manifest.get("editor_import_template_path"),
        "human_confirmation_checklist_path": manifest.get("human_confirmation_checklist_path"),
        "readme_path": manifest.get("readme_path"),
        "source_replacement_suggestions_path": manifest.get("source_replacement_suggestions_path"),
        "source_proxy_manifest_path": manifest.get("source_proxy_manifest_path"),
        "source_export_project_path": manifest.get("source_export_project_path"),
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "instruction_count": summary.get("instruction_count", 0) if isinstance(summary, dict) else 0,
        "ready_pending_human_confirmation_count": summary.get("ready_pending_human_confirmation_count", 0)
        if isinstance(summary, dict)
        else 0,
        "pending_human_media_count": summary.get("pending_human_media_count", 0) if isinstance(summary, dict) else 0,
        "blocked_instruction_count": summary.get("blocked_instruction_count", 0) if isinstance(summary, dict) else 0,
        "executable_after_human_confirmation_count": summary.get("executable_after_human_confirmation_count", 0)
        if isinstance(summary, dict)
        else 0,
        "human_confirmation_required_count": summary.get("human_confirmation_required_count", 0)
        if isinstance(summary, dict)
        else 0,
        "ready_asset_ids": ready_asset_ids,
        "pending_asset_ids": pending_asset_ids,
        "blocked_asset_ids": blocked_asset_ids,
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "human_confirmation_gate_active": validation.get("human_confirmation_gate_active") is True
        if isinstance(validation, dict)
        else False,
        "replacement_execution_performed": validation.get("replacement_execution_performed") is True
        if isinstance(validation, dict)
        else False,
        "editing_software_opened": validation.get("editing_software_opened") is True
        if isinstance(validation, dict)
        else False,
        "generation_status": manifest.get("generation_status"),
        "human_confirmation_required": manifest.get("human_confirmation_required") is True,
        "review_required": manifest.get("review_required") is True,
    }


def _editor_replacement_execution_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/edit/replacement_execution/execution_manifest.json",
        f"assets/{platform}/edit/replacement_execution/execution_plan.json",
        f"assets/{platform}/edit/replacement_execution/execution_audit_log.json",
        f"assets/{platform}/edit/replacement_execution/human_execution_approval_request.md",
        f"assets/{platform}/edit/replacement_execution/README.md",
    ]
    manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "replacement_execution" / "execution_manifest.json"
    )
    if isinstance(manifest, dict):
        if manifest.get("human_execution_approval_present") is True:
            approval_path = manifest.get("human_execution_approval_path")
            if isinstance(approval_path, str) and approval_path:
                paths.append(approval_path)
        source_artifacts = manifest.get("source_artifacts")
        if isinstance(source_artifacts, list):
            paths.extend([path for path in source_artifacts if isinstance(path, str)])
    return _dedupe(paths)


def _editor_replacement_execution_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "replacement_execution" / "execution_manifest.json"
    )
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    summary = manifest.get("summary")
    export_boundary = manifest.get("export_boundary")
    execution_items = manifest.get("execution_items")
    ready_asset_ids: list[str] = []
    approved_asset_ids: list[str] = []
    blocked_asset_ids: list[str] = []
    executable_asset_ids: list[str] = []
    if isinstance(execution_items, list):
        for item in execution_items:
            if not isinstance(item, dict):
                continue
            asset_id = str(item.get("asset_id") or "")
            if not asset_id:
                continue
            if item.get("command_ready_after_approval") is True:
                ready_asset_ids.append(asset_id)
            if item.get("human_execution_approved") is True:
                approved_asset_ids.append(asset_id)
            if str(item.get("execution_status") or "").startswith("blocked_"):
                blocked_asset_ids.append(asset_id)
            if item.get("execution_status") == "ready_for_manual_execution":
                executable_asset_ids.append(asset_id)
    return {
        "manifest_path": manifest.get("manifest_path"),
        "execution_plan_path": manifest.get("execution_plan_path"),
        "audit_log_path": manifest.get("audit_log_path"),
        "approval_request_path": manifest.get("approval_request_path"),
        "readme_path": manifest.get("readme_path"),
        "source_instruction_manifest_path": manifest.get("source_instruction_manifest_path"),
        "source_replacement_commands_path": manifest.get("source_replacement_commands_path"),
        "human_execution_approval_path": manifest.get("human_execution_approval_path"),
        "human_execution_approval_present": manifest.get("human_execution_approval_present") is True,
        "human_execution_approval_valid": manifest.get("human_execution_approval_valid") is True,
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "editor_replacement_execution": export_boundary.get("editor_replacement_execution")
        if isinstance(export_boundary, dict)
        else None,
        "command_count": summary.get("command_count", 0) if isinstance(summary, dict) else 0,
        "ready_after_instruction_gate_count": summary.get("ready_after_instruction_gate_count", 0)
        if isinstance(summary, dict)
        else 0,
        "human_execution_approved_count": summary.get("human_execution_approved_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_execution_count": summary.get("blocked_execution_count", 0) if isinstance(summary, dict) else 0,
        "blocked_pending_approval_count": summary.get("blocked_pending_approval_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_proxy_media_missing_count": summary.get("blocked_proxy_media_missing_count", 0)
        if isinstance(summary, dict)
        else 0,
        "executable_after_approval_count": summary.get("executable_after_approval_count", 0)
        if isinstance(summary, dict)
        else 0,
        "executed_count": summary.get("executed_count", 0) if isinstance(summary, dict) else 0,
        "ready_asset_ids": ready_asset_ids,
        "approved_asset_ids": approved_asset_ids,
        "blocked_asset_ids": blocked_asset_ids,
        "executable_asset_ids": executable_asset_ids,
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "human_execution_approval_required": validation.get("human_execution_approval_required") is True
        if isinstance(validation, dict)
        else True,
        "replacement_execution_performed": validation.get("replacement_execution_performed") is True
        if isinstance(validation, dict)
        else False,
        "editing_software_opened": validation.get("editing_software_opened") is True
        if isinstance(validation, dict)
        else False,
        "project_file_mutation_performed": validation.get("project_file_mutation_performed") is True
        if isinstance(validation, dict)
        else False,
        "generation_status": manifest.get("generation_status"),
        "review_required": manifest.get("review_required") is True,
    }


def _editor_project_mutation_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/edit/mutation_sandbox/mutation_manifest.json",
        f"assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml",
        f"assets/{platform}/edit/mutation_sandbox/mutation_diff.json",
        f"assets/{platform}/edit/mutation_sandbox/rollback_manifest.json",
        f"assets/{platform}/edit/mutation_sandbox/mutation_audit_log.json",
        f"assets/{platform}/edit/mutation_sandbox/human_final_review_checklist.md",
        f"assets/{platform}/edit/mutation_sandbox/README.md",
    ]
    manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "mutation_manifest.json"
    )
    if isinstance(manifest, dict):
        if manifest.get("human_mutation_approval_present") is True:
            approval_path = manifest.get("human_mutation_approval_path")
            if isinstance(approval_path, str) and approval_path:
                paths.append(approval_path)
        source_artifacts = manifest.get("source_artifacts")
        if isinstance(source_artifacts, list):
            paths.extend([path for path in source_artifacts if isinstance(path, str)])
    return _dedupe(paths)


def _editor_project_mutation_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "mutation_manifest.json"
    )
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    summary = manifest.get("summary")
    export_boundary = manifest.get("export_boundary")
    mutation_items = manifest.get("mutation_items")
    mutated_asset_ids: list[str] = []
    blocked_asset_ids: list[str] = []
    if isinstance(mutation_items, list):
        for item in mutation_items:
            if not isinstance(item, dict):
                continue
            asset_id = str(item.get("asset_id") or "")
            if not asset_id:
                continue
            if item.get("mutation_status") == "sandbox_patch_applied":
                mutated_asset_ids.append(asset_id)
            if str(item.get("mutation_status") or "").startswith("blocked_"):
                blocked_asset_ids.append(asset_id)
    return {
        "manifest_path": manifest.get("manifest_path"),
        "patched_project_path": manifest.get("patched_project_path"),
        "mutation_diff_path": manifest.get("mutation_diff_path"),
        "rollback_manifest_path": manifest.get("rollback_manifest_path"),
        "audit_log_path": manifest.get("audit_log_path"),
        "final_review_checklist_path": manifest.get("final_review_checklist_path"),
        "readme_path": manifest.get("readme_path"),
        "source_execution_manifest_path": manifest.get("source_execution_manifest_path"),
        "source_execution_plan_path": manifest.get("source_execution_plan_path"),
        "source_export_manifest_path": manifest.get("source_export_manifest_path"),
        "source_project_path": manifest.get("source_project_path"),
        "human_mutation_approval_path": manifest.get("human_mutation_approval_path"),
        "human_mutation_approval_present": manifest.get("human_mutation_approval_present") is True,
        "human_mutation_approval_valid": manifest.get("human_mutation_approval_valid") is True,
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "editor_project_mutation_sandbox": export_boundary.get("editor_project_mutation_sandbox")
        if isinstance(export_boundary, dict)
        else None,
        "execution_item_count": summary.get("execution_item_count", 0) if isinstance(summary, dict) else 0,
        "mutation_applied_count": summary.get("mutation_applied_count", 0) if isinstance(summary, dict) else 0,
        "blocked_mutation_count": summary.get("blocked_mutation_count", 0) if isinstance(summary, dict) else 0,
        "blocked_pending_approval_count": summary.get("blocked_pending_approval_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_execution_not_ready_count": summary.get("blocked_execution_not_ready_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_proxy_media_missing_count": summary.get("blocked_proxy_media_missing_count", 0)
        if isinstance(summary, dict)
        else 0,
        "target_missing_count": summary.get("target_missing_count", 0) if isinstance(summary, dict) else 0,
        "mutated_asset_ids": mutated_asset_ids,
        "blocked_asset_ids": blocked_asset_ids,
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "human_mutation_approval_required": validation.get("human_mutation_approval_required") is True
        if isinstance(validation, dict)
        else True,
        "patched_copy_generated": validation.get("patched_copy_generated") is True if isinstance(validation, dict) else False,
        "original_project_mutated": validation.get("original_project_mutated") is True if isinstance(validation, dict) else False,
        "replacement_execution_performed": validation.get("replacement_execution_performed") is True
        if isinstance(validation, dict)
        else False,
        "editing_software_opened": validation.get("editing_software_opened") is True
        if isinstance(validation, dict)
        else False,
        "generation_status": manifest.get("generation_status"),
        "review_required": manifest.get("review_required") is True,
    }


def _editor_software_import_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/edit/software_import_executor/import_executor_manifest.json",
        f"assets/{platform}/edit/software_import_executor/import_plan.json",
        f"assets/{platform}/edit/software_import_executor/import_commands.json",
        f"assets/{platform}/edit/software_import_executor/software_import_audit_log.json",
        f"assets/{platform}/edit/software_import_executor/rollback_safety_report.json",
        f"assets/{platform}/edit/software_import_executor/isolated_execution_request.md",
        f"assets/{platform}/edit/software_import_executor/README.md",
    ]
    manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "software_import_executor" / "import_executor_manifest.json"
    )
    if isinstance(manifest, dict):
        if manifest.get("human_software_import_approval_present") is True:
            approval_path = manifest.get("human_software_import_approval_path")
            if isinstance(approval_path, str) and approval_path:
                paths.append(approval_path)
        source_artifacts = manifest.get("source_artifacts")
        if isinstance(source_artifacts, list):
            paths.extend([path for path in source_artifacts if isinstance(path, str)])
    return _dedupe(paths)


def _editor_software_import_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "software_import_executor" / "import_executor_manifest.json"
    )
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    summary = manifest.get("summary")
    export_boundary = manifest.get("export_boundary")
    import_items = manifest.get("import_items")
    ready_asset_ids: list[str] = []
    blocked_asset_ids: list[str] = []
    if isinstance(import_items, list):
        for item in import_items:
            if not isinstance(item, dict):
                continue
            asset_id = str(item.get("asset_id") or "")
            if not asset_id:
                continue
            if item.get("import_status") == "ready_for_isolated_manual_import":
                ready_asset_ids.append(asset_id)
            if str(item.get("import_status") or "").startswith("blocked_"):
                blocked_asset_ids.append(asset_id)
    return {
        "manifest_path": manifest.get("manifest_path"),
        "import_plan_path": manifest.get("import_plan_path"),
        "import_commands_path": manifest.get("import_commands_path"),
        "audit_log_path": manifest.get("audit_log_path"),
        "rollback_safety_report_path": manifest.get("rollback_safety_report_path"),
        "execution_request_path": manifest.get("execution_request_path"),
        "readme_path": manifest.get("readme_path"),
        "source_mutation_manifest_path": manifest.get("source_mutation_manifest_path"),
        "source_mutation_diff_path": manifest.get("source_mutation_diff_path"),
        "source_rollback_manifest_path": manifest.get("source_rollback_manifest_path"),
        "source_patched_project_path": manifest.get("source_patched_project_path"),
        "human_software_import_approval_path": manifest.get("human_software_import_approval_path"),
        "human_software_import_approval_present": manifest.get("human_software_import_approval_present") is True,
        "human_software_import_approval_valid": manifest.get("human_software_import_approval_valid") is True,
        "target_editor": manifest.get("target_editor"),
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "editor_software_import_executor": export_boundary.get("editor_software_import_executor")
        if isinstance(export_boundary, dict)
        else None,
        "import_item_count": summary.get("import_item_count", 0) if isinstance(summary, dict) else 0,
        "ready_for_isolated_manual_import_count": summary.get("ready_for_isolated_manual_import_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_import_count": summary.get("blocked_import_count", 0) if isinstance(summary, dict) else 0,
        "blocked_pending_approval_count": summary.get("blocked_pending_approval_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_no_sandbox_patch_count": summary.get("blocked_no_sandbox_patch_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_patched_project_missing_count": summary.get("blocked_patched_project_missing_count", 0)
        if isinstance(summary, dict)
        else 0,
        "executed_count": summary.get("executed_count", 0) if isinstance(summary, dict) else 0,
        "editing_software_opened_count": summary.get("editing_software_opened_count", 0)
        if isinstance(summary, dict)
        else 0,
        "ready_asset_ids": ready_asset_ids,
        "blocked_asset_ids": blocked_asset_ids,
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "patched_project_exists": validation.get("patched_project_exists") is True if isinstance(validation, dict) else False,
        "rollback_available": validation.get("rollback_available") is True if isinstance(validation, dict) else False,
        "human_software_import_approval_required": validation.get("human_software_import_approval_required") is True
        if isinstance(validation, dict)
        else True,
        "software_import_execution_performed": validation.get("software_import_execution_performed") is True
        if isinstance(validation, dict)
        else False,
        "editing_software_opened": validation.get("editing_software_opened") is True
        if isinstance(validation, dict)
        else False,
        "project_file_mutation_performed": validation.get("project_file_mutation_performed") is True
        if isinstance(validation, dict)
        else False,
        "original_project_mutated": validation.get("original_project_mutated") is True
        if isinstance(validation, dict)
        else False,
        "replacement_execution_performed": validation.get("replacement_execution_performed") is True
        if isinstance(validation, dict)
        else False,
        "isolated_manual_launch_required": validation.get("isolated_manual_launch_required") is True
        if isinstance(validation, dict)
        else True,
        "generation_status": manifest.get("generation_status"),
        "review_required": manifest.get("review_required") is True,
    }


def _editor_software_real_runner_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json",
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_environment_snapshot.json",
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json",
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json",
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_audit_log.json",
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json",
        f"assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval_request.md",
        f"assets/{platform}/edit/software_real_runner_sandbox/README.md",
    ]
    manifest = _read_json_if_exists(
        run_dir
        / "assets"
        / platform
        / "edit"
        / "software_real_runner_sandbox"
        / "runner_sandbox_manifest.json"
    )
    if isinstance(manifest, dict):
        if manifest.get("human_real_run_approval_present") is True:
            approval_path = manifest.get("human_real_run_approval_path")
            if isinstance(approval_path, str) and approval_path:
                paths.append(approval_path)
        source_artifacts = manifest.get("source_artifacts")
        if isinstance(source_artifacts, list):
            paths.extend([path for path in source_artifacts if isinstance(path, str)])
    return _dedupe(paths)


def _editor_software_real_runner_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(
        run_dir
        / "assets"
        / platform
        / "edit"
        / "software_real_runner_sandbox"
        / "runner_sandbox_manifest.json"
    )
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    summary = manifest.get("summary")
    export_boundary = manifest.get("export_boundary")
    runner_items = manifest.get("runner_items")
    ready_asset_ids: list[str] = []
    blocked_asset_ids: list[str] = []
    if isinstance(runner_items, list):
        for item in runner_items:
            if not isinstance(item, dict):
                continue
            asset_id = str(item.get("asset_id") or "")
            if not asset_id:
                continue
            if item.get("real_run_status") == "ready_for_manual_external_sandbox_launch":
                ready_asset_ids.append(asset_id)
            if str(item.get("real_run_status") or "").startswith("blocked_"):
                blocked_asset_ids.append(asset_id)
    return {
        "manifest_path": manifest.get("manifest_path"),
        "environment_snapshot_path": manifest.get("environment_snapshot_path"),
        "launch_plan_path": manifest.get("launch_plan_path"),
        "command_preview_path": manifest.get("command_preview_path"),
        "audit_log_path": manifest.get("audit_log_path"),
        "evidence_manifest_path": manifest.get("evidence_manifest_path"),
        "approval_request_path": manifest.get("approval_request_path"),
        "readme_path": manifest.get("readme_path"),
        "source_import_manifest_path": manifest.get("source_import_manifest_path"),
        "source_import_plan_path": manifest.get("source_import_plan_path"),
        "source_import_commands_path": manifest.get("source_import_commands_path"),
        "source_rollback_safety_report_path": manifest.get("source_rollback_safety_report_path"),
        "source_patched_project_path": manifest.get("source_patched_project_path"),
        "human_real_run_approval_path": manifest.get("human_real_run_approval_path"),
        "human_real_run_approval_present": manifest.get("human_real_run_approval_present") is True,
        "human_real_run_approval_valid": manifest.get("human_real_run_approval_valid") is True,
        "target_editor": manifest.get("target_editor"),
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "editor_software_real_runner_sandbox": export_boundary.get("editor_software_real_runner_sandbox")
        if isinstance(export_boundary, dict)
        else None,
        "runner_item_count": summary.get("runner_item_count", 0) if isinstance(summary, dict) else 0,
        "ready_for_manual_external_sandbox_launch_count": summary.get(
            "ready_for_manual_external_sandbox_launch_count",
            0,
        )
        if isinstance(summary, dict)
        else 0,
        "blocked_runner_count": summary.get("blocked_runner_count", 0) if isinstance(summary, dict) else 0,
        "blocked_pending_approval_count": summary.get("blocked_pending_approval_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_import_not_ready_count": summary.get("blocked_import_not_ready_count", 0)
        if isinstance(summary, dict)
        else 0,
        "launched_count": summary.get("launched_count", 0) if isinstance(summary, dict) else 0,
        "process_spawned_count": summary.get("process_spawned_count", 0) if isinstance(summary, dict) else 0,
        "editing_software_opened_count": summary.get("editing_software_opened_count", 0)
        if isinstance(summary, dict)
        else 0,
        "ready_asset_ids": ready_asset_ids,
        "blocked_asset_ids": blocked_asset_ids,
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "human_real_run_approval_required": validation.get("human_real_run_approval_required") is True
        if isinstance(validation, dict)
        else True,
        "real_software_launch_performed": validation.get("real_software_launch_performed") is True
        if isinstance(validation, dict)
        else False,
        "software_import_execution_performed": validation.get("software_import_execution_performed") is True
        if isinstance(validation, dict)
        else False,
        "editing_software_opened": validation.get("editing_software_opened") is True
        if isinstance(validation, dict)
        else False,
        "project_file_mutation_performed": validation.get("project_file_mutation_performed") is True
        if isinstance(validation, dict)
        else False,
        "process_spawned": validation.get("process_spawned") is True if isinstance(validation, dict) else False,
        "manual_external_launch_required": validation.get("manual_external_launch_required") is True
        if isinstance(validation, dict)
        else True,
        "external_process_isolation_required": validation.get("external_process_isolation_required") is True
        if isinstance(validation, dict)
        else True,
        "generation_status": manifest.get("generation_status"),
        "review_required": manifest.get("review_required") is True,
    }


def _editor_software_run_evidence_source_paths(run_dir: Path, platform: str) -> list[str]:
    paths = [
        f"assets/{platform}/edit/software_run_evidence/real_run_evidence_manifest.json",
        f"assets/{platform}/edit/software_run_evidence/evidence_validation_report.json",
        f"assets/{platform}/edit/software_run_evidence/rollback_decision_report.json",
        f"assets/{platform}/edit/software_run_evidence/post_launch_evidence_checklist.md",
        f"assets/{platform}/edit/software_run_evidence/README.md",
    ]
    manifest = _read_json_if_exists(
        run_dir
        / "assets"
        / platform
        / "edit"
        / "software_run_evidence"
        / "real_run_evidence_manifest.json"
    )
    if isinstance(manifest, dict):
        if manifest.get("human_real_run_result_present") is True:
            result_path = manifest.get("human_real_run_result_path")
            if isinstance(result_path, str) and result_path:
                paths.append(result_path)
        evidence_files = manifest.get("evidence_files")
        if isinstance(evidence_files, list):
            paths.extend([path for path in evidence_files if isinstance(path, str)])
        source_artifacts = manifest.get("source_artifacts")
        if isinstance(source_artifacts, list):
            paths.extend([path for path in source_artifacts if isinstance(path, str)])
    return _dedupe(paths)


def _editor_software_run_evidence_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(
        run_dir
        / "assets"
        / platform
        / "edit"
        / "software_run_evidence"
        / "real_run_evidence_manifest.json"
    )
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    summary = manifest.get("summary")
    export_boundary = manifest.get("export_boundary")
    return {
        "manifest_path": manifest.get("manifest_path"),
        "validation_report_path": manifest.get("validation_report_path"),
        "rollback_decision_report_path": manifest.get("rollback_decision_report_path"),
        "checklist_path": manifest.get("checklist_path"),
        "readme_path": manifest.get("readme_path"),
        "source_runner_manifest_path": manifest.get("source_runner_manifest_path"),
        "source_launch_plan_path": manifest.get("source_launch_plan_path"),
        "source_command_preview_path": manifest.get("source_command_preview_path"),
        "source_runner_evidence_manifest_path": manifest.get("source_runner_evidence_manifest_path"),
        "human_real_run_result_path": manifest.get("human_real_run_result_path"),
        "human_real_run_result_present": manifest.get("human_real_run_result_present") is True,
        "human_real_run_result_valid": manifest.get("human_real_run_result_valid") is True,
        "editor_software_run_evidence": export_boundary.get("editor_software_run_evidence")
        if isinstance(export_boundary, dict)
        else None,
        "evidence_item_count": summary.get("evidence_item_count", 0) if isinstance(summary, dict) else 0,
        "human_real_run_evidence_ingested_count": summary.get("human_real_run_evidence_ingested_count", 0)
        if isinstance(summary, dict)
        else 0,
        "blocked_evidence_count": summary.get("blocked_evidence_count", 0) if isinstance(summary, dict) else 0,
        "evidence_file_count": summary.get("evidence_file_count", 0) if isinstance(summary, dict) else 0,
        "existing_evidence_file_count": summary.get("existing_evidence_file_count", 0)
        if isinstance(summary, dict)
        else 0,
        "missing_evidence_file_count": summary.get("missing_evidence_file_count", 0)
        if isinstance(summary, dict)
        else 0,
        "rollback_required_count": summary.get("rollback_required_count", 0) if isinstance(summary, dict) else 0,
        "rollback_decision": manifest.get("rollback_decision"),
        "evidence_files": manifest.get("evidence_files", []),
        "missing_evidence_files": manifest.get("missing_evidence_files", []),
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "human_real_run_result_required": validation.get("human_real_run_result_required") is True
        if isinstance(validation, dict)
        else True,
        "real_software_launch_performed_by_automation": validation.get(
            "real_software_launch_performed_by_automation"
        )
        is True
        if isinstance(validation, dict)
        else False,
        "software_import_execution_performed_by_automation": validation.get(
            "software_import_execution_performed_by_automation"
        )
        is True
        if isinstance(validation, dict)
        else False,
        "editing_software_opened_by_automation": validation.get("editing_software_opened_by_automation") is True
        if isinstance(validation, dict)
        else False,
        "project_file_mutation_performed_by_automation": validation.get(
            "project_file_mutation_performed_by_automation"
        )
        is True
        if isinstance(validation, dict)
        else False,
        "process_spawned_by_automation": validation.get("process_spawned_by_automation") is True
        if isinstance(validation, dict)
        else False,
        "upload_performed": validation.get("upload_performed") is True if isinstance(validation, dict) else False,
        "publishing_performed": validation.get("publishing_performed") is True
        if isinstance(validation, dict)
        else False,
        "generation_status": manifest.get("generation_status"),
        "review_required": manifest.get("review_required") is True,
    }


def _aggregate_editor_software_run_evidence_boundary(platform_packages: list[dict[str, Any]]) -> str:
    evidence_summaries = [
        package.get("editor_software_run_evidence")
        for package in platform_packages
        if isinstance(package, dict) and package.get("platform") in {"douyin", "shipinhao", "bilibili"}
    ]
    if evidence_summaries and all(
        isinstance(summary, dict)
        and summary.get("editor_software_run_evidence") == "human_evidence_ingested_no_automation_execution"
        for summary in evidence_summaries
    ):
        return "human_evidence_ingested_no_automation_execution"
    return "blocked_pending_human_real_run_result"


def _aggregate_voiceover_tts_boundary(platform_packages: list[dict[str, Any]]) -> str:
    summaries = [
        package.get("voiceover_tts")
        for package in platform_packages
        if isinstance(package, dict) and package.get("platform") in {"douyin", "shipinhao", "bilibili"}
    ]
    if summaries and all(
        isinstance(summary, dict)
        and summary.get("provider_external") is True
        and summary.get("provider") == "openai-speech-api"
        for summary in summaries
    ):
        return "performed_external_openai_speech_pending_human_review"
    if summaries and all(
        isinstance(summary, dict)
        and summary.get("provider_external") is True
        and summary.get("provider") == "siliconflow-audio-speech-api"
        for summary in summaries
    ):
        return "performed_external_siliconflow_speech_pending_human_review"
    if summaries and any(isinstance(summary, dict) and summary.get("provider_external") is True for summary in summaries):
        return "performed_mixed_voiceover_tts_pending_human_review"
    return "performed_locally_draft_no_external_provider"


def _timed_subtitle_source_paths(platform: str) -> list[str]:
    return [
        f"{platform}/timed_subtitles.json",
        f"{platform}/timed_subtitles.srt",
    ]


def _timed_subtitles_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    timed_subtitles = _read_json_if_exists(run_dir / platform / "timed_subtitles.json")
    if not isinstance(timed_subtitles, dict):
        return {}
    return {
        "path": f"{platform}/timed_subtitles.json",
        "srt_path": f"{platform}/timed_subtitles.srt",
        "adapter": timed_subtitles.get("adapter"),
        "adapter_version": timed_subtitles.get("adapter_version"),
        "subtitle_count": timed_subtitles.get("subtitle_count", 0),
        "storyboard_scene_count": timed_subtitles.get("storyboard_scene_count", 0),
        "total_duration_seconds": timed_subtitles.get("total_duration_seconds", 0),
        "correction_count": len(timed_subtitles.get("corrections", []))
        if isinstance(timed_subtitles.get("corrections"), list)
        else 0,
        "tts_ready": timed_subtitles.get("timeline_policy", {}).get("tts_ready") is True
        if isinstance(timed_subtitles.get("timeline_policy"), dict)
        else False,
        "validation_status": timed_subtitles.get("validation", {}).get("status")
        if isinstance(timed_subtitles.get("validation"), dict)
        else None,
        "review_required": timed_subtitles.get("review_required") is True,
    }


def _voiceover_tts_source_paths(platform: str) -> list[str]:
    return [
        f"assets/{platform}/voiceover/voiceover.wav",
        f"assets/{platform}/voiceover/voiceover_manifest.json",
    ]


def _voiceover_tts_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "voiceover" / "voiceover_manifest.json")
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    return {
        "audio_path": manifest.get("audio_path"),
        "manifest_path": f"assets/{platform}/voiceover/voiceover_manifest.json",
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "provider": manifest.get("provider"),
        "provider_external": manifest.get("provider_external") is True,
        "generation_status": manifest.get("generation_status"),
        "rights_status": manifest.get("rights_status"),
        "audio_generation_mode": manifest.get("audio_generation_mode"),
        "provider_metadata": manifest.get("provider_metadata", {}),
        "voice_id": manifest.get("voice_id"),
        "duration_seconds": manifest.get("duration_seconds", 0),
        "segment_count": manifest.get("segment_count", 0),
        "timed_subtitle_count": manifest.get("timed_subtitle_count", 0),
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "audio_duration_matches_timeline": validation.get("audio_duration_matches_timeline") is True
        if isinstance(validation, dict)
        else False,
        "review_required": manifest.get("review_required") is True,
    }


def _edit_project_source_paths(platform: str) -> list[str]:
    return [
        f"assets/{platform}/edit/edit_timeline.json",
        f"assets/{platform}/edit/edit_manifest.json",
        f"assets/{platform}/edit/draft_cut.edl",
    ]


def _export_project_source_paths(platform: str) -> list[str]:
    return [
        f"assets/{platform}/edit/project.fcpxml",
        f"assets/{platform}/edit/import_readme.md",
        f"assets/{platform}/edit/offline_media_report.json",
        f"assets/{platform}/edit/export_manifest.json",
    ]


def _project_bundle_source_paths(platform: str) -> list[str]:
    return [
        f"assets/{platform}/bundle/project_bundle.zip",
        f"assets/{platform}/bundle/project_bundle_manifest.json",
        f"assets/{platform}/bundle/file_manifest.json",
        f"assets/{platform}/bundle/README.md",
    ]


def _edit_project_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "edit" / "edit_manifest.json")
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    track_summary = manifest.get("track_summary")
    return {
        "timeline_path": manifest.get("timeline_path"),
        "manifest_path": manifest.get("manifest_path"),
        "edl_path": manifest.get("edl_path"),
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "duration_seconds": manifest.get("duration_seconds", 0),
        "frame_rate": manifest.get("frame_rate", 0),
        "track_summary": track_summary if isinstance(track_summary, dict) else {},
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "video_duration_matches": validation.get("video_duration_matches") is True
        if isinstance(validation, dict)
        else False,
        "audio_duration_matches": validation.get("audio_duration_matches") is True
        if isinstance(validation, dict)
        else False,
        "subtitle_duration_matches": validation.get("subtitle_duration_matches") is True
        if isinstance(validation, dict)
        else False,
        "review_required": manifest.get("review_required") is True,
    }


def _export_project_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "edit" / "export_manifest.json")
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    track_summary = manifest.get("track_summary")
    return {
        "project_path": manifest.get("project_path"),
        "readme_path": manifest.get("readme_path"),
        "offline_report_path": manifest.get("offline_report_path"),
        "manifest_path": manifest.get("manifest_path"),
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "project_format": manifest.get("project_format"),
        "duration_seconds": manifest.get("duration_seconds", 0),
        "frame_rate": manifest.get("frame_rate", 0),
        "track_summary": track_summary if isinstance(track_summary, dict) else {},
        "validation": validation if isinstance(validation, dict) else {},
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "referenced_media_files_exist": validation.get("referenced_media_files_exist") is True
        if isinstance(validation, dict)
        else False,
        "offline_broll_count": validation.get("offline_broll_count", 0) if isinstance(validation, dict) else 0,
        "review_required": manifest.get("review_required") is True,
    }


def _project_bundle_summary_for_platform(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest = _read_json_if_exists(run_dir / "assets" / platform / "bundle" / "project_bundle_manifest.json")
    if not isinstance(manifest, dict):
        return {}
    validation = manifest.get("validation")
    bundle_summary = manifest.get("bundle_summary")
    return {
        "bundle_path": manifest.get("bundle_path"),
        "manifest_path": manifest.get("manifest_path"),
        "file_manifest_path": manifest.get("file_manifest_path"),
        "readme_path": manifest.get("readme_path"),
        "adapter": manifest.get("adapter"),
        "adapter_version": manifest.get("adapter_version"),
        "bundle_format": manifest.get("bundle_format"),
        "bundle_summary": bundle_summary if isinstance(bundle_summary, dict) else {},
        "validation": validation if isinstance(validation, dict) else {},
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "required_files_present": validation.get("required_files_present") is True
        if isinstance(validation, dict)
        else False,
        "bundle_bytes": validation.get("bundle_bytes", 0) if isinstance(validation, dict) else 0,
        "review_required": manifest.get("review_required") is True,
    }


def _platform_label(platform: str) -> str:
    return {
        "douyin": "抖音",
        "shipinhao": "视频号",
        "bilibili": "B站",
    }.get(platform, platform)


def _default_aspect_ratio(platform: str) -> str:
    return "16:9" if platform == "bilibili" else "9:16"


def _platform_duration_seconds(run_dir: Path, platform: str, plan: dict[str, Any]) -> int:
    storyboard = _read_json_if_exists(run_dir / platform / "storyboard.json")
    if isinstance(storyboard, list):
        total = 0
        for scene in storyboard:
            if isinstance(scene, dict):
                try:
                    total += int(scene.get("duration_seconds") or 0)
                except (TypeError, ValueError):
                    continue
        if total > 0:
            return total
    try:
        return int(plan.get("recommended_duration_seconds") or 0)
    except (TypeError, ValueError):
        return 0


def _video_deliverables_for_platform(run_dir: Path, platform: str) -> dict[str, str]:
    candidates = {
        "voiceover_script": f"{platform}/script.md",
        "storyboard": f"{platform}/storyboard.json",
        "subtitle_script": f"{platform}/subtitles.srt",
        "timed_subtitles": f"{platform}/timed_subtitles.json",
        "timed_subtitles_srt": f"{platform}/timed_subtitles.srt",
        "voiceover_audio": f"assets/{platform}/voiceover/voiceover.wav",
        "voiceover_manifest": f"assets/{platform}/voiceover/voiceover_manifest.json",
        "edit_timeline": f"assets/{platform}/edit/edit_timeline.json",
        "edit_manifest": f"assets/{platform}/edit/edit_manifest.json",
        "draft_cut_edl": f"assets/{platform}/edit/draft_cut.edl",
        "project_fcpxml": f"assets/{platform}/edit/project.fcpxml",
        "project_import_readme": f"assets/{platform}/edit/import_readme.md",
        "offline_media_report": f"assets/{platform}/edit/offline_media_report.json",
        "export_manifest": f"assets/{platform}/edit/export_manifest.json",
        "project_bundle_zip": f"assets/{platform}/bundle/project_bundle.zip",
        "project_bundle_manifest": f"assets/{platform}/bundle/project_bundle_manifest.json",
        "project_bundle_file_manifest": f"assets/{platform}/bundle/file_manifest.json",
        "project_bundle_readme": f"assets/{platform}/bundle/README.md",
        "shot_list": f"{platform}/shot_list.json",
        "broll_list": f"{platform}/broll_list.json",
        "cover_prompt": f"{platform}/cover_prompt.md",
        "generated_cover_image": f"assets/{platform}/cover/cover.png",
        "generated_cover_metadata": f"assets/{platform}/cover/cover_metadata.json",
        "storyboard_preview": f"assets/{platform}/storyboard/storyboard_preview.png",
        "storyboard_preview_metadata": f"assets/{platform}/storyboard/storyboard_preview_metadata.json",
        "material_manifest": f"assets/{platform}/materials/material_manifest.json",
        "material_readme": f"assets/{platform}/materials/README.md",
        "licensed_media_ingest_manifest": f"assets/{platform}/licensed_media/ingest_manifest.json",
        "licensed_media_ingest_readme": f"assets/{platform}/licensed_media/README.md",
        "licensed_media_review_handoff": f"assets/{platform}/licensed_media/review_handoff.md",
        "licensed_media_proxy_manifest": f"assets/{platform}/licensed_media/proxy_manifest.json",
        "licensed_media_replacement_suggestions": f"assets/{platform}/licensed_media/replacement_suggestions.json",
        "licensed_media_proxy_readme": f"assets/{platform}/licensed_media/proxy/README.md",
        "editor_replacement_instruction_manifest": f"assets/{platform}/edit/replacement_instructions/instruction_manifest.json",
        "editor_replacement_commands": f"assets/{platform}/edit/replacement_instructions/replacement_commands.json",
        "editor_import_template_fcpxml": f"assets/{platform}/edit/replacement_instructions/editor_import_template.fcpxml",
        "editor_human_confirmation_checklist": f"assets/{platform}/edit/replacement_instructions/human_confirmation_checklist.md",
        "editor_replacement_readme": f"assets/{platform}/edit/replacement_instructions/README.md",
        "editor_replacement_execution_manifest": f"assets/{platform}/edit/replacement_execution/execution_manifest.json",
        "editor_replacement_execution_plan": f"assets/{platform}/edit/replacement_execution/execution_plan.json",
        "editor_replacement_execution_audit_log": f"assets/{platform}/edit/replacement_execution/execution_audit_log.json",
        "editor_replacement_approval_request": f"assets/{platform}/edit/replacement_execution/human_execution_approval_request.md",
        "editor_replacement_execution_readme": f"assets/{platform}/edit/replacement_execution/README.md",
        "editor_project_mutation_manifest": f"assets/{platform}/edit/mutation_sandbox/mutation_manifest.json",
        "editor_project_patched_fcpxml": f"assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml",
        "editor_project_mutation_diff": f"assets/{platform}/edit/mutation_sandbox/mutation_diff.json",
        "editor_project_rollback_manifest": f"assets/{platform}/edit/mutation_sandbox/rollback_manifest.json",
        "editor_project_mutation_audit_log": f"assets/{platform}/edit/mutation_sandbox/mutation_audit_log.json",
        "editor_project_final_review_checklist": f"assets/{platform}/edit/mutation_sandbox/human_final_review_checklist.md",
        "editor_project_mutation_readme": f"assets/{platform}/edit/mutation_sandbox/README.md",
        "editor_software_import_manifest": f"assets/{platform}/edit/software_import_executor/import_executor_manifest.json",
        "editor_software_import_plan": f"assets/{platform}/edit/software_import_executor/import_plan.json",
        "editor_software_import_commands": f"assets/{platform}/edit/software_import_executor/import_commands.json",
        "editor_software_import_audit_log": f"assets/{platform}/edit/software_import_executor/software_import_audit_log.json",
        "editor_software_import_rollback_safety_report": f"assets/{platform}/edit/software_import_executor/rollback_safety_report.json",
        "editor_software_import_execution_request": f"assets/{platform}/edit/software_import_executor/isolated_execution_request.md",
        "editor_software_import_readme": f"assets/{platform}/edit/software_import_executor/README.md",
        "editor_software_real_runner_manifest": f"assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json",
        "editor_software_real_runner_environment_snapshot": f"assets/{platform}/edit/software_real_runner_sandbox/runner_environment_snapshot.json",
        "editor_software_real_runner_launch_plan": f"assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json",
        "editor_software_real_runner_command_preview": f"assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json",
        "editor_software_real_runner_audit_log": f"assets/{platform}/edit/software_real_runner_sandbox/runner_audit_log.json",
        "editor_software_real_runner_evidence_manifest": f"assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json",
        "editor_software_real_runner_approval_request": f"assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval_request.md",
        "editor_software_real_runner_readme": f"assets/{platform}/edit/software_real_runner_sandbox/README.md",
        "editor_software_run_evidence_manifest": f"assets/{platform}/edit/software_run_evidence/real_run_evidence_manifest.json",
        "editor_software_run_evidence_validation_report": f"assets/{platform}/edit/software_run_evidence/evidence_validation_report.json",
        "editor_software_run_evidence_rollback_decision_report": f"assets/{platform}/edit/software_run_evidence/rollback_decision_report.json",
        "editor_software_run_evidence_checklist": f"assets/{platform}/edit/software_run_evidence/post_launch_evidence_checklist.md",
        "editor_software_run_evidence_readme": f"assets/{platform}/edit/software_run_evidence/README.md",
    }
    execution_manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "replacement_execution" / "execution_manifest.json"
    )
    if isinstance(execution_manifest, dict):
        approval_path = execution_manifest.get("human_execution_approval_path")
        if execution_manifest.get("human_execution_approval_present") is True and isinstance(approval_path, str):
            candidates["editor_replacement_human_execution_approval"] = approval_path
    mutation_manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "mutation_manifest.json"
    )
    if isinstance(mutation_manifest, dict):
        approval_path = mutation_manifest.get("human_mutation_approval_path")
        if mutation_manifest.get("human_mutation_approval_present") is True and isinstance(approval_path, str):
            candidates["editor_project_human_mutation_approval"] = approval_path
    software_import_manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "edit" / "software_import_executor" / "import_executor_manifest.json"
    )
    if isinstance(software_import_manifest, dict):
        approval_path = software_import_manifest.get("human_software_import_approval_path")
        if software_import_manifest.get("human_software_import_approval_present") is True and isinstance(approval_path, str):
            candidates["editor_software_import_human_approval"] = approval_path
    real_runner_manifest = _read_json_if_exists(
        run_dir
        / "assets"
        / platform
        / "edit"
        / "software_real_runner_sandbox"
        / "runner_sandbox_manifest.json"
    )
    if isinstance(real_runner_manifest, dict):
        approval_path = real_runner_manifest.get("human_real_run_approval_path")
        if real_runner_manifest.get("human_real_run_approval_present") is True and isinstance(approval_path, str):
            candidates["editor_software_real_runner_human_approval"] = approval_path
    run_evidence_manifest = _read_json_if_exists(
        run_dir
        / "assets"
        / platform
        / "edit"
        / "software_run_evidence"
        / "real_run_evidence_manifest.json"
    )
    if isinstance(run_evidence_manifest, dict):
        result_path = run_evidence_manifest.get("human_real_run_result_path")
        if run_evidence_manifest.get("human_real_run_result_present") is True and isinstance(result_path, str):
            candidates["editor_software_run_human_result"] = result_path
    licensed_media_manifest = _read_json_if_exists(
        run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json"
    )
    if isinstance(licensed_media_manifest, dict):
        registry_path = licensed_media_manifest.get("human_media_registry_path")
        if licensed_media_manifest.get("human_media_registry_exists") is True and isinstance(registry_path, str):
            candidates["licensed_media_human_registry"] = registry_path
    material_manifest = _read_json_if_exists(run_dir / "assets" / platform / "materials" / "material_manifest.json")
    materialized_assets = material_manifest.get("materialized_assets") if isinstance(material_manifest, dict) else None
    if isinstance(materialized_assets, list):
        for asset in materialized_assets:
            if not isinstance(asset, dict) or not asset.get("reference_path"):
                continue
            asset_id = str(asset.get("asset_id") or Path(str(asset["reference_path"])).stem)
            candidates[f"material_reference_{asset_id}"] = str(asset["reference_path"])
    proxy_manifest = _read_json_if_exists(run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json")
    proxy_assets = proxy_manifest.get("proxy_assets") if isinstance(proxy_manifest, dict) else None
    if isinstance(proxy_assets, list):
        for asset in proxy_assets:
            if not isinstance(asset, dict) or not asset.get("proxy_media_path"):
                continue
            asset_id = str(asset.get("asset_id") or Path(str(asset["proxy_media_path"])).stem)
            candidates[f"licensed_media_proxy_{asset_id}"] = str(asset["proxy_media_path"])
    storyboard_metadata = _read_json_if_exists(
        run_dir / "assets" / platform / "storyboard" / "storyboard_preview_metadata.json"
    )
    frames = storyboard_metadata.get("frames") if isinstance(storyboard_metadata, dict) else None
    if isinstance(frames, list):
        for frame in frames:
            if not isinstance(frame, dict) or not frame.get("path"):
                continue
            shot_id = str(frame.get("shot_id") or frame.get("linked_shot_id") or Path(str(frame["path"])).stem)
            candidates[f"storyboard_keyframe_{shot_id}"] = str(frame["path"])
    if platform == "bilibili":
        candidates["chapters"] = "bilibili/chapters.json"
        candidates["description"] = "bilibili/description.md"
    return {
        name: path
        for name, path in candidates.items()
        if (run_dir / path).exists()
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _state_db_path(output_root: Path) -> Path:
    return output_root / "_state" / "workflow_state.sqlite"
