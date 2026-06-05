from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedEditorSoftwareRunEvidence:
    manifest: dict[str, Any]
    validation_report: dict[str, Any]
    rollback_decision_report: dict[str, Any]
    checklist_md: str
    readme_text: str


BLOCKED_BOUNDARY = "blocked_pending_human_real_run_result"
INGESTED_BOUNDARY = "human_evidence_ingested_no_automation_execution"
ACCEPTED_RESULT_STATUS = "human_real_run_completed"


def generate_editor_software_run_evidence(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    runner_manifest: dict[str, Any],
    launch_plan: dict[str, Any],
    command_preview: dict[str, Any],
    runner_evidence_manifest: dict[str, Any],
    human_real_run_result: dict[str, Any] | None,
    manifest_path: str,
    validation_report_path: str,
    rollback_decision_report_path: str,
    checklist_path: str,
    readme_path: str,
) -> GeneratedEditorSoftwareRunEvidence:
    expected_result_path = f"assets/{platform}/edit/software_run_evidence/human_real_run_result.json"
    result = _result_state(
        human_real_run_result,
        expected_result_path=expected_result_path,
        runner_manifest_sha256=_stable_sha256(runner_manifest),
    )
    runner_items = [item for item in runner_manifest.get("runner_items", []) if isinstance(item, dict)]
    evidence_items = [
        _evidence_item_for_runner_item(item, result_active=result["result_active"])
        for item in runner_items
    ]
    ingested_count = len([item for item in evidence_items if item["evidence_status"] == "human_real_run_evidence_ingested"])
    blocked_count = len([item for item in evidence_items if str(item["evidence_status"]).startswith("blocked_")])
    boundary_state = INGESTED_BOUNDARY if result["result_active"] and ingested_count > 0 else BLOCKED_BOUNDARY
    evidence_files = [path for path in result["evidence_files"] if isinstance(path, str)]
    existing_evidence_files = [path for path in evidence_files if (run_dir / path).exists()]
    missing_evidence_files = [path for path in evidence_files if not (run_dir / path).exists()]
    rollback_required = result["rollback_required"]
    rollback_decision = (
        "human_requested_rollback_review"
        if rollback_required
        else "no_rollback_requested_pending_final_human_closeout"
        if result["result_active"]
        else "blocked_pending_human_real_run_result"
    )
    sandbox_root = f"assets/{platform}/edit/software_run_evidence"
    source_artifacts = _dedupe(
        [
            runner_manifest.get("manifest_path"),
            runner_manifest.get("launch_plan_path"),
            runner_manifest.get("command_preview_path"),
            runner_manifest.get("evidence_manifest_path"),
            launch_plan.get("launch_plan_path"),
            command_preview.get("command_preview_path"),
            runner_evidence_manifest.get("evidence_manifest_path"),
            result["result_path"] if result["result_present"] else None,
            *evidence_files,
            manifest_path,
            validation_report_path,
            rollback_decision_report_path,
            checklist_path,
            readme_path,
        ]
    )
    export_boundary = {
        "editor_software_run_evidence": boundary_state,
        "real_software_launch_by_automation": "not_performed",
        "software_import_execution_by_automation": "not_performed",
        "editing_software": "not_opened_by_automation",
        "project_file_mutation": "not_performed_by_evidence_ingest",
        "original_project_mutation": "not_performed",
        "replacement_execution_by_automation": "not_performed",
        "process_spawn": "not_performed",
        "evidence_ingest_only": True,
        "requires_human_real_run_result": True,
        "asset_download": "not_performed",
        "external_asset_search": "not_performed",
        "license_purchase": "not_performed",
        "upload": "not_performed",
        "publishing": "not_performed",
    }
    summary = {
        "evidence_item_count": len(evidence_items),
        "human_real_run_evidence_ingested_count": ingested_count,
        "blocked_evidence_count": blocked_count,
        "evidence_file_count": len(evidence_files),
        "existing_evidence_file_count": len(existing_evidence_files),
        "missing_evidence_file_count": len(missing_evidence_files),
        "rollback_required_count": 1 if rollback_required else 0,
    }
    validation = {
        "status": "PASSED" if evidence_items else "NEEDS_REVIEW",
        "human_real_run_result_required": True,
        "human_real_run_result_present": result["result_present"],
        "human_real_run_result_valid": result["result_active"],
        "runner_manifest_sha256": result["runner_manifest_sha256"],
        "evidence_files_exist": not missing_evidence_files,
        "missing_evidence_files": missing_evidence_files,
        "real_software_launch_performed_by_automation": False,
        "software_import_execution_performed_by_automation": False,
        "editing_software_opened_by_automation": False,
        "project_file_mutation_performed_by_automation": False,
        "process_spawned_by_automation": False,
        "upload_performed": False,
        "publishing_performed": False,
        "rollback_required": rollback_required,
    }
    manifest = {
        "schema_version": "phase4.editor_software_run_evidence_manifest.v1",
        "artifact_type": "editor_software_run_evidence",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "manifest_path": manifest_path,
        "validation_report_path": validation_report_path,
        "rollback_decision_report_path": rollback_decision_report_path,
        "checklist_path": checklist_path,
        "readme_path": readme_path,
        "sandbox_root": sandbox_root,
        "source_runner_manifest_path": runner_manifest.get("manifest_path"),
        "source_launch_plan_path": runner_manifest.get("launch_plan_path") or launch_plan.get("launch_plan_path"),
        "source_command_preview_path": runner_manifest.get("command_preview_path") or command_preview.get("command_preview_path"),
        "source_runner_evidence_manifest_path": runner_manifest.get("evidence_manifest_path")
        or runner_evidence_manifest.get("evidence_manifest_path"),
        "human_real_run_result_path": result["result_path"],
        "human_real_run_result_present": result["result_present"],
        "human_real_run_result_valid": result["result_active"],
        "evidence_items": evidence_items,
        "evidence_files": evidence_files,
        "missing_evidence_files": missing_evidence_files,
        "rollback_decision": rollback_decision,
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "source_artifacts": source_artifacts,
        "generation_status": "generated_local_software_run_evidence_pending_human_result",
        "manual_review_required": True,
        "human_real_run_result_required": True,
        "review_required": True,
        "adapter": "local-editor-software-run-evidence-adapter",
        "adapter_version": "1.0",
    }
    validation_report = {
        "schema_version": "phase4.editor_software_run_evidence_validation_report.v1",
        "artifact_type": "editor_software_run_evidence_validation_report",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "validation_report_path": validation_report_path,
        "evidence_items": evidence_items,
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "review_required": True,
    }
    rollback_decision_report = {
        "schema_version": "phase4.editor_software_run_evidence_rollback_decision_report.v1",
        "artifact_type": "editor_software_run_evidence_rollback_decision_report",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "rollback_decision_report_path": rollback_decision_report_path,
        "rollback_decision": rollback_decision,
        "rollback_required": rollback_required,
        "rollback_reason": result["rollback_reason"],
        "rollback_policy": "human_decision_only_no_automation_rollback",
        "export_boundary": export_boundary,
        "validation": validation,
        "review_required": True,
    }
    checklist_md = _render_checklist(platform_label, result, summary, rollback_decision)
    readme_text = _render_readme(platform_label, result, summary)
    return GeneratedEditorSoftwareRunEvidence(
        manifest=manifest,
        validation_report=validation_report,
        rollback_decision_report=rollback_decision_report,
        checklist_md=checklist_md,
        readme_text=readme_text,
    )


