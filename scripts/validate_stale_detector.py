from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import resume_workflow  # noqa: E402
from content_agent_os.stale_detector import assess_task_health, summarize_task_health  # noqa: E402
from content_agent_os.state_store import WorkflowStateStore  # noqa: E402
from content_agent_os.supervision import write_supervision_outputs  # noqa: E402


def fail(message: str) -> None:
    print(f"Stale detector validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def main() -> int:
    now = datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc)
    validate_health_states(now)
    validate_supervision_outputs(now)
    validate_resume_conversion(now)
    print("Stale detector validation passed.")
    print("Checked health classification, supervision snapshot wiring, and resume conversion.")
    return 0


def validate_health_states(now: datetime) -> None:
    workflow_run = {"run_id": "run_health_validation", "status": "RUNNING"}

    stale = assess_task_health(
        workflow_run=workflow_run,
        task_view={
            "task_id": "task_run_health_validation_research",
            "step_id": "research",
            "agent": "research-agent",
            "status": "RUNNING",
            "started_at": (now - timedelta(minutes=45)).isoformat(),
            "ended_at": None,
        },
        now=now,
        threshold_minutes=30,
    )
    expect(stale["state"] == "stale", "old RUNNING task should be stale")
    expect(stale["recoverable"] is True, "stale task should be recoverable")
    expect(stale["failure_category"] == "ENV_ERROR", "stale task should map to ENV_ERROR")

    watch = assess_task_health(
        workflow_run=workflow_run,
        task_view={
            "task_id": "task_run_health_validation_outline",
            "step_id": "master_outline",
            "agent": "outline-agent",
            "status": "RUNNING",
            "started_at": (now - timedelta(minutes=5)).isoformat(),
            "ended_at": None,
        },
        now=now,
        threshold_minutes=30,
    )
    expect(watch["state"] == "watch", "recent RUNNING task should stay in watch state")
    expect(watch["recoverable"] is False, "watch task should not be recoverable yet")

    interrupted = assess_task_health(
        workflow_run=workflow_run,
        task_view={
            "task_id": "task_run_health_validation_topic",
            "step_id": "topic_angles",
            "agent": "topic-agent",
            "status": "RUNNING",
            "started_at": None,
            "ended_at": None,
        },
        now=now,
        threshold_minutes=30,
    )
    expect(interrupted["state"] == "interrupted", "RUNNING task without started_at should be interrupted")
    expect(interrupted["recoverable"] is True, "interrupted task should be recoverable")

    complete = assess_task_health(
        workflow_run={"run_id": "run_health_validation", "status": "DONE"},
        task_view={
            "task_id": "task_run_health_validation_research",
            "step_id": "research",
            "agent": "research-agent",
            "status": "PASSED",
            "started_at": (now - timedelta(minutes=10)).isoformat(),
            "ended_at": (now - timedelta(minutes=9)).isoformat(),
        },
        now=now,
        threshold_minutes=30,
    )
    expect(complete["state"] == "complete", "PASSED task should be complete")
    expect(complete["recoverable"] is False, "complete task should not be recoverable")


def validate_supervision_outputs(now: datetime) -> None:
    with tempfile.TemporaryDirectory(prefix="content-agent-os-stale-supervision-") as tmp:
        root = Path(tmp)
        run_dir = root / "run_stale_validation"
        (run_dir / "logs/tasks").mkdir(parents=True)
        (run_dir / "research_report.md").write_text("# Research\n", encoding="utf-8")
        (run_dir / "logs/tasks/research.json").write_text("{}\n", encoding="utf-8")
        (run_dir / "logs/tasks/master_outline.json").write_text("{}\n", encoding="utf-8")

        workflow_run = _workflow_run(
            run_id="run_stale_validation",
            workflow=_two_step_workflow(),
            status="RUNNING",
            created_at=(now - timedelta(minutes=60)).isoformat(),
            updated_at=now.isoformat(),
            task_runs=[
                _task_run(
                    "research",
                    "research-agent",
                    "PASSED",
                    now - timedelta(minutes=50),
                    now - timedelta(minutes=49),
                    ["research_report.md"],
                ),
                _task_run(
                    "master_outline",
                    "outline-agent",
                    "RUNNING",
                    now - timedelta(minutes=45),
                    None,
                    [],
                ),
            ],
        )
        attempts = [
            _attempt("run_stale_validation", 1, workflow_run["task_runs"][0]),
            _attempt("run_stale_validation", 1, workflow_run["task_runs"][1]),
        ]
        paths = write_supervision_outputs(run_dir, workflow_run, attempts)
        snapshot = _load_json(paths["snapshot"])

        summary = snapshot["summary"]
        detector = snapshot["stale_detector"]
        detector_summary = detector["summary"]
        expect(summary["stale_count"] == 1, "supervision summary should count one stale task")
        expect(summary["recoverable_count"] == 1, "supervision summary should count one recoverable fault")
        expect(summary["failure_count"] == 1, "supervision should expose stale task as a failure")
        expect(detector_summary["stale_count"] == 1, "detector summary should count one stale task")
        expect(detector_summary["recoverable_count"] == 1, "detector summary should count one recoverable fault")
        expect(len(detector["recoverable_faults"]) == 1, "detector should expose one recoverable fault")
        expect(detector["recoverable_faults"][0]["step_id"] == "master_outline", "recoverable fault step mismatch")
        expect(snapshot["current_step"]["step_id"] == "master_outline", "current step should prefer stale task")
        expect(snapshot["current_step"]["recoverable"] is True, "current stale step should be recoverable")
        expect(snapshot["failures"][0]["recoverable"] is True, "failure view should keep recoverable flag")

        task_health = {task["step_id"]: task["health"]["state"] for task in snapshot["tasks"]}
        expect(task_health["research"] == "complete", "passed task health should be complete")
        expect(task_health["master_outline"] == "stale", "running old task health should be stale")

        report = paths["report"].read_text(encoding="utf-8")
        dashboard = paths["dashboard"].read_text(encoding="utf-8")
        expect("## Stale Detector" in report, "supervision report missing stale detector section")
        expect("master_outline" in report, "supervision report missing stale step")
        expect("recoverable faults: 1" in dashboard, "dashboard missing recoverable fault count")
        expect("health: stale" in dashboard, "dashboard missing stale health marker")


