from __future__ import annotations

import argparse
import os
import time
import uuid
from pathlib import Path

from .job_queue import DurableJobStore, execute_claimed_job, job_db_path
from .runner import DEFAULT_OUTPUT_ROOT


def run_worker_once(*, output_root: Path, worker_id: str) -> dict[str, object]:
    store = DurableJobStore(job_db_path(output_root))
    job = store.claim_next(worker_id=worker_id)
    if job is None:
        return {
            "schema_version": "phase5.worker_tick.v1",
            "worker_id": worker_id,
            "status": "IDLE",
            "job": None,
        }
    finished = execute_claimed_job(store, job, output_root=output_root)
    return {
        "schema_version": "phase5.worker_tick.v1",
        "worker_id": worker_id,
        "status": finished["status"],
        "job": finished,
    }


def run_worker_loop(*, output_root: Path, worker_id: str, once: bool, poll_interval_seconds: int) -> None:
    if poll_interval_seconds < 1:
        raise ValueError("--poll-interval-seconds must be >= 1")
    while True:
        result = run_worker_once(output_root=output_root, worker_id=worker_id)
        job = result.get("job")
        job_id = job.get("job_id") if isinstance(job, dict) else None
        print(f"Worker tick {worker_id}: {result['status']} job={job_id or 'none'}")
        if once:
            return
        time.sleep(poll_interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Content Agent OS local worker.")
    parser.add_argument("--output-root", default=os.environ.get("CONTENT_AGENT_OUTPUT_ROOT", str(DEFAULT_OUTPUT_ROOT)))
    parser.add_argument("--worker-id", default=os.environ.get("CONTENT_AGENT_WORKER_ID") or f"worker_{uuid.uuid4().hex[:8]}")
    parser.add_argument("--once", action="store_true", default=_truthy(os.environ.get("CONTENT_AGENT_WORKER_ONCE", "0")))
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=int(os.environ.get("CONTENT_AGENT_WORKER_POLL_INTERVAL_SECONDS", "5")),
    )
    args = parser.parse_args()
    run_worker_loop(
        output_root=Path(args.output_root),
        worker_id=args.worker_id,
        once=args.once,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    return 0


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
