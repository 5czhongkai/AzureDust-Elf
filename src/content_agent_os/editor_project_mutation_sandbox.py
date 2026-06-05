from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedEditorProjectMutationSandbox:
    manifest: dict[str, Any]
    patched_project_text: str
    mutation_diff: dict[str, Any]
    rollback_manifest: dict[str, Any]
    audit_log: dict[str, Any]
    final_review_checklist_md: str
    readme_text: str


BLOCKED_BOUNDARY = "blocked_pending_explicit_human_mutation_approval"
APPROVED_BOUNDARY = "sandbox_patch_generated_from_explicit_human_approval"
ACCEPTED_APPROVAL_STATUS = "approved_for_project_mutation_sandbox"


def generate_editor_project_mutation_sandbox(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    execution_manifest: dict[str, Any],
    execution_plan: dict[str, Any],
    export_manifest: dict[str, Any],
    edit_timeline: dict[str, Any],
    source_project_text: str,
    human_mutation_approval: dict[str, Any] | None,
    manifest_path: str,
    patched_project_path: str,
    mutation_diff_path: str,
    rollback_manifest_path: str,
    audit_log_path: str,
    final_review_checklist_path: str,
    readme_path: str,
) -> GeneratedEditorProjectMutationSandbox:
    expected_approval_path = f"assets/{platform}/edit/mutation_sandbox/human_mutation_approval.json"
    approval = _approval_state(human_mutation_approval, expected_approval_path=expected_approval_path)
    source_project_path = str(export_manifest.get("project_path") or f"assets/{platform}/edit/project.fcpxml")
    original_sha256 = _sha256_text(source_project_text)
    root = ET.fromstring(source_project_text.encode("utf-8"))
    shot_refs = _shot_refs_by_id(edit_timeline)
    path_refs = _shot_refs_by_placeholder_path(edit_timeline)
    execution_items = [
        item
        for item in execution_plan.get("commands", execution_manifest.get("execution_items", []))
        if isinstance(item, dict) and item.get("asset_id")
    ]

    mutation_items: list[dict[str, Any]] = []
    mutations: list[dict[str, Any]] = []
    for item in execution_items:
        mutation_item = _mutation_item_for_execution_item(
            run_dir=run_dir,
            item=item,
            approval_active=approval["approval_active"],
            approved_asset_ids=approval["approved_asset_ids"],
            shot_refs=shot_refs,
            path_refs=path_refs,
            root=root,
            source_project_path=source_project_path,
            patched_project_path=patched_project_path,
        )
        mutation_items.append(mutation_item)
        if mutation_item["mutation_status"] == "sandbox_patch_applied":
            mutations.append(_mutation_record(mutation_item))

    mutation_applied_count = len(mutations)
    blocked_count = len([item for item in mutation_items if str(item["mutation_status"]).startswith("blocked_")])
    target_missing_count = len([item for item in mutation_items if item["mutation_status"] == "blocked_fcpxml_asset_ref_missing"])
    patched_project_text = source_project_text
    if mutation_applied_count > 0:
        patched_project_text = _serialize_fcpxml(root)
    patched_sha256 = _sha256_text(patched_project_text)
    boundary_state = APPROVED_BOUNDARY if approval["approval_active"] and mutation_applied_count > 0 else BLOCKED_BOUNDARY
    source_artifacts = _dedupe(
        [
            execution_manifest.get("manifest_path"),
            execution_manifest.get("execution_plan_path"),
            execution_manifest.get("audit_log_path"),
            execution_manifest.get("approval_request_path"),
            execution_plan.get("execution_plan_path"),
            export_manifest.get("manifest_path"),
            export_manifest.get("project_path"),
            f"assets/{platform}/edit/edit_timeline.json",
            approval["approval_path"] if approval["approval_present"] else None,
            *[
                item.get("proxy_media_path")
                for item in mutation_items
                if isinstance(item.get("proxy_media_path"), str)
            ],
            manifest_path,
            patched_project_path,
            mutation_diff_path,
            rollback_manifest_path,
            audit_log_path,
            final_review_checklist_path,
            readme_path,
        ]
    )
    export_boundary = {
        "editor_project_mutation_sandbox": boundary_state,
        "original_project_mutation": "not_performed",
        "sandbox_project_mutation": "performed_on_patched_copy_only"
        if mutation_applied_count > 0
        else "not_performed",
        "replacement_execution": "not_performed",
        "editing_software": "not_opened",
        "project_file_mutation": "patched_copy_only_original_not_mutated",
        "requires_explicit_human_mutation_approval": True,
        "asset_download": "not_performed",
        "external_asset_search": "not_performed",
        "license_purchase": "not_performed",
        "upload": "not_performed",
        "publishing": "not_performed",
    }
    validation = {
        "status": "PASSED" if source_project_text.strip() and target_missing_count == 0 else "NEEDS_REVIEW",
        "source_project_exists": True,
        "patched_copy_generated": bool(patched_project_text.strip()),
        "original_project_mutated": False,
        "editing_software_opened": False,
        "replacement_execution_performed": False,
        "upload_performed": False,
        "publishing_performed": False,
        "human_mutation_approval_required": True,
        "human_mutation_approval_present": approval["approval_present"],
        "human_mutation_approval_valid": approval["approval_active"],
        "mutation_applied_count": mutation_applied_count,
        "blocked_mutation_count": blocked_count,
        "target_missing_count": target_missing_count,
        "original_project_sha256": original_sha256,
        "patched_project_sha256": patched_sha256,
        "patched_project_differs_from_original": original_sha256 != patched_sha256,
    }
    summary = {
        "execution_item_count": len(mutation_items),
        "mutation_applied_count": mutation_applied_count,
        "blocked_mutation_count": blocked_count,
        "blocked_pending_approval_count": len(
            [item for item in mutation_items if item["mutation_status"] == "blocked_pending_human_mutation_approval"]
        ),
        "blocked_execution_not_ready_count": len(
            [item for item in mutation_items if item["mutation_status"] == "blocked_execution_not_ready"]
        ),
        "blocked_proxy_media_missing_count": len(
            [item for item in mutation_items if item["mutation_status"] == "blocked_proxy_media_missing"]
        ),
        "target_missing_count": target_missing_count,
    }
    manifest = {
        "schema_version": "phase4.editor_project_mutation_sandbox_manifest.v1",
        "artifact_type": "editor_project_mutation_sandbox",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-editor-project-mutation-sandbox-adapter",
        "adapter_version": "0.1.0",
        "manifest_path": manifest_path,
        "patched_project_path": patched_project_path,
        "mutation_diff_path": mutation_diff_path,
        "rollback_manifest_path": rollback_manifest_path,
        "audit_log_path": audit_log_path,
        "final_review_checklist_path": final_review_checklist_path,
        "readme_path": readme_path,
        "source_execution_manifest_path": execution_manifest.get("manifest_path"),
        "source_execution_plan_path": execution_manifest.get("execution_plan_path")
        or execution_plan.get("execution_plan_path"),
        "source_export_manifest_path": export_manifest.get("manifest_path"),
        "source_project_path": source_project_path,
        "source_edit_timeline_path": f"assets/{platform}/edit/edit_timeline.json",
        "human_mutation_approval_path": approval["approval_path"],
        "human_mutation_approval_present": approval["approval_present"],
        "human_mutation_approval_valid": approval["approval_active"],
        "mutation_items": mutation_items,
        "mutations": mutations,
        "summary": summary,
        "source_artifacts": source_artifacts,
        "export_boundary": export_boundary,
        "validation": validation,
        "generation_status": "generated_local_project_mutation_sandbox_pending_final_human_review",
        "manual_review_required": True,
        "human_mutation_approval_required": True,
        "review_required": True,
    }
    mutation_diff = {
        "schema_version": "phase4.editor_project_mutation_diff.v1",
        "artifact_type": "editor_project_mutation_diff",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "manifest_path": manifest_path,
        "mutation_diff_path": mutation_diff_path,
        "original_project_path": source_project_path,
        "patched_project_path": patched_project_path,
        "mutations": mutations,
        "mutation_items": mutation_items,
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "manual_review_required": True,
        "human_mutation_approval_required": True,
        "review_required": True,
    }
    rollback_manifest = {
        "schema_version": "phase4.editor_project_mutation_rollback_manifest.v1",
        "artifact_type": "editor_project_mutation_rollback_manifest",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "original_project_path": source_project_path,
        "patched_project_path": patched_project_path,
        "rollback_policy": "discard_patched_copy_keep_original_project",
        "original_project_sha256": original_sha256,
        "patched_project_sha256": patched_sha256,
        "mutations": mutations,
        "summary": summary,
        "manual_review_required": True,
        "review_required": True,
    }
    audit_log = {
        "schema_version": "phase4.editor_project_mutation_audit_log.v1",
        "artifact_type": "editor_project_mutation_audit_log",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "events": _audit_events(
            approval=approval,
            mutation_applied_count=mutation_applied_count,
            source_project_path=source_project_path,
            patched_project_path=patched_project_path,
        ),
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
    }
    return GeneratedEditorProjectMutationSandbox(
        manifest=manifest,
        patched_project_text=patched_project_text,
        mutation_diff=mutation_diff,
        rollback_manifest=rollback_manifest,
        audit_log=audit_log,
        final_review_checklist_md=_render_final_review_checklist(
            topic=topic,
            platform_label=platform_label,
            manifest=manifest,
        ),
        readme_text=_render_readme(topic=topic, platform_label=platform_label, manifest=manifest),
    )


