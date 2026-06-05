from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedEditorReplacementExecution:
    manifest: dict[str, Any]
    execution_plan: dict[str, Any]
    audit_log: dict[str, Any]
    approval_request_md: str
    readme_text: str


EXECUTION_BOUNDARY = "blocked_pending_explicit_human_approval"
APPROVED_BOUNDARY = "approved_but_not_executed_by_default"
ACCEPTED_APPROVAL_STATUS = "approved_for_execution"


def generate_editor_replacement_execution(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    instruction_manifest: dict[str, Any],
    replacement_commands: dict[str, Any],
    human_execution_approval: dict[str, Any] | None,
    manifest_path: str,
    execution_plan_path: str,
    audit_log_path: str,
    approval_request_path: str,
    readme_path: str,
) -> GeneratedEditorReplacementExecution:
    commands = [
        command
        for command in replacement_commands.get("commands", [])
        if isinstance(command, dict) and command.get("asset_id")
    ]
    expected_approval_path = f"assets/{platform}/edit/replacement_execution/human_execution_approval.json"
    approval = _approval_state(human_execution_approval, expected_approval_path=expected_approval_path)
    approved_asset_ids = approval["approved_asset_ids"]
    execution_items = [
        _execution_item_for_command(
            run_dir=run_dir,
            command=command,
            approved_asset_ids=approved_asset_ids,
            approval_active=approval["approval_active"],
        )
        for command in commands
    ]
    command_count = len(execution_items)
    ready_count = len([item for item in execution_items if item["command_ready_after_approval"]])
    approved_count = len([item for item in execution_items if item["human_execution_approved"]])
    blocked_count = len([item for item in execution_items if item["execution_status"].startswith("blocked_")])
    missing_proxy_count = len([item for item in execution_items if item["execution_status"] == "blocked_proxy_media_missing"])
    executable_count = len([item for item in execution_items if item["execution_status"] == "ready_for_manual_execution"])
    executed_count = len([item for item in execution_items if item["execution_performed"] is True])
    source_artifacts = _dedupe(
        [
            instruction_manifest.get("manifest_path"),
            replacement_commands.get("replacement_commands_path"),
            instruction_manifest.get("editor_import_template_path"),
            instruction_manifest.get("human_confirmation_checklist_path"),
            instruction_manifest.get("readme_path"),
            approval["approval_path"] if approval["approval_present"] else None,
            *[
                item.get("proxy_media_path")
                for item in execution_items
                if isinstance(item.get("proxy_media_path"), str)
            ],
            manifest_path,
            execution_plan_path,
            audit_log_path,
            approval_request_path,
            readme_path,
        ]
    )
    export_boundary = {
        "editor_replacement_execution": APPROVED_BOUNDARY if approval["approval_active"] else EXECUTION_BOUNDARY,
        "replacement_execution": "not_performed",
        "editing_software": "not_opened",
        "project_file_mutation": "not_performed",
        "requires_explicit_human_approval": True,
        "asset_download": "not_performed",
        "external_asset_search": "not_performed",
        "license_purchase": "not_performed",
        "upload": "not_performed",
        "publishing": "not_performed",
    }
    validation = {
        "status": "PASSED" if command_count > 0 and executed_count == 0 else "NEEDS_REVIEW",
        "command_count": command_count,
        "ready_after_instruction_gate_count": ready_count,
        "human_execution_approved_count": approved_count,
        "blocked_pending_approval_count": len(
            [item for item in execution_items if item["execution_status"] == "blocked_pending_human_execution_approval"]
        ),
        "blocked_proxy_media_missing_count": missing_proxy_count,
        "executable_after_approval_count": executable_count,
        "replacement_execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "human_execution_approval_required": True,
        "human_execution_approval_present": approval["approval_present"],
        "human_execution_approval_valid": approval["approval_active"],
    }
    summary = {
        "command_count": command_count,
        "ready_after_instruction_gate_count": ready_count,
        "human_execution_approved_count": approved_count,
        "blocked_execution_count": blocked_count,
        "blocked_pending_approval_count": validation["blocked_pending_approval_count"],
        "blocked_proxy_media_missing_count": missing_proxy_count,
        "executable_after_approval_count": executable_count,
        "executed_count": executed_count,
    }
    manifest = {
        "schema_version": "phase4.editor_replacement_execution_manifest.v1",
        "artifact_type": "editor_replacement_execution",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-editor-replacement-execution-adapter",
        "adapter_version": "0.1.0",
        "manifest_path": manifest_path,
        "execution_plan_path": execution_plan_path,
        "audit_log_path": audit_log_path,
        "approval_request_path": approval_request_path,
        "readme_path": readme_path,
        "source_instruction_manifest_path": instruction_manifest.get("manifest_path"),
        "source_replacement_commands_path": replacement_commands.get("replacement_commands_path"),
        "human_execution_approval_path": approval["approval_path"],
        "human_execution_approval_present": approval["approval_present"],
        "human_execution_approval_valid": approval["approval_active"],
        "execution_items": execution_items,
        "summary": summary,
        "source_artifacts": source_artifacts,
        "export_boundary": export_boundary,
        "validation": validation,
        "generation_status": "generated_local_execution_adapter_plan_pending_explicit_human_approval",
        "manual_review_required": True,
        "human_execution_approval_required": True,
        "review_required": True,
    }
    execution_plan = {
        "schema_version": "phase4.editor_replacement_execution_plan.v1",
        "artifact_type": "editor_replacement_execution_plan",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "manifest_path": manifest_path,
        "execution_plan_path": execution_plan_path,
        "commands": execution_items,
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "manual_review_required": True,
        "human_execution_approval_required": True,
        "review_required": True,
    }
    audit_log = {
        "schema_version": "phase4.editor_replacement_execution_audit_log.v1",
        "artifact_type": "editor_replacement_execution_audit_log",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "events": [
            {
                "event_type": "execution_adapter_plan_generated",
                "status": "blocked_pending_explicit_human_approval"
                if not approval["approval_active"]
                else "approved_but_not_executed",
                "replacement_execution_performed": False,
                "editing_software_opened": False,
                "project_file_mutation_performed": False,
                "command_count": command_count,
            }
        ],
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
    }
    return GeneratedEditorReplacementExecution(
        manifest=manifest,
        execution_plan=execution_plan,
        audit_log=audit_log,
        approval_request_md=_render_approval_request(
            topic=topic,
            platform_label=platform_label,
            manifest=manifest,
            approval=approval,
        ),
        readme_text=_render_readme(topic=topic, platform_label=platform_label, manifest=manifest),
    )


