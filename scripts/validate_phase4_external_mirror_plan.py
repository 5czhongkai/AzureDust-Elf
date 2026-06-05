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
MIRROR_OUTPUTS = [
    "artifact_store/external_mirror_plan.json",
    "artifact_store/sync_command_preview.md",
    "artifact_store/human_distribution_approval_request.md",
    "artifact_store/external_mirror_readme.md",
]


def fail(message: str) -> None:
    print(f"Phase 4 external mirror plan validation failed: {message}", file=sys.stderr)
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


def validate_workflow_external_mirror_step() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    store_step = steps.get("artifact_store")
    mirror_step = steps.get("external_mirror_plan")
    fact_check = steps.get("fact_check")
    expect(store_step is not None, "workflow missing artifact_store step")
    expect(mirror_step is not None, "workflow missing external_mirror_plan step")
    expect(mirror_step.agent == "external-mirror-plan-agent", "external_mirror_plan must use external-mirror-plan-agent")
    expect(mirror_step.depends_on == ["artifact_store"], "external_mirror_plan must depend only on artifact_store")
    for output_path in MIRROR_OUTPUTS:
        expect(output_path in mirror_step.outputs, f"external_mirror_plan missing output: {output_path}")
        expect(output_path in workflow.outputs, f"workflow must export external mirror output: {output_path}")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect("artifact_store" in fact_check.depends_on, "fact_check must still depend on artifact_store")
    expect("external_mirror_plan" in fact_check.depends_on, "fact_check must depend on external_mirror_plan")


