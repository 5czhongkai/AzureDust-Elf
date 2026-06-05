from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedEditorSoftwareRealRunnerSandbox:
    manifest: dict[str, Any]
    environment_snapshot: dict[str, Any]
    launch_plan: dict[str, Any]
    command_preview: dict[str, Any]
    audit_log: dict[str, Any]
    evidence_manifest: dict[str, Any]
    approval_request_md: str
    readme_text: str


BLOCKED_BOUNDARY = "blocked_pending_explicit_human_real_run_approval"
APPROVED_BOUNDARY = "approved_for_manual_external_sandbox_launch_not_executed"
ACCEPTED_APPROVAL_STATUS = "approved_for_editor_software_real_runner_sandbox"


def generate_editor_software_real_runner_sandbox(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    import_manifest: dict[str, Any],
    import_plan: dict[str, Any],
    import_commands: dict[str, Any],
    rollback_safety_report: dict[str, Any],
    human_real_run_approval: dict[str, Any] | None,
    manifest_path: str,
    environment_snapshot_path: str,
    launch_plan_path: str,
    command_preview_path: str,
    audit_log_path: str,
    evidence_manifest_path: str,
    approval_request_path: str,
    readme_path: str,
) -> GeneratedEditorSoftwareRealRunnerSandbox:
    expected_approval_path = f"assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval.json"
    source_import_manifest_path = str(import_manifest.get("manifest_path") or "")
    source_import_plan_path = str(import_manifest.get("import_plan_path") or "")
    source_import_commands_path = str(import_manifest.get("import_commands_path") or "")
    source_rollback_safety_report_path = str(import_manifest.get("rollback_safety_report_path") or "")
    patched_project_path = str(
        import_manifest.get("source_patched_project_path")
        or import_plan.get("source_patched_project_path")
        or rollback_safety_report.get("patched_project_path")
        or ""
    )
    patched_project_sha256 = str(
        import_manifest.get("validation", {}).get("patched_project_sha256")
        if isinstance(import_manifest.get("validation"), dict)
        else ""
    ) or str(rollback_safety_report.get("patched_project_sha256") or "")
    approval = _approval_state(
        human_real_run_approval,
        expected_approval_path=expected_approval_path,
        patched_project_sha256=patched_project_sha256,
    )
    import_items = [item for item in import_manifest.get("import_items", []) if isinstance(item, dict)]
    commands = [item for item in import_commands.get("commands", []) if isinstance(item, dict)]
    runner_items = [
        _runner_item_for_import_item(
            item,
            approval_active=approval["approval_active"],
            patched_project_path=patched_project_path,
        )
        for item in import_items
    ]
    launch_commands = [
        _launch_command_for_import_command(
            run_dir=run_dir,
            platform=platform,
            command=command,
            approval_active=approval["approval_active"],
        )
        for command in commands
    ]
    ready_count = len([item for item in runner_items if item["real_run_status"] == "ready_for_manual_external_sandbox_launch"])
    blocked_count = len([item for item in runner_items if str(item["real_run_status"]).startswith("blocked_")])
    boundary_state = APPROVED_BOUNDARY if approval["approval_active"] and ready_count > 0 else BLOCKED_BOUNDARY
    sandbox_root = f"assets/{platform}/edit/software_real_runner_sandbox"
    source_artifacts = _dedupe(
        [
            source_import_manifest_path,
            source_import_plan_path,
            source_import_commands_path,
            import_manifest.get("audit_log_path"),
            source_rollback_safety_report_path,
            import_manifest.get("execution_request_path"),
            patched_project_path,
            approval["approval_path"] if approval["approval_present"] else None,
            manifest_path,
            environment_snapshot_path,
            launch_plan_path,
            command_preview_path,
            audit_log_path,
            evidence_manifest_path,
            approval_request_path,
            readme_path,
        ]
    )
    export_boundary = {
        "editor_software_real_runner_sandbox": boundary_state,
        "real_software_launch": "not_performed",
        "software_import_execution": "not_performed",
        "editing_software": "not_opened",
        "project_file_mutation": "not_performed_by_runner",
        "original_project_mutation": "not_performed",
        "replacement_execution": "not_performed",
        "requires_explicit_human_real_run_approval": True,
        "external_process_isolation": "required_before_human_launch",
        "process_spawn": "not_performed",
        "asset_download": "not_performed",
        "external_asset_search": "not_performed",
        "license_purchase": "not_performed",
        "upload": "not_performed",
        "publishing": "not_performed",
    }
    summary = {
        "runner_item_count": len(runner_items),
        "ready_for_manual_external_sandbox_launch_count": ready_count,
        "blocked_runner_count": blocked_count,
        "blocked_pending_approval_count": len(
            [item for item in runner_items if item["real_run_status"] == "blocked_pending_human_real_run_approval"]
        ),
        "blocked_import_not_ready_count": len(
            [item for item in runner_items if item["real_run_status"] == "blocked_import_not_ready"]
        ),
        "launched_count": 0,
        "process_spawned_count": 0,
        "editing_software_opened_count": 0,
    }
    validation = {
        "status": "PASSED" if runner_items and patched_project_path and patched_project_sha256 else "NEEDS_REVIEW",
        "patched_project_path": patched_project_path,
        "patched_project_sha256": patched_project_sha256,
        "human_real_run_approval_required": True,
        "human_real_run_approval_present": approval["approval_present"],
        "human_real_run_approval_valid": approval["approval_active"],
        "real_software_launch_performed": False,
        "software_import_execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "original_project_mutated": False,
        "replacement_execution_performed": False,
        "process_spawned": False,
        "upload_performed": False,
        "publishing_performed": False,
        "manual_external_launch_required": True,
        "external_process_isolation_required": True,
        "ready_for_manual_external_sandbox_launch_count": ready_count,
    }
    environment_snapshot = {
        "schema_version": "phase4.editor_software_real_runner_environment_snapshot.v1",
        "artifact_type": "editor_software_real_runner_environment_snapshot",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "environment_snapshot_path": environment_snapshot_path,
        "sandbox_root": sandbox_root,
        "working_directory": str(run_dir),
        "source_patched_project_path": patched_project_path,
        "source_import_manifest_path": source_import_manifest_path,
        "source_import_plan_path": source_import_plan_path,
        "source_import_commands_path": source_import_commands_path,
        "source_rollback_safety_report_path": source_rollback_safety_report_path,
        "target_editor": import_manifest.get("target_editor") or "fcpxml_compatible_editor",
        "isolation_requirements": [
            "Use a human-controlled external editor environment.",
            "Do not run inside the content automation process.",
            "Capture before/after evidence if a human launches the editor manually.",
            "Keep the original project file immutable.",
        ],
        "export_boundary": export_boundary,
        "validation": validation,
        "review_required": True,
    }
    launch_plan = {
        "schema_version": "phase4.editor_software_real_runner_launch_plan.v1",
        "artifact_type": "editor_software_real_runner_launch_plan",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "launch_plan_path": launch_plan_path,
        "sandbox_root": sandbox_root,
        "source_patched_project_path": patched_project_path,
        "runner_items": runner_items,
        "launch_commands": launch_commands,
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "manual_review_required": True,
        "human_real_run_approval_required": True,
        "review_required": True,
    }
    command_preview = {
        "schema_version": "phase4.editor_software_real_runner_command_preview.v1",
        "artifact_type": "editor_software_real_runner_command_preview",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "command_preview_path": command_preview_path,
        "commands": launch_commands,
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "manual_review_required": True,
        "human_real_run_approval_required": True,
        "review_required": True,
    }
    audit_log = {
        "schema_version": "phase4.editor_software_real_runner_audit_log.v1",
        "artifact_type": "editor_software_real_runner_audit_log",
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
    evidence_manifest = {
        "schema_version": "phase4.editor_software_real_runner_evidence_manifest.v1",
        "artifact_type": "editor_software_real_runner_evidence_manifest",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "evidence_manifest_path": evidence_manifest_path,
        "expected_evidence_after_manual_launch": [
            "manual_launch_timestamp",
            "editor_process_identity",
            "opened_project_path",
            "post_launch_screenshot_or_export_log",
            "human_outcome_note",
        ],
        "evidence_collected": [],
        "evidence_collection_status": "not_started_no_real_software_launch",
        "real_software_launch_performed": False,
        "software_import_execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "export_boundary": export_boundary,
        "validation": validation,
        "review_required": True,
    }
    manifest = {
        "schema_version": "phase4.editor_software_real_runner_sandbox_manifest.v1",
        "artifact_type": "editor_software_real_runner_sandbox",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-editor-software-real-runner-sandbox-adapter",
        "adapter_version": "0.1.0",
        "manifest_path": manifest_path,
        "environment_snapshot_path": environment_snapshot_path,
        "launch_plan_path": launch_plan_path,
        "command_preview_path": command_preview_path,
        "audit_log_path": audit_log_path,
        "evidence_manifest_path": evidence_manifest_path,
        "approval_request_path": approval_request_path,
        "readme_path": readme_path,
        "source_import_manifest_path": source_import_manifest_path,
        "source_import_plan_path": source_import_plan_path,
        "source_import_commands_path": source_import_commands_path,
        "source_rollback_safety_report_path": source_rollback_safety_report_path,
        "source_patched_project_path": patched_project_path,
        "human_real_run_approval_path": approval["approval_path"],
        "human_real_run_approval_present": approval["approval_present"],
        "human_real_run_approval_valid": approval["approval_active"],
        "target_editor": import_manifest.get("target_editor") or "fcpxml_compatible_editor",
        "runner_items": runner_items,
        "summary": summary,
        "source_artifacts": source_artifacts,
        "export_boundary": export_boundary,
        "validation": validation,
        "generation_status": "generated_local_editor_software_real_runner_sandbox_pending_explicit_human_launch",
        "manual_review_required": True,
        "human_real_run_approval_required": True,
        "review_required": True,
    }
    return GeneratedEditorSoftwareRealRunnerSandbox(
        manifest=manifest,
        environment_snapshot=environment_snapshot,
        launch_plan=launch_plan,
        command_preview=command_preview,
        audit_log=audit_log,
        evidence_manifest=evidence_manifest,
        approval_request_md=_render_approval_request(
            topic=topic,
            platform_label=platform_label,
            manifest=manifest,
            approved=approval["approval_active"],
        ),
        readme_text=_render_readme(platform_label=platform_label, manifest=manifest),
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
        and approval.get("human_real_run_approval") is True
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


def _runner_item_for_import_item(
    item: dict[str, Any],
    *,
    approval_active: bool,
    patched_project_path: str,
) -> dict[str, Any]:
    import_status = str(item.get("import_status") or "")
    if import_status != "ready_for_isolated_manual_import":
        real_run_status = "blocked_import_not_ready"
    elif not approval_active:
        real_run_status = "blocked_pending_human_real_run_approval"
    else:
        real_run_status = "ready_for_manual_external_sandbox_launch"
    return {
        "command_id": str(item.get("command_id") or f"real_run_{item.get('asset_id')}"),
        "asset_id": str(item.get("asset_id") or ""),
        "shot_id": item.get("shot_id"),
        "timeline_track": item.get("timeline_track"),
        "source_import_status": import_status,
        "patched_project_path": item.get("patched_project_path") or patched_project_path,
        "human_real_run_approved": approval_active,
        "real_run_status": real_run_status,
        "real_software_launch_performed": False,
        "software_import_execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "process_spawned": False,
        "upload_performed": False,
        "publishing_performed": False,
        "execution_mode": "manual_external_sandbox_launch_only",
    }


def _launch_command_for_import_command(
    *,
    run_dir: Path,
    platform: str,
    command: dict[str, Any],
    approval_active: bool,
) -> dict[str, Any]:
    patched_project_path = str(command.get("patched_project_path") or "")
    absolute_project_path = str((run_dir / patched_project_path).resolve()) if patched_project_path else ""
    manual_command_preview = command.get("manual_command_preview") or (
        f'open -a "Final Cut Pro" "{absolute_project_path}"' if absolute_project_path else ""
    )
    command_ready = command.get("execution_status") == "ready_for_isolated_manual_import" and approval_active
    return {
        "command_id": str(command.get("command_id") or f"{platform}_real_runner_command"),
        "asset_id": str(command.get("asset_id") or ""),
        "command_type": "editor_software_real_runner_sandbox",
        "source_command_type": command.get("command_type"),
        "target_editor": command.get("target_editor") or "fcpxml_compatible_editor",
        "platform": platform,
        "patched_project_path": patched_project_path,
        "manual_command_preview": manual_command_preview,
        "external_sandbox_required": True,
        "human_real_run_approval_required": True,
        "human_real_run_approved": approval_active,
        "manual_launch_ready": command_ready,
        "auto_execute": False,
        "dry_run_only": True,
        "execution_status": (
            "ready_for_manual_external_sandbox_launch"
            if command_ready
            else "blocked_pending_human_real_run_approval"
            if command.get("execution_status") == "ready_for_isolated_manual_import"
            else "blocked_import_not_ready"
        ),
        "real_software_launch_performed": False,
        "software_import_execution_performed": False,
        "editing_software_opened": False,
        "project_file_mutation_performed": False,
        "process_spawned": False,
        "upload_performed": False,
        "publishing_performed": False,
    }


def _audit_events(*, approval: dict[str, Any], ready_count: int, patched_project_path: str) -> list[dict[str, Any]]:
    events = [
        {
            "event_type": "editor_software_real_runner_sandbox_generated",
            "patched_project_path": patched_project_path,
            "human_real_run_approval_present": approval["approval_present"],
            "human_real_run_approval_valid": approval["approval_active"],
            "ready_for_manual_external_sandbox_launch_count": ready_count,
            "real_software_launch_performed": False,
            "software_import_execution_performed": False,
            "editing_software_opened": False,
            "project_file_mutation_performed": False,
            "process_spawned": False,
        }
    ]
    if approval["approval_active"]:
        events.append(
            {
                "event_type": "explicit_human_real_run_approval_verified",
                "approval_path": approval["approval_path"],
                "approved_by": approval["approved_by"],
                "ready_for_manual_external_sandbox_launch_count": ready_count,
                "real_software_launch_performed": False,
                "software_import_execution_performed": False,
                "editing_software_opened": False,
                "project_file_mutation_performed": False,
                "process_spawned": False,
            }
        )
    else:
        events.append(
            {
                "event_type": "real_runner_blocked_or_manual_only",
                "approval_path": approval["approval_path"],
                "real_software_launch_performed": False,
                "software_import_execution_performed": False,
                "editing_software_opened": False,
                "project_file_mutation_performed": False,
                "process_spawned": False,
            }
        )
    return events


def _render_approval_request(
    *,
    topic: str,
    platform_label: str,
    manifest: dict[str, Any],
    approved: bool,
) -> str:
    summary = manifest.get("summary", {})
    return "\n".join(
        [
            "# Editor Software Real Runner Sandbox Approval Request",
            "",
            f"- Topic: {topic}",
            f"- Platform: {platform_label}",
            f"- Patched project: `{manifest.get('source_patched_project_path')}`",
            f"- Boundary: `{manifest.get('export_boundary', {}).get('editor_software_real_runner_sandbox')}`",
            f"- Approval present and valid: {approved}",
            f"- Ready for manual external sandbox launch: {summary.get('ready_for_manual_external_sandbox_launch_count')}",
            f"- Blocked runner items: {summary.get('blocked_runner_count')}",
            "",
            "## Required Human Approval File",
            "",
            "Create this file only after reviewing the import executor package, rollback safety report, external editor sandbox, and evidence capture plan:",
            "",
            "```json",
            "{",
            '  "approval_status": "approved_for_editor_software_real_runner_sandbox",',
            '  "human_real_run_approval": true,',
            f'  "approved_patched_project_sha256": "{manifest.get("validation", {}).get("patched_project_sha256")}",',
            '  "approved_by": "human",',
            '  "approval_note": "Reviewed external editor sandbox, rollback plan, and evidence capture requirements."',
            "}",
            "```",
            "",
            "This agent did not launch editing software, spawn a process, execute import, mutate files, upload, or publish.",
            "",
        ]
    )


def _render_readme(*, platform_label: str, manifest: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Editor Software Real Runner Sandbox",
            "",
            f"- Platform: {platform_label}",
            f"- Manifest: `{manifest.get('manifest_path')}`",
            f"- Launch plan: `{manifest.get('launch_plan_path')}`",
            f"- Command preview: `{manifest.get('command_preview_path')}`",
            "",
            "This layer prepares a real-editor launch sandbox contract from the isolated import executor package.",
            "It does not open editing software, spawn a process, execute import, mutate project files, upload, or publish.",
            "A human must review the approval request and launch any editor command manually in an external isolated environment.",
            "",
        ]
    )


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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
