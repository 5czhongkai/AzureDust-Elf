from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.agents import AgentExecutionContext, run_agent  # noqa: E402
from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]
PROXY_BOUNDARY = "performed_locally_from_human_registered_media_only"
EXPECTED_PENDING_STATUSES = {
    "reference_generated_pending_licensed_media",
    "pending_human_licensed_media",
    "licensed_media_candidate_pending_review",
    "licensed_media_ready_for_editor_replacement",
}


def fail(message: str) -> None:
    print(f"Phase 4 licensed media proxy validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(path: Path) -> Any:
    if not path.exists():
        fail(f"missing JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON file {path}: {exc}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_agent_outputs(run_dir: Path, outputs: dict[str, Any]) -> None:
    for relative_path, content in outputs.items():
        destination = run_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            destination.write_bytes(content)
        elif isinstance(content, (dict, list)):
            write_json(destination, content)
        else:
            destination.write_text(str(content), encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_workflow_proxy_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect("final/licensed_media_proxy_manifest.json" in workflow.outputs, "workflow must export licensed media proxy manifest")

    for platform in VIDEO_PLATFORMS:
        ingest_step_id = f"{platform}_licensed_media_ingest"
        proxy_step_id = f"{platform}_licensed_media_proxy"
        edit_step_id = f"{platform}_edit_project"
        proxy_step = steps.get(proxy_step_id)
        edit_step = steps.get(edit_step_id)

        expect(proxy_step is not None, f"workflow missing step: {proxy_step_id}")
        expect(proxy_step.agent == "licensed-media-proxy-agent", f"{proxy_step_id} must use licensed-media-proxy-agent")
        expect(proxy_step.platform == platform, f"{proxy_step_id} platform mismatch")
        expect(ingest_step_id in proxy_step.depends_on, f"{proxy_step_id} must depend on {ingest_step_id}")
        for output_path in [
            f"assets/{platform}/licensed_media/proxy_manifest.json",
            f"assets/{platform}/licensed_media/replacement_suggestions.json",
            f"assets/{platform}/licensed_media/proxy/README.md",
        ]:
            expect(output_path in proxy_step.outputs, f"{proxy_step_id} missing output: {output_path}")
        expect(edit_step is not None, f"workflow missing edit step for {platform}")
        expect(proxy_step_id in edit_step.depends_on, f"{edit_step_id} must depend on licensed media proxy")
        expect(proxy_step_id in fact_check.depends_on, f"fact_check must depend on {proxy_step_id}")


def validate_default_no_registry_run() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 授权素材代理拷贝验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/licensed_media_proxy_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing licensed media proxy manifest",
        )
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}

        video_package = load_json(run_dir / "final/video_production_package.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        final_proxy_manifest = load_json(run_dir / "final/licensed_media_proxy_manifest.json")
        expect(
            video_package.get("licensed_media_proxy_manifest") == "final/licensed_media_proxy_manifest.json",
            "video package must reference licensed media proxy manifest",
        )
        expect(
            content_package.get("licensed_media_proxy_manifest") == "final/licensed_media_proxy_manifest.json",
            "content package must reference licensed media proxy manifest",
        )
        expect(video_package.get("export_boundary", {}).get("licensed_media_proxy") == PROXY_BOUNDARY, "video package proxy boundary mismatch")
        expect(final_proxy_manifest.get("schema_version") == "phase4.licensed_media_proxy_bundle_manifest.v1", "final proxy schema mismatch")
        expect(final_proxy_manifest.get("artifact_type") == "licensed_media_proxy_bundle", "final proxy type mismatch")
        expect(final_proxy_manifest.get("validation", {}).get("status") == "PASSED", "final proxy validation must pass")
        expect(final_proxy_manifest.get("validation", {}).get("ready_source_media_count") == 0, "default final proxy should have no ready source")
        expect(final_proxy_manifest.get("validation", {}).get("proxy_copied_count") == 0, "default final proxy should not copy media")
        expect(final_proxy_manifest.get("validation", {}).get("pending_human_media_count", 0) >= 1, "default final proxy should keep pending human media")
        expect(final_proxy_manifest.get("validation", {}).get("proxy_copy_complete_for_ready_media") is True, "final proxy copy completeness must pass")
        _validate_proxy_boundary(final_proxy_manifest.get("export_boundary", {}), "final proxy")

        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        final_entries = {
            item.get("platform"): item
            for item in final_proxy_manifest.get("platform_proxies", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            validate_default_platform_proxy(
                run_dir=run_dir,
                platform=platform,
                modes_by_step=modes_by_step,
                package=packages.get(platform),
                final_entry=final_entries.get(platform),
            )


def validate_default_platform_proxy(
    *,
    run_dir: Path,
    platform: str,
    modes_by_step: dict[str, str | None],
    package: dict[str, Any] | None,
    final_entry: dict[str, Any] | None,
) -> None:
    step_id = f"{platform}_licensed_media_proxy"
    expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")

    proxy_manifest_path = run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json"
    suggestions_path = run_dir / "assets" / platform / "licensed_media" / "replacement_suggestions.json"
    readme_path = run_dir / "assets" / platform / "licensed_media" / "proxy" / "README.md"
    proxy_manifest = load_json(proxy_manifest_path)
    suggestions = load_json(suggestions_path)
    expect(readme_path.exists(), f"{platform} proxy README missing")
    expect(proxy_manifest.get("schema_version") == "phase4.licensed_media_proxy_manifest.v1", f"{platform} proxy schema mismatch")
    expect(proxy_manifest.get("artifact_type") == "licensed_media_proxy", f"{platform} proxy artifact type mismatch")
    expect(proxy_manifest.get("adapter") == "local-licensed-media-proxy-adapter", f"{platform} proxy adapter mismatch")
    expect(suggestions.get("schema_version") == "phase4.licensed_media_replacement_suggestions.v1", f"{platform} suggestions schema mismatch")
    expect(suggestions.get("artifact_type") == "licensed_media_replacement_suggestions", f"{platform} suggestions type mismatch")
    expect(proxy_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} proxy validation must pass")
    expect(proxy_manifest.get("validation", {}).get("all_licensed_media_slots_covered") is True, f"{platform} proxy must cover ingest slots")
    expect(proxy_manifest.get("validation", {}).get("proxy_copy_complete_for_ready_media") is True, f"{platform} proxy copy completeness must pass")
    _validate_proxy_boundary(proxy_manifest.get("export_boundary", {}), platform)

    summary = proxy_manifest.get("summary", {})
    required_count = int(summary.get("required_final_media_count") or 0)
    expect(required_count >= 1, f"{platform} proxy must require final media")
    expect(summary.get("ready_source_media_count") == 0, f"{platform} default run should have no ready media")
    expect(summary.get("proxy_copied_count") == 0, f"{platform} default run should not copy proxy media")
    expect(summary.get("pending_human_media_count") == required_count, f"{platform} default run pending count mismatch")

    proxy_assets = proxy_manifest.get("proxy_assets", [])
    suggestion_items = suggestions.get("suggestions", [])
    expect(len(proxy_assets) == required_count, f"{platform} proxy asset count mismatch")
    expect(len(suggestion_items) == required_count, f"{platform} suggestion count mismatch")
    reference_paths = set()
    for asset in proxy_assets:
        expect(asset.get("asset_type") == "licensed_broll_proxy", f"{platform} proxy asset type mismatch")
        expect(asset.get("replacement_status") == "pending_human_media", f"{platform} default proxy should await human media")
        expect(asset.get("proxy_copy_status") == "not_copied_pending_human_media", f"{platform} default proxy copy status mismatch")
        expect(asset.get("editor_replacement_ready") is False, f"{platform} default proxy must not be editor ready")
        expect(asset.get("proxy_media_path") is None, f"{platform} default proxy must not invent proxy media")
        reference_paths.add(asset.get("reference_path"))
    for suggestion in suggestion_items:
        expect(suggestion.get("replacement_status") == "pending_human_media", f"{platform} default suggestion should await human media")
        expect(suggestion.get("proxy_media_path") is None, f"{platform} default suggestion must not invent proxy media")

    readme = readme_path.read_text(encoding="utf-8")
    expect("local human-registered media" in readme, f"{platform} proxy README missing local registry boundary")
    expect("does not search, download, purchase licenses, upload, publish, or open editing software" in readme, f"{platform} proxy README missing safety boundary")

    edit_timeline = load_json(run_dir / "assets" / platform / "edit" / "edit_timeline.json")
    placeholders = [
        clip.get("broll_placeholder")
        for clip in edit_timeline.get("tracks", {}).get("video", [])
        if isinstance(clip, dict) and isinstance(clip.get("broll_placeholder"), dict)
    ]
    expect(len(placeholders) >= required_count, f"{platform} edit timeline must preserve proxy placeholders")
    for placeholder in placeholders[:required_count]:
        expect(placeholder.get("reference_path") in reference_paths, f"{platform} edit placeholder reference mismatch")
        expect(placeholder.get("licensed_media_proxy_manifest_path") == f"assets/{platform}/licensed_media/proxy_manifest.json", f"{platform} edit placeholder missing proxy manifest")
        expect(placeholder.get("licensed_media_replacement_suggestions_path") == f"assets/{platform}/licensed_media/replacement_suggestions.json", f"{platform} edit placeholder missing suggestions")
        expect(placeholder.get("licensed_media_proxy_readme_path") == f"assets/{platform}/licensed_media/proxy/README.md", f"{platform} edit placeholder missing proxy README")
        expect(placeholder.get("replacement_status") == "pending_human_media", f"{platform} edit placeholder replacement status mismatch")
        expect(placeholder.get("proxy_media_path") is None, f"{platform} default edit placeholder must not include proxy media")

    offline_report = load_json(run_dir / "assets" / platform / "edit" / "offline_media_report.json")
    slots = offline_report.get("offline_broll_slots", [])
    expect(len(slots) >= required_count, f"{platform} offline report must preserve proxy slots")
    for slot in slots[:required_count]:
        expect(slot.get("reference_path") in reference_paths, f"{platform} offline slot reference mismatch")
        expect(slot.get("status") in EXPECTED_PENDING_STATUSES, f"{platform} default offline slot status mismatch")
        expect(slot.get("licensed_media_proxy_manifest_path") == f"assets/{platform}/licensed_media/proxy_manifest.json", f"{platform} offline slot missing proxy manifest")
        expect(slot.get("licensed_media_replacement_suggestions_path") == f"assets/{platform}/licensed_media/replacement_suggestions.json", f"{platform} offline slot missing suggestions")
        expect(slot.get("licensed_media_proxy_readme_path") == f"assets/{platform}/licensed_media/proxy/README.md", f"{platform} offline slot missing proxy README")
        expect(slot.get("proxy_media_path") is None, f"{platform} default offline slot must not include proxy media")

    with_zip_paths(run_dir / "assets" / platform / "bundle" / "project_bundle.zip", platform, [
        "licensed_media/proxy_manifest.json",
        "licensed_media/replacement_suggestions.json",
        "licensed_media/proxy/README.md",
    ])

    expect(isinstance(package, dict), f"video package missing platform: {platform}")
    deliverables = package.get("deliverables", {})
    expect(deliverables.get("licensed_media_proxy_manifest") == f"assets/{platform}/licensed_media/proxy_manifest.json", f"{platform} package proxy manifest path mismatch")
    expect(deliverables.get("licensed_media_replacement_suggestions") == f"assets/{platform}/licensed_media/replacement_suggestions.json", f"{platform} package suggestions path mismatch")
    expect(deliverables.get("licensed_media_proxy_readme") == f"assets/{platform}/licensed_media/proxy/README.md", f"{platform} package proxy README path mismatch")
    package_summary = package.get("licensed_media_proxy", {})
    expect(package_summary.get("validation_status") == "PASSED", f"{platform} package proxy summary must pass")
    expect(package_summary.get("ready_source_media_count") == 0, f"{platform} package should have no ready source")
    expect(package_summary.get("proxy_copied_count") == 0, f"{platform} package should not copy proxy media")
    expect(package_summary.get("pending_human_media_count") == required_count, f"{platform} package pending count mismatch")
    expect(package_summary.get("proxy_copy_complete_for_ready_media") is True, f"{platform} package proxy copy completeness mismatch")

    expect(isinstance(final_entry, dict), f"final proxy manifest missing platform: {platform}")
    expect(final_entry.get("manifest_path") == f"assets/{platform}/licensed_media/proxy_manifest.json", f"{platform} final proxy manifest path mismatch")
    expect(final_entry.get("replacement_suggestions_path") == f"assets/{platform}/licensed_media/replacement_suggestions.json", f"{platform} final suggestions path mismatch")
    expect(final_entry.get("readme_path") == f"assets/{platform}/licensed_media/proxy/README.md", f"{platform} final proxy README path mismatch")
    expect(final_entry.get("validation", {}).get("status") == "PASSED", f"{platform} final proxy validation must pass")


def validate_human_registry_proxy_copy() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 人工授权素材代理拷贝验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        platform = "douyin"
        material_manifest = load_json(run_dir / "assets" / platform / "materials" / "material_manifest.json")
        material_assets = material_manifest.get("materialized_assets", [])
        expect(isinstance(material_assets, list) and material_assets, "douyin material manifest must contain assets")
        asset_id = str(material_assets[0]["asset_id"])
        source_media_path = f"assets/{platform}/licensed_media/human_supplied/{asset_id}_final.txt"
        source_media = run_dir / source_media_path
        source_media.parent.mkdir(parents=True, exist_ok=True)
        source_media.write_text(f"self-created fixture for {asset_id}\n", encoding="utf-8")
        registry_path = run_dir / "assets" / platform / "licensed_media" / "human_media_registry.json"
        write_json(
            registry_path,
            {
                "media": [
                    {
                        "asset_id": asset_id,
                        "licensed_media_path": source_media_path,
                        "license_source": "self_created_local_test_fixture",
                        "rights_owner": "human",
                        "usage_scope": "test_only",
                        "reviewer": "human",
                        "review_status": "approved_for_edit",
                        "rights_confirmation": "self_created_confirmed",
                    }
                ]
            },
        )

        ctx = AgentExecutionContext(
            run_dir=run_dir,
            topic="Phase 4 人工授权素材代理拷贝验收",
            platforms=VIDEO_PLATFORMS,
            produced_artifacts=[],
        )
        for agent_id in [
            "licensed-media-ingest-agent",
            "licensed-media-proxy-agent",
            "edit-project-agent",
            "export-project-agent",
            "project-bundle-agent",
        ]:
            result = run_agent({"agent": agent_id, "metadata": {"platform": platform}}, ctx)
            write_agent_outputs(run_dir, result.outputs)

        ingest_manifest = load_json(run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json")
        proxy_manifest = load_json(run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json")
        suggestions = load_json(run_dir / "assets" / platform / "licensed_media" / "replacement_suggestions.json")
        edit_timeline = load_json(run_dir / "assets" / platform / "edit" / "edit_timeline.json")
        offline_report = load_json(run_dir / "assets" / platform / "edit" / "offline_media_report.json")

        expect(ingest_manifest.get("human_media_registry_exists") is True, "ingest should detect human_media_registry.json")
        expect(ingest_manifest.get("summary", {}).get("ready_for_editor_replacement_count") == 1, "ingest should mark one media item ready")
        ready_item = _find_by_asset_id(ingest_manifest.get("licensed_media", []), asset_id)
        expect(ready_item.get("intake_status") == "approved_candidate_ready_for_editor_replacement", "ingest ready intake status mismatch")
        expect(ready_item.get("ready_for_editor_replacement") is True, "ingest ready item should be editor-ready")
        expect(ready_item.get("media_sha256") == sha256(source_media), "ingest source checksum mismatch")

        expect(proxy_manifest.get("summary", {}).get("ready_source_media_count") == 1, "proxy should see one ready source")
        expect(proxy_manifest.get("summary", {}).get("proxy_copied_count") == 1, "proxy should copy one ready source")
        expect(proxy_manifest.get("validation", {}).get("proxy_copy_complete_for_ready_media") is True, "proxy copy completeness should pass")
        proxy_asset = _find_by_asset_id(proxy_manifest.get("proxy_assets", []), asset_id)
        proxy_path = proxy_asset.get("proxy_media_path")
        expect(proxy_asset.get("replacement_status") == "proxy_ready_for_editor_replacement", "proxy replacement status mismatch")
        expect(proxy_asset.get("proxy_copy_status") == "copied", "proxy copy status mismatch")
        expect(proxy_asset.get("editor_replacement_ready") is True, "proxy asset should be editor-ready")
        expect(isinstance(proxy_path, str) and proxy_path.endswith("_proxy.txt"), "proxy media path should preserve source suffix")
        proxy_file = run_dir / str(proxy_path)
        expect(proxy_file.exists(), "proxy media file missing")
        expect(sha256(proxy_file) == sha256(source_media), "proxy media checksum should match source media")
        expect(proxy_asset.get("proxy_media_sha256") == sha256(proxy_file), "proxy manifest checksum mismatch")

        suggestion = _find_by_asset_id(suggestions.get("suggestions", []), asset_id)
        expect(suggestion.get("replacement_status") == "proxy_ready_for_editor_replacement", "replacement suggestion status mismatch")
        expect(suggestion.get("proxy_media_path") == proxy_path, "replacement suggestion proxy path mismatch")
        expect(suggestion.get("editor_replacement_ready") is True, "replacement suggestion should be editor-ready")

        placeholder = _find_placeholder_by_asset_id(edit_timeline, asset_id)
        expect(placeholder.get("proxy_media_path") == proxy_path, "edit placeholder proxy path mismatch")
        expect(placeholder.get("editor_replacement_ready") is True, "edit placeholder should be editor-ready")
        expect(placeholder.get("replacement_status") == "proxy_ready_for_editor_replacement", "edit placeholder replacement status mismatch")

        slot = _find_slot_by_asset_id(offline_report, asset_id)
        expect(slot.get("status") == "proxy_ready_for_editor_replacement", "offline slot should be proxy-ready")
        expect(slot.get("proxy_media_path") == proxy_path, "offline slot proxy path mismatch")
        expect(slot.get("editor_replacement_ready") is True, "offline slot should be editor-ready")

        with_zip_paths(
            run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
            platform,
            [
                "licensed_media/proxy_manifest.json",
                "licensed_media/replacement_suggestions.json",
                "licensed_media/proxy/README.md",
                f"licensed_media/proxy/{Path(str(proxy_path)).name}",
            ],
        )


def _validate_proxy_boundary(boundary: dict[str, Any], label: str) -> None:
    expect(boundary.get("licensed_media_proxy") == PROXY_BOUNDARY, f"{label} proxy boundary mismatch")
    expect(boundary.get("editing_software") == "not_opened", f"{label} proxy must not open editing software")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        expect(boundary.get(key) == "not_performed", f"{label} proxy must mark {key} as not_performed")


def with_zip_paths(bundle_path: Path, platform: str, required_paths: list[str]) -> None:
    try:
        with ZipFile(bundle_path) as archive:
            archive_paths = set(archive.namelist())
    except BadZipFile as exc:
        fail(f"{platform} project bundle ZIP is invalid: {exc}")
    for archive_path in required_paths:
        expect(archive_path in archive_paths, f"{platform} bundle missing proxy file: {archive_path}")


def _find_by_asset_id(items: Any, asset_id: str) -> dict[str, Any]:
    if not isinstance(items, list):
        fail(f"expected list while finding asset: {asset_id}")
    for item in items:
        if isinstance(item, dict) and str(item.get("asset_id")) == asset_id:
            return item
    fail(f"missing asset_id in collection: {asset_id}")
    raise AssertionError("unreachable")


def _find_placeholder_by_asset_id(edit_timeline: dict[str, Any], asset_id: str) -> dict[str, Any]:
    for clip in edit_timeline.get("tracks", {}).get("video", []):
        if not isinstance(clip, dict):
            continue
        placeholder = clip.get("broll_placeholder")
        if isinstance(placeholder, dict) and str(placeholder.get("asset_id")) == asset_id:
            return placeholder
    fail(f"missing edit placeholder for asset_id: {asset_id}")
    raise AssertionError("unreachable")


def _find_slot_by_asset_id(offline_report: dict[str, Any], asset_id: str) -> dict[str, Any]:
    for slot in offline_report.get("offline_broll_slots", []):
        if not isinstance(slot, dict):
            continue
        placeholder = slot.get("placeholder")
        placeholder_asset_id = placeholder.get("asset_id") if isinstance(placeholder, dict) else None
        if str(slot.get("asset_id") or placeholder_asset_id) == asset_id:
            return slot
    fail(f"missing offline B-roll slot for asset_id: {asset_id}")
    raise AssertionError("unreachable")


def main() -> int:
    validate_workflow_proxy_steps()
    print("Phase 4 licensed media proxy drill passed: workflow proxy steps")
    validate_default_no_registry_run()
    print("Phase 4 licensed media proxy drill passed: default pending handoff without human registry")
    validate_human_registry_proxy_copy()
    print("Phase 4 licensed media proxy drill passed: human registry to proxy copy and replacement suggestions")
    print("Phase 4 licensed media proxy validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
