from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedExternalMirrorPlan:
    plan: dict[str, Any]
    sync_command_preview_md: str
    approval_request_md: str
    readme_text: str


def generate_external_mirror_plan(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    artifact_store_manifest: dict[str, Any],
    plan_path: str,
    sync_command_preview_path: str,
    approval_request_path: str,
    readme_path: str,
) -> GeneratedExternalMirrorPlan:
    mirror_items = [
        _mirror_item(run_dir, run_id, item)
        for item in artifact_store_manifest.get("downloads", [])
        if isinstance(item, dict)
    ]
    expected_count = int(
        artifact_store_manifest.get("store_summary", {}).get("expected_download_count")
        or len(mirror_items)
    )
    ready_source_count = len(
        [item for item in mirror_items if item["source_exists"] and item["checksum_verified"]]
    )
    validation_status = "PASSED" if ready_source_count == expected_count and expected_count > 0 else "NEEDS_REVIEW"
    source_artifacts = _dedupe(
        [
            artifact_store_manifest.get("manifest_path"),
            artifact_store_manifest.get("readme_path"),
            artifact_store_manifest.get("download_index_path"),
            artifact_store_manifest.get("checksums_path"),
            *[item["source_path"] for item in mirror_items],
            plan_path,
            sync_command_preview_path,
            approval_request_path,
            readme_path,
        ]
    )
    plan = {
        "schema_version": "phase4.external_mirror_plan.v1",
        "artifact_type": "external_mirror_plan",
        "run_id": run_id,
        "topic": topic,
        "plan_path": plan_path,
        "sync_command_preview_path": sync_command_preview_path,
        "approval_request_path": approval_request_path,
        "readme_path": readme_path,
        "source_artifact_store_manifest_path": artifact_store_manifest.get("manifest_path")
        or "artifact_store/artifact_store_manifest.json",
        "target_options": _target_options(run_id),
        "mirror_items": mirror_items,
        "mirror_summary": {
            "mirror_item_count": len(mirror_items),
            "expected_mirror_item_count": expected_count,
            "ready_source_count": ready_source_count,
            "approved_mirror_count": 0,
            "blocked_mirror_count": len(mirror_items),
        },
        "source_artifacts": source_artifacts,
        "export_boundary": {
            "external_mirror_plan_generation": "performed_locally_plan_only",
            "external_storage_sync": "not_performed",
            "upload": "not_performed",
            "publishing": "not_performed",
            "login": "not_performed",
            "platform_action": "not_performed",
            "network_access": "not_performed",
            "requires_human_distribution_approval": True,
        },
        "validation": {
            "status": validation_status,
            "mirror_item_count": len(mirror_items),
            "expected_mirror_item_count": expected_count,
            "ready_source_count": ready_source_count,
            "approved_mirror_count": 0,
            "external_storage_sync_performed": False,
            "upload_performed": False,
            "publishing_performed": False,
            "login_performed": False,
            "platform_action_performed": False,
            "network_access_performed": False,
            "human_distribution_approval_required": True,
            "human_distribution_approval_present": False,
        },
        "generation_status": "generated_local_external_mirror_plan_pending_human_distribution_approval",
        "manual_review_required": True,
        "human_distribution_approval_required": True,
        "review_required": True,
    }
    return GeneratedExternalMirrorPlan(
        plan=plan,
        sync_command_preview_md=_render_sync_command_preview(run_id=run_id, plan=plan),
        approval_request_md=_render_approval_request(run_id=run_id, topic=topic, plan=plan),
        readme_text=_render_readme(run_id=run_id, topic=topic, plan=plan),
    )


