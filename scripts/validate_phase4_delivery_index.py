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


def fail(message: str) -> None:
    print(f"Phase 4 delivery index validation failed: {message}", file=sys.stderr)
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


def validate_workflow_delivery_step() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    step = steps.get("delivery_index")
    expect(step is not None, "workflow missing delivery_index step")
    expect(step.agent == "delivery-index-agent", "delivery_index must use delivery-index-agent")
    for platform in VIDEO_PLATFORMS:
        expect(f"{platform}_project_bundle" in step.depends_on, f"delivery_index must depend on {platform}_project_bundle")
    expect("final/delivery_index.json" in step.outputs, "delivery_index missing JSON output")
    expect("final/delivery_readme.md" in step.outputs, "delivery_index missing README output")
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect("delivery_index" in fact_check.depends_on, "fact_check must depend on delivery_index")
    expect("final/delivery_index.json" in workflow.outputs, "workflow must export delivery index")
    expect("final/delivery_readme.md" in workflow.outputs, "workflow must export delivery README")


def validate_delivery_index_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 交付索引验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )
        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect("final/delivery_index.json" in workflow_run.get("artifacts", []), "workflow artifacts missing delivery index")
        expect("final/delivery_readme.md" in workflow_run.get("artifacts", []), "workflow artifacts missing delivery README")
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        expect(modes_by_step.get("delivery_index") == "agent-local", "delivery_index must run through run_agent")
        delivery_metadata = logs_by_step.get("delivery_index", {}).get("agent_result", {}).get("metadata", {})
        expect(delivery_metadata.get("agent_interface") == "run_agent(task_spec)", "delivery_index missing run_agent proof")
        expect(delivery_metadata.get("delivery_status") == "PASSED", "delivery_index metadata must pass")

        delivery_index = load_json(run_dir / "final/delivery_index.json")
        delivery_readme = (run_dir / "final/delivery_readme.md").read_text(encoding="utf-8")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        expect(delivery_index.get("schema_version") == "phase4.delivery_index.v1", "delivery index schema mismatch")
        expect(delivery_index.get("artifact_type") == "delivery_index", "delivery index type mismatch")
        expect(delivery_index.get("validation", {}).get("status") == "PASSED", "delivery index validation must pass")
        expect(delivery_index.get("archive_summary", {}).get("bundle_count") == 3, "delivery index must include three bundles")
        expect(delivery_index.get("archive_summary", {}).get("all_required_files_present") is True, "delivery index must confirm required files")
        expect(
            delivery_index.get("export_boundary", {}).get("external_storage_sync") == "not_performed",
            "delivery index must not sync external storage",
        )
        expect(delivery_index.get("export_boundary", {}).get("upload") == "not_performed", "delivery index must not upload")
        expect(content_package.get("delivery_index") == "final/delivery_index.json", "content package missing delivery index path")
        expect(content_package.get("delivery_readme") == "final/delivery_readme.md", "content package missing delivery README path")
        expect("| Platform | Bundle | Bytes | SHA-256 | Status |" in delivery_readme, "delivery README missing bundle table")

        download_items = {
            item.get("platform"): item
            for item in delivery_index.get("download_items", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            item = download_items.get(platform)
            expect(isinstance(item, dict), f"delivery index missing download item: {platform}")
            bundle_path = run_dir / str(item.get("path"))
            expect(bundle_path.exists(), f"{platform} delivery bundle path missing")
            expect(item.get("bytes") == bundle_path.stat().st_size, f"{platform} delivery byte size mismatch")
            expect(item.get("sha256") == _sha256(bundle_path), f"{platform} delivery checksum mismatch")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    validate_workflow_delivery_step()
    print("Phase 4 delivery index drill passed: workflow delivery step")
    validate_delivery_index_run()
    print("Phase 4 delivery index drill passed: delivery index, checksums, and content package embedding")
    print("Phase 4 delivery index validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
