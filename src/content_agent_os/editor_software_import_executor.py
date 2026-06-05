from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedEditorSoftwareImportExecutor:
    manifest: dict[str, Any]
    import_plan: dict[str, Any]
    import_commands: dict[str, Any]
    audit_log: dict[str, Any]
    rollback_safety_report: dict[str, Any]
    execution_request_md: str
    readme_text: str


BLOCKED_BOUNDARY = "blocked_pending_explicit_human_software_import_approval"
APPROVED_BOUNDARY = "approved_for_isolated_manual_import_not_executed"
ACCEPTED_APPROVAL_STATUS = "approved_for_editor_software_import"


def generate_editor_software_import_executor(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    mutation_manifest: dict[str, Any],
    mutation_diff: dict[str, Any],
    rollback_manifest: dict[str, Any],
    patched_project_text: str,
    human_software_import_approval: dict[str, Any] | None,
    manifest_path: str,
    import_plan_path: str,
    import_commands_path: str,
    audit_log_path: str,
    rollback_safety_report_path: str,
    execution_request_path: str,
    readme_path: str,
) -> GeneratedEditorSoftwareImportExecutor:
    expected_approval_path = f"assets/{platform}/edit/software_import_executor/human_software_import_approval.json"
    patched_project_path = str(
        mutation_manifest.get("patched_project_path")
        or f"assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml"
    )
    approval = _approval_state(
        human_software_import_approval,
        expected_approval_path=expected_approval_path,
        patched_project_sha256=_sha256_text(patched_project_text),
    )
    patched_project_exists = bool(patched_project_text.strip())
    rollback_available = bool(rollback_manifest.get("rollback_policy"))
    mutation_items = [
        item
        for item in mutation_manifest.get("mutation_items", [])
        if isinstance(item, dict) and item.get("asset_id")
    ]
    import_items = [
        _import_item_for_mutation_item(
            item,
            approval_active=approval["approval_active"],
            patched_project_exists=patched_project_exists,
        )
        for item in mutation_items
    ]
    command_items = [
        _command_for_import_item(
            run_dir=run_dir,
            platform=platform,
            item=item,
            patched_project_path=patched_project_path,
        )
        for item in import_items
    ]
    ready_count = len([item for item in import_items if item["import_status"] == "ready_for_isolated_manual_import"])
    blocked_count = len([item for item in import_items if str(item["import_status"]).startswith("blocked_")])
    boundary_state = APPROVED_BOUNDARY if approval["approval_active"] and ready_count > 0 else BLOCKED_BOUNDARY
    source_artifacts = _dedupe(
        [
            mutation_manifest.get("manifest_path"),
            mutation_manifest.get("patched_project_path"),
            mutation_manifest.get("mutation_diff_path"),
            mutation_manifest.get("rollback_manifest_path"),
            mutation_manifest.get("audit_log_path"),
            mutation_manifest.get("final_review_checklist_path"),
            mutation_diff.get("mutation_diff_path"),
            approval["approval_path"] if approval["approval_present"] else None,
            manifest_path,
            import_plan_path,
            import_commands_path,
            audit_log_path,
            rollback_safety_report_path,
            execution_request_path,
            readme_path,
        ]
    )
    export_boundary = {
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
        "upload": "not_performed",
        "publishing": "not_performed",
    }
    summary = {
        "import_item_count": len(import_items),
        "ready_for_isolated_manual_import_count": ready_count,
        "blocked_import_count": blocked_count,
        "blocked_pending_approval_count": len(
            [item for item in import_items if item["import_status"] == "blocked_pending_human_software_import_approval"]
        ),
        "blocked_no_sandbox_patch_count": len(
            [item for item in import_items if item["import_status"] == "blocked_no_sandbox_patch_for_item"]
        ),
        "blocked_patched_project_missing_count": len(
            [item for item in import_items if item["import_status"] == "blocked_patched_project_missing"]
        ),
        "executed_count": 0,
        "editing_software_opened_count": 0,
    }
    validation = {
        "status": "PASSED" if patched_project_exists and rollback_available and import_items else "NEEDS_REVIEW",
        "patched_project_exists": patched_project_exists,
        "rollback_available": rollback_available,
        "human_software_import_approval_required": True,
        "human_software_import_approval_present": approval["approval_present"],
        "human_software_import_approval_valid": approval["approval_active"],
        "software_import_execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "original_project_mutated": False,
        "replacement_execution_performed": False,
        "upload_performed": False,
        "publishing_performed": False,
        "isolated_manual_launch_required": True,
        "patched_project_sha256": _sha256_text(patched_project_text),
        "ready_for_isolated_manual_import_count": ready_count,
    }
    manifest = {
        "schema_version": "phase4.editor_software_import_executor_manifest.v1",
        "artifact_type": "editor_software_import_executor",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-editor-software-import-executor-adapter",
        "adapter_version": "0.1.0",
        "manifest_path": manifest_path,
        "import_plan_path": import_plan_path,
        "import_commands_path": import_commands_path,
        "audit_log_path": audit_log_path,
        "rollback_safety_report_path": rollback_safety_report_path,
        "execution_request_path": execution_request_path,
        "readme_path": readme_path,
        "source_mutation_manifest_path": mutation_manifest.get("manifest_path"),
        "source_mutation_diff_path": mutation_manifest.get("mutation_diff_path"),
        "source_rollback_manifest_path": mutation_manifest.get("rollback_manifest_path"),
        "source_patched_project_path": patched_project_path,
        "human_software_import_approval_path": approval["approval_path"],
        "human_software_import_approval_present": approval["approval_present"],
        "human_software_import_approval_valid": approval["approval_active"],
        "target_editor": "fcpxml_compatible_editor",
        "import_items": import_items,
        "summary": summary,
        "source_artifacts": source_artifacts,
        "export_boundary": export_boundary,
        "validation": validation,
        "generation_status": "generated_local_editor_software_import_executor_pending_explicit_human_launch",
        "manual_review_required": True,
        "human_software_import_approval_required": True,
        "review_required": True,
    }
    import_plan = {
        "schema_version": "phase4.editor_software_import_plan.v1",
        "artifact_type": "editor_software_import_plan",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "manifest_path": manifest_path,
        "import_plan_path": import_plan_path,
        "source_patched_project_path": patched_project_path,
        "target_editor": "fcpxml_compatible_editor",
        "import_items": import_items,
        "commands": command_items,
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "manual_review_required": True,
        "human_software_import_approval_required": True,
        "review_required": True,
    }
    import_commands = {
        "schema_version": "phase4.editor_software_import_commands.v1",
        "artifact_type": "editor_software_import_commands",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "import_commands_path": import_commands_path,
        "commands": command_items,
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "manual_review_required": True,
        "human_software_import_approval_required": True,
        "review_required": True,
    }
    audit_log = {
        "schema_version": "phase4.editor_software_import_audit_log.v1",
        "artifact_type": "editor_software_import_audit_log",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "events": _audit_events(
            approval=approval,
            ready_count=ready_count,
            patched_project_path=patched_project_path,
        ),
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "review_required": True,
    }
    rollback_safety_report = {
        "schema_version": "phase4.editor_software_import_rollback_safety_report.v1",
        "artifact_type": "editor_software_import_rollback_safety_report",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "source_rollback_manifest_path": mutation_manifest.get("rollback_manifest_path"),
        "source_patched_project_path": patched_project_path,
        "original_project_path": rollback_manifest.get("original_project_path"),
        "patched_project_path": rollback_manifest.get("patched_project_path") or patched_project_path,
        "rollback_policy": rollback_manifest.get("rollback_policy") or "discard_imported_project_keep_original_and_sandbox_copy",
        "original_project_sha256": rollback_manifest.get("original_project_sha256"),
        "patched_project_sha256": rollback_manifest.get("patched_project_sha256") or _sha256_text(patched_project_text),
        "software_import_execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "export_boundary": export_boundary,
        "validation": validation,
        "manual_review_required": True,
        "review_required": True,
    }
    return GeneratedEditorSoftwareImportExecutor(
        manifest=manifest,
        import_plan=import_plan,
        import_commands=import_commands,
        audit_log=audit_log,
        rollback_safety_report=rollback_safety_report,
        execution_request_md=_render_execution_request(
            topic=topic,
            platform_label=platform_label,
            manifest=manifest,
            approved=approval["approval_active"],
        ),
        readme_text=_render_readme(
            platform_label=platform_label,
            manifest=manifest,
        ),
    )


