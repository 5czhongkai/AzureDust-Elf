from __future__ import annotations

import json
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.console_server import ConsoleConfig, ConsoleRuntime, make_console_handler  # noqa: E402
from content_agent_os.job_queue import CLEANUP_CONFIRMATION, DurableJobStore, job_db_path  # noqa: E402


SECRET_SENTINEL = "phase5-queue-retention-secret-sentinel"


def fail(message: str) -> None:
    print(f"Phase 5 queue retention validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_text(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def http_json(base_url: str, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON response for {path}: {exc}")


def http_text(base_url: str, path: str) -> str:
    with urllib.request.urlopen(base_url + path, timeout=10) as response:
        return response.read().decode("utf-8")


def validate_static_contract() -> None:
    makefile = read_text("Makefile")
    expect("validate-phase5-queue-retention:" in makefile, "Makefile missing queue retention target")
    expect("scripts/validate_phase5_queue_retention.py" in makefile, "Makefile target must run queue retention validator")

    base_validator = read_text("scripts/validate_v0.py")
    for phrase in [
        "scripts/validate_phase5_queue_retention.py",
        "validate-phase5-queue-retention:",
    ]:
        expect(phrase in base_validator, f"base validator missing phrase: {phrase}")

    env_example = read_text(".env.example")
    expect("CONTENT_AGENT_JOB_RETENTION_DAYS" in env_example, ".env.example missing job retention")
    expect("CONTENT_AGENT_AUDIT_RETENTION_DAYS" in env_example, ".env.example missing audit retention")

    for doc_path in [
        "README.md",
        "docs/RUNBOOK.md",
        "docs/IMPLEMENTATION_ROADMAP.md",
    ]:
        doc = read_text(doc_path)
        expect("queue history" in doc, f"{doc_path} missing queue history note")
        expect("make validate-phase5-queue-retention" in doc, f"{doc_path} missing queue retention validation command")


def validate_store_cleanup(tmp_root: Path) -> None:
    store = DurableJobStore(job_db_path(tmp_root / "outputs/runs"))
    old_done = make_job(store, "old done")
    old_failed = make_job(store, "old failed")
    old_canceled = make_job(store, "old canceled")
    queued = make_job(store, "protected queued")
    running = make_job(store, "protected running")

    store.claim_job(str(old_done["job_id"]), worker_id="retention-worker")
    store.mark_done(str(old_done["job_id"]), run_dir=tmp_root / "outputs/runs/run_old_done")
    store.claim_job(str(old_failed["job_id"]), worker_id="retention-worker")
    store.mark_failed(str(old_failed["job_id"]), error=SECRET_SENTINEL)
    store.cancel_job(str(old_canceled["job_id"]), actor="validation", message="old canceled")
    store.claim_job(str(running["job_id"]), worker_id="retention-worker")

    make_old(store.db_path, [old_done["job_id"], old_failed["job_id"], old_canceled["job_id"]])
    make_audit_old(store.db_path)

    dry_run = store.cleanup_dry_run(job_retention_days=30, audit_retention_days=90)
    expect(dry_run["dry_run"] is True, "dry-run must identify itself")
    expect(dry_run["delete_job_count"] == 3, "dry-run should find three terminal old jobs")
    expect(dry_run["protected_counts"]["QUEUED"] == 1, "dry-run must protect queued")
    expect(dry_run["protected_counts"]["RUNNING"] == 1, "dry-run must protect running")
    expect(store.get_job(str(old_done["job_id"])) is not None, "dry-run must not delete jobs")

    try:
        store.cleanup(confirmation="", job_retention_days=30, audit_retention_days=90)
    except ValueError as exc:
        expect("confirmation" in str(exc), "cleanup without confirmation should explain requirement")
    else:
        fail("cleanup without confirmation should fail")

    result = store.cleanup(
        confirmation=CLEANUP_CONFIRMATION,
        actor="validation",
        job_retention_days=30,
        audit_retention_days=90,
    )
    expect(result["deleted_job_count"] == 3, "cleanup should delete old terminal jobs")
    expect(store.get_job(str(queued["job_id"])) is not None, "cleanup must keep queued job")
    expect(store.get_job(str(running["job_id"])) is not None, "cleanup must keep running job")
    audit_text = json.dumps(store.audit_log(limit=50), ensure_ascii=False)
    expect(SECRET_SENTINEL not in audit_text, "old audit containing sentinel should be cleaned")


def validate_http_and_html(tmp_root: Path) -> None:
    runtime = ConsoleRuntime(
        ConsoleConfig(
            workflow_path=tmp_root / "workflow.yaml",
            output_root=tmp_root / "outputs/runs",
            backup_root=tmp_root / "backups",
            default_platforms=["wechat"],
            execute_inline_jobs=False,
            job_retention_days=30,
            audit_retention_days=90,
        )
    )
    runtime.config.workflow_path.write_text("id: q\nname: q\nversion: 0\nsteps: []\noutputs: []\n", encoding="utf-8")
    old = make_job(runtime.job_store, "http old")
    runtime.job_store.claim_job(str(old["job_id"]), worker_id="http-retention")
    runtime.job_store.mark_done(str(old["job_id"]), run_dir=tmp_root / "outputs/runs/run_http_old")
    make_old(runtime.job_store.db_path, [old["job_id"]])

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_console_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        workspace_html = http_text(base_url, "/")
        expect("队列维护" not in workspace_html, "creator workspace should not expose queue maintenance")
        html = http_text(base_url, "/admin")
        for phrase in ["队列维护", "保留策略", "清理预览", "确认清理"]:
            expect(phrase in html, f"admin console HTML missing phrase: {phrase}")
        expect(SECRET_SENTINEL not in html, "admin console HTML must not expose sentinel")

        dry_run = http_json(base_url, "/api/jobs/cleanup-dry-run", method="POST")
        expect(dry_run["delete_job_count"] == 1, "HTTP cleanup dry-run should find old job")
        expect(runtime.job_store.get_job(str(old["job_id"])) is not None, "HTTP dry-run must not delete")

        try:
            http_json(base_url, "/api/jobs/cleanup", method="POST", payload={"confirmation": ""})
        except urllib.error.HTTPError as exc:
            expect(exc.code == 400, "cleanup without confirmation should return 400")
        else:
            fail("HTTP cleanup without confirmation should fail")

        cleanup = http_json(
            base_url,
            "/api/jobs/cleanup",
            method="POST",
            payload={"confirmation": CLEANUP_CONFIRMATION},
        )
        expect(cleanup["deleted_job_count"] == 1, "HTTP cleanup should delete old job")
        expect(runtime.job_store.get_job(str(old["job_id"])) is None, "HTTP cleanup should remove old job")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def make_job(store: DurableJobStore, topic: str) -> dict[str, Any]:
    return store.create_run_job(workflow_path=Path("workflow.yaml"), topic=topic, platforms=["wechat"])


def make_old(db_path: Path, job_ids: list[str]) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    with sqlite3.connect(db_path) as conn:
        for job_id in job_ids:
            conn.execute(
                "UPDATE console_job SET created_at = ?, updated_at = ?, ended_at = COALESCE(ended_at, ?) WHERE job_id = ?",
                (old, old, old, job_id),
            )


def make_audit_old(db_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE console_job_audit SET created_at = ?", (old,))


def main() -> int:
    validate_static_contract()
    with TemporaryDirectory() as tmp:
        validate_store_cleanup(Path(tmp))
    with TemporaryDirectory() as tmp:
        validate_http_and_html(Path(tmp))
    print("Phase 5 queue retention validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
