from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


DEFAULT_MAX_AUTO_RETRIES = 1
DEFAULT_RETRYABLE_CATEGORIES = {"ENV_ERROR"}
DEFAULT_RETRYABLE_STATES = {"stale", "interrupted"}


def build_retry_policy_config(*, max_auto_retries: int | None = None) -> dict[str, Any]:
    return {
        "enabled": _read_bool_env("CONTENT_AGENT_OS_RETRY_POLICY_ENABLED", True),
        "max_auto_retries": _resolve_max_auto_retries(max_auto_retries),
        "retryable_categories": sorted(DEFAULT_RETRYABLE_CATEGORIES),
        "retryable_recovery_states": sorted(DEFAULT_RETRYABLE_STATES),
    }


def decide_retry(
    *,
    task_run: dict[str, Any],
    prior_attempts: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    policy = config or build_retry_policy_config()
    step_id = str(task_run.get("step_id", "unknown"))
    retry_count = _auto_retry_count(prior_attempts)
    max_auto_retries = int(policy.get("max_auto_retries", DEFAULT_MAX_AUTO_RETRIES))
    recoverable = bool(task_run.get("recoverable"))
    category = str(task_run.get("failure_category") or "ENV_ERROR")
    recovery_state = str(task_run.get("recovery_state") or "")

    decision = {
        "step_id": step_id,
        "task_id": task_run.get("task_id"),
        "enabled": bool(policy.get("enabled", True)),
        "should_retry": False,
        "decision": "manual",
        "reason": "Manual recovery required.",
        "retry_count": retry_count,
        "max_auto_retries": max_auto_retries,
        "failure_category": category,
        "recovery_state": recovery_state,
        "created_at": now.isoformat(),
    }

    if not decision["enabled"]:
        decision["decision"] = "disabled"
        decision["reason"] = "Retry policy is disabled by CONTENT_AGENT_OS_RETRY_POLICY_ENABLED."
        return decision

    if not recoverable:
        decision["decision"] = "not_recoverable"
        decision["reason"] = "Failure is not marked recoverable."
        return decision

    if category not in set(policy.get("retryable_categories", [])):
        decision["decision"] = "category_blocked"
        decision["reason"] = f"Failure category {category} is not auto-retryable."
        return decision

    if recovery_state not in set(policy.get("retryable_recovery_states", [])):
        decision["decision"] = "state_blocked"
        decision["reason"] = f"Recovery state {recovery_state or 'unknown'} is not auto-retryable."
        return decision

    if retry_count >= max_auto_retries:
        decision["decision"] = "budget_exhausted"
        decision["reason"] = f"Auto retry budget exhausted for step {step_id}."
        return decision

    decision["should_retry"] = True
    decision["decision"] = "retry"
    decision["reason"] = f"Recoverable {recovery_state} fault is within retry budget."
    return decision


def build_retry_event(
    *,
    task_run: dict[str, Any],
    decision: dict[str, Any],
    attempt: int | None,
    stage: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    return {
        "event": "auto_retry",
        "stage": stage,
        "step_id": task_run.get("step_id"),
        "task_id": task_run.get("task_id"),
        "attempt": attempt,
        "decision": decision.get("decision"),
        "should_retry": bool(decision.get("should_retry")),
        "reason": decision.get("reason"),
        "retry_count": decision.get("retry_count"),
        "max_auto_retries": decision.get("max_auto_retries"),
        "failure_category": decision.get("failure_category"),
        "recovery_state": decision.get("recovery_state"),
        "created_at": now.isoformat(),
    }


def summarize_retry_policy(
    workflow_run: dict[str, Any],
    task_views: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = config or build_retry_policy_config()
    events = list(workflow_run.get("retry_events", []))
    retryable_failures = [
        task
        for task in task_views
        if task.get("failure") and task.get("failure", {}).get("recoverable")
    ]
    auto_retry_count = sum(1 for event in events if event.get("stage") == "scheduled" and event.get("should_retry"))
    return {
        "config": policy,
        "summary": {
            "enabled": bool(policy.get("enabled", True)),
            "max_auto_retries": int(policy.get("max_auto_retries", DEFAULT_MAX_AUTO_RETRIES)),
            "retryable_failure_count": len(retryable_failures),
            "auto_retry_count": auto_retry_count,
            "event_count": len(events),
        },
        "events": events,
    }


def _auto_retry_count(prior_attempts: list[dict[str, Any]]) -> int:
    count = 0
    for attempt in prior_attempts:
        record = attempt.get("record", {})
        retry_policy = record.get("retry_policy") if isinstance(record, dict) else None
        if isinstance(retry_policy, dict) and retry_policy.get("auto_retry"):
            count += 1
    return count


def _resolve_max_auto_retries(max_auto_retries: int | None) -> int:
    if max_auto_retries is not None:
        return max(0, int(max_auto_retries))
    raw = os.getenv("CONTENT_AGENT_OS_MAX_AUTO_RETRIES", "").strip()
    if not raw:
        return DEFAULT_MAX_AUTO_RETRIES
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MAX_AUTO_RETRIES


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
