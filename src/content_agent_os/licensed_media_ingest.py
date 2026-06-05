from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedLicensedMediaIngest:
    manifest: dict[str, Any]
    readme_text: str
    review_handoff_text: str


READY_REVIEW_STATUS = "approved_for_edit"
READY_RIGHTS_CONFIRMATIONS = {
    "licensed_confirmed",
    "self_created_confirmed",
    "licensed_or_self_created_confirmed",
}


def generate_licensed_media_ingest(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    material_manifest: dict[str, Any],
    human_media_registry: dict[str, Any] | None,
    manifest_path: str,
    readme_path: str,
    review_handoff_path: str,
    human_media_registry_path: str,
) -> GeneratedLicensedMediaIngest:
    materialized_assets = [
        item
        for item in material_manifest.get("materialized_assets", [])
        if isinstance(item, dict) and item.get("asset_id")
    ]
    registry_by_asset_id = _registry_by_asset_id(human_media_registry)

    licensed_media: list[dict[str, Any]] = []
    for asset in materialized_assets:
        asset_id = str(asset["asset_id"])
        registry_entry = registry_by_asset_id.get(asset_id, {})
        licensed_media.append(
            _licensed_media_record(
                run_dir=run_dir,
                platform=platform,
                asset=asset,
                registry_entry=registry_entry,
                manifest_path=manifest_path,
                readme_path=readme_path,
                review_handoff_path=review_handoff_path,
            )
        )

    pending_count = len([item for item in licensed_media if item["intake_status"] == "pending_human_media"])
    candidate_count = len([item for item in licensed_media if item["media_exists"]])
    ready_count = len([item for item in licensed_media if item["ready_for_editor_replacement"]])
    validation_status = "PASSED" if len(licensed_media) == len(materialized_assets) and bool(licensed_media) else "NEEDS_REVIEW"
    registry_exists = (run_dir / human_media_registry_path).exists()

    source_artifacts = [
        path
        for path in [
            material_manifest.get("manifest_path"),
            material_manifest.get("readme_path"),
            human_media_registry_path if registry_exists else None,
        ]
        if isinstance(path, str) and path
    ]
    for item in licensed_media:
        if isinstance(item.get("reference_path"), str):
            source_artifacts.append(str(item["reference_path"]))
        if isinstance(item.get("licensed_media_path"), str):
            source_artifacts.append(str(item["licensed_media_path"]))
        if isinstance(item.get("license_proof_path"), str):
            source_artifacts.append(str(item["license_proof_path"]))

    manifest = {
        "schema_version": "phase4.licensed_media_ingest_manifest.v1",
        "artifact_type": "licensed_media_ingest",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-licensed-media-ingest-adapter",
        "adapter_version": "0.1.0",
        "manifest_path": manifest_path,
        "readme_path": readme_path,
        "review_handoff_path": review_handoff_path,
        "human_media_registry_path": human_media_registry_path,
        "human_media_registry_exists": registry_exists,
        "source_artifacts": _dedupe(source_artifacts),
        "licensed_media": licensed_media,
        "summary": {
            "required_final_media_count": len(licensed_media),
            "pending_human_media_count": pending_count,
            "candidate_media_count": candidate_count,
            "ready_for_editor_replacement_count": ready_count,
            "licensed_final_media_required_count": len(licensed_media),
        },
        "export_boundary": {
            "licensed_media_ingest": "review_handoff_only_pending_human_supplied_media",
            "asset_download": "not_performed",
            "external_asset_search": "not_performed",
            "editing_software": "not_opened",
            "upload": "not_performed",
            "publishing": "not_performed",
        },
        "validation": {
            "status": validation_status,
            "all_materialized_assets_covered": len(licensed_media) == len(materialized_assets),
            "required_final_media_count": len(licensed_media),
            "pending_human_media_count": pending_count,
            "candidate_media_count": candidate_count,
            "ready_for_editor_replacement_count": ready_count,
            "intake_complete": ready_count == len(licensed_media) and bool(licensed_media),
            "licensed_final_media_required": True,
        },
        "generation_status": "generated_review_handoff_pending_human_licensed_media",
        "manual_review_required": True,
        "review_required": True,
    }

    return GeneratedLicensedMediaIngest(
        manifest=manifest,
        readme_text=_render_readme(topic=topic, platform_label=platform_label, manifest=manifest),
        review_handoff_text=_render_review_handoff(topic=topic, platform_label=platform_label, manifest=manifest),
    )