def _mutation_item_for_execution_item(
    *,
    run_dir: Path,
    item: dict[str, Any],
    approval_active: bool,
    approved_asset_ids: set[str],
    shot_refs: dict[str, str],
    path_refs: dict[str, str],
    root: ET.Element,
    source_project_path: str,
    patched_project_path: str,
) -> dict[str, Any]:
    asset_id = str(item["asset_id"])
    proxy_path = _optional_string(item.get("proxy_media_path"))
    proxy_file = _resolve_local_path(run_dir, proxy_path)
    proxy_exists = bool(proxy_file and proxy_file.exists() and proxy_file.is_file())
    approved = approval_active and (asset_id in approved_asset_ids or "*" in approved_asset_ids)
    source_ref = _source_asset_ref_for_item(item, shot_refs, path_refs)
    asset_element = _asset_element_by_id(root, source_ref) if source_ref else None
    original_src = asset_element.get("src") if asset_element is not None else None
    original_name = asset_element.get("name") if asset_element is not None else None

    if item.get("execution_status") != "ready_for_manual_execution":
        status = "blocked_execution_not_ready"
    elif not proxy_exists:
        status = "blocked_proxy_media_missing"
    elif not approved:
        status = "blocked_pending_human_mutation_approval"
    elif asset_element is None:
        status = "blocked_fcpxml_asset_ref_missing"
    else:
        patched_src = proxy_file.resolve().as_uri() if proxy_file is not None else None
        patched_name = proxy_file.name if proxy_file is not None else None
        if patched_src:
            asset_element.set("src", patched_src)
        if patched_name:
            asset_element.set("name", patched_name)
        status = "sandbox_patch_applied"

    patched_src = asset_element.get("src") if asset_element is not None else None
    patched_name = asset_element.get("name") if asset_element is not None else None
    return {
        "command_id": item.get("command_id") or f"replace_{asset_id}",
        "asset_id": asset_id,
        "shot_id": item.get("shot_id"),
        "timeline_track": item.get("timeline_track"),
        "start_seconds": item.get("start_seconds"),
        "end_seconds": item.get("end_seconds"),
        "placeholder_source_path": item.get("placeholder_source_path"),
        "proxy_media_path": proxy_path,
        "proxy_media_exists": proxy_exists,
        "proxy_media_sha256": item.get("proxy_media_sha256"),
        "source_asset_ref": source_ref,
        "original_src": original_src,
        "patched_src": patched_src,
        "original_name": original_name,
        "patched_name": patched_name,
        "execution_status": item.get("execution_status"),
        "human_execution_approved": item.get("human_execution_approved") is True,
        "human_mutation_approved": approved,
        "mutation_status": status,
        "mutation_applied": status == "sandbox_patch_applied",
        "original_project_path": source_project_path,
        "patched_project_path": patched_project_path,
        "rollback_action": "discard_patched_copy_keep_original_project",
        "editing_software_opened": False,
        "original_project_mutated": False,
        "replacement_execution_performed": False,
    }