def _mirror_item(run_dir: Path, run_id: str, artifact_item: dict[str, Any]) -> dict[str, Any]:
    platform = str(artifact_item.get("platform") or "")
    source_path = str(artifact_item.get("store_path") or "")
    source_file = run_dir / source_path
    source_exists = source_file.exists()
    checksum = _sha256(source_file) if source_exists else None
    expected_checksum = artifact_item.get("sha256")
    checksum_verified = source_exists and checksum == expected_checksum
    file_name = Path(source_path).name or f"{platform}_project_bundle.zip"
    remote_key = f"content-agent-os/{run_id}/{file_name}"
    return {
        "platform": platform,
        "platform_label": artifact_item.get("platform_label") or platform,
        "source_path": source_path,
        "bytes": artifact_item.get("bytes") or 0,
        "sha256": checksum,
        "expected_sha256": expected_checksum,
        "source_exists": source_exists,
        "checksum_verified": checksum_verified,
        "proposed_remote_key": remote_key,
        "mirror_status": "blocked_pending_human_distribution_approval",
        "target_status": "target_not_selected",
        "sync_command_preview_id": f"mirror_{platform}_project_bundle",
        "external_storage_sync_performed": False,
        "upload_performed": False,
        "publishing_performed": False,
        "login_performed": False,
        "platform_action_performed": False,
        "review_required": True,
    }


def _target_options(run_id: str) -> list[dict[str, Any]]:
    return [
        {
            "target_id": "object_storage",
            "target_label": "Object storage bucket",
            "example_uri": f"s3://example-bucket/content-agent-os/{run_id}/",
            "enabled_by_default": False,
            "requires_human_credentials": True,
            "execution_status": "not_performed",
        },
        {
            "target_id": "shared_drive",
            "target_label": "Shared drive or team folder",
            "example_uri": f"drive://content-agent-os/{run_id}/",
            "enabled_by_default": False,
            "requires_human_credentials": True,
            "execution_status": "not_performed",
        },
        {
            "target_id": "media_asset_library",
            "target_label": "External media asset library",
            "example_uri": f"media-library://content-agent-os/{run_id}/",
            "enabled_by_default": False,
            "requires_human_credentials": True,
            "execution_status": "not_performed",
        },
    ]


def _render_sync_command_preview(*, run_id: str, plan: dict[str, Any]) -> str:
    lines = [
        "# External Mirror Sync Command Preview",
        "",
        f"- Run ID: {run_id}",
        "- Status: preview only",
        "- Execution: not performed",
        "- Login: not performed",
        "- Upload: not performed",
        "- Publishing: not performed",
        "",
        "The commands below are comments for human review. They were not executed.",
        "",
    ]
    for item in plan["mirror_items"]:
        remote_key = item["proposed_remote_key"]
        source_path = item["source_path"]
        lines.extend(
            [
                f"## {item['platform_label']}",
                "",
                f"- Source: `{source_path}`",
                f"- Proposed remote key: `{remote_key}`",
                "",
                "```bash",
                f"# Preview only: rclone copy \"{source_path}\" \"remote:{remote_key}\"",
                f"# Preview only: aws s3 cp \"{source_path}\" \"s3://example-bucket/{remote_key}\"",
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _render_approval_request(*, run_id: str, topic: str, plan: dict[str, Any]) -> str:
    lines = [
        "# Human Distribution Approval Request",
        "",
        f"- Run ID: {run_id}",
        f"- Topic: {topic}",
        f"- Mirror items: {plan['mirror_summary']['mirror_item_count']}",
        f"- Ready sources: {plan['mirror_summary']['ready_source_count']}",
        "- External sync performed: no",
        "- Upload performed: no",
        "- Publishing performed: no",
        "",
        "Human approval is required before any external storage mirror, file upload, or platform distribution action.",
        "",
        "## Review Items",
        "",
    ]
    for item in plan["mirror_items"]:
        lines.extend(
            [
                f"### {item['platform_label']}",
                "",
                f"- Source: `{item['source_path']}`",
                f"- SHA-256: `{item.get('sha256') or 'missing'}`",
                f"- Proposed remote key: `{item['proposed_remote_key']}`",
                f"- Status: {item['mirror_status']}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_readme(*, run_id: str, topic: str, plan: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# External Mirror Plan",
            "",
            f"- Run ID: {run_id}",
            f"- Topic: {topic}",
            f"- Validation: {plan['validation']['status']}",
            f"- Mirror items: {plan['mirror_summary']['mirror_item_count']}",
            "",
            "This folder contains a plan for mirroring local artifact store downloads to an external destination.",
            "It is a planning artifact only. It does not log in, sync external storage, upload files, publish content, or call platform APIs.",
            "",
            "Review `human_distribution_approval_request.md` before any human performs distribution outside this workspace.",
            "",
        ]
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dedupe(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
