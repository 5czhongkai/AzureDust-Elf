from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state_store import WorkflowStateStore
from .supervision import write_supervision_outputs


APPROVAL_NOT_REQUIRED = "NOT_REQUIRED"
APPROVAL_PENDING = "PENDING"
APPROVAL_APPROVED = "APPROVED"
APPROVAL_REJECTED = "REJECTED"


def normalize_repair_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not entry.get("manual_required"):
        entry.setdefault("approval_status", APPROVAL_NOT_REQUIRED)
        return entry

    status = str(entry.get("approval_status") or "").upper()
    if not status:
        status = APPROVAL_APPROVED if entry.get("approved_at") else APPROVAL_PENDING
    entry["approval_status"] = status
    return entry


def normalize_repair_log(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_repair_entry(dict(entry)) for entry in entries]


def repair_approval_status(entry: dict[str, Any] | None) -> str:
    if not entry:
        return APPROVAL_NOT_REQUIRED
    normalized = normalize_repair_entry(dict(entry))
    return str(normalized.get("approval_status") or APPROVAL_NOT_REQUIRED).upper()


def repair_needs_human_approval(entry: dict[str, Any] | None) -> bool:
    return bool(entry and entry.get("manual_required") and repair_approval_status(entry) == APPROVAL_PENDING)


def repair_is_approved(entry: dict[str, Any] | None) -> bool:
    return bool(entry and repair_approval_status(entry) == APPROVAL_APPROVED)


def latest_repair_for_step(
    entries: list[dict[str, Any]],
    *,
    step_id: str,
    task_id: str | None = None,
) -> dict[str, Any] | None:
    for entry in reversed(entries):
        if entry.get("status") == "FAILED":
            continue
        if task_id and entry.get("task_id") == task_id:
            return entry
        if entry.get("failed_step_id") == step_id:
            return entry
    return None


def summarize_approval_gate(entries: list[dict[str, Any]]) -> dict[str, int]:
    normalized = normalize_repair_log(entries)
    manual_entries = [entry for entry in normalized if entry.get("manual_required")]
    return {
        "manual_required_count": len(manual_entries),
        "pending_approval_count": sum(1 for entry in manual_entries if repair_approval_status(entry) == APPROVAL_PENDING),
        "approved_repair_count": sum(1 for entry in manual_entries if repair_approval_status(entry) == APPROVAL_APPROVED),
        "rejected_repair_count": sum(1 for entry in manual_entries if repair_approval_status(entry) == APPROVAL_REJECTED),
    }


def approve_repair_plan(
    *,
    run_id: str,
    output_root: Path,
    repair_id: str | None = None,
    approved_by: str = "human",
    approval_note: str = "",
) -> tuple[Path, dict[str, Any]]:
    store = WorkflowStateStore(output_root / "_state" / "workflow_state.sqlite")
    persisted = store.load_workflow_run(run_id)
    if persisted is None:
        raise FileNotFoundError(f"Workflow run not found in state store: {run_id}")

    snapshot = dict(persisted.get("snapshot") or persisted)
    repair_log = normalize_repair_log(list(snapshot.get("repair_log", [])))
    if not repair_log:
        raise RuntimeError(f"No repair plans found for run: {run_id}")

    target = _select_repair_for_approval(repair_log, repair_id)
    now = _utc_now_iso()
    target["approval_status"] = APPROVAL_APPROVED
    target["approved_at"] = now
    target["approved_by"] = approved_by or "human"
    target["approval_note"] = approval_note
    target["status"] = "APPROVED"

    snapshot["repair_log"] = repair_log
    snapshot["updated_at"] = now
    if snapshot.get("status") in {"NEEDS_HUMAN", "FAILED"}:
        snapshot["status"] = "REPAIRING"
    snapshot["note"] = (
        f"Repair plan {target.get('repair_id')} was approved by {target.get('approved_by')}; "
        "run resume to replay the failed step."
    )

    run_dir = Path(str(persisted["run_dir"]))
    _write_json(run_dir / "workflow_run.json", snapshot)
    _write_json(run_dir / "repair" / "repair_log.json", repair_log)
    store.save_workflow_run(
        snapshot,
        workflow_path=str(persisted["workflow_path"]),
        run_dir=str(run_dir),
        current_step_id=persisted.get("current_step_id"),
        failure_task_id=persisted.get("failure_task_id"),
        failure_category=persisted.get("failure_category"),
        failure_message=persisted.get("failure_message"),
    )
    write_supervision_outputs(run_dir, snapshot, store.load_task_attempts(run_id))
    return run_dir, target


def _select_repair_for_approval(entries: list[dict[str, Any]], repair_id: str | None) -> dict[str, Any]:
    if repair_id:
        for entry in entries:
            if entry.get("repair_id") == repair_id:
                if not entry.get("manual_required"):
                    raise RuntimeError(f"Repair plan {repair_id} does not require human approval.")
                if repair_approval_status(entry) == APPROVAL_APPROVED:
                    raise RuntimeError(f"Repair plan {repair_id} is already approved.")
                return entry
        raise RuntimeError(f"Repair plan not found: {repair_id}")

    pending = [
        entry
        for entry in entries
        if entry.get("manual_required") and repair_approval_status(entry) == APPROVAL_PENDING
    ]
    if len(pending) != 1:
        raise RuntimeError(
            "Repair approval requires --repair-id when there are "
            f"{len(pending)} pending manual repair plans."
        )
    return pending[0]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
