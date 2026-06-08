from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    agent: str
    depends_on: list[str]
    outputs: list[str]
    platform: str | None = None
    requires_any_platform: list[str] | None = None
    parallel_group: str | None = None
    requires_human_approval: bool = False


@dataclass(frozen=True)
class Workflow:
    id: str
    name: str
    version: str
    description: str
    inputs: list[str]
    steps: list[WorkflowStep]
    outputs: list[str]


def load_workflow(path: Path) -> Workflow:
    data = _load_yaml(path)
    return workflow_from_dict(data)


def workflow_from_dict(data: dict[str, Any]) -> Workflow:
    steps = [
        WorkflowStep(
            id=str(item["id"]),
            agent=str(item["agent"]),
            depends_on=list(item.get("depends_on", [])),
            outputs=list(item.get("outputs", [])),
            platform=item.get("platform"),
            requires_any_platform=list(item.get("requires_any_platform", [])) or None,
            parallel_group=item.get("parallel_group"),
            requires_human_approval=bool(item.get("requires_human_approval", False)),
        )
        for item in data.get("steps", [])
    ]
    _validate_steps(steps)
    return Workflow(
        id=str(data["id"]),
        name=str(data["name"]),
        version=str(data["version"]),
        description=str(data.get("description", "")),
        inputs=list(data.get("inputs", [])),
        steps=steps,
        outputs=list(data.get("outputs", [])),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return _load_workflow_yaml_subset(path.read_text(encoding="utf-8"))

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Workflow YAML must be a mapping: {path}")
    return loaded


def _load_workflow_yaml_subset(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    section: str | None = None
    current_step: dict[str, Any] | None = None
    current_step_list_key: str | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if indent == 0:
            current_step = None
            current_step_list_key = None
            if stripped.endswith(":"):
                section = stripped[:-1]
                data[section] = []
                continue
            key, value = _split_key_value(stripped)
            section = None
            data[key] = _parse_scalar(value)
            continue

        if section in {"inputs", "outputs"} and indent == 2 and stripped.startswith("- "):
            data.setdefault(section, []).append(_parse_scalar(stripped[2:].strip()))
            continue

        if section == "steps":
            if indent == 2 and stripped.startswith("- "):
                current_step = {}
                data.setdefault("steps", []).append(current_step)
                current_step_list_key = None
                payload = stripped[2:].strip()
                if payload:
                    key, value = _split_key_value(payload)
                    current_step[key] = _parse_scalar(value)
                continue

            if current_step is None:
                raise ValueError(f"Step property appeared before a step item: {raw_line}")

            if indent == 4:
                if stripped.endswith(":"):
                    current_step_list_key = stripped[:-1]
                    current_step[current_step_list_key] = []
                    continue
                key, value = _split_key_value(stripped)
                current_step[key] = _parse_scalar(value)
                current_step_list_key = None
                continue

            if indent == 6 and stripped.startswith("- ") and current_step_list_key:
                current_step[current_step_list_key].append(_parse_scalar(stripped[2:].strip()))
                continue

        raise ValueError(f"Unsupported workflow YAML line: {raw_line}")

    return data


def _split_key_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"Expected key/value pair: {text}")
    key, value = text.split(":", 1)
    return key.strip(), value.strip()


def _parse_scalar(value: str) -> Any:
    if value == "[]":
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",")]
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _validate_steps(steps: list[WorkflowStep]) -> None:
    seen: set[str] = set()
    for step in steps:
        if step.id in seen:
            raise ValueError(f"Duplicate workflow step id: {step.id}")
        seen.add(step.id)

    missing: dict[str, list[str]] = {}
    for step in steps:
        unknown = [dep for dep in step.depends_on if dep not in seen]
        if unknown:
            missing[step.id] = unknown
    if missing:
        raise ValueError(f"Workflow has unknown dependencies: {missing}")
