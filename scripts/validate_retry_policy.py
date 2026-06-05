from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.retry_policy import build_retry_policy_config, decide_retry  # noqa: E402
from content_agent_os.runner import resume_workflow  # noqa: E402
from content_agent_os.state_store import WorkflowStateStore  # noqa: E402


def fail(message: str) -> None:
    print(f"Retry policy validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def main() -> int:
    now = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    validate_policy_decisions(now)
    validate_resume_auto_retry(now)
    validate_retry_budget_exhaustion(now)
    print("Retry policy validation passed.")
    print("Checked retry decisions, automatic resume replay, and retry budget exhaustion.")
    return 0


def validate_policy_decisions(now: datetime) -> None:
    config = build_retry_policy_config(max_auto_retries=1)
    recoverable_task = {
        "task_id": "task_run_retry_validation_research",
        "step_id": "research",
        "failure_category": "ENV_ERROR",
        "recoverable": True,
        "recovery_state": "stale",
    }
    retry = decide_retry(task_run=recoverable_task, prior_attempts=[], config=config, now=now)
    expect(retry["should_retry"] is True, "recoverable stale ENV_ERROR should auto retry")
    expect(retry["decision"] == "retry", "recoverable stale ENV_ERROR decision should be retry")

    blocked_category = decide_retry(
        task_run=recoverable_task | {"failure_category": "POLICY_ERROR"},
        prior_attempts=[],
        config=config,
        now=now,
    )
    expect(blocked_category["should_retry"] is False, "POLICY_ERROR should not auto retry")
    expect(blocked_category["decision"] == "category_blocked", "POLICY_ERROR should be category_blocked")

    exhausted = decide_retry(
        task_run=recoverable_task,
        prior_attempts=[_attempt("run_retry_validation", 2, _task_run("research", "RUNNING", now, None), auto_retry=True)],
        config=config,
        now=now,
    )
    expect(exhausted["should_retry"] is False, "existing auto retry should exhaust default budget")
    expect(exhausted["decision"] == "budget_exhausted", "budget exhaustion decision mismatch")


def validate_resume_auto_retry(now: datetime) -> None:
    with tempfile.TemporaryDirectory(prefix="content-agent-os-retry-resume-") as tmp:
        output_root = Path(tmp) / "runs"
        run_id = "run_retry_auto_validation"
        run_dir = output_root / run_id
        (run_dir / "logs/tasks").mkdir(parents=True)

        workflow = _one_step_workflow()
        running_task = _task_run("research", "RUNNING", now - timedelta(minutes=45), None)
        snapshot = _workflow_run(
            run_id=run_id,
            workflow=workflow,
            status="RUNNING",
            created_at=(now - timedelta(minutes=46)).isoformat(),
            updated_at=(now - timedelta(minutes=45)).isoformat(),
            task_runs=[running_task],
            retry_events=[],
        )

        store = WorkflowStateStore(output_root / "_state" / "workflow_state.sqlite")
        store.save_workflow_run(
            snapshot,
            workflow_path=str(Path(tmp) / "retry_validation.yaml"),
            run_dir=str(run_dir),
            current_step_id="research",
        )
        store.save_task_attempt(_attempt(run_id, 1, running_task))

        resume_workflow(run_id=run_id, output_root=output_root)

        workflow_after = _load_json(run_dir / "workflow_run.json")
        expect(workflow_after["status"] == "DONE", "auto retry resume should finish workflow")
        expect(len(workflow_after.get("retry_events", [])) >= 3, "workflow should record retry events")
        event_stages = [event.get("stage") for event in workflow_after.get("retry_events", [])]
        for stage in ["scheduled", "started", "passed"]:
            expect(stage in event_stages, f"retry event missing stage: {stage}")

        attempts = store.load_task_attempts(run_id)
        failed_attempts = [attempt for attempt in attempts if attempt["status"] == "FAILED"]
        passed_attempts = [attempt for attempt in attempts if attempt["status"] == "PASSED"]
        expect(len(failed_attempts) == 1, "stale attempt should be converted to failed")
        expect(len(passed_attempts) == 1, "auto retry should produce one passed attempt")
        passed_retry = passed_attempts[0].get("record", {}).get("retry_policy", {})
        expect(passed_retry.get("auto_retry") is True, "passed replay attempt should be marked auto_retry")
        expect(passed_retry.get("decision", {}).get("decision") == "retry", "passed replay should preserve retry decision")

        snapshot_after = _load_json(run_dir / "monitor/supervision_snapshot.json")
        retry_summary = snapshot_after["retry_policy"]["summary"]
        expect(retry_summary["auto_retry_count"] == 1, "supervision should count one scheduled auto retry")
        expect(retry_summary["event_count"] >= 3, "supervision should expose retry event history")
        expect(snapshot_after["summary"]["auto_retry_count"] == 1, "top-level summary should count auto retry")


def validate_retry_budget_exhaustion(now: datetime) -> None:
    with tempfile.TemporaryDirectory(prefix="content-agent-os-retry-budget-") as tmp:
        output_root = Path(tmp) / "runs"
        run_id = "run_retry_budget_validation"
        run_dir = output_root / run_id
        (run_dir / "logs/tasks").mkdir(parents=True)

        workflow = _one_step_workflow()
        running_task = _task_run("research", "RUNNING", now - timedelta(minutes=45), None)
        snapshot = _workflow_run(
            run_id=run_id,
            workflow=workflow,
            status="RUNNING",
            created_at=(now - timedelta(minutes=46)).isoformat(),
            updated_at=(now - timedelta(minutes=45)).isoformat(),
            task_runs=[running_task],
            retry_events=[],
        )

        store = WorkflowStateStore(output_root / "_state" / "workflow_state.sqlite")
        store.save_workflow_run(
            snapshot,
            workflow_path=str(Path(tmp) / "retry_budget_validation.yaml"),
            run_dir=str(run_dir),
            current_step_id="research",
        )
        store.save_task_attempt(_attempt(run_id, 1, running_task))
        first_retry_running = _task_run("research", "RUNNING", now - timedelta(minutes=35), None)
        store.save_task_attempt(_attempt(run_id, 2, first_retry_running, auto_retry=True))

        try:
            resume_workflow(run_id=run_id, output_root=output_root)
        except RuntimeError as exc:
            expect("unsatisfied dependencies" not in str(exc), "budget exhaustion should not produce dependency error")

        workflow_after = _load_json(run_dir / "workflow_run.json")
        expect(workflow_after["status"] == "FAILED", "budget-exhausted resume should remain FAILED")
        retry_events = workflow_after.get("retry_events", [])
        expect(any(event.get("stage") == "blocked" for event in retry_events), "budget exhaustion should record blocked event")
        expect(any(event.get("decision") == "budget_exhausted" for event in retry_events), "blocked event should explain budget exhaustion")

        attempts = store.load_task_attempts(run_id)
        failed_attempts = [attempt for attempt in attempts if attempt["status"] == "FAILED"]
        passed_attempts = [attempt for attempt in attempts if attempt["status"] == "PASSED"]
        expect(len(failed_attempts) == 1, "budget exhaustion should convert retry RUNNING attempt to failed once")
        expect(len(passed_attempts) == 0, "budget exhaustion should not replay the task again")

        snapshot_after = _load_json(run_dir / "monitor/supervision_snapshot.json")
        retry_summary = snapshot_after["retry_policy"]["summary"]
        expect(retry_summary["auto_retry_count"] == 0, "budget-exhausted run should schedule no new auto retry")
        expect(retry_summary["event_count"] >= 1, "budget-exhausted run should expose blocked retry event")
        expect(snapshot_after["failures"][0]["retry_decision"]["decision"] == "budget_exhausted", "failure should include retry decision")


def _workflow_run(
    *,
    run_id: str,
    workflow: dict,
    status: str,
    created_at: str,
    updated_at: str,
    task_runs: list[dict],
    retry_events: list[dict],
) -> dict:
    return {
        "run_id": run_id,
        "workflow_id": workflow["id"],
        "workflow": workflow,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "topic": "Retry policy validation",
        "platforms": ["wechat"],
        "tasks": [
            {
                "task_id": f"task_{run_id}_{step['id']}",
                "agent": step["agent"],
                "metadata": {"step_id": step["id"]},
            }
            for step in workflow["steps"]
        ],
        "task_runs": task_runs,
        "artifacts": [],
        "failures": [],
        "retry_events": retry_events,
    }


def _one_step_workflow() -> dict:
    return {
        "id": "retry_policy_validation",
        "name": "Retry policy validation",
        "version": "0.0.0",
        "description": "Validate retry policy resume behavior.",
        "inputs": [],
        "steps": [
            {
                "id": "research",
                "agent": "research-agent",
                "depends_on": [],
                "outputs": ["research_report.md", "sources.json"],
            }
        ],
        "outputs": [],
    }


def _task_run(step_id: str, status: str, started_at: datetime, ended_at: datetime | None) -> dict:
    return {
        "task_id": f"task_run_retry_validation_{step_id}",
        "step_id": step_id,
        "agent": "research-agent",
        "status": status,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat() if ended_at else None,
        "artifact_paths": [],
        "log_path": f"logs/tasks/{step_id}.json",
        "execution_mode": "agent-local",
    }


def _attempt(run_id: str, attempt: int, task_run: dict, *, auto_retry: bool = False) -> dict:
    record = {
        "task_run": task_run,
        "task_spec": {
            "task_id": f"task_{run_id}_{task_run['step_id']}",
            "agent": task_run["agent"],
        },
    }
    if auto_retry:
        record["retry_policy"] = {
            "auto_retry": True,
            "decision": {
                "decision": "retry",
                "should_retry": True,
                "reason": "Synthetic prior auto retry.",
            },
            "retry_attempt": attempt,
        }
    return {
        "run_id": run_id,
        "step_id": task_run["step_id"],
        "attempt": attempt,
        "task_id": f"task_{run_id}_{task_run['step_id']}",
        "agent": task_run["agent"],
        "status": task_run["status"],
        "started_at": task_run["started_at"],
        "ended_at": task_run.get("ended_at"),
        "execution_mode": task_run.get("execution_mode"),
        "log_path": task_run.get("log_path"),
        "artifact_paths": task_run.get("artifact_paths", []),
        "failure_category": task_run.get("failure_category"),
        "failure_message": task_run.get("failure_message"),
        "record": record,
        "created_at": task_run["started_at"],
        "updated_at": task_run.get("ended_at") or task_run["started_at"],
    }


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON file {path}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
