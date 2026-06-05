from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


DEFAULT_STALE_AFTER_MINUTES = 30.0
ACTIVE_WORKFLOW_STATUSES = {
    "PENDING",
    "ASSIGNED",
    "RUNNING",
    "VALIDATING",
    "REPAIRING",
    "NEEDS_HUMAN",
}


def build_stale_detector_config(
    *,
    threshold_minutes: float | None = None,
) -> dict[str, Any]:
    return {
        "enabled": _read_bool_env("CONTENT_AGENT_OS_STALE_DETECTOR_ENABLED", True),
        "threshold_minutes": _resolve_threshold_minutes(threshold_minutes),
    }


def summarize_task_health(
    workflow_run: dict[str, Any],
    task_views: list[dict[str, Any]],
    *,
    mode: str = "monitor",
    now: datetime | None = None,
    threshold_minutes: float | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    detector = build_stale_detector_config(threshold_minutes=threshold_minutes)
    threshold = float(detector["threshold_minutes"])
    workflow_status = str(workflow_run.get("status", "PENDING"))

    enriched_tasks: list[dict[str, Any]] = []
    stale_tasks: list[dict[str, Any]] = []
    watch_tasks: list[dict[str, Any]] = []
    recoverable_faults: list[dict[str, Any]] = []

    for task in task_views:
        health = assess_task_health(
            workflow_run=workflow_run,
            task_view=task,
            mode=mode,
            now=now,
            threshold_minutes=threshold,
            enabled=bool(detector["enabled"]),
        )
        enriched = dict(task)
        enriched["health"] = health
        if health["recoverable"]:
            fault = build_recoverable_fault(enriched, health, detected_at=now)
            enriched["failure"] = fault
            recoverable_faults.append(fault)
            if health["state"] in {"stale", "interrupted"}:
                stale_tasks.append(enriched)
        elif health["state"] == "watch":
            watch_tasks.append(enriched)
        enriched_tasks.append(enriched)

    summary = {
        "threshold_minutes": threshold,
        "detected_at": now.isoformat(),
        "workflow_status": workflow_status,
        "workflow_active": workflow_status in ACTIVE_WORKFLOW_STATUSES,
        "task_count": len(enriched_tasks),
        "running_count": sum(1 for task in enriched_tasks if task["status"] == "RUNNING"),
        "watch_count": len(watch_tasks),
        "stale_count": sum(1 for task in enriched_tasks if task["health"]["state"] == "stale"),
        "interrupted_count": sum(1 for task in enriched_tasks if task["health"]["state"] == "interrupted"),
        "recoverable_count": len(recoverable_faults),
    }

    return {
        "config": detector,
        "detected_at": now.isoformat(),
        "summary": summary,
        "tasks": enriched_tasks,
        "stale_tasks": stale_tasks,
        "watch_tasks": watch_tasks,
        "recoverable_faults": recoverable_faults,
    }


def assess_task_health(
    *,
    workflow_run: dict[str, Any],
    task_view: dict[str, Any],
    mode: str = "monitor",
    now: datetime | None = None,
    threshold_minutes: float | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    threshold = _resolve_threshold_minutes(threshold_minutes)
    status = str(task_view.get("status", "PENDING"))
    workflow_status = str(workflow_run.get("status", "PENDING"))
    started_at = _parse_datetime(task_view.get("started_at"))
    ended_at = _parse_datetime(task_view.get("ended_at"))
    age_minutes = _minutes_since(started_at, now) if started_at is not None else None

    if status == "PASSED":
        return _health(
            state="complete",
            recoverable=False,
            reason="Task already passed.",
            workflow_status=workflow_status,
            threshold_minutes=threshold,
            age_minutes=age_minutes,
            detected_at=now,
        )

    if status == "FAILED":
        return _health(
            state="failed",
            recoverable=False,
            reason="Task already failed and is waiting for normal workflow resume handling.",
            workflow_status=workflow_status,
            threshold_minutes=threshold,
            age_minutes=age_minutes,
            detected_at=now,
        )

    if status == "SKIPPED":
        return _health(
            state="skipped",
            recoverable=False,
            reason="Task was skipped because its platform was not selected.",
            workflow_status=workflow_status,
            threshold_minutes=threshold,
            age_minutes=age_minutes,
            detected_at=now,
        )

    if status != "RUNNING":
        return _health(
            state="unknown",
            recoverable=False,
            reason=f"Unexpected task status: {status}.",
            workflow_status=workflow_status,
            threshold_minutes=threshold,
            age_minutes=age_minutes,
            detected_at=now,
        )

    if not enabled and mode == "monitor":
        return _health(
            state="watch",
            recoverable=False,
            reason="Stale detector is disabled by CONTENT_AGENT_OS_STALE_DETECTOR_ENABLED.",
            workflow_status=workflow_status,
            threshold_minutes=threshold,
            age_minutes=age_minutes,
            detected_at=now,
        )

    if mode == "resume":
        if age_minutes is None:
            state = "interrupted"
            reason = "RUNNING attempt has no started_at timestamp; treating it as interrupted on resume."
        elif age_minutes >= threshold:
            state = "stale"
            reason = (
                f"RUNNING attempt has been active for {age_minutes:.1f} minutes, "
                f"which exceeds the {threshold:.1f}-minute stale threshold."
            )
        else:
            state = "interrupted"
            reason = (
                f"RUNNING attempt is recoverable and will be replayed on resume "
                f"({age_minutes:.1f} minutes old)."
            )
        return _health(
            state=state,
            recoverable=True,
            reason=reason,
            workflow_status=workflow_status,
            threshold_minutes=threshold,
            age_minutes=age_minutes,
            detected_at=now,
        )

    if workflow_status not in ACTIVE_WORKFLOW_STATUSES:
        return _health(
            state="stale",
            recoverable=True,
            reason=f"Workflow status is {workflow_status}, so the RUNNING task is stale.",
            workflow_status=workflow_status,
            threshold_minutes=threshold,
            age_minutes=age_minutes,
            detected_at=now,
        )

    if age_minutes is None:
        return _health(
            state="interrupted",
            recoverable=True,
            reason="RUNNING task is missing started_at metadata and is treated as a recoverable interrupt.",
            workflow_status=workflow_status,
            threshold_minutes=threshold,
            age_minutes=age_minutes,
            detected_at=now,
        )

    if age_minutes >= threshold:
        return _health(
            state="stale",
            recoverable=True,
            reason=(
                f"RUNNING task has been active for {age_minutes:.1f} minutes, "
                f"which exceeds the {threshold:.1f}-minute stale threshold."
            ),
            workflow_status=workflow_status,
            threshold_minutes=threshold,
            age_minutes=age_minutes,
            detected_at=now,
        )

    return _health(
        state="watch",
        recoverable=False,
        reason=(
            f"RUNNING task is still within the {threshold:.1f}-minute watch window "
            f"({age_minutes:.1f} minutes old)."
        ),
        workflow_status=workflow_status,
        threshold_minutes=threshold,
        age_minutes=age_minutes,
        detected_at=now,
    )


def build_recoverable_fault(
    task_view: dict[str, Any],
    health: dict[str, Any],
    *,
    detected_at: datetime,
) -> dict[str, Any]:
    task_id = task_view.get("task_id")
    step_id = task_view.get("step_id")
    reason = str(health.get("reason", "Recoverable task fault detected."))
    return {
        "task_id": task_id,
        "step_id": step_id,
        "agent": task_view.get("agent"),
        "category": "ENV_ERROR",
        "message": reason,
        "recoverable": True,
        "recovery_state": health.get("state"),
        "log_path": task_view.get("log_path"),
        "status": task_view.get("status"),
        "age_minutes": health.get("age_minutes"),
        "threshold_minutes": health.get("threshold_minutes"),
        "workflow_status": health.get("workflow_status"),
        "detected_at": detected_at.isoformat(),
    }


def _health(
    *,
    state: str,
    recoverable: bool,
    reason: str,
    workflow_status: str,
    threshold_minutes: float,
    age_minutes: float | None,
    detected_at: datetime,
) -> dict[str, Any]:
    return {
        "state": state,
        "recoverable": recoverable,
        "reason": reason,
        "workflow_status": workflow_status,
        "threshold_minutes": threshold_minutes,
        "age_minutes": age_minutes,
        "detected_at": detected_at.isoformat(),
        "failure_category": "ENV_ERROR" if recoverable else None,
        "failure_message": reason if recoverable else None,
        "recommended_action": "make resume RUN_ID=\"...\"" if recoverable else "continue monitoring",
    }


def _resolve_threshold_minutes(threshold_minutes: float | None) -> float:
    if threshold_minutes is not None:
        return float(threshold_minutes)
    raw = os.getenv("CONTENT_AGENT_OS_STALE_AFTER_MINUTES", "").strip()
    if not raw:
        return DEFAULT_STALE_AFTER_MINUTES
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_STALE_AFTER_MINUTES
    return value if value > 0 else DEFAULT_STALE_AFTER_MINUTES


def _minutes_since(started_at: datetime, now: datetime) -> float:
    return max(0.0, (now - started_at).total_seconds() / 60.0)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default
