from __future__ import annotations

from typing import Any


FAILURE_CATEGORIES = {
    "ENV_ERROR",
    "DATA_ERROR",
    "SCHEMA_ERROR",
    "QUALITY_ERROR",
    "POLICY_ERROR",
    "PERMISSION_ERROR",
}


def classify_failure(exc: BaseException, *, step_id: str, agent_id: str, task_spec: dict[str, Any]) -> str:
    message = _failure_message(exc, step_id=step_id, agent_id=agent_id, task_spec=task_spec)
    lower = message.lower()

    if isinstance(exc, PermissionError):
        return "PERMISSION_ERROR"

    if any(token in lower for token in ["login", "cookie", "upload", "publish", "post", "forward", "sync"]):
        return "PERMISSION_ERROR"

    if any(token in lower for token in ["policy", "copyright", "sensitive", "uncleared", "illegal", "compliance"]):
        return "POLICY_ERROR"

    if any(token in lower for token in ["schema", "invalid json", "does not match", "missing key", "additional properties", "output"]):
        return "SCHEMA_ERROR"

    if isinstance(exc, FileNotFoundError) or any(token in lower for token in ["missing", "not found", "requires", "upstream artifact", "dependency"]):
        return "DATA_ERROR"

    if any(token in lower for token in ["quality", "too short", "hook", "title", "content", "draft", "weak"]):
        return "QUALITY_ERROR"

    return "ENV_ERROR"


def failure_message(exc: BaseException, *, step_id: str, agent_id: str, task_spec: dict[str, Any]) -> str:
    return _failure_message(exc, step_id=step_id, agent_id=agent_id, task_spec=task_spec)


def _failure_message(exc: BaseException, *, step_id: str, agent_id: str, task_spec: dict[str, Any]) -> str:
    task_id = str(task_spec.get("task_id", "unknown-task"))
    return f"{step_id}/{agent_id} ({task_id}): {exc}"
