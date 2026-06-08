from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.console_server import ConsoleConfig, ConsoleRuntime, make_console_handler  # noqa: E402
from content_agent_os.job_queue import DurableJobStore, job_db_path  # noqa: E402


SECRET_SENTINEL = "phase5-queue-ops-secret-sentinel"


def fail(message: str) -> None:
    print(f"Phase 5 queue ops validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_text(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def http_json(base_url: str, path: str, *, method: str = "GET") -> Any:
    request = urllib.request.Request(base_url + path, method=method)
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
    expect("validate-phase5-queue-ops:" in makefile, "Makefile missing queue ops target")
    expect("scripts/validate_phase5_queue_ops.py" in makefile, "Makefile target must run queue ops validator")

    base_validator = read_text("scripts/validate_v0.py")
    expect("scripts/validate_phase5_queue_ops.py" in base_validator, "base validator missing queue ops validator")
    expect("validate-phase5-queue-ops:" in base_validator, "base validator missing queue ops target")

    for doc_path in [
        "README.md",
        "docs/RUNBOOK.md",
        "docs/IMPLEMENTATION_ROADMAP.md",
    ]:
        doc = read_text(doc_path)
        expect("queue observability" in doc, f"{doc_path} missing queue observability note")
        expect("make validate-phase5-queue-ops" in doc, f"{doc_path} missing queue ops validation command")


def validate_store_ops(tmp_root: Path) -> None:
    workflow_path = tmp_root / "workflow.yaml"
    workflow_path.write_text("id: q\nname: q\nversion: 0\nsteps: []\noutputs: []\n", encoding="utf-8")
    output_root = tmp_root / "outputs/runs"
    store = DurableJobStore(job_db_path(output_root))

    queued = store.create_run_job(workflow_path=workflow_path, topic="cancel me", platforms=["wechat"])
    canceled = store.cancel_job(str(queued["job_id"]), actor="validation", message="cancel validation")
    expect(canceled["status"] == "CANCELED", "cancel should set CANCELED")

    retried = store.retry_job(str(canceled["job_id"]), actor="validation", message="retry validation")
    expect(retried["status"] == "QUEUED", "retry should create queued job")

    claimed = store.claim_job(str(retried["job_id"]), worker_id="ops-worker")
    expect(claimed is not None and claimed["status"] == "RUNNING", "claim should set RUNNING")
    failed = store.mark_running_failed(str(retried["job_id"]), actor="validation", message="stale worker")
    expect(failed["status"] == "FAILED", "mark failed should set FAILED")
    health = store.queue_health()
    expect(health["counts"]["FAILED"] >= 1, "queue health should count failed jobs")
    audit = store.audit_log(limit=20)
    actions = {item["action"] for item in audit}
    for action in {"enqueue", "cancel", "retry", "created_from_retry", "claim", "mark_failed"}:
        expect(action in actions, f"audit log missing action: {action}")
    audit_text = json.dumps(audit, ensure_ascii=False)
    expect(SECRET_SENTINEL not in audit_text, "audit log must not expose sentinel secret")


def validate_http_and_html(tmp_root: Path) -> None:
    workflow_path = tmp_root / "workflow.yaml"
    workflow_path.write_text("id: q\nname: q\nversion: 0\nsteps: []\noutputs: []\n", encoding="utf-8")
    output_root = tmp_root / "outputs/runs"
    runtime = ConsoleRuntime(
        ConsoleConfig(
            workflow_path=workflow_path,
            output_root=output_root,
            backup_root=tmp_root / "backups",
            default_platforms=["wechat"],
            execute_inline_jobs=False,
        )
    )
    job = runtime.start_run("HTTP queue ops", ["wechat"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_console_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        workspace_html = http_text(base_url, "/")
        expect("队列状态" in workspace_html, "creator workspace should keep queue status summary")
        expect("队列数据库" not in workspace_html, "creator workspace should not expose queue database")
        expect("data-admin-job-action" not in workspace_html, "creator workspace should not expose queue operation actions")
        expect("data-job-action" not in workspace_html, "creator workspace should not expose legacy queue operation actions")
        html = http_text(base_url, "/admin")
        for phrase in ["后端控制台", "队列任务", "队列数据库", "排队中", "生成中", "失败", "取消"]:
            expect(phrase in html, f"admin console HTML missing phrase: {phrase}")
        expect(SECRET_SENTINEL not in html, "admin console HTML must not expose sentinel secret")

        jobs = http_json(base_url, "/api/jobs")
        expect(jobs.get("schema_version") == "phase5.job_index.v1", "jobs schema mismatch")
        expect("queue_health" in jobs, "jobs endpoint missing queue health")
        filtered = http_json(base_url, "/api/jobs?status=QUEUED")
        expect(filtered["jobs"][0]["job_id"] == job["job_id"], "status filter should return queued job")
        health = http_json(base_url, "/api/queue-health")
        expect(health.get("schema_version") == "phase5.queue_health.v1", "queue health schema mismatch")

        canceled = http_json(base_url, f"/api/jobs/{job['job_id']}/cancel", method="POST")
        expect(canceled["status"] == "CANCELED", "HTTP cancel should cancel job")
        retry = http_json(base_url, f"/api/jobs/{job['job_id']}/retry", method="POST")
        expect(retry["status"] == "QUEUED", "HTTP retry should enqueue job")
        runtime.job_store.claim_job(str(retry["job_id"]), worker_id="http-worker")
        failed = http_json(base_url, f"/api/jobs/{retry['job_id']}/mark-failed", method="POST")
        expect(failed["status"] == "FAILED", "HTTP mark-failed should fail running job")
        audit = http_json(base_url, f"/api/jobs/{retry['job_id']}/audit")
        expect(audit.get("schema_version") == "phase5.job_audit_index.v1", "audit schema mismatch")
        audit_text = json.dumps(audit, ensure_ascii=False)
        expect("mark_failed" in audit_text, "audit endpoint should include mark_failed")
        expect(SECRET_SENTINEL not in audit_text, "audit endpoint must not expose sentinel secret")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    validate_static_contract()
    with TemporaryDirectory() as tmp:
        validate_store_ops(Path(tmp))
    with TemporaryDirectory() as tmp:
        validate_http_and_html(Path(tmp))
    print("Phase 5 queue ops validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
