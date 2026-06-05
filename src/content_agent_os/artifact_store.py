from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedArtifactStore:
    manifest: dict[str, Any]
    readme_text: str
    download_index_text: str
    checksums_text: str
    delivery_index_copy: dict[str, Any]
    download_files: dict[str, bytes]


def generate_artifact_store(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    delivery_index: dict[str, Any],
    manifest_path: str,
    readme_path: str,
    download_index_path: str,
    checksums_path: str,
    delivery_index_copy_path: str,
) -> GeneratedArtifactStore:
    download_files: dict[str, bytes] = {}
    downloads: list[dict[str, Any]] = []
    for item in delivery_index.get("download_items", []):
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform") or "")
        source_path = str(item.get("path") or "")
        if not platform or not source_path:
            continue
        source_file = run_dir / source_path
        store_path = f"artifact_store/downloads/{platform}_project_bundle.zip"
        source_exists = source_file.exists()
        file_bytes = source_file.read_bytes() if source_exists else b""
        checksum = _sha256_bytes(file_bytes) if source_exists else None
        source_checksum = item.get("sha256")
        checksum_matches = source_exists and checksum == source_checksum
        if source_exists:
            download_files[store_path] = file_bytes
        downloads.append(
            {
                "platform": platform,
                "platform_label": item.get("platform_label") or platform,
                "source_path": source_path,
                "store_path": store_path,
                "bytes": len(file_bytes) if source_exists else 0,
                "sha256": checksum,
                "source_sha256": source_checksum,
                "source_exists": source_exists,
                "checksum_matches_delivery_index": checksum_matches,
                "review_required": True,
            }
        )

    expected_download_count = int(
        delivery_index.get("archive_summary", {}).get("expected_bundle_count")
        or len(delivery_index.get("platforms", []))
        or len(downloads)
    )
    source_present_count = len([item for item in downloads if item["source_exists"]])
    checksum_match_count = len([item for item in downloads if item["checksum_matches_delivery_index"]])
    total_bytes = sum(int(item["bytes"]) for item in downloads)
    all_sources_present = source_present_count == expected_download_count and expected_download_count > 0
    all_checksums_match = checksum_match_count == expected_download_count and expected_download_count > 0
    validation_status = "PASSED" if all_sources_present and all_checksums_match else "NEEDS_REVIEW"
    source_artifacts = _dedupe(
        [
            "final/delivery_index.json",
            delivery_index.get("readme_path"),
            *[item["source_path"] for item in downloads],
            manifest_path,
            readme_path,
            download_index_path,
            checksums_path,
            delivery_index_copy_path,
        ]
    )
    manifest = {
        "schema_version": "phase4.artifact_store_manifest.v1",
        "artifact_type": "artifact_store",
        "run_id": run_id,
        "topic": topic,
        "store_root": "artifact_store",
        "manifest_path": manifest_path,
        "readme_path": readme_path,
        "download_index_path": download_index_path,
        "checksums_path": checksums_path,
        "delivery_index_copy_path": delivery_index_copy_path,
        "source_delivery_index_path": "final/delivery_index.json",
        "downloads": downloads,
        "store_summary": {
            "download_count": source_present_count,
            "expected_download_count": expected_download_count,
            "checksum_match_count": checksum_match_count,
            "total_download_bytes": total_bytes,
            "all_sources_present": all_sources_present,
            "all_checksums_match": all_checksums_match,
        },
        "source_artifacts": source_artifacts,
        "export_boundary": {
            "artifact_store_generation": "performed_locally_file_copy",
            "local_download_directory": "generated",
            "external_storage_sync": "not_performed",
            "upload": "not_performed",
            "publishing": "not_performed",
            "login": "not_performed",
            "platform_action": "not_performed",
        },
        "validation": {
            "status": validation_status,
            "download_count": source_present_count,
            "expected_download_count": expected_download_count,
            "checksum_match_count": checksum_match_count,
            "all_sources_present": all_sources_present,
            "all_checksums_match": all_checksums_match,
        },
        "generation_status": "generated_local_artifact_store_pending_human_distribution",
        "manual_review_required": True,
        "review_required": True,
    }
    return GeneratedArtifactStore(
        manifest=manifest,
        readme_text=_render_readme(topic=topic, run_id=run_id, manifest=manifest),
        download_index_text=_render_download_index(topic=topic, run_id=run_id, manifest=manifest),
        checksums_text=_render_checksums(downloads),
        delivery_index_copy=delivery_index,
        download_files=download_files,
    )


def _render_readme(*, topic: str, run_id: str, manifest: dict[str, Any]) -> str:
    summary = manifest["store_summary"]
    lines = [
        "# Artifact Store",
        "",
        f"- Run ID: {run_id}",
        f"- Topic: {topic}",
        f"- Validation: {manifest['validation']['status']}",
        f"- Downloads: {summary['download_count']}/{summary['expected_download_count']}",
        f"- Total bytes: {summary['total_download_bytes']}",
        "",
        "## Local Downloads",
        "",
        "| Platform | File | Bytes | SHA-256 |",
        "| --- | --- | ---: | --- |",
    ]
    for item in manifest["downloads"]:
        sha256 = item.get("sha256") or "missing"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item["platform_label"]),
                    f"`{item['store_path']}`",
                    str(item["bytes"]),
                    f"`{sha256}`",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This store is a local filesystem handoff only.",
            "- No external storage sync, login, upload, publishing, or platform action was performed.",
            "- Human review is required before distributing any file outside the workspace.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_download_index(*, topic: str, run_id: str, manifest: dict[str, Any]) -> str:
    lines = [
        "# Download Index",
        "",
        f"- Run ID: {run_id}",
        f"- Topic: {topic}",
        f"- Source delivery index: {manifest['source_delivery_index_path']}",
        "",
    ]
    for item in manifest["downloads"]:
        lines.extend(
            [
                f"## {item['platform_label']}",
                "",
                f"- Local file: `{item['store_path']}`",
                f"- Source file: `{item['source_path']}`",
                f"- Bytes: {item['bytes']}",
                f"- SHA-256: `{item.get('sha256') or 'missing'}`",
                f"- Checksum matches delivery index: {item['checksum_matches_delivery_index']}",
                "",
            ]
        )
    lines.extend(
        [
            "No upload, external sync, login, publishing, or platform action was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_checksums(downloads: list[dict[str, Any]]) -> str:
    lines = []
    for item in downloads:
        sha256 = item.get("sha256")
        if not isinstance(sha256, str) or not sha256:
            continue
        relative_path = str(item["store_path"]).removeprefix("artifact_store/")
        lines.append(f"{sha256}  {relative_path}")
    return "\n".join(lines) + ("\n" if lines else "")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _dedupe(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
