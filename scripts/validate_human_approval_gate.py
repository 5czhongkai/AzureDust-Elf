from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.approval_gate import approve_repair_plan  # noqa: E402
from content_agent_os.runner import resume_workflow  # noqa: E402
from content_agent_os.state_store import WorkflowStateStore  # noqa: E402


def fail(message: str) -> None:
    print(f"Human approval gate validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def main() -> int:
    now = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    validate_human_approval_gate(now)
    print("Human approval gate validation passed.")
    print("Checked pending approval blocking, approval recording, and resume replay after approval.")
    return 0


def validate_human_approval_gate(now: datetime) -> None:
    with tempfile.TemporaryDirectory(prefix="content-agent-os-human-approval-") as tmp:
        output_root = Path(tmp) / "runs"
        run_id = "run_human_approval_validation"
        run_dir = output_root / run_id
        (run_dir / "logs/tasks").mkdir(parents=True)

        workflow = _one_step_workflow()
        failed_task = _task_run("research", "FAILED", now - timedelta(minutes=2), now - timedelta(minutes=1))
        snapshot = _workflow_run(
            run_id=run_id,
            workflow=workflow,
            status="FAILED",
            created_at=(now - timedelta(minutes=3)).isoformat(),
            updated_at=(now - timedelta(minutes=1)).isoformat(),
            task_runs=[failed_task],
            failures=[
                {
                    "task_id": f"task_{run_id}_research",
                    "step_id": "research",
                    "agent": "research-agent",
                    "failure_type": "POLICY_ERROR",
                    "message": "policy risk in draft",
                }
            ],
        )

        store = WorkflowStateStore(output_root / "_state" / "workflow_state.sqlite")
        store.save_workflow_run(
            snapshot,
            workflow_path=str(Path(tmp) / "human_approval_validation.yaml"),
            run_dir=str(run_dir),
            current_step_id="research",
            failure_task_id=f"task_{run_id}_research",
            failure_category="POLICY_ERROR",
            failure_message="policy risk in draft",
        )
        store.save_task_attempt(_attempt(run_id, 1, failed_task, failure_category="POLICY_ERROR", failure_message="policy risk in draft"))

        try:
            resume_workflow(run_id=run_id, output_root=output_root)
        except RuntimeError as exc:
            expect("human approval" in str(exc).lower(), "resume should block on human approval")
        else:
            fail("resume should have been blocked by the human approval gate")

        workflow_waiting = _load_json(run_dir / "workflow_run.json")
        expect(workflow_waiting["status"] == "NEEDS_HUMAN", "workflow should pause in NEEDS_HUMAN")
        repair_log = workflow_waiting.get("repair_log", [])
        expect(len(repair_log) == 1, "waiting workflow should have one repair plan")
        entry = repair_log[0]
        expect(entry.get("manual_required") is True, "waiting repair plan should require manual review")
        expect(entry.get("approval_status") == "PENDING", "waiting repair plan should be pending approval")

        snapshot_waiting = _load_json(run_dir / "monitor/supervision_snapshot.json")
        expect(snapshot_waiting["summary"]["pending_approval_count"] == 1, "supervision should count pending approval")
        expect(snapshot_waiting["repair_log"]["summary"]["approved_repair_count"] == 0, "approved count should be zero before approval")
        expect("approve-repair" in "\n".join(snapshot_waiting["next_actions"]), "next actions should mention approval command")

        approve_repair_plan(
            run_id=run_id,
            output_root=output_root,
            repair_id=entry["repair_id"],
            approved_by="manual-reviewer",
            approval_note="reviewed and cleared for replay",
        )

        workflow_approved = _load_json(run_dir / "workflow_run.json")
        approved_entry = workflow_approved.get("repair_log", [])[0]
        expect(approved_entry.get("approval_status") == "APPROVED", "repair plan should be marked approved")
        expect(approved_entry.get("approved_by") == "manual-reviewer", "approved_by should persist")
        expect(workflow_approved["status"] == "REPAIRING", "approved workflow should move into repairing state")
        repair_log_file = _load_json(run_dir / "repair/repair_log.json")
        expect(repair_log_file[0].get("approval_status") == "APPROVED", "repair log file should persist approval status")

        snapshot_approved = _load_json(run_dir / "monitor/supervision_snapshot.json")
        expect(snapshot_approved["summary"]["pending_approval_count"] == 0, "pending approval count should clear after approval")
        expect(snapshot_approved["summary"]["repair_count"] == 1, "repair count should remain one")
        expect(snapshot_approved["repair_log"]["summary"]["approved_repair_count"] == 1, "approved count should be one")
        expect("make resume" in "\n".join(snapshot_approved["next_actions"]), "approved workflow should point to resume")

        resume_workflow(run_id=run_id, output_root=output_root)

        workflow_done = _load_json(run_dir / "workflow_run.json")
        expect(workflow_done["status"] == "DONE", "workflow should finish after approval and resume")
        final_entry = workflow_done.get("repair_log", [])[0]
        expect(final_entry.get("approval_status") == "APPROVED", "approval status should remain approved")

        attempts = store.load_task_attempts(run_id)
        passed_attempts = [attempt for attempt in attempts if attempt["status"] == "PASSED"]
        expect(len(passed_attempts) == 1, "approved replay should produce one passed attempt")
        expect(_load_json(run_dir / "final/content_package_manifest.json")["review_required"] is True, "final package should still require review")


def _workflow_run(
    *,
    run_id: str,
    workflow: dict,
    status: str,
    created_at: str,
    updated_at: str,
    task_runs: list[dict],
    failures: list[dict],
) -> dict:
    return {
        "run_id": run_id,
        "workflow_id": workflow["id"],
        "workflow": workflow,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "topic": "Human approval validation",
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
        "failures": failures,
        "retry_events": [],
        "repair_log": [],
    }


def _one_step_workflow() -> dict:
    return {
        "id": "human_approval_validation",
        "name": "Human approval validation",
        "version": "0.0.0",
        "description": "Validate human approval gate behavior.",
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
        "task_id": f"task_run_human_approval_{step_id}",
        "step_id": step_id,
        "agent": "research-agent",
        "status": status,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat() if ended_at else None,
        "artifact_paths": [],
        "log_path": f"logs/tasks/{step_id}.json",
        "execution_mode": "agent-local",
        "failure_category": "POLICY_ERROR" if status == "FAILED" else None,
        "failure_message": "policy risk in draft" if status == "FAILED" else None,
    }


def _attempt(
    run_id: str,
    attempt: int,
    task_run: dict,
    *,
    failure_category: str | None = None,
    failure_message: str | None = None,
) -> dict:
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
        "failure_category": failure_category,
        "failure_message": failure_message,
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