def _mutation_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": item.get("asset_id"),
        "command_id": item.get("command_id"),
        "shot_id": item.get("shot_id"),
        "source_asset_ref": item.get("source_asset_ref"),
        "original_src": item.get("original_src"),
        "patched_src": item.get("patched_src"),
        "original_name": item.get("original_name"),
        "patched_name": item.get("patched_name"),
        "mutation_status": item.get("mutation_status"),
        "original_project_path": item.get("original_project_path"),
        "patched_project_path": item.get("patched_project_path"),
        "rollback_action": item.get("rollback_action"),
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
        and approval.get("human_mutation_approval") is True
        and bool(approved_asset_ids),
        "approval_path": approval.get("approval_path") or expected_approval_path,
        "approved_asset_ids": approved_asset_ids,
    }


def _shot_refs_by_id(edit_timeline: dict[str, Any]) -> dict[str, str]:
    tracks = edit_timeline.get("tracks")
    video = tracks.get("video") if isinstance(tracks, dict) else []
    result: dict[str, str] = {}
    if not isinstance(video, list):
        return result
    for index, clip in enumerate(video, start=1):
        if not isinstance(clip, dict):
            continue
        shot_id = str(clip.get("id") or clip.get("shot_id") or "")
        if shot_id:
            result[shot_id] = f"r_video_{index}"
    return result