def _approval_state(
    approval: dict[str, Any] | None,
    *,
    expected_approval_path: str,
    patched_project_sha256: str,
) -> dict[str, Any]:
    if not isinstance(approval, dict):
        return {
            "approval_present": False,
            "approval_active": False,
            "approval_path": expected_approval_path,
            "approved_by": None,
            "approval_note": None,
        }
    approved_hash = str(approval.get("approved_patched_project_sha256") or "")
    approval_active = (
        approval.get("approval_status") == ACCEPTED_APPROVAL_STATUS
        and approval.get("human_software_import_approval") is True
        and approved_hash == patched_project_sha256
        and bool(str(approval.get("approved_by") or "").strip())
    )
    return {
        "approval_present": True,
        "approval_active": approval_active,
        "approval_path": str(approval.get("approval_path") or expected_approval_path),
        "approved_by": approval.get("approved_by"),
        "approval_note": approval.get("approval_note"),
    }


def _import_item_for_mutation_item(
    item: dict[str, Any],
    *,
    approval_active: bool,
    patched_project_exists: bool,
) -> dict[str, Any]:
    mutation_status = str(item.get("mutation_status") or "")
    if not patched_project_exists:
        import_status = "blocked_patched_project_missing"
    elif not approval_active:
        import_status = "blocked_pending_human_software_import_approval"
    elif mutation_status != "sandbox_patch_applied":
        import_status = "blocked_no_sandbox_patch_for_item"
    else:
        import_status = "ready_for_isolated_manual_import"
    return {
        "command_id": str(item.get("command_id") or f"import_{item.get('asset_id')}"),
        "asset_id": str(item.get("asset_id") or ""),
        "shot_id": item.get("shot_id"),
        "timeline_track": item.get("timeline_track"),
        "start_seconds": item.get("start_seconds"),
        "end_seconds": item.get("end_seconds"),
        "source_asset_ref": item.get("source_asset_ref"),
        "patched_src": item.get("patched_src"),
        "patched_project_path": item.get("patched_project_path"),
        "source_mutation_status": mutation_status,
        "human_software_import_approved": approval_active,
        "import_status": import_status,
        "import_execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "upload_performed": False,
        "publishing_performed": False,
        "execution_mode": "isolated_manual_import_only",
    }