def _execution_item_for_command(
    *,
    run_dir: Path,
    command: dict[str, Any],
    approved_asset_ids: set[str],
    approval_active: bool,
) -> dict[str, Any]:
    asset_id = str(command["asset_id"])
    proxy_path = _optional_string(command.get("proxy_media_path"))
    proxy_file = _resolve_local_path(run_dir, proxy_path)
    proxy_exists = bool(proxy_file and proxy_file.exists() and proxy_file.is_file())
    command_ready = command.get("can_execute_after_human_confirmation") is True
    approved = approval_active and (asset_id in approved_asset_ids or "*" in approved_asset_ids)
    if not command_ready:
        status = "blocked_instruction_not_ready"
    elif proxy_path and not proxy_exists:
        status = "blocked_proxy_media_missing"
    elif not approved:
        status = "blocked_pending_human_execution_approval"
    else:
        status = "ready_for_manual_execution"
    return {
        "command_id": command.get("command_id") or f"replace_{asset_id}",
        "asset_id": asset_id,
        "shot_id": command.get("shot_id"),
        "timeline_track": command.get("timeline_track"),
        "start_seconds": command.get("start_seconds"),
        "end_seconds": command.get("end_seconds"),
        "placeholder_source_path": command.get("placeholder_source_path"),
        "proxy_media_path": proxy_path,
        "proxy_media_exists": proxy_exists,
        "proxy_media_sha256": command.get("proxy_media_sha256"),
        "command_ready_after_approval": command_ready,
        "human_execution_approved": approved,
        "execution_status": status,
        "execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "execution_mode": "manual_execution_only",
    }


