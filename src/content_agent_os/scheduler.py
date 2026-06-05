from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .job_queue import DurableJobStore, job_db_path
from .runner import DEFAULT_PLATFORMS, DEFAULT_OUTPUT_ROOT


DEFAULT_TOPIC = "AI内容创作自动化系统"
DEFAULT_INTERVAL_SECONDS = 86400


def run_scheduler_tick(
    *,
    workflow_path: Path,
    topic: str,
    platforms: list[str],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    dry_run: bool = True,
) -> dict[str, Any]:
    generated_at = _utc_now_iso()
    tick_id = f"scheduler_tick_{_utc_now_compact()}_{uuid.uuid4().hex[:8]}"
    scheduler_root = output_root / "_scheduler"
    scheduler_root.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "schema_version": "phase5.scheduler_tick.v1",
        "tick_id": tick_id,
        "generated_at": generated_at,
        "workflow_path": str(workflow_path),
        "workflow_exists": workflow_path.exists(),
        "topic": topic,
        "platforms": platforms,
        "output_root": str(output_root),
        "interval_seconds": interval_seconds,
        "dry_run": dry_run,
        "will_dispatch": False,
        "will_enqueue": False,
        "status": "DRY_RUN" if dry_run else "PENDING",
        "job_id": None,
        "run_dir": None,
    }

    if not workflow_path.exists():
        result["status"] = "BLOCKED"
        result["reason"] = f"workflow not found: {workflow_path}"
    elif dry_run:
        result["reason"] = "dry-run mode; no workflow job was enqueued"
    else:
        result["will_enqueue"] = True
        store = DurableJobStore(job_db_path(output_root))
        job = store.create_run_job(
            workflow_path=workflow_path,
            topic=topic,
            platforms=platforms,
        )
        result["status"] = "ENQUEUED"
        result["job_id"] = job["job_id"]

    tick_path = scheduler_root / f"{tick_id}.json"
    result["tick_path"] = str(tick_path)
    _write_json(tick_path, result)
    return result


def run_scheduler_loop(
    *,
    workflow_path: Path,
    topic: str,
    platforms: list[str],
    output_root: Path,
    interval_seconds: int,
    dry_run: bool,
    once: bool,
) -> None:
    if interval_seconds < 1:
        raise ValueError("--interval-seconds must be >= 1")

    while True:
        result = run_scheduler_tick(
            workflow_path=workflow_path,
            topic=topic,
            platforms=platforms,
            output_root=output_root,
            interval_seconds=interval_seconds,
            dry_run=dry_run,
        )
        print(
            "Scheduler tick "
            f"{result['tick_id']}: {result['status']} "
            f"(dry_run={result['dry_run']}, tick_path={result['tick_path']})"
        )
        if once:
            return
        time.sleep(interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Content Agent OS local scheduler.")
    parser.add_argument("--workflow", default=os.environ.get("CONTENT_AGENT_WORKFLOW", "workflows/one_topic_multi_platform.yaml"))
    parser.add_argument("--topic", default=os.environ.get("CONTENT_AGENT_SCHEDULE_TOPIC") or os.environ.get("CONTENT_AGENT_TOPIC") or DEFAULT_TOPIC)
    parser.add_argument("--platforms", default=os.environ.get("CONTENT_AGENT_PLATFORMS", ",".join(DEFAULT_PLATFORMS)))
    parser.add_argument("--output-root", default=os.environ.get("CONTENT_AGENT_OUTPUT_ROOT", str(DEFAULT_OUTPUT_ROOT)))
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.environ.get("CONTENT_AGENT_SCHEDULE_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))),
    )
    parser.add_argument("--once", action="store_true", default=_truthy(os.environ.get("CONTENT_AGENT_SCHEDULER_ONCE", "0")))
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=_truthy(os.environ.get("CONTENT_AGENT_SCHEDULER_DRY_RUN", "1")))
    parser.add_argument("--execute", dest="dry_run", action="store_false")
    args = parser.parse_args()

    platforms = [item.strip() for item in args.platforms.split(",") if item.strip()]
    run_scheduler_loop(
        workflow_path=Path(args.workflow),
        topic=args.topic,
        platforms=platforms or DEFAULT_PLATFORMS,
        output_root=Path(args.output_root),
        interval_seconds=args.interval_seconds,
        dry_run=args.dry_run,
        once=args.once,
    )
    return 0


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
