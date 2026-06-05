from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


@dataclass(frozen=True)
class GeneratedProjectBundle:
    bundle_bytes: bytes
    manifest: dict[str, Any]
    file_manifest: dict[str, Any]
    readme_text: str


def generate_project_bundle(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    export_manifest: dict[str, Any],
    offline_report: dict[str, Any],
    editor_replacement_manifest: dict[str, Any] | None = None,
    editor_replacement_execution_manifest: dict[str, Any] | None = None,
    editor_project_mutation_manifest: dict[str, Any] | None = None,
    editor_software_import_manifest: dict[str, Any] | None = None,
    editor_software_real_runner_manifest: dict[str, Any] | None = None,
    editor_software_run_evidence_manifest: dict[str, Any] | None = None,
    bundle_path: str,
    manifest_path: str,
    file_manifest_path: str,
    readme_path: str,
) -> GeneratedProjectBundle:
    entries = _bundle_entries(
        run_dir,
        platform,
        export_manifest,
        editor_replacement_manifest,
        editor_replacement_execution_manifest,
        editor_project_mutation_manifest,
        editor_software_import_manifest,
        editor_software_real_runner_manifest,
        editor_software_run_evidence_manifest,
    )
    required_missing = [entry for entry in entries if entry["required"] and not entry["exists"]]
    readme_text = _render_bundle_readme(
        topic=topic,
        platform_label=platform_label,
        bundle_path=bundle_path,
        file_count=len([entry for entry in entries if entry["exists"]]),
        offline_broll_count=int(offline_report.get("offline_broll_count") or 0),
    )
    bundle_bytes = _render_zip(run_dir, readme_text, entries)
    file_manifest = {
        "schema_version": "phase4.project_bundle_file_manifest.v1",
        "artifact_type": "project_bundle_file_manifest",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "bundle_path": bundle_path,
        "files": entries,
        "summary": {
            "file_count": len([entry for entry in entries if entry["exists"]]),
            "required_missing_count": len(required_missing),
            "bundle_bytes": len(bundle_bytes),
        },
        "review_required": True,
    }
    manifest = {
        "schema_version": "phase4.project_bundle_manifest.v1",
        "artifact_type": "project_bundle",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-project-bundle-adapter",
        "adapter_version": "0.1.0",
        "bundle_format": "zip",
        "bundle_path": bundle_path,
        "manifest_path": manifest_path,
        "file_manifest_path": file_manifest_path,
        "readme_path": readme_path,
        "source_artifacts": [entry["source_path"] for entry in entries if entry["exists"]],
        "deliverables": {
            "bundle_zip": bundle_path,
            "bundle_manifest": manifest_path,
            "file_manifest": file_manifest_path,
            "bundle_readme": readme_path,
        },
        "bundle_summary": file_manifest["summary"],
        "validation": {
            "status": "PASSED" if not required_missing and len(bundle_bytes) > 0 else "NEEDS_REVIEW",
            "required_files_present": not required_missing,
            "required_missing_count": len(required_missing),
            "file_count": file_manifest["summary"]["file_count"],
            "bundle_bytes": len(bundle_bytes),
            "offline_broll_count": int(offline_report.get("offline_broll_count") or 0),
        },
        "generation_status": "generated_local_project_bundle_pending_human_review",
        "manual_review_required": True,
        "review_notes": [
            "Project bundle is a local ZIP handoff built from export project artifacts.",
            "Editor replacement instruction templates are included when generated, but replacement execution remains behind human confirmation.",
            "Editor replacement execution plans are included when generated, but no replacement execution was performed by the bundle step.",
            "Editor project mutation sandbox copies are included when generated; the original FCPXML project remains unchanged.",
            "Editor software import executor plans are included when generated; no editing software was opened by the bundle step.",
            "Editor software real-runner sandbox files are included when generated; no external process was spawned by the bundle step.",
            "Editor software run evidence files are included when generated; external real-run evidence is only ingested from human-provided files.",
            "B-roll remains offline until licensed media is imported.",
            "No editing software was opened and no upload, sync, or publishing action was performed.",
        ],
        "review_required": True,
    }
    return GeneratedProjectBundle(
        bundle_bytes=bundle_bytes,
        manifest=manifest,
        file_manifest=file_manifest,
        readme_text=readme_text,
    )