def _approval_state(approval: dict[str, Any] | None, *, expected_approval_path: str) -> dict[str, Any]:
    if not isinstance(approval, dict):
        return {
            "approval_present": False,
            "approval_active": False,
            "approval_path": expected_approval_path,
            "approved_asset_ids": set(),
        }
    approved_asset_ids = {
        str(item)
        for item in approval.get("approved_asset_ids", [])
        if isinstance(item, str) and item.strip()
    }
    return {
        "approval_present": True,
        "approval_active": approval.get("approval_status") == ACCEPTED_APPROVAL_STATUS
        and approval.get("human_execution_approval") is True
        and bool(approved_asset_ids),
        "approval_path": approval.get("approval_path") or expected_approval_path,
        "approved_asset_ids": approved_asset_ids,
    }


def _render_approval_request(
    *,
    topic: str,
    platform_label: str,
    manifest: dict[str, Any],
    approval: dict[str, Any],
) -> str:
    lines = [
        "# Editor Replacement Execution Approval Request",
        "",
        f"- Topic: {topic}",
        f"- Platform: {platform_label}",
        f"- Execution manifest: `{manifest['manifest_path']}`",
        f"- Execution plan: `{manifest['execution_plan_path']}`",
        f"- Commands requiring approval: {manifest['summary']['command_count']}",
        f"- Human execution approval present: {approval['approval_present']}",
        f"- Human execution approval valid: {approval['approval_active']}",
        "",
        "No replacement was executed by this layer. Review every item below before creating `human_execution_approval.json`.",
        "",
    ]
    for item in manifest.get("execution_items", []):
        lines.extend(
            [
                f"- [ ] `{item['asset_id']}` status `{item['execution_status']}`",
                f"  - Proxy media: `{item.get('proxy_media_path')}`",
                f"  - Timeline target: `{item.get('shot_id')}` from {item.get('start_seconds')}s to {item.get('end_seconds')}s",
                "  - Confirm rights, visual fit, timeline placement, audio/subtitle sync, and final editor approval.",
            ]
        )
    lines.extend(
        [
            "",
            "Approval file contract:",
            "",
            "```json",
            "{",
            '  "approval_status": "approved_for_execution",',
            '  "human_execution_approval": true,',
            '  "approved_asset_ids": ["asset_id_or_*"],',
            '  "approved_by": "human",',
            '  "approval_note": "Reviewed rights, timeline, and final editor replacement scope."',
            "}",
            "```",
            "",
            "This request is an approval gate only. No editing software was opened, no project file was mutated, and no upload or publishing action was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_readme(*, topic: str, platform_label: str, manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    return "\n".join(
        [
            "# Editor Replacement Execution Adapter",
            "",
            f"- Topic: {topic}",
            f"- Platform: {platform_label}",
            f"- Execution plan: `{manifest['execution_plan_path']}`",
            f"- Approval request: `{manifest['approval_request_path']}`",
            f"- Audit log: `{manifest['audit_log_path']}`",
            f"- Commands: {summary['command_count']}",
            f"- Blocked pending approval: {summary['blocked_pending_approval_count']}",
            f"- Ready for manual execution after approval: {summary['executable_after_approval_count']}",
            "",
            "This layer prepares an auditable execution adapter plan only.",
            "It does not open editing software, mutate project files, execute replacements, upload, publish, search, download, or purchase media.",
            "Create `human_execution_approval.json` only after human review of the approval request and replacement plan.",
            "",
        ]
    )


def _resolve_local_path(run_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return run_dir / path


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _dedupe(paths: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not path:
            continue
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result
