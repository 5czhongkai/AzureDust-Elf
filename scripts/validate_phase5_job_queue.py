from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.console_server import ConsoleConfig, ConsoleRuntime  # noqa: E402
from content_agent_os.api_key_store import PLATFORM_API_KEY_ENV_KEYS  # noqa: E402
from content_agent_os.job_queue import DurableJobStore, job_db_path  # noqa: E402
from content_agent_os.scheduler import run_scheduler_tick  # noqa: E402
from content_agent_os.worker import run_worker_once  # noqa: E402


API_KEY_SENTINEL = "phase5-worker-api-key-sentinel"


def fail(message: str) -> None:
    print(f"Phase 5 job queue validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_text(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def validate_static_contract() -> None:
    for path in [
        "src/content_agent_os/job_queue.py",
        "src/content_agent_os/worker.py",
        "src/content_agent_os/scheduler.py",
        "scripts/validate_phase5_job_queue.py",
    ]:
        expect((ROOT / path).exists(), f"missing required path: {path}")

    makefile = read_text("Makefile")
    for target in [
        "worker:",
        "worker-once:",
        "scheduler:",
        "scheduler-once:",
        "validate-phase5-job-queue:",
    ]:
        expect(target in makefile, f"Makefile missing target: {target}")

    compose = read_text("docker-compose.yml")
    expect("content_agent_os.worker" in compose, "worker profile must run durable worker")
    expect("CONTENT_AGENT_CONSOLE_INLINE_JOBS" in compose, "console compose env missing inline jobs flag")
    expect("CONTENT_AGENT_WORKER_POLL_INTERVAL_SECONDS" in compose, "worker compose env missing poll interval")

    env_example = read_text(".env.example")
    for phrase in [
        "CONTENT_AGENT_CONSOLE_INLINE_JOBS",
        "CONTENT_AGENT_WORKER_ONCE",
        "CONTENT_AGENT_WORKER_POLL_INTERVAL_SECONDS",
    ]:
        expect(phrase in env_example, f".env.example missing phrase: {phrase}")

    base_validator = read_text("scripts/validate_v0.py")
    for phrase in [
        "src/content_agent_os/job_queue.py",
        "src/content_agent_os/worker.py",
        "scripts/validate_phase5_job_queue.py",
        "validate-phase5-job-queue:",
    ]:
        expect(phrase in base_validator, f"base validator missing phrase: {phrase}")

    for doc_path in [
        "README.md",
        "docs/RUNBOOK.md",
        "docs/IMPLEMENTATION_ROADMAP.md",
    ]:
        doc = read_text(doc_path)
        expect("durable job queue" in doc, f"{doc_path} missing durable job queue note")
        expect("make validate-phase5-job-queue" in doc, f"{doc_path} missing job queue validation command")


def validate_console_enqueue_and_worker(tmp_root: Path) -> None:
    workflow_path = tmp_root / "queue_validation_workflow.yaml"
    output_root = tmp_root / "outputs/runs"
    backup_root = tmp_root / "backups"
    write_one_step_workflow(workflow_path)
    config = ConsoleConfig(
        workflow_path=workflow_path,
        output_root=output_root,
        backup_root=backup_root,
        default_platforms=["wechat"],
        execute_inline_jobs=False,
    )
    runtime = ConsoleRuntime(config)
    previous_wechat_key = os.environ.get("CONTENT_AGENT_WECHAT_API_KEY")
    runtime.save_api_keys({"keys": {"wechat": API_KEY_SENTINEL}})
    os.environ.pop("CONTENT_AGENT_WECHAT_API_KEY", None)
    attachments = [
        {
            "id": "attachment_validation",
            "name": "brief.txt",
            "mime_type": "text/plain",
            "kind": "text",
            "size_bytes": 12,
            "path": str(tmp_root / "brief.txt"),
        }
    ]
    job = runtime.start_run("Phase 5 durable queue validation", ["wechat"], attachments=attachments)
    expect(job.get("status") == "QUEUED", "console must enqueue run job")
    expect(job.get("attachments", [{}])[0].get("name") == "brief.txt", "console must enqueue attachments")
    expect(job_db_path(output_root).exists(), "console must create durable job database")

    restarted = ConsoleRuntime(config)
    jobs = restarted.list_jobs()["jobs"]
    expect(jobs and jobs[0]["job_id"] == job["job_id"], "job must survive console runtime restart")
    expect(jobs[0]["status"] == "QUEUED", "restarted console must see queued job")
    expect(jobs[0].get("attachments", [{}])[0].get("name") == "brief.txt", "attachments must survive console restart")

    result = run_worker_once(output_root=output_root, worker_id="validation-worker")
    expect(result.get("status") == "DONE", "worker must complete queued run job")
    expect(
        os.environ.get(PLATFORM_API_KEY_ENV_KEYS["wechat"]) == API_KEY_SENTINEL,
        "worker must load console-saved platform API key store before execution",
    )
    finished = restarted.get_job(str(job["job_id"]))
    expect(finished["status"] == "DONE", "durable job status must be DONE")
    run_dir = Path(str(finished["run_dir"]))
    expect(run_dir.exists(), "worker must create workflow run directory")
    workflow_run = load_json(run_dir / "workflow_run.json")
    expect(workflow_run.get("status") == "DONE", "worker-created workflow must finish")
    expect(workflow_run.get("input_attachments", [{}])[0].get("name") == "brief.txt", "workflow run must record input attachments")
    expect(
        workflow_run.get("tasks", [{}])[0].get("inputs", {}).get("input_attachments", [{}])[0].get("name") == "brief.txt",
        "task inputs must include input attachments",
    )
    attachment_manifest = load_json(run_dir / "input_attachments_manifest.json")
    expect(attachment_manifest.get("attachments", [{}])[0].get("name") == "brief.txt", "worker must write input attachment manifest")

    resume_job = restarted.start_resume(str(finished["run_id"]))
    expect(resume_job.get("status") == "QUEUED", "console must enqueue resume job")
    resume_result = run_worker_once(output_root=output_root, worker_id="validation-worker")
    expect(resume_result.get("status") == "DONE", "worker must complete queued resume job")
    if previous_wechat_key is None:
        os.environ.pop("CONTENT_AGENT_WECHAT_API_KEY", None)
    else:
        os.environ["CONTENT_AGENT_WECHAT_API_KEY"] = previous_wechat_key


def validate_scheduler_handoff(tmp_root: Path) -> None:
    workflow_path = tmp_root / "scheduler_validation_workflow.yaml"
    output_root = tmp_root / "outputs/runs"
    write_one_step_workflow(workflow_path)

    dry_run = run_scheduler_tick(
        workflow_path=workflow_path,
        topic="Phase 5 scheduler dry-run",
        platforms=["wechat"],
        output_root=output_root,
        interval_seconds=60,
        dry_run=True,
    )
    expect(dry_run.get("status") == "DRY_RUN", "scheduler dry-run must stay DRY_RUN")
    expect(not DurableJobStore(job_db_path(output_root)).list_jobs(), "scheduler dry-run must not enqueue jobs")

    enqueued = run_scheduler_tick(
        workflow_path=workflow_path,
        topic="Phase 5 scheduler handoff",
        platforms=["wechat"],
        output_root=output_root,
        interval_seconds=60,
        dry_run=False,
    )
    expect(enqueued.get("status") == "ENQUEUED", "scheduler execute mode must enqueue")
    expect(enqueued.get("job_id"), "scheduler enqueue must return job_id")
    store = DurableJobStore(job_db_path(output_root))
    job = store.get_job(str(enqueued["job_id"]))
    expect(job is not None and job["status"] == "QUEUED", "scheduler job must be queued")
    result = run_worker_once(output_root=output_root, worker_id="scheduler-validation-worker")
    expect(result.get("status") == "DONE", "worker must consume scheduler job")


def write_one_step_workflow(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "id: phase5_job_queue_validation",
                "name: Phase 5 Job Queue Validation",
                "version: 0.0.0",
                "description: Validate durable job queue worker handoff.",
                "inputs: []",
                "steps:",
                "  - id: research",
                "    agent: research-agent",
                "    depends_on: []",
                "    outputs:",
                "      - research_report.md",
                "      - sources.json",
                "outputs: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"missing JSON file: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def main() -> int:
    validate_static_contract()
    with TemporaryDirectory() as tmp:
        validate_console_enqueue_and_worker(Path(tmp))
    with TemporaryDirectory() as tmp:
        validate_scheduler_handoff(Path(tmp))
    print("Phase 5 job queue validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
