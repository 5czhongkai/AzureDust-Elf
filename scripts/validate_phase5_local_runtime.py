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
    make_console_handler,
)


SECRET_SENTINEL = "phase5-local-runtime-secret-sentinel"


def fail(message: str) -> None:
    print(f"Phase 5 local runtime validation failed: {message}", file=sys.stderr)
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


def validate_static_contract() -> None:
    makefile = read_text("Makefile")
    expect("validate-phase5-local-runtime:" in makefile, "Makefile missing local runtime target")
    expect(
        "scripts/validate_phase5_local_runtime.py" in makefile,
        "Makefile target must run local runtime validator",
    )

    base_validator = read_text("scripts/validate_v0.py")
    for needle in [
        "scripts/validate_phase5_local_runtime.py",
        "validate-phase5-local-runtime:",
        "docs/V35_PHASE5_LOCAL_RUNTIME_AUDIT.md",
    ]:
        expect(needle in base_validator, f"base validator missing {needle}")

    for doc_path in [
        "README.md",
        "docs/RUNBOOK.md",
        "docs/IMPLEMENTATION_ROADMAP.md",
        "docs/V35_PHASE5_LOCAL_RUNTIME_AUDIT.md",
    ]:
        doc = read_text(doc_path)
        expect("local runtime" in doc, f"{doc_path} missing local runtime note")
        expect("make validate-phase5-local-runtime" in doc, f"{doc_path} missing validation command")
        expect("Docker" in doc and "optional" in doc, f"{doc_path} must clarify Docker is optional")


def validate_payload(payload: dict[str, Any]) -> None:
    expect(payload.get("schema_version") == "phase5.local_runtime_status.v1", "local runtime schema mismatch")
    expect(payload.get("status") == "ok", "local runtime fixture should be ok")
    expect(payload.get("docker_required") is False, "Docker must not be required for local runtime")
    expect(payload.get("worker_queue_ready") is True, "worker queue should be ready")
    expect(payload.get("scheduler_default_dry_run") is True, "scheduler should default to dry-run")
    payload_text = json.dumps(payload, ensure_ascii=False)
    expect(SECRET_SENTINEL not in payload_text, "local runtime must not expose secret values")

    commands = {item.get("command"): item for item in payload.get("commands", [])}
    for command in [
        "make console",
        "make worker-once",
        "make worker",
        "make scheduler-once",
        "make scheduler",
        "docker compose up console",
    ]:
        expect(command in commands, f"local runtime commands missing {command}")
    expect(commands["docker compose up console"].get("required") is False, "Docker command must be optional")
    for command in ["make console", "make worker-once", "make worker", "make scheduler-once", "make scheduler"]:
        expect(commands[command].get("required") is True, f"{command} should be a local runtime command")
        expect(commands[command].get("ready") is True, f"{command} should be ready in fixture")


def validate_runtime_and_http(tmp_root: Path) -> None:
    output_root = tmp_root / "outputs/runs"
    backup_root = tmp_root / "backups"
    (output_root / "_state").mkdir(parents=True)
    backup_root.mkdir(parents=True)
    runtime = ConsoleRuntime(
        ConsoleConfig(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            output_root=output_root,
            backup_root=backup_root,
            default_platforms=["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"],
        )
    )
    validate_payload(runtime.local_runtime_status())
    setup = runtime.setup_check()
    setup_text = json.dumps(setup, ensure_ascii=False)
    expect("local_runtime" in setup_text, "setup check should include local_runtime check")
    expect("make validate-phase5-local-runtime" in setup_text, "setup check missing local runtime command")

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_console_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        validate_payload(http_json(base_url, "/api/local-runtime"))
        workspace_html = http_text(base_url, "/")
        expect("后端控制台" in workspace_html, "creator workspace missing admin console link")
        expect("本机状态" not in workspace_html, "creator workspace should not expose local runtime panel")
        html = http_text(base_url, "/admin")
        expect("后端控制台" in html, "admin console HTML missing title")
        expect("本机状态" in html, "admin console HTML missing local runtime panel")
        expect("Docker" in html, "admin console HTML missing Docker optional note")
        expect("make worker-once" in html, "admin console HTML missing worker command")
        expect("make scheduler-once" in html, "admin console HTML missing scheduler command")
        expect(SECRET_SENTINEL not in html, "admin console HTML must not expose secret values")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    validate_static_contract()
    previous_secret = os.environ.get("OPENAI_API_KEY")
    previous_scheduler = os.environ.get("CONTENT_AGENT_SCHEDULER_DRY_RUN")
    try:
        os.environ["OPENAI_API_KEY"] = SECRET_SENTINEL
        os.environ.pop("CONTENT_AGENT_SCHEDULER_DRY_RUN", None)
        with TemporaryDirectory() as tmp:
            validate_runtime_and_http(Path(tmp))
    finally:
        if previous_secret is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous_secret
        if previous_scheduler is None:
            os.environ.pop("CONTENT_AGENT_SCHEDULER_DRY_RUN", None)
        else:
            os.environ["CONTENT_AGENT_SCHEDULER_DRY_RUN"] = previous_scheduler
    print("Phase 5 local runtime validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