def _shot_refs_by_placeholder_path(edit_timeline: dict[str, Any]) -> dict[str, str]:
    tracks = edit_timeline.get("tracks")
    video = tracks.get("video") if isinstance(tracks, dict) else []
    result: dict[str, str] = {}
    if not isinstance(video, list):
        return result
    for index, clip in enumerate(video, start=1):
        if not isinstance(clip, dict):
            continue
        source_path = str(clip.get("source_path") or "")
        if source_path:
            result[source_path] = f"r_video_{index}"
    return result


def _source_asset_ref_for_item(
    item: dict[str, Any],
    shot_refs: dict[str, str],
    path_refs: dict[str, str],
) -> str | None:
    shot_id = _optional_string(item.get("shot_id"))
    if shot_id and shot_id in shot_refs:
        return shot_refs[shot_id]
    placeholder = _optional_string(item.get("placeholder_source_path"))
    if placeholder and placeholder in path_refs:
        return path_refs[placeholder]
    return None


def _asset_element_by_id(root: ET.Element, asset_id: str | None) -> ET.Element | None:
    if not asset_id:
        return None
    for element in root.iter("asset"):
        if element.get("id") == asset_id:
            return element
    return None


def _audit_events(
    *,
    approval: dict[str, Any],
    mutation_applied_count: int,
    source_project_path: str,
    patched_project_path: str,
) -> list[dict[str, Any]]:
    events = [
        {
            "event_type": "mutation_sandbox_plan_generated",
            "human_mutation_approval_present": approval["approval_present"],
            "human_mutation_approval_valid": approval["approval_active"],
            "original_project_path": source_project_path,
            "patched_project_path": patched_project_path,
            "original_project_mutated": False,
            "editing_software_opened": False,
            "replacement_execution_performed": False,
        }
    ]
    if mutation_applied_count > 0:
        events.append(
            {
                "event_type": "sandbox_patch_generated",
                "mutation_applied_count": mutation_applied_count,
                "original_project_mutated": False,
                "patched_copy_only": True,
                "editing_software_opened": False,
                "replacement_execution_performed": False,
            }
        )
    else:
        events.append(
            {
                "event_type": "sandbox_patch_blocked_or_noop",
                "status": "blocked_pending_explicit_human_mutation_approval"
                if not approval["approval_active"]
                else "no_eligible_ready_items",
                "mutation_applied_count": 0,
                "original_project_mutated": False,
                "editing_software_opened": False,
                "replacement_execution_performed": False,
            }
        )
    return events