def validate_external_mirror_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 external mirror plan 验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )
        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        for output_path in MIRROR_OUTPUTS:
            expect(output_path in workflow_run.get("artifacts", []), f"workflow artifacts missing {output_path}")
            expect((run_dir / output_path).exists(), f"external mirror output missing: {output_path}")

        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        expect(modes_by_step.get("external_mirror_plan") == "agent-local", "external_mirror_plan must run through run_agent")
        metadata = logs_by_step.get("external_mirror_plan", {}).get("agent_result", {}).get("metadata", {})
        expect(metadata.get("agent_interface") == "run_agent(task_spec)", "external_mirror_plan missing run_agent proof")
        expect(metadata.get("external_mirror_plan_status") == "PASSED", "external_mirror_plan metadata must pass")
        expect(metadata.get("external_storage_sync_performed") is False, "external mirror must not sync storage")
        expect(metadata.get("upload_performed") is False, "external mirror must not upload")
        expect(metadata.get("publishing_performed") is False, "external mirror must not publish")
        expect(metadata.get("login_performed") is False, "external mirror must not login")
        expect(metadata.get("platform_action_performed") is False, "external mirror must not perform platform action")
        expect(metadata.get("network_access_performed") is False, "external mirror must not access network")

        plan = load_json(run_dir / "artifact_store/external_mirror_plan.json")
        artifact_store = load_json(run_dir / "artifact_store/artifact_store_manifest.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        sync_preview = (run_dir / "artifact_store/sync_command_preview.md").read_text(encoding="utf-8")
        approval_request = (run_dir / "artifact_store/human_distribution_approval_request.md").read_text(encoding="utf-8")
        readme = (run_dir / "artifact_store/external_mirror_readme.md").read_text(encoding="utf-8")

        expect(plan.get("schema_version") == "phase4.external_mirror_plan.v1", "external mirror plan schema mismatch")
        expect(plan.get("artifact_type") == "external_mirror_plan", "external mirror plan type mismatch")
        expect(plan.get("validation", {}).get("status") == "PASSED", "external mirror plan validation must pass")
        expect(plan.get("mirror_summary", {}).get("mirror_item_count") == 3, "external mirror plan must include three items")
        expect(plan.get("mirror_summary", {}).get("ready_source_count") == 3, "external mirror sources must be ready")
        expect(plan.get("mirror_summary", {}).get("approved_mirror_count") == 0, "external mirror must have no approvals")
        boundary = plan.get("export_boundary", {})
        expect(
            boundary.get("external_mirror_plan_generation") == "performed_locally_plan_only",
            "external mirror plan boundary mismatch",
        )
        for key in ["external_storage_sync", "upload", "publishing", "login", "platform_action", "network_access"]:
            expect(boundary.get(key) == "not_performed", f"external mirror plan must mark {key} as not_performed")
        expect(boundary.get("requires_human_distribution_approval") is True, "external mirror must require human approval")
        validation = plan.get("validation", {})
        for key in [
            "external_storage_sync_performed",
            "upload_performed",
            "publishing_performed",
            "login_performed",
            "platform_action_performed",
            "network_access_performed",
        ]:
            expect(validation.get(key) is False, f"external mirror validation must report {key}=false")
        expect(validation.get("human_distribution_approval_required") is True, "human approval must be required")
        expect(validation.get("human_distribution_approval_present") is False, "human approval must not be present by default")

        artifact_items = {
            item.get("platform"): item
            for item in artifact_store.get("downloads", [])
            if isinstance(item, dict)
        }
        mirror_items = {
            item.get("platform"): item
            for item in plan.get("mirror_items", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            artifact_item = artifact_items.get(platform)
            mirror_item = mirror_items.get(platform)
            expect(isinstance(artifact_item, dict), f"artifact store missing item: {platform}")
            expect(isinstance(mirror_item, dict), f"external mirror missing item: {platform}")
            source_path = run_dir / str(mirror_item.get("source_path"))
            expect(source_path.exists(), f"{platform} mirror source missing")
            expect(mirror_item.get("sha256") == _sha256(source_path), f"{platform} mirror checksum mismatch")
            expect(mirror_item.get("expected_sha256") == artifact_item.get("sha256"), f"{platform} expected checksum mismatch")
            expect(mirror_item.get("checksum_verified") is True, f"{platform} checksum must verify")
            expect(mirror_item.get("mirror_status") == "blocked_pending_human_distribution_approval", f"{platform} mirror status mismatch")
            expect(mirror_item.get("target_status") == "target_not_selected", f"{platform} target status mismatch")
            for key in [
                "external_storage_sync_performed",
                "upload_performed",
                "publishing_performed",
                "login_performed",
                "platform_action_performed",
            ]:
                expect(mirror_item.get(key) is False, f"{platform} mirror item must report {key}=false")
            expect(str(mirror_item.get("source_path")) in sync_preview, f"{platform} sync preview missing source path")
            expect(str(mirror_item.get("proposed_remote_key")) in sync_preview, f"{platform} sync preview missing remote key")
            expect(str(mirror_item.get("source_path")) in approval_request, f"{platform} approval request missing source path")

        expect("# External Mirror Sync Command Preview" in sync_preview, "sync preview missing heading")
        expect("# Preview only:" in sync_preview, "sync preview must be comment-only preview")
        expect("# Human Distribution Approval Request" in approval_request, "approval request missing heading")
        expect("# External Mirror Plan" in readme, "external mirror README missing heading")
        expect("not log in, sync external storage, upload files, publish content" in readme, "external mirror README missing boundary")
        expect(
            content_package.get("external_mirror_plan") == "artifact_store/external_mirror_plan.json",
            "content package missing external mirror plan path",
        )
        expect(
            content_package.get("external_mirror_sync_command_preview") == "artifact_store/sync_command_preview.md",
            "content package missing sync command preview path",
        )
        expect(
            content_package.get("external_mirror_approval_request")
            == "artifact_store/human_distribution_approval_request.md",
            "content package missing approval request path",
        )
        expect(
            content_package.get("external_mirror_readme") == "artifact_store/external_mirror_readme.md",
            "content package missing external mirror README path",
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    validate_workflow_external_mirror_step()
    print("Phase 4 external mirror plan drill passed: workflow external_mirror_plan step")
    validate_external_mirror_run()
    print("Phase 4 external mirror plan drill passed: plan-only external distribution handoff")
    print("Phase 4 external mirror plan validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
