from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedLicensedMediaProxy:
    manifest: dict[str, Any]
    replacement_suggestions: dict[str, Any]
    readme_text: str
    proxy_files: dict[str, bytes]


READY_INTAKE_STATUS = "approved_candidate_ready_for_editor_replacement"
PROXY_BOUNDARY = "performed_locally_from_human_registered_media_only"


def generate_licensed_media_proxy(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    licensed_media_manifest: dict[str, Any],
    manifest_path: str,
    replacement_suggestions_path: str,
    readme_path: str,
    proxy_dir: str,
) -> GeneratedLicensedMediaProxy:
    licensed_media = [
        item
        for item in licensed_media_manifest.get("licensed_media", [])
        if isinstance(item, dict) and item.get("asset_id")
    ]

    proxy_files: dict[str, bytes] = {}
    suggestions: list[dict[str, Any]] = []
    proxy_assets: list[dict[str, Any]] = []
    for item in licensed_media:
        suggestion, proxy_asset, proxy_bytes = _replacement_suggestion(
            run_dir=run_dir,
            platform=platform,
            media=item,
            proxy_dir=proxy_dir,
            manifest_path=manifest_path,
            replacement_suggestions_path=replacement_suggestions_path,
            readme_path=readme_path,
        )
        suggestions.append(suggestion)
        proxy_assets.append(proxy_asset)
        proxy_path = proxy_asset.get("proxy_media_path")
        if isinstance(proxy_path, str) and proxy_bytes is not None:
            proxy_files[proxy_path] = proxy_bytes

    ready_source_count = len([asset for asset in proxy_assets if asset["source_ready_for_proxy"]])
    copied_count = len([asset for asset in proxy_assets if asset["proxy_copy_status"] == "copied"])
    pending_count = len([asset for asset in proxy_assets if asset["replacement_status"] == "pending_human_media"])
    candidate_count = len(
        [asset for asset in proxy_assets if asset["replacement_status"] == "candidate_registered_pending_review"]
    )
    blocked_count = len([asset for asset in proxy_assets if asset["replacement_status"].startswith("blocked_")])

    source_artifacts = [
        path
        for path in [
            licensed_media_manifest.get("manifest_path"),
            licensed_media_manifest.get("readme_path"),
            licensed_media_manifest.get("review_handoff_path"),
            licensed_media_manifest.get("human_media_registry_path")
            if licensed_media_manifest.get("human_media_registry_exists") is True
            else None,
        ]
        if isinstance(path, str) and path
    ]
    for asset in proxy_assets:
        for key in ["reference_path", "licensed_media_path", "license_proof_path", "proxy_media_path"]:
            value = asset.get(key)
            if isinstance(value, str) and value:
                source_artifacts.append(value)
    source_artifacts.extend([manifest_path, replacement_suggestions_path, readme_path])

    manifest = {
        "schema_version": "phase4.licensed_media_proxy_manifest.v1",
        "artifact_type": "licensed_media_proxy",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-licensed-media-proxy-adapter",
        "adapter_version": "0.1.0",
        "manifest_path": manifest_path,
        "replacement_suggestions_path": replacement_suggestions_path,
        "readme_path": readme_path,
        "proxy_dir": proxy_dir,
        "licensed_media_ingest_manifest_path": licensed_media_manifest.get("manifest_path"),
        "source_artifacts": _dedupe(source_artifacts),
        "proxy_assets": proxy_assets,
        "summary": {
            "required_final_media_count": len(proxy_assets),
            "ready_source_media_count": ready_source_count,
            "proxy_copied_count": copied_count,
            "pending_human_media_count": pending_count,
            "candidate_pending_review_count": candidate_count,
            "blocked_proxy_count": blocked_count,
            "editor_replacement_ready_count": copied_count,
        },
        "export_boundary": {
            "licensed_media_proxy": PROXY_BOUNDARY,
            "asset_download": "not_performed",
            "external_asset_search": "not_performed",
            "license_purchase": "not_performed",
            "editing_software": "not_opened",
            "upload": "not_performed",
            "publishing": "not_performed",
        },
        "validation": {
            "status": "PASSED" if len(proxy_assets) == len(licensed_media) and bool(proxy_assets) else "NEEDS_REVIEW",
            "all_licensed_media_slots_covered": len(proxy_assets) == len(licensed_media),
            "proxy_copy_complete_for_ready_media": copied_count == ready_source_count,
            "ready_source_media_count": ready_source_count,
            "proxy_copied_count": copied_count,
            "pending_human_media_count": pending_count,
            "editor_replacement_ready_count": copied_count,
        },
        "generation_status": "generated_local_proxy_replacement_suggestions_pending_editor_review",
        "manual_review_required": True,
        "review_required": True,
    }

    replacement_suggestions = {
        "schema_version": "phase4.licensed_media_replacement_suggestions.v1",
        "artifact_type": "licensed_media_replacement_suggestions",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "manifest_path": manifest_path,
        "replacement_suggestions_path": replacement_suggestions_path,
        "suggestions": suggestions,
        "summary": manifest["summary"],
        "export_boundary": manifest["export_boundary"],
        "validation": manifest["validation"],
        "manual_review_required": True,
        "review_required": True,
    }

    return GeneratedLicensedMediaProxy(
        manifest=manifest,
        replacement_suggestions=replacement_suggestions,
        readme_text=_render_readme(topic=topic, platform_label=platform_label, manifest=manifest),
        proxy_files=proxy_files,
    )