def validate_resume_conversion(now: datetime) -> None:
    with tempfile.TemporaryDirectory(prefix="content-agent-os-stale-resume-") as tmp:
        output_root = Path(tmp) / "runs"
        run_id = "run_resume_stale_validation"
        run_dir = output_root / run_id
        (run_dir / "logs/tasks").mkdir(parents=True)

        workflow = _one_step_workflow()
        started_at = now - timedelta(minutes=45)
        running_task = _task_run("research", "research-agent", "RUNNING", started_at, None, [])
        snapshot = _workflow_run(
            run_id=run_id,
            workflow=workflow,
            status="RUNNING",
            created_at=(now - timedelta(minutes=46)).isoformat(),
            updated_at=(now - timedelta(minutes=45)).isoformat(),
            task_runs=[running_task],
        )

        store = WorkflowStateStore(output_root / "_state" / "workflow_state.sqlite")
        store.save_workflow_run(
            snapshot,
            workflow_path=str(Path(tmp) / "resume_stale_validation.yaml"),
            run_dir=str(run_dir),
            current_step_id="research",
        )
        store.save_task_attempt(_attempt(run_id, 1, running_task))

        resumed_dir = resume_workflow(run_id=run_id, output_root=output_root)
        expect(resumed_dir == run_dir, "resume_workflow returned unexpected run directory")
        workflow_after = _load_json(run_dir / "workflow_run.json")
        expect(workflow_after["status"] == "DONE", "resume should finish after replaying stale task")

        attempts = store.load_task_attempts(run_id)
        failed_attempts = [attempt for attempt in attempts if attempt["status"] == "FAILED"]
        passed_attempts = [attempt for attempt in attempts if attempt["status"] == "PASSED"]
        expect(len(failed_attempts) == 1, "resume should convert stale RUNNING attempt into one FAILED attempt")
        expect(len(passed_attempts) == 1, "resume should create one PASSED replay attempt")
        failed = failed_attempts[0]
        expect(failed["failure_category"] == "ENV_ERROR", "converted stale attempt should be ENV_ERROR")
        expect("stale threshold" in str(failed["failure_message"]), "converted failure should explain stale threshold")
        stale_record = failed["record"].get("stale_detector", {})
        expect(stale_record.get("recoverable") is True, "converted failed attempt should be recoverable")
        expect(stale_record.get("health", {}).get("state") == "stale", "converted failed attempt should preserve stale state")

        final_snapshot = _load_json(run_dir / "monitor/supervision_snapshot.json")
        final_detector = final_snapshot["stale_detector"]["summary"]
        expect(final_detector["stale_count"] == 0, "completed resume should have no active stale tasks")
        expect(final_detector["recoverable_count"] == 0, "completed resume should have no active recoverable faults")

        conn = sqlite3.connect(output_root / "_state" / "workflow_state.sqlite")
        row = conn.execute("SELECT status FROM workflow_run WHERE run_id = ?", (run_id,)).fetchone()
        expect(row is not None and row[0] == "DONE", "state store workflow_run should finish as DONE")


def _workflow_run(
    *,
    run_id: str,
    workflow: dict,
    status: str,
    created_at: str,
    updated_at: str,
    task_runs: list[dict],
) -> dict:
    return {
        "run_id": run_id,
        "workflow_id": workflow["id"],
        "workflow": workflow,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "topic": "Stale detector validation",
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
        "artifact_manifest": [],
        "failures": [],
    }


def _one_step_workflow() -> dict:
    return {
        "id": "resume_stale_validation",
        "name": "Resume stale validation",
        "version": "0.0.0",
        "description": "Validate stale detector resume conversion.",
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


def _two_step_workflow() -> dict:
    workflow = _one_step_workflow()
    workflow["id"] = "supervision_stale_validation"
    workflow["name"] = "Supervision stale validation"
    workflow["steps"].append(
        {
            "id": "master_outline",
            "agent": "outline-agent",
            "depends_on": ["research"],
            "outputs": ["master_outline.md"],
        }
    )
    return workflow


def _task_run(
    step_id: str,
    agent: str,
    status: str,
    started_at: datetime,
    ended_at: datetime | None,
    artifact_paths: list[str],
) -> dict:
    run_id = "run_resume_stale_validation" if status == "RUNNING" and step_id == "research" else "run_stale_validation"
    return {
        "task_id": f"task_{run_id}_{step_id}",
        "step_id": step_id,
        "agent": agent,
        "status": status,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat() if ended_at else None,
        "artifact_paths": artifact_paths,
        "log_path": f"logs/tasks/{step_id}.json",
        "execution_mode": "agent-local",
    }


def _attempt(run_id: str, attempt: int, task_run: dict) -> dict:
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
        "record": {
            "task_run": task_run,
            "task_spec": {
                "task_id": f"task_{run_id}_{task_run['step_id']}",
                "agent": task_run["agent"],
            },
        },
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
