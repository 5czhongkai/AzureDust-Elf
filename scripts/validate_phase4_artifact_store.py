from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]
STORE_OUTPUTS = [
    "artifact_store/artifact_store_manifest.json",
    "artifact_store/README.md",
    "artifact_store/download_index.md",
    "artifact_store/checksums.sha256",
    "artifact_store/manifests/delivery_index.json",
    "artifact_store/downloads/douyin_project_bundle.zip",
    "artifact_store/downloads/shipinhao_project_bundle.zip",
    "artifact_store/downloads/bilibili_project_bundle.zip",
]


def fail(message: str) -> None:
    print(f"Phase 4 artifact store validation failed: {message}", file=sys.stderr)
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


def validate_workflow_artifact_store_step() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    delivery_step = steps.get("delivery_index")
    store_step = steps.get("artifact_store")
    fact_check = steps.get("fact_check")
    expect(delivery_step is not None, "workflow missing delivery_index step")
    expect(store_step is not None, "workflow missing artifact_store step")
    expect(store_step.agent == "artifact-store-agent", "artifact_store must use artifact-store-agent")
    expect(store_step.depends_on == ["delivery_index"], "artifact_store must depend only on delivery_index")
    for output_path in STORE_OUTPUTS:
        expect(output_path in store_step.outputs, f"artifact_store missing output: {output_path}")
        expect(output_path in workflow.outputs, f"workflow must export artifact store output: {output_path}")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect("delivery_index" in fact_check.depends_on, "fact_check must still depend on delivery_index")
    expect("artifact_store" in fact_check.depends_on, "fact_check must depend on artifact_store")


def validate_artifact_store_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 artifact store 验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )
        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        for output_path in STORE_OUTPUTS:
            expect(output_path in workflow_run.get("artifacts", []), f"workflow artifacts missing {output_path}")
            expect((run_dir / output_path).exists(), f"artifact store output missing: {output_path}")

        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        expect(modes_by_step.get("artifact_store") == "agent-local", "artifact_store must run through run_agent")
        metadata = logs_by_step.get("artifact_store", {}).get("agent_result", {}).get("metadata", {})
        expect(metadata.get("agent_interface") == "run_agent(task_spec)", "artifact_store missing run_agent proof")
        expect(metadata.get("artifact_store_status") == "PASSED", "artifact_store metadata must pass")
        expect(metadata.get("external_storage_sync_performed") is False, "artifact_store must not sync external storage")
        expect(metadata.get("upload_performed") is False, "artifact_store must not upload")
        expect(metadata.get("publishing_performed") is False, "artifact_store must not publish")

        manifest = load_json(run_dir / "artifact_store/artifact_store_manifest.json")
        delivery_index = load_json(run_dir / "final/delivery_index.json")
        copied_delivery_index = load_json(run_dir / "artifact_store/manifests/delivery_index.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        readme = (run_dir / "artifact_store/README.md").read_text(encoding="utf-8")
        download_index = (run_dir / "artifact_store/download_index.md").read_text(encoding="utf-8")
        checksums = (run_dir / "artifact_store/checksums.sha256").read_text(encoding="utf-8")

        expect(manifest.get("schema_version") == "phase4.artifact_store_manifest.v1", "artifact store schema mismatch")
        expect(manifest.get("artifact_type") == "artifact_store", "artifact store type mismatch")
        expect(manifest.get("validation", {}).get("status") == "PASSED", "artifact store validation must pass")
        expect(manifest.get("store_summary", {}).get("download_count") == 3, "artifact store must contain three downloads")
        expect(manifest.get("store_summary", {}).get("all_sources_present") is True, "all sources must be present")
        expect(manifest.get("store_summary", {}).get("all_checksums_match") is True, "all checksums must match")
        boundary = manifest.get("export_boundary", {})
        expect(boundary.get("artifact_store_generation") == "performed_locally_file_copy", "artifact store boundary mismatch")
        expect(boundary.get("external_storage_sync") == "not_performed", "artifact store must not sync external storage")
        expect(boundary.get("upload") == "not_performed", "artifact store must not upload")
        expect(boundary.get("publishing") == "not_performed", "artifact store must not publish")
        expect(boundary.get("login") == "not_performed", "artifact store must not login")
        expect(boundary.get("platform_action") == "not_performed", "artifact store must not perform platform action")
        expect(copied_delivery_index == delivery_index, "artifact store delivery index copy must match source")
        expect("# Artifact Store" in readme, "artifact store README missing heading")
        expect("# Download Index" in download_index, "artifact store download index missing heading")

        delivery_items = {
            item.get("platform"): item
            for item in delivery_index.get("download_items", [])
            if isinstance(item, dict)
        }
        store_items = {
            item.get("platform"): item
            for item in manifest.get("downloads", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            delivery_item = delivery_items.get(platform)
            store_item = store_items.get(platform)
            expect(isinstance(delivery_item, dict), f"delivery index missing item: {platform}")
            expect(isinstance(store_item, dict), f"artifact store missing item: {platform}")
            source_path = run_dir / str(delivery_item.get("path"))
            store_path = run_dir / str(store_item.get("store_path"))
            expect(source_path.exists(), f"{platform} source bundle missing")
            expect(store_path.exists(), f"{platform} store bundle missing")
            expect(store_path.read_bytes() == source_path.read_bytes(), f"{platform} store bundle must copy source bytes")
            expect(store_item.get("bytes") == source_path.stat().st_size, f"{platform} byte size mismatch")
            expect(store_item.get("sha256") == _sha256(source_path), f"{platform} store checksum mismatch")
            expect(store_item.get("source_sha256") == delivery_item.get("sha256"), f"{platform} source checksum mismatch")
            expect(store_item.get("checksum_matches_delivery_index") is True, f"{platform} checksum must match delivery index")
            relative_store_path = str(store_item.get("store_path")).removeprefix("artifact_store/")
            expect(relative_store_path in checksums, f"{platform} checksums file missing store path")
            expect(str(store_item.get("sha256")) in checksums, f"{platform} checksums file missing checksum")

        expect(
            content_package.get("artifact_store_manifest") == "artifact_store/artifact_store_manifest.json",
            "content package missing artifact store manifest path",
        )
        expect(content_package.get("artifact_store_readme") == "artifact_store/README.md", "content package missing store README")
        expect(
            content_package.get("artifact_store_download_index") == "artifact_store/download_index.md",
            "content package missing download index",
        )
        expect(
            content_package.get("artifact_store_checksums") == "artifact_store/checksums.sha256",
            "content package missing checksums path",
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    validate_workflow_artifact_store_step()
    print("Phase 4 artifact store drill passed: workflow artifact_store step")
    validate_artifact_store_run()
    print("Phase 4 artifact store drill passed: local downloadable store and checksums")
    print("Phase 4 artifact store validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