def _command_for_import_item(
    *,
    run_dir: Path,
    platform: str,
    item: dict[str, Any],
    patched_project_path: str,
) -> dict[str, Any]:
    absolute_project_path = str((run_dir / patched_project_path).resolve())
    command_preview = f'open -a "Final Cut Pro" "{absolute_project_path}"'
    return {
        "command_id": item["command_id"],
        "asset_id": item["asset_id"],
        "command_type": "editor_software_import",
        "target_editor": "fcpxml_compatible_editor",
        "platform": platform,
        "patched_project_path": patched_project_path,
        "manual_command_preview": command_preview,
        "isolated_execution_required": True,
        "auto_execute": False,
        "dry_run_only": True,
        "human_software_import_approval_required": True,
        "human_software_import_approved": item["human_software_import_approved"],
        "execution_status": item["import_status"],
        "import_execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "upload_performed": False,
        "publishing_performed": False,
    }


def _audit_events(
    *,
    approval: dict[str, Any],
    ready_count: int,
    patched_project_path: str,
) -> list[dict[str, Any]]:
    events = [
        {
            "event_type": "editor_software_import_executor_plan_generated",
            "patched_project_path": patched_project_path,
            "human_software_import_approval_present": approval["approval_present"],
            "human_software_import_approval_valid": approval["approval_active"],
            "ready_for_isolated_manual_import_count": ready_count,
            "software_import_execution_performed": False,
            "editing_software_opened": False,
            "project_file_mutation_performed": False,
        }
    ]
    if approval["approval_active"]:
        events.append(
            {
                "event_type": "explicit_human_software_import_approval_verified",
                "approval_path": approval["approval_path"],
                "approved_by": approval["approved_by"],
                "ready_for_isolated_manual_import_count": ready_count,
                "software_import_execution_performed": False,
                "editing_software_opened": False,
                "project_file_mutation_performed": False,
            }
        )
    else:
        events.append(
            {
                "event_type": "software_import_blocked_or_manual_only",
                "approval_path": approval["approval_path"],
                "software_import_execution_performed": False,
                "editing_software_opened": False,
                "project_file_mutation_performed": False,
            }
        )
    return events


def _render_execution_request(
    *,
    topic: str,
    platform_label: str,
    manifest: dict[str, Any],
    approved: bool,
) -> str:
    summary = manifest.get("summary", {})
    return "\n".join(
        [
            "# Editor Software Import Execution Request",
            "",
            f"- Topic: {topic}",
            f"- Platform: {platform_label}",
            f"- Patched project: `{manifest.get('source_patched_project_path')}`",
            f"- Import boundary: `{manifest.get('export_boundary', {}).get('editor_software_import_executor')}`",
            f"- Approval present and valid: {approved}",
            f"- Ready for isolated manual import: {summary.get('ready_for_isolated_manual_import_count')}",
            f"- Blocked import items: {summary.get('blocked_import_count')}",
            "",
            "## Required Human Approval File",
            "",
            "Create this file only after final review of the sandbox patched project, rollback report, and editor environment:",
            "",
            "```json",
            "{",
            '  "approval_status": "approved_for_editor_software_import",',
            '  "human_software_import_approval": true,',
            f'  "approved_patched_project_sha256": "{manifest.get("validation", {}).get("patched_project_sha256")}",',
            '  "approved_by": "human",',
            '  "approval_note": "Reviewed sandbox patched project, rollback plan, and isolated editor environment."',
            "}",
            "```",
            "",
            "No editing software was opened by this agent. No import, project mutation, upload, or publishing action was performed.",
            "",
        ]
    )


def _render_readme(*, platform_label: str, manifest: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Editor Software Import Executor",
            "",
            f"- Platform: {platform_label}",
            f"- Manifest: `{manifest.get('manifest_path')}`",
            f"- Import plan: `{manifest.get('import_plan_path')}`",
            f"- Import commands: `{manifest.get('import_commands_path')}`",
            "",
            "This layer connects the sandbox patched FCPXML project to a real editor import adapter contract.",
            "It does not open editing software, execute imports, mutate project files, upload, or publish.",
            "A human must review `isolated_execution_request.md`, create `human_software_import_approval.json`, and then launch any command manually in an isolated editor environment.",
            "",
        ]
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