def _evidence_item_for_runner_item(item: dict[str, Any], *, result_active: bool) -> dict[str, Any]:
    runner_ready = item.get("real_run_status") == "ready_for_manual_external_sandbox_launch"
    status = "human_real_run_evidence_ingested" if result_active and runner_ready else "blocked_pending_human_real_run_result"
    return {
        "asset_id": item.get("asset_id"),
        "source_runner_item_status": item.get("real_run_status"),
        "evidence_status": status,
        "human_real_run_result_required": True,
        "human_real_run_result_valid": result_active,
        "real_software_launch_performed_by_automation": False,
        "software_import_execution_performed_by_automation": False,
        "editing_software_opened_by_automation": False,
        "project_file_mutation_performed_by_automation": False,
        "process_spawned_by_automation": False,
        "upload_performed": False,
        "publishing_performed": False,
    }


def _result_state(
    result: dict[str, Any] | None,
    *,
    expected_result_path: str,
    runner_manifest_sha256: str,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {
            "result_present": False,
            "result_active": False,
            "result_path": expected_result_path,
            "runner_manifest_sha256": runner_manifest_sha256,
            "evidence_files": [],
            "rollback_required": False,
            "rollback_reason": "",
        }
    expected_hash = str(result.get("approved_runner_manifest_sha256") or "")
    result_active = (
        result.get("result_status") == ACCEPTED_RESULT_STATUS
        and result.get("human_real_run_completed") is True
        and result.get("completed_by") == "human"
        and expected_hash == runner_manifest_sha256
    )
    return {
        "result_present": True,
        "result_active": result_active,
        "result_path": str(result.get("result_path") or expected_result_path),
        "runner_manifest_sha256": runner_manifest_sha256,
        "evidence_files": [path for path in result.get("evidence_files", []) if isinstance(path, str)],
        "rollback_required": result.get("rollback_required") is True,
        "rollback_reason": str(result.get("rollback_reason") or ""),
    }


def _render_checklist(platform_label: str, result: dict[str, Any], summary: dict[str, Any], rollback_decision: str) -> str:
    return "\n".join(
        [
            "# Post-Launch Evidence Checklist",
            "",
            f"- Platform: {platform_label}",
            f"- Human real run result present: {result['result_present']}",
            f"- Human real run result valid: {result['result_active']}",
            f"- Evidence items: {summary['evidence_item_count']}",
            f"- Evidence files listed: {summary['evidence_file_count']}",
            f"- Rollback decision: {rollback_decision}",
            "- Automation real software launch: not performed",
            "- Automation software import execution: not performed",
            "- Automation process spawn: not performed",
            "- Automation project file mutation: not performed",
            "",
            "Human closeout still required before publishing or upload.",
        ]
    )


def _render_readme(platform_label: str, result: dict[str, Any], summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Editor Software Run Evidence",
            "",
            f"Platform: {platform_label}",
            "",
            "This folder ingests human-provided evidence from an external editor sandbox run.",
            "It does not launch editing software, spawn a process, execute import, mutate project files, upload, or publish.",
            "",
            f"- Human result present: {result['result_present']}",
            f"- Human result valid: {result['result_active']}",
            f"- Evidence items: {summary['evidence_item_count']}",
            f"- Blocked evidence items: {summary['blocked_evidence_count']}",
        ]
    )


def _stable_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dedupe(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
