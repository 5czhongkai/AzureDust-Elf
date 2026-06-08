from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.console_server import (  # noqa: E402
    ConsoleConfig,
    ConsoleRuntime,
    SECRET_ENV_KEYS,
    make_console_handler,
)


SECRET_SENTINEL = "phase5-setup-secret-sentinel"


def fail(message: str) -> None:
    print(f"Phase 5 setup-check validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_text(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def http_json(base_url: str, path: str) -> Any:
    with urllib.request.urlopen(base_url + path, timeout=10) as response:
        body = response.read().decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON response for {path}: {exc}")


def http_text(base_url: str, path: str) -> str:
    with urllib.request.urlopen(base_url + path, timeout=10) as response:
        return response.read().decode("utf-8")


def write_ready_fixture(output_root: Path) -> None:
    run_dir = output_root / "run_20260603T000000Z"
    (run_dir / "monitor").mkdir(parents=True, exist_ok=True)
    (output_root / "_state").mkdir(parents=True, exist_ok=True)
    (output_root / "_state/workflow_state.sqlite").write_text("fixture\n", encoding="utf-8")
    workflow_run = {
        "schema_version": "workflow_run.v1",
        "run_id": run_dir.name,
        "workflow_id": "one_topic_multi_platform",
        "topic": "Phase 5 setup validation",
        "platforms": ["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"],
        "status": "DONE",
        "created_at": "2026-06-03T00:00:00+00:00",
        "updated_at": "2026-06-03T00:01:00+00:00",
        "workflow": {"steps": []},
        "task_runs": [],
        "artifacts": [],
    }
    snapshot = {
        "schema_version": "phase3.supervision.v1",
        "run": {"run_id": run_dir.name, "status": "DONE"},
        "summary": {"completed_steps": 1, "total_steps": 1, "progress_percent": 100},
        "tasks": [],
    }
    (run_dir / "workflow_run.json").write_text(json.dumps(workflow_run, indent=2) + "\n", encoding="utf-8")
    (run_dir / "monitor/supervision_snapshot.json").write_text(
        json.dumps(snapshot, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_setup_payload(payload: dict[str, Any]) -> None:
    expect(payload.get("schema_version") == "phase5.setup_check.v1", "setup check schema mismatch")
    expect(payload.get("status") == "ok", "ready fixture should pass setup check")
    expect(payload.get("bad_count") == 0, "ready fixture should have no bad checks")
    payload_text = json.dumps(payload, ensure_ascii=False)
    expect(SECRET_SENTINEL not in payload_text, "setup check must not expose secret values")

    checks = {item.get("id"): item for item in payload.get("checks", [])}
    for check_id in [
        "python",
        "workflow",
        "platforms",
        "env_example",
        "compose_profiles",
        "output_root",
        "backup_root",
        "resume_state_db",
        "job_queue_db",
        "local_runtime",
        "latest_backup",
        "secrets",
        "secret_policy",
    ]:
        expect(check_id in checks, f"setup check missing {check_id}")
    expect(checks["secrets"].get("status") == "ok", "secret presence should be ok for fixture")
    expect(checks["secret_policy"].get("status") == "ok", "secret boundary must be ok")

    commands = {item.get("command") for item in payload.get("commands", [])}
    for command in [
        "make validate",
        "make validate-phase5-console",
        "make validate-phase5-migration",
        "make validate-phase5-setup",
        "make validate-phase5-profiles",
        "make validate-phase5-job-queue",
        "make validate-phase5-local-runtime",
        "make console",
        "docker compose up console",
    ]:
        expect(command in commands, f"setup commands missing {command}")


def validate_static_contract() -> None:
    makefile = read_text("Makefile")
    expect("validate-phase5-setup:" in makefile, "Makefile missing setup validation target")
    expect(
        "scripts/validate_phase5_setup_check.py" in makefile,
        "Makefile target must run setup-check validator",
    )

    base_validator = read_text("scripts/validate_v0.py")
    expect("scripts/validate_phase5_setup_check.py" in base_validator, "base validator missing setup script")
    expect("validate-phase5-setup:" in base_validator, "base validator missing setup target")

    readme = read_text("README.md")
    expect("GET /api/setup-check" in readme, "README missing setup-check API")
    expect("make validate-phase5-setup" in readme, "README missing setup validation command")

    runbook = read_text("docs/RUNBOOK.md")
    expect("GET /api/setup-check" in runbook, "runbook missing setup-check API")
    expect("make validate-phase5-setup" in runbook, "runbook missing setup validation command")

    migration = read_text("docs/PHASE5_MIGRATION.md")
    expect("GET /api/setup-check" in migration, "migration doc missing setup-check API")
    expect("make validate-phase5-setup" in migration, "migration doc missing setup validation command")

    roadmap = read_text("docs/IMPLEMENTATION_ROADMAP.md")
    expect("Step 4 已接入本地配置向导" in roadmap, "roadmap missing setup step")


def validate_runtime_and_http(tmp_root: Path) -> None:
    output_root = tmp_root / "outputs/runs"
    backup_root = tmp_root / "backups"
    write_ready_fixture(output_root)
    runtime = ConsoleRuntime(
        ConsoleConfig(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            output_root=output_root,
            backup_root=backup_root,
            default_platforms=["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"],
        )
    )
    runtime.create_backup()
    validate_setup_payload(runtime.setup_check())

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_console_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        validate_setup_payload(http_json(base_url, "/api/setup-check"))
        workspace_html = http_text(base_url, "/")
        expect("后端控制台" in workspace_html, "creator workspace missing admin console link")
        expect("本机状态" not in workspace_html, "creator workspace should not expose local setup panel")
        html = http_text(base_url, "/admin")
        expect("后端控制台" in html, "admin console HTML missing title")
        expect("配置检查" in html, "admin console HTML missing setup panel")
        expect("本机状态" in html, "admin console HTML missing local setup panel")
        expect("make validate-phase5-setup" in html, "admin console HTML missing setup validation command")
        expect(SECRET_SENTINEL not in html, "admin console HTML must not expose secret values")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    validate_static_contract()
    previous_env = {key: os.environ.get(key) for key in SECRET_ENV_KEYS}
    try:
        for key in SECRET_ENV_KEYS:
            os.environ[key] = SECRET_SENTINEL
        with TemporaryDirectory() as tmp:
            validate_runtime_and_http(Path(tmp))
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print("Phase 5 setup-check validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
