from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.scheduler import run_scheduler_tick  # noqa: E402


def fail(message: str) -> None:
    print(f"Phase 5 profiles validation failed: {message}", file=sys.stderr)
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
    compose = read_text("docker-compose.yml")
    for phrase in [
        "worker:",
        "scheduler:",
        'profiles: ["worker"]',
        'profiles: ["scheduler"]',
        "content_agent_os.worker",
        "content_agent_os.scheduler",
        "CONTENT_AGENT_TOPIC",
        "CONTENT_AGENT_WORKER_POLL_INTERVAL_SECONDS",
        "CONTENT_AGENT_SCHEDULE_INTERVAL_SECONDS",
        "CONTENT_AGENT_SCHEDULER_DRY_RUN",
    ]:
        expect(phrase in compose, f"docker-compose.yml missing phrase: {phrase}")

    makefile = read_text("Makefile")
    for target in [
        "worker:",
        "worker-once:",
        "scheduler:",
        "scheduler-once:",
        "validate-phase5-profiles:",
    ]:
        expect(target in makefile, f"Makefile missing target: {target}")
    expect("scripts/validate_phase5_profiles.py" in makefile, "Makefile target must run profile validator")

    env_example = read_text(".env.example")
    for phrase in [
        "CONTENT_AGENT_TOPIC",
        "CONTENT_AGENT_WORKER_ONCE",
        "CONTENT_AGENT_WORKER_POLL_INTERVAL_SECONDS",
        "CONTENT_AGENT_SCHEDULE_TOPIC",
        "CONTENT_AGENT_SCHEDULE_INTERVAL_SECONDS",
        "CONTENT_AGENT_SCHEDULER_DRY_RUN",
        "CONTENT_AGENT_SCHEDULER_ONCE",
    ]:
        expect(phrase in env_example, f".env.example missing phrase: {phrase}")

    base_validator = read_text("scripts/validate_v0.py")
    expect("src/content_agent_os/scheduler.py" in base_validator, "base validator missing scheduler module")
    expect("scripts/validate_phase5_profiles.py" in base_validator, "base validator missing profile validator")
    expect("validate-phase5-profiles:" in base_validator, "base validator missing profile target")

    setup_validator = read_text("scripts/validate_phase5_setup_check.py")
    expect("compose_profiles" in setup_validator, "setup validator missing compose profile check")
    expect("make validate-phase5-profiles" in setup_validator, "setup validator missing profile command")

    for doc_path in [
        "README.md",
        "docs/RUNBOOK.md",
        "docs/IMPLEMENTATION_ROADMAP.md",
    ]:
        doc = read_text(doc_path)
        expect("worker" in doc, f"{doc_path} missing worker profile note")
        expect("scheduler" in doc, f"{doc_path} missing scheduler profile note")
        expect("make validate-phase5-profiles" in doc, f"{doc_path} missing profile validation command")


def validate_scheduler_dry_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "outputs/runs"
        result = run_scheduler_tick(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 5 profile validation",
            platforms=["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"],
            output_root=output_root,
            interval_seconds=60,
            dry_run=True,
        )
        expect(result.get("schema_version") == "phase5.scheduler_tick.v1", "scheduler tick schema mismatch")
        expect(result.get("status") == "DRY_RUN", "scheduler dry-run should not dispatch")
        expect(result.get("will_dispatch") is False, "scheduler dry-run must not dispatch")
        tick_path = Path(str(result.get("tick_path")))
        expect(tick_path.exists(), "scheduler dry-run must write a tick record")
        tick = json.loads(tick_path.read_text(encoding="utf-8"))
        expect(tick.get("dry_run") is True, "tick record must preserve dry_run=true")
        run_dirs = [path for path in output_root.glob("run_*") if path.is_dir()]
        expect(not run_dirs, "scheduler dry-run must not create workflow run directories")


def main() -> int:
    validate_static_contract()
    validate_scheduler_dry_run()
    print("Phase 5 profiles validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
