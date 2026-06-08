from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .approval_gate import approve_repair_plan
from .runner import resume_workflow, run_workflow
from .supervision import generate_supervision_outputs


RUN_OUTPUTS = [
    ("Workflow state", "workflow_run.json"),
    ("Run supervision", "monitor/supervision_report.md"),
    ("Failure dashboard", "monitor/failure_dashboard.html"),
    ("Content package", "final/content_package_manifest.json"),
    ("Video production package", "final/video_production_package.json"),
    ("Materialization manifest", "final/materialization_manifest.json"),
    ("Licensed media ingest manifest", "final/licensed_media_ingest_manifest.json"),
    ("Licensed media proxy manifest", "final/licensed_media_proxy_manifest.json"),
    ("Editor replacement instruction manifest", "final/editor_replacement_instruction_manifest.json"),
    ("Editor replacement execution manifest", "final/editor_replacement_execution_manifest.json"),
    ("Editor project mutation manifest", "final/editor_project_mutation_manifest.json"),
    ("Editor software import manifest", "final/editor_software_import_manifest.json"),
    ("Editor software real runner manifest", "final/editor_software_real_runner_manifest.json"),
    ("Editor software run evidence manifest", "final/editor_software_run_evidence_manifest.json"),
    ("Edit project manifest", "final/edit_project_manifest.json"),
    ("Export project manifest", "final/export_project_manifest.json"),
    ("Project bundle manifest", "final/project_bundle_manifest.json"),
    ("Delivery index", "final/delivery_index.json"),
    ("Artifact store", "artifact_store/artifact_store_manifest.json"),
    ("External mirror plan", "artifact_store/external_mirror_plan.json"),
]


def _print_existing_run_outputs(run_dir: Path) -> None:
    for label, relative in RUN_OUTPUTS:
        path = run_dir / relative
        if path.exists():
            print(f"{label}: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Content Agent OS workflows.")
    parser.add_argument("--workflow", default="workflows/one_topic_multi_platform.yaml", help="Workflow definition path.")
    parser.add_argument("--topic", default=None, help="Topic to generate content for.")
    parser.add_argument("--run-id", default=None, help="Existing run id to resume or inspect.")
    parser.add_argument("--platforms", default="wechat,xiaohongshu,douyin,shipinhao,bilibili")
    parser.add_argument("--mode", choices=["demo", "run", "resume", "monitor", "approve-repair"], default="run")
    parser.add_argument("--repair-id", default=None, help="Repair plan id to approve or reject.")
    parser.add_argument("--approved-by", default="human", help="Human approver label.")
    parser.add_argument("--approval-note", default="", help="Approval note to persist with the repair plan.")
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()

    workflow_path = Path(args.workflow)
    if args.mode in {"demo", "run"} and not workflow_path.exists():
        raise SystemExit(f"Workflow not found: {workflow_path}")

    platforms = [item.strip() for item in args.platforms.split(",") if item.strip()]
    output_root = Path(args.output_root) if args.output_root else Path("outputs/runs")

    if args.mode == "monitor":
        run_dir, paths, snapshot = generate_supervision_outputs(run_id=args.run_id, output_root=output_root)
        summary = snapshot["summary"]
        detector_summary = snapshot.get("stale_detector", {}).get("summary", {})
        retry_summary = snapshot.get("retry_policy", {}).get("summary", {})
        repair_summary = snapshot.get("repair_log", {}).get("summary", {})
        print(f"Supervision refreshed: {run_dir}")
        print(f"Status: {snapshot['run'].get('status')} ({summary.get('completed_steps')}/{summary.get('total_steps')} steps)")
        print(
            f"Stale detector: stale={detector_summary.get('stale_count', 0)}, "
            f"interrupted={detector_summary.get('interrupted_count', 0)}, "
            f"watch={detector_summary.get('watch_count', 0)}"
        )
        print(
            f"Retry policy: auto_retries={retry_summary.get('auto_retry_count', 0)}, "
            f"events={retry_summary.get('event_count', 0)}"
        )
        print(
            f"Repair log: repairs={repair_summary.get('repair_count', 0)}, "
            f"manual_required={repair_summary.get('manual_required_count', 0)}, "
            f"pending_approval={repair_summary.get('pending_approval_count', 0)}, "
            f"approved={repair_summary.get('approved_repair_count', 0)}"
        )
        print(f"Report: {paths['report']}")
        print(f"Failure dashboard: {paths['dashboard']}")
        print(f"Snapshot: {paths['snapshot']}")
        return 0

    if args.mode == "run":
        if not args.topic:
            raise SystemExit("--topic is required for run mode")
        run_dir = run_workflow(workflow_path=workflow_path, topic=args.topic, platforms=platforms, output_root=output_root)
        print(f"Created workflow run: {run_dir}")
        _print_existing_run_outputs(run_dir)
        return 0

    if args.mode == "resume":
        if not args.run_id:
            raise SystemExit("--run-id is required for resume mode")
        run_dir = resume_workflow(run_id=args.run_id, output_root=output_root)
        print(f"Resumed workflow run: {run_dir}")
        _print_existing_run_outputs(run_dir)
        return 0

    if args.mode == "approve-repair":
        if not args.run_id:
            raise SystemExit("--run-id is required for approve-repair mode")
        run_dir, repair_entry = approve_repair_plan(
            run_id=args.run_id,
            output_root=output_root,
            repair_id=args.repair_id,
            approved_by=args.approved_by,
            approval_note=args.approval_note,
        )
        print(f"Approved repair plan: {repair_entry.get('repair_id')}")
        print(f"Workflow run: {run_dir}")
        print(f"Workflow state: {run_dir / 'workflow_run.json'}")
        print(f"Repair log: {run_dir / 'repair/repair_log.json'}")
        return 0

    if not args.topic:
        raise SystemExit("--topic is required for demo mode")
    now = datetime.now(timezone.utc)
    run_id = "demo_" + now.strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path("outputs/demo-runs") / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    request = {
        "run_id": run_id,
        "created_at": now.isoformat(),
        "workflow": str(workflow_path),
        "topic": args.topic,
        "platforms": platforms,
        "status": "PENDING",
        "note": "V0 demo request only; no model calls or publishing actions are performed.",
    }

    request_path = output_dir / "run_request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    plan_path = output_dir / "plan.md"
    plan_path.write_text(
        "\n".join(
            [
                f"# Demo Run {run_id}",
                "",
                f"- Topic: {args.topic}",
                f"- Workflow: {workflow_path}",
                f"- Platforms: {', '.join(platforms)}",
                "- Status: PENDING",
                "",
                "This file proves the V0 runner can create a durable run folder.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Created demo run: {output_dir}")
    print(f"Run request: {request_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
