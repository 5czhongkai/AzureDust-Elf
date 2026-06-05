from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VIDEO_PLATFORMS = {"douyin", "shipinhao", "bilibili"}
PLATFORM_LABELS = {
    "douyin": "抖音",
    "shipinhao": "视频号",
    "bilibili": "B站",
}


@dataclass(frozen=True)
class GeneratedDeliveryIndex:
    index: dict[str, Any]
    readme_text: str


def generate_delivery_index(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platforms: list[str],
    index_path: str,
    readme_path: str,
) -> GeneratedDeliveryIndex:
    video_platforms = [platform for platform in platforms if platform in VIDEO_PLATFORMS]
    platform_deliveries = [
        _platform_delivery(run_dir, platform)
        for platform in video_platforms
    ]
    bundle_count = len([item for item in platform_deliveries if item["bundle_exists"]])
    passed_count = len([item for item in platform_deliveries if item["validation_status"] == "PASSED"])
    total_bundle_bytes = sum(int(item.get("bundle_bytes") or 0) for item in platform_deliveries)
    all_required_files_present = all(item.get("required_files_present") is True for item in platform_deliveries)
    validation_status = (
        "PASSED"
        if passed_count == len(video_platforms) and all_required_files_present
        else "NEEDS_REVIEW"
    )
    download_items = [
        {
            "platform": item["platform"],
            "platform_label": item["platform_label"],
            "path": item["bundle_path"],
            "bytes": item["bundle_bytes"],
            "sha256": item["sha256"],
            "review_required": True,
        }
        for item in platform_deliveries
        if item.get("bundle_exists")
    ]
    index = {
        "schema_version": "phase4.delivery_index.v1",
        "artifact_type": "delivery_index",
        "run_id": run_id,
        "topic": topic,
        "index_path": index_path,
        "readme_path": readme_path,
        "platforms": video_platforms,
        "download_items": download_items,
        "platform_deliveries": platform_deliveries,
        "archive_summary": {
            "bundle_count": bundle_count,
            "expected_bundle_count": len(video_platforms),
            "passed_bundle_count": passed_count,
            "total_bundle_bytes": total_bundle_bytes,
            "all_required_files_present": all_required_files_present,
        },
        "source_artifacts": [
            path
            for item in platform_deliveries
            for path in [
                item.get("bundle_path"),
                item.get("bundle_manifest_path"),
                item.get("file_manifest_path"),
                item.get("bundle_readme_path"),
            ]
            if isinstance(path, str)
        ],
        "export_boundary": {
            "delivery_index_generation": "performed_locally_no_upload",
            "external_storage_sync": "not_performed",
            "publishing": "not_performed",
            "upload": "not_performed",
        },
        "validation": {
            "status": validation_status,
            "bundle_count": bundle_count,
            "expected_bundle_count": len(video_platforms),
            "passed_bundle_count": passed_count,
            "all_required_files_present": all_required_files_present,
        },
        "generation_status": "generated_local_delivery_index_pending_human_review",
        "manual_review_required": True,
        "review_required": True,
    }
    return GeneratedDeliveryIndex(
        index=index,
        readme_text=_render_delivery_readme(topic=topic, run_id=run_id, index=index),
    )


def _platform_delivery(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest_path = run_dir / "assets" / platform / "bundle" / "project_bundle_manifest.json"
    manifest = _read_json_if_exists(manifest_path)
    if not isinstance(manifest, dict):
        manifest = {}
    bundle_path = str(manifest.get("bundle_path") or f"assets/{platform}/bundle/project_bundle.zip")
    file_manifest_path = str(manifest.get("file_manifest_path") or f"assets/{platform}/bundle/file_manifest.json")
    readme_path = str(manifest.get("readme_path") or f"assets/{platform}/bundle/README.md")
    bundle_file = run_dir / bundle_path
    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        validation = {}
    return {
        "platform": platform,
        "platform_label": PLATFORM_LABELS.get(platform, platform),
        "bundle_path": bundle_path,
        "bundle_manifest_path": str(manifest.get("manifest_path") or manifest_path.relative_to(run_dir)),
        "file_manifest_path": file_manifest_path,
        "bundle_readme_path": readme_path,
        "bundle_exists": bundle_file.exists(),
        "bundle_bytes": bundle_file.stat().st_size if bundle_file.exists() else 0,
        "sha256": _sha256(bundle_file) if bundle_file.exists() else None,
        "validation_status": validation.get("status"),
        "required_files_present": validation.get("required_files_present") is True,
        "offline_broll_count": validation.get("offline_broll_count", 0),
        "review_required": True,
    }


def _render_delivery_readme(*, topic: str, run_id: str, index: dict[str, Any]) -> str:
    lines = [
        "# Delivery Index",
        "",
        f"- Run ID: {run_id}",
        f"- Topic: {topic}",
        f"- Validation: {index['validation']['status']}",
        f"- Bundle count: {index['archive_summary']['bundle_count']}/{index['archive_summary']['expected_bundle_count']}",
        "",
        "## Project Bundles",
        "",
        "| Platform | Bundle | Bytes | SHA-256 | Status |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in index["platform_deliveries"]:
        sha256 = item.get("sha256") or "missing"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item["platform_label"]),
                    f"`{item['bundle_path']}`",
                    str(item["bundle_bytes"]),
                    f"`{sha256}`",
                    str(item.get("validation_status") or "MISSING"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This index is local only.",
            "- No external storage sync was performed.",
            "- No upload, publishing, login, or platform action was performed.",
            "- Human review is required before sharing any bundle outside the workspace.",
            "",
        ]
    )
    return "\n".join(lines)


def _read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