def _replacement_suggestion(
    *,
    run_dir: Path,
    platform: str,
    media: dict[str, Any],
    proxy_dir: str,
    manifest_path: str,
    replacement_suggestions_path: str,
    readme_path: str,
) -> tuple[dict[str, Any], dict[str, Any], bytes | None]:
    asset_id = str(media["asset_id"])
    source_path = _optional_string(media.get("licensed_media_path"))
    source_file = _resolve_local_path(run_dir, source_path)
    source_exists = bool(source_file and source_file.exists() and source_file.is_file())
    source_bytes = source_file.read_bytes() if source_exists and source_file else None
    source_sha256 = hashlib.sha256(source_bytes).hexdigest() if source_bytes is not None else None
    ready = media.get("ready_for_editor_replacement") is True and media.get("intake_status") == READY_INTAKE_STATUS
    can_copy = ready and source_exists and source_bytes is not None
    proxy_path = _proxy_path(proxy_dir, asset_id, source_path) if can_copy else None
    proxy_sha256 = hashlib.sha256(source_bytes).hexdigest() if source_bytes is not None and proxy_path else None

    if can_copy:
        replacement_status = "proxy_ready_for_editor_replacement"
        copy_status = "copied"
        instruction = "Replace the B-roll placeholder with the local proxy media path after final editor review."
    elif ready and not source_exists:
        replacement_status = "blocked_registered_media_missing"
        copy_status = "source_missing"
        instruction = "Fix the registered licensed_media_path before generating a proxy copy."
    elif media.get("intake_status") == "candidate_registered_pending_review":
        replacement_status = "candidate_registered_pending_review"
        copy_status = "not_copied_pending_review"
        instruction = "Complete human editorial and rights review before proxy copy."
    else:
        replacement_status = "pending_human_media"
        copy_status = "not_copied_pending_human_media"
        instruction = "Provide and approve local licensed or self-created media in human_media_registry.json."

    proxy_asset = {
        "asset_id": asset_id,
        "platform": platform,
        "asset_type": "licensed_broll_proxy",
        "source_reference_asset_type": media.get("source_reference_asset_type"),
        "reference_path": media.get("reference_path"),
        "planned_target_path": media.get("planned_target_path"),
        "licensed_media_path": source_path,
        "license_proof_path": media.get("license_proof_path"),
        "proxy_media_path": proxy_path,
        "source_media_exists": source_exists,
        "source_media_bytes": len(source_bytes) if source_bytes is not None else 0,
        "source_media_sha256": source_sha256,
        "proxy_media_bytes": len(source_bytes) if proxy_path and source_bytes is not None else 0,
        "proxy_media_sha256": proxy_sha256,
        "source_ready_for_proxy": ready,
        "proxy_copy_status": copy_status,
        "replacement_status": replacement_status,
        "editor_replacement_ready": can_copy,
        "licensed_media_intake_status": media.get("intake_status"),
        "licensed_media_review_status": media.get("review_status"),
        "rights_confirmation": media.get("rights_confirmation"),
        "manifest_path": manifest_path,
        "replacement_suggestions_path": replacement_suggestions_path,
        "readme_path": readme_path,
        "manual_review_required": True,
    }
    suggestion = {
        "asset_id": asset_id,
        "shot_replacement_target": media.get("planned_target_path"),
        "reference_path": media.get("reference_path"),
        "licensed_media_path": source_path,
        "proxy_media_path": proxy_path,
        "replacement_status": replacement_status,
        "proxy_copy_status": copy_status,
        "editor_replacement_ready": can_copy,
        "instruction": instruction,
        "manual_review_required": True,
    }
    return suggestion, proxy_asset, source_bytes if proxy_path else None


def _proxy_path(proxy_dir: str, asset_id: str, source_path: str | None) -> str:
    suffix = Path(source_path or "").suffix or ".media"
    return f"{proxy_dir}/{asset_id}_proxy{suffix}"


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


def _render_readme(*, topic: str, platform_label: str, manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    return "\n".join(
        [
            "# Licensed Media Proxy",
            "",
            f"- Topic: {topic}",
            f"- Platform: {platform_label}",
            f"- Required final media: {summary['required_final_media_count']}",
            f"- Ready source media: {summary['ready_source_media_count']}",
            f"- Proxy copied: {summary['proxy_copied_count']}",
            f"- Pending human media: {summary['pending_human_media_count']}",
            "",
            "## Boundary",
            "",
            "This step only copies local human-registered media that has passed review and rights confirmation.",
            "It does not search, download, purchase licenses, upload, publish, or open editing software.",
            "Proxy media is an editor handoff copy, not an automated final export.",
            "",
            "## Editor Handoff",
            "",
            f"- Replacement suggestions: `{manifest['replacement_suggestions_path']}`",
            f"- Proxy directory: `{manifest['proxy_dir']}`",
            "Review every suggestion before replacing B-roll placeholders in the editing project.",
            "",
        ]
    )


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result