def _bundle_entries(
    run_dir: Path,
    platform: str,
    export_manifest: dict[str, Any],
    editor_replacement_manifest: dict[str, Any] | None = None,
    editor_replacement_execution_manifest: dict[str, Any] | None = None,
    editor_project_mutation_manifest: dict[str, Any] | None = None,
    editor_software_import_manifest: dict[str, Any] | None = None,
    editor_software_real_runner_manifest: dict[str, Any] | None = None,
    editor_software_run_evidence_manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    deliverables = export_manifest.get("deliverables")
    if not isinstance(deliverables, dict):
        deliverables = {}
    candidates = [
        ("project/project.fcpxml", export_manifest.get("project_path"), True),
        ("docs/import_readme.md", export_manifest.get("readme_path"), True),
        ("reports/offline_media_report.json", export_manifest.get("offline_report_path"), True),
        ("metadata/export_manifest.json", export_manifest.get("manifest_path"), True),
        ("metadata/edit_timeline.json", deliverables.get("edit_timeline"), True),
        ("metadata/draft_cut.edl", deliverables.get("draft_cut_edl"), True),
        ("subtitles/timed_subtitles.srt", deliverables.get("subtitle_sidecar"), True),
    ]
    if isinstance(editor_replacement_manifest, dict):
        candidates.extend(
            [
                (
                    "replacement_instructions/instruction_manifest.json",
                    editor_replacement_manifest.get("manifest_path"),
                    True,
                ),
                (
                    "replacement_instructions/replacement_commands.json",
                    editor_replacement_manifest.get("replacement_commands_path"),
                    True,
                ),
                (
                    "replacement_instructions/editor_import_template.fcpxml",
                    editor_replacement_manifest.get("editor_import_template_path"),
                    True,
                ),
                (
                    "replacement_instructions/human_confirmation_checklist.md",
                    editor_replacement_manifest.get("human_confirmation_checklist_path"),
                    True,
                ),
                (
                    "replacement_instructions/README.md",
                    editor_replacement_manifest.get("readme_path"),
                    True,
                ),
            ]
        )
    if isinstance(editor_replacement_execution_manifest, dict):
        candidates.extend(
            [
                (
                    "replacement_execution/execution_manifest.json",
                    editor_replacement_execution_manifest.get("manifest_path"),
                    True,
                ),
                (
                    "replacement_execution/execution_plan.json",
                    editor_replacement_execution_manifest.get("execution_plan_path"),
                    True,
                ),
                (
                    "replacement_execution/execution_audit_log.json",
                    editor_replacement_execution_manifest.get("audit_log_path"),
                    True,
                ),
                (
                    "replacement_execution/human_execution_approval_request.md",
                    editor_replacement_execution_manifest.get("approval_request_path"),
                    True,
                ),
                (
                    "replacement_execution/README.md",
                    editor_replacement_execution_manifest.get("readme_path"),
                    True,
                ),
            ]
        )
        approval_path = editor_replacement_execution_manifest.get("human_execution_approval_path")
        if (
            editor_replacement_execution_manifest.get("human_execution_approval_present") is True
            and isinstance(approval_path, str)
        ):
            candidates.append(("replacement_execution/human_execution_approval.json", approval_path, True))
    if isinstance(editor_project_mutation_manifest, dict):
        candidates.extend(
            [
                (
                    "mutation_sandbox/mutation_manifest.json",
                    editor_project_mutation_manifest.get("manifest_path"),
                    True,
                ),
                (
                    "mutation_sandbox/patched_project.fcpxml",
                    editor_project_mutation_manifest.get("patched_project_path"),
                    True,
                ),
                (
                    "mutation_sandbox/mutation_diff.json",
                    editor_project_mutation_manifest.get("mutation_diff_path"),
                    True,
                ),
                (
                    "mutation_sandbox/rollback_manifest.json",
                    editor_project_mutation_manifest.get("rollback_manifest_path"),
                    True,
                ),
                (
                    "mutation_sandbox/mutation_audit_log.json",
                    editor_project_mutation_manifest.get("audit_log_path"),
                    True,
                ),
                (
                    "mutation_sandbox/human_final_review_checklist.md",
                    editor_project_mutation_manifest.get("final_review_checklist_path"),
                    True,
                ),
                (
                    "mutation_sandbox/README.md",
                    editor_project_mutation_manifest.get("readme_path"),
                    True,
                ),
            ]
        )
        approval_path = editor_project_mutation_manifest.get("human_mutation_approval_path")
        if (
            editor_project_mutation_manifest.get("human_mutation_approval_present") is True
            and isinstance(approval_path, str)
        ):
            candidates.append(("mutation_sandbox/human_mutation_approval.json", approval_path, True))
    if isinstance(editor_software_import_manifest, dict):
        candidates.extend(
            [
                (
                    "software_import_executor/import_executor_manifest.json",
                    editor_software_import_manifest.get("manifest_path"),
                    True,
                ),
                (
                    "software_import_executor/import_plan.json",
                    editor_software_import_manifest.get("import_plan_path"),
                    True,
                ),
                (
                    "software_import_executor/import_commands.json",
                    editor_software_import_manifest.get("import_commands_path"),
                    True,
                ),
                (
                    "software_import_executor/software_import_audit_log.json",
                    editor_software_import_manifest.get("audit_log_path"),
                    True,
                ),
                (
                    "software_import_executor/rollback_safety_report.json",
                    editor_software_import_manifest.get("rollback_safety_report_path"),
                    True,
                ),
                (
                    "software_import_executor/isolated_execution_request.md",
                    editor_software_import_manifest.get("execution_request_path"),
                    True,
                ),
                (
                    "software_import_executor/README.md",
                    editor_software_import_manifest.get("readme_path"),
                    True,
                ),
            ]
        )
        approval_path = editor_software_import_manifest.get("human_software_import_approval_path")
        if (
            editor_software_import_manifest.get("human_software_import_approval_present") is True
            and isinstance(approval_path, str)
        ):
            candidates.append(("software_import_executor/human_software_import_approval.json", approval_path, True))
    if isinstance(editor_software_real_runner_manifest, dict):
        candidates.extend(
            [
                (
                    "software_real_runner_sandbox/runner_sandbox_manifest.json",
                    editor_software_real_runner_manifest.get("manifest_path"),
                    True,
                ),
                (
                    "software_real_runner_sandbox/runner_environment_snapshot.json",
                    editor_software_real_runner_manifest.get("environment_snapshot_path"),
                    True,
                ),
                (
                    "software_real_runner_sandbox/runner_launch_plan.json",
                    editor_software_real_runner_manifest.get("launch_plan_path"),
                    True,
                ),
                (
                    "software_real_runner_sandbox/runner_command_preview.json",
                    editor_software_real_runner_manifest.get("command_preview_path"),
                    True,
                ),
                (
                    "software_real_runner_sandbox/runner_audit_log.json",
                    editor_software_real_runner_manifest.get("audit_log_path"),
                    True,
                ),
                (
                    "software_real_runner_sandbox/runner_evidence_manifest.json",
                    editor_software_real_runner_manifest.get("evidence_manifest_path"),
                    True,
                ),
                (
                    "software_real_runner_sandbox/human_real_run_approval_request.md",
                    editor_software_real_runner_manifest.get("approval_request_path"),
                    True,
                ),
                (
                    "software_real_runner_sandbox/README.md",
                    editor_software_real_runner_manifest.get("readme_path"),
                    True,
                ),
            ]
        )
        approval_path = editor_software_real_runner_manifest.get("human_real_run_approval_path")
        if (
            editor_software_real_runner_manifest.get("human_real_run_approval_present") is True
            and isinstance(approval_path, str)
        ):
            candidates.append(("software_real_runner_sandbox/human_real_run_approval.json", approval_path, True))
    if isinstance(editor_software_run_evidence_manifest, dict):
        candidates.extend(
            [
                (
                    "software_run_evidence/real_run_evidence_manifest.json",
                    editor_software_run_evidence_manifest.get("manifest_path"),
                    True,
                ),
                (
                    "software_run_evidence/evidence_validation_report.json",
                    editor_software_run_evidence_manifest.get("validation_report_path"),
                    True,
                ),
                (
                    "software_run_evidence/rollback_decision_report.json",
                    editor_software_run_evidence_manifest.get("rollback_decision_report_path"),
                    True,
                ),
                (
                    "software_run_evidence/post_launch_evidence_checklist.md",
                    editor_software_run_evidence_manifest.get("checklist_path"),
                    True,
                ),
                (
                    "software_run_evidence/README.md",
                    editor_software_run_evidence_manifest.get("readme_path"),
                    True,
                ),
            ]
        )
        result_path = editor_software_run_evidence_manifest.get("human_real_run_result_path")
        if (
            editor_software_run_evidence_manifest.get("human_real_run_result_present") is True
            and isinstance(result_path, str)
        ):
            candidates.append(("software_run_evidence/human_real_run_result.json", result_path, True))
    for source in export_manifest.get("source_artifacts", []):
        if not isinstance(source, str) or not source:
            continue
        if source.endswith("voiceover.wav"):
            candidates.append(("audio/voiceover.wav", source, True))
        elif "/licensed_media/" in source and source.endswith("proxy_manifest.json"):
            candidates.append(("licensed_media/proxy_manifest.json", source, True))
        elif "/licensed_media/" in source and source.endswith("replacement_suggestions.json"):
            candidates.append(("licensed_media/replacement_suggestions.json", source, True))
        elif "/licensed_media/proxy/" in source and source.endswith("README.md"):
            candidates.append(("licensed_media/proxy/README.md", source, True))
        elif "/licensed_media/proxy/" in source:
            candidates.append((f"licensed_media/proxy/{Path(source).name}", source, True))
        elif "/licensed_media/" in source and source.endswith("ingest_manifest.json"):
            candidates.append(("licensed_media/ingest_manifest.json", source, True))
        elif "/licensed_media/" in source and source.endswith("review_handoff.md"):
            candidates.append(("licensed_media/review_handoff.md", source, True))
        elif "/licensed_media/" in source and source.endswith("README.md"):
            candidates.append(("licensed_media/README.md", source, True))
        elif "/licensed_media/" in source and source.endswith("human_media_registry.json"):
            candidates.append(("licensed_media/human_media_registry.json", source, True))
        elif "/licensed_media/" in source:
            candidates.append((f"licensed_media/{Path(source).name}", source, True))
        elif "/materials/" in source and source.endswith(".png"):
            candidates.append((f"materials/{Path(source).name}", source, True))
        elif source.endswith(".png"):
            candidates.append((f"storyboard/{Path(source).name}", source, True))
        elif source.endswith("edit_manifest.json"):
            candidates.append(("metadata/edit_manifest.json", source, True))
    if isinstance(editor_replacement_manifest, dict):
        for source in editor_replacement_manifest.get("source_artifacts", []):
            if not isinstance(source, str) or not source:
                continue
            if "/edit/replacement_instructions/" in source:
                candidates.append((f"replacement_instructions/{Path(source).name}", source, True))
    if isinstance(editor_replacement_execution_manifest, dict):
        for source in editor_replacement_execution_manifest.get("source_artifacts", []):
            if not isinstance(source, str) or not source:
                continue
            if "/edit/replacement_execution/" in source:
                candidates.append((f"replacement_execution/{Path(source).name}", source, True))
    if isinstance(editor_project_mutation_manifest, dict):
        for source in editor_project_mutation_manifest.get("source_artifacts", []):
            if not isinstance(source, str) or not source:
                continue
            if "/edit/mutation_sandbox/" in source:
                candidates.append((f"mutation_sandbox/{Path(source).name}", source, True))
    if isinstance(editor_software_import_manifest, dict):
        for source in editor_software_import_manifest.get("source_artifacts", []):
            if not isinstance(source, str) or not source:
                continue
            if "/edit/software_import_executor/" in source:
                candidates.append((f"software_import_executor/{Path(source).name}", source, True))
    if isinstance(editor_software_real_runner_manifest, dict):
        for source in editor_software_real_runner_manifest.get("source_artifacts", []):
            if not isinstance(source, str) or not source:
                continue
            if "/edit/software_real_runner_sandbox/" in source:
                candidates.append((f"software_real_runner_sandbox/{Path(source).name}", source, True))
    if isinstance(editor_software_run_evidence_manifest, dict):
        for source in editor_software_run_evidence_manifest.get("source_artifacts", []):
            if not isinstance(source, str) or not source:
                continue
            if "/edit/software_run_evidence/" in source:
                candidates.append((f"software_run_evidence/{Path(source).name}", source, True))
    candidates.append(("metadata/export_source.json", export_manifest.get("manifest_path"), True))

    entries: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_archive_paths: set[str] = set()
    for archive_path, source_path, required in candidates:
        if not isinstance(source_path, str) or not source_path:
            continue
        if source_path in seen_sources:
            continue
        seen_sources.add(source_path)
        archive_path = _unique_archive_path(archive_path, seen_archive_paths)
        seen_archive_paths.add(archive_path)
        source = run_dir / source_path
        exists = source.exists()
        entries.append(
            {
                "archive_path": archive_path,
                "source_path": source_path,
                "exists": exists,
                "required": required,
                "bytes": source.stat().st_size if exists else 0,
            }
        )
    return entries


def _render_zip(run_dir: Path, readme_text: str, entries: list[dict[str, Any]]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        _write_zip_text(archive, "README.md", readme_text)
        for entry in entries:
            if not entry["exists"]:
                continue
            source = run_dir / entry["source_path"]
            _write_zip_bytes(archive, entry["archive_path"], source.read_bytes())
    return buffer.getvalue()


def _render_bundle_readme(
    *,
    topic: str,
    platform_label: str,
    bundle_path: str,
    file_count: int,
    offline_broll_count: int,
) -> str:
    return "\n".join(
        [
            "# Project Bundle",
            "",
            f"- Topic: {topic}",
            f"- Platform: {platform_label}",
            f"- Bundle path: `{bundle_path}`",
            f"- Files in bundle: {file_count}",
            f"- Offline B-roll slots: {offline_broll_count}",
            "",
            "Open `project/project.fcpxml` as a draft editor handoff.",
            "Review `replacement_instructions/human_confirmation_checklist.md` before applying any replacement command or import template.",
            "Review `replacement_execution/human_execution_approval_request.md` before creating any explicit execution approval file.",
            "Review `mutation_sandbox/human_final_review_checklist.md` before using any patched sandbox project copy.",
            "Review `software_import_executor/isolated_execution_request.md` before launching any editor import manually.",
            "Review `software_real_runner_sandbox/human_real_run_approval_request.md` before starting any real editor process in an external sandbox.",
            "Review `software_run_evidence/post_launch_evidence_checklist.md` after any human external real run before closeout.",
            "Import `subtitles/timed_subtitles.srt` as the subtitle sidecar if your editor does not attach subtitles automatically.",
            "Review `reports/offline_media_report.json` before replacing B-roll placeholders with licensed media.",
            "No original project mutation, replacement execution, editing software, upload, sync, or publishing action was performed by this bundle step.",
            "",
        ]
    )


def _write_zip_text(archive: ZipFile, archive_path: str, text: str) -> None:
    _write_zip_bytes(archive, archive_path, text.encode("utf-8"))


def _write_zip_bytes(archive: ZipFile, archive_path: str, data: bytes) -> None:
    info = ZipInfo(archive_path)
    info.date_time = (2026, 1, 1, 0, 0, 0)
    info.compress_type = ZIP_DEFLATED
    archive.writestr(info, data)


def _unique_archive_path(path: str, seen: set[str]) -> str:
    if path not in seen:
        return path
    stem = Path(path).stem
    suffix = Path(path).suffix
    parent = Path(path).parent
    index = 2
    while True:
        candidate = str(parent / f"{stem}_{index}{suffix}")
        if candidate not in seen:
            return candidate
        index += 1