def _registry_by_asset_id(human_media_registry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(human_media_registry, dict):
        return {}
    entries = human_media_registry.get("media") or human_media_registry.get("licensed_media")
    if not isinstance(entries, list):
        return {}
    return {
        str(entry["asset_id"]): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("asset_id")
    }


def _licensed_media_record(
    *,
    run_dir: Path,
    platform: str,
    asset: dict[str, Any],
    registry_entry: dict[str, Any],
    manifest_path: str,
    readme_path: str,
    review_handoff_path: str,
) -> dict[str, Any]:
    asset_id = str(asset["asset_id"])
    media_path = _optional_string(
        registry_entry.get("licensed_media_path")
        or registry_entry.get("media_path")
        or registry_entry.get("final_media_path")
    )
    license_proof_path = _optional_string(registry_entry.get("license_proof_path"))
    review_status = str(registry_entry.get("review_status") or "awaiting_human_review")
    rights_confirmation = str(registry_entry.get("rights_confirmation") or "unconfirmed")
    media_file = _resolve_local_path(run_dir, media_path)
    media_exists = bool(media_file and media_file.exists() and media_file.is_file())
    media_bytes = media_file.stat().st_size if media_exists and media_file else 0
    media_sha256 = hashlib.sha256(media_file.read_bytes()).hexdigest() if media_exists and media_file else None
    ready = (
        media_exists
        and review_status == READY_REVIEW_STATUS
        and rights_confirmation in READY_RIGHTS_CONFIRMATIONS
    )
    if ready:
        intake_status = "approved_candidate_ready_for_editor_replacement"
    elif media_exists:
        intake_status = "candidate_registered_pending_review"
    else:
        intake_status = "pending_human_media"

    return {
        "asset_id": asset_id,
        "platform": platform,
        "asset_type": "licensed_broll_media",
        "source_reference_asset_type": asset.get("asset_type"),
        "reference_path": asset.get("reference_path"),
        "planned_target_path": asset.get("planned_target_path"),
        "licensed_media_path": media_path,
        "license_proof_path": license_proof_path,
        "media_exists": media_exists,
        "media_bytes": media_bytes,
        "media_sha256": media_sha256,
        "license_source": _optional_string(registry_entry.get("license_source")),
        "rights_owner": _optional_string(registry_entry.get("rights_owner")),
        "usage_scope": _optional_string(registry_entry.get("usage_scope")),
        "reviewer": _optional_string(registry_entry.get("reviewer")),
        "review_status": review_status,
        "rights_confirmation": rights_confirmation,
        "intake_status": intake_status,
        "ready_for_editor_replacement": ready,
        "licensed_final_media_required": True,
        "manual_review_required": True,
        "manifest_path": manifest_path,
        "readme_path": readme_path,
        "review_handoff_path": review_handoff_path,
        "required_human_actions": _required_human_actions(media_exists, review_status, rights_confirmation),
    }


def _required_human_actions(
    media_exists: bool,
    review_status: str,
    rights_confirmation: str,
) -> list[str]:
    actions = []
    if not media_exists:
        actions.append("Provide a local self-created or licensed final media file and register it in human_media_registry.json.")
    if review_status != READY_REVIEW_STATUS:
        actions.append("Set review_status to approved_for_edit after human visual and editorial review.")
    if rights_confirmation not in READY_RIGHTS_CONFIRMATIONS:
        actions.append("Confirm rights as licensed_confirmed, self_created_confirmed, or licensed_or_self_created_confirmed.")
    return actions


def _render_readme(*, topic: str, platform_label: str, manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    return "\n".join(
        [
            "# Licensed Media Ingest",
            "",
            f"- Topic: {topic}",
            f"- Platform: {platform_label}",
            f"- Required final media: {summary['required_final_media_count']}",
            f"- Candidate media registered: {summary['candidate_media_count']}",
            f"- Ready for editor replacement: {summary['ready_for_editor_replacement_count']}",
            f"- Pending human media: {summary['pending_human_media_count']}",
            "",
            "## Boundary",
            "",
            "This step creates the local ingest manifest and review handoff only.",
            "It does not search, download, license, upload, publish, or open editing software.",
            "Final B-roll media must be supplied and approved by a human before editor replacement.",
            "",
            "## Human Registry",
            "",
            f"Optional registry path: `{manifest['human_media_registry_path']}`",
            "Add one record per asset with `asset_id`, `licensed_media_path`, `license_source`, `rights_confirmation`, and `review_status`.",
            "",
        ]
    )


def _render_review_handoff(*, topic: str, platform_label: str, manifest: dict[str, Any]) -> str:
    lines = [
        "# Licensed Media Review Handoff",
        "",
        f"- Topic: {topic}",
        f"- Platform: {platform_label}",
        f"- Validation: {manifest['validation']['status']}",
        "",
        "## Checklist",
        "",
    ]
    for item in manifest["licensed_media"]:
        lines.extend(
            [
                f"### {item['asset_id']}",
                "",
                f"- Reference: `{item.get('reference_path')}`",
                f"- Planned target: `{item.get('planned_target_path')}`",
                f"- Licensed media path: `{item.get('licensed_media_path') or 'PENDING'}`",
                f"- Intake status: {item['intake_status']}",
                f"- Review status: {item['review_status']}",
                f"- Rights confirmation: {item['rights_confirmation']}",
                "",
                "Required actions:",
            ]
        )
        for action in item["required_human_actions"]:
            lines.append(f"- {action}")
        lines.append("")
    return "\n".join(lines)


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _resolve_local_path(run_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return run_dir / path


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result