def _render_final_review_checklist(*, topic: str, platform_label: str, manifest: dict[str, Any]) -> str:
    lines = [
        "# Editor Project Mutation Sandbox Final Review",
        "",
        f"- Topic: {topic}",
        f"- Platform: {platform_label}",
        f"- Mutation manifest: `{manifest['manifest_path']}`",
        f"- Patched project copy: `{manifest['patched_project_path']}`",
        f"- Original project: `{manifest['source_project_path']}`",
        f"- Applied sandbox mutations: {manifest['summary']['mutation_applied_count']}",
        "",
        "Review each item before replacing or importing anything in an editor.",
        "",
    ]
    for item in manifest.get("mutation_items", []):
        lines.extend(
            [
                f"- [ ] `{item['asset_id']}` status `{item['mutation_status']}`",
                f"  - Source asset ref: `{item.get('source_asset_ref')}`",
                f"  - Proxy media: `{item.get('proxy_media_path')}`",
                f"  - Original src: `{item.get('original_src')}`",
                f"  - Patched src: `{item.get('patched_src')}`",
                "  - Confirm rights, visual fit, timing, rollback plan, and final editor approval.",
            ]
        )
    lines.extend(
        [
            "",
            "Approval file contract for generating a sandbox patch:",
            "",
            "```json",
            "{",
            '  "approval_status": "approved_for_project_mutation_sandbox",',
            '  "human_mutation_approval": true,',
            '  "approved_asset_ids": ["asset_id_or_*"],',
            '  "approved_by": "human",',
            '  "approval_note": "Reviewed execution plan and allow sandbox patched project generation."',
            "}",
            "```",
            "",
            "This layer does not open editing software, mutate the original project, execute replacements, upload, or publish.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_readme(*, topic: str, platform_label: str, manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    return "\n".join(
        [
            "# Editor Project Mutation Sandbox",
            "",
            f"- Topic: {topic}",
            f"- Platform: {platform_label}",
            f"- Patched project copy: `{manifest['patched_project_path']}`",
            f"- Mutation diff: `{manifest['mutation_diff_path']}`",
            f"- Rollback manifest: `{manifest['rollback_manifest_path']}`",
            f"- Final review checklist: `{manifest['final_review_checklist_path']}`",
            f"- Applied sandbox mutations: {summary['mutation_applied_count']}",
            f"- Blocked mutation items: {summary['blocked_mutation_count']}",
            "",
            "This layer may generate a patched FCPXML copy only after explicit human mutation approval.",
            "It never mutates the original project file, opens editing software, executes replacements, uploads, or publishes.",
            "If the sandbox patch is not approved or has no ready execution items, the patched project is an unchanged copy for review continuity.",
            "",
        ]
    )


def _serialize_fcpxml(root: ET.Element) -> str:
    body = ET.tostring(root, encoding="unicode")
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<!DOCTYPE fcpxml>",
            body,
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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
