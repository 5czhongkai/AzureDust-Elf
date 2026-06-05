from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"Phase 5 migration validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_text(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def expect_phrases(text: str, phrases: list[str], *, source: str) -> None:
    for phrase in phrases:
        expect(phrase in text, f"{source} missing phrase: {phrase}")


def main() -> int:
    migration = read_text("docs/PHASE5_MIGRATION.md")
    expect_phrases(
        migration,
        [
            "outputs/",
            "backups/",
            "outputs/runs/_state/workflow_state.sqlite",
            "outputs/runs/_state/console_jobs.sqlite",
            ".env.example",
            "OPENAI_API_KEY",
            "SILICONFLOW_API_KEY",
            "CONTENT_AGENT_OS_TTS_API_KEY",
            "make validate",
            "make validate-phase5-console",
            "make validate-phase5-migration",
            "make validate-phase5-setup",
            "make validate-phase5-profiles",
            "make validate-phase5-job-queue",
            "make console",
            "make scheduler-once",
            "GET /api/setup-check",
            "phase5.setup_check.v1",
            "CONTENT_AGENT_SCHEDULER_DRY_RUN",
            "POST /api/restore-dry-run",
            "POST /api/restore",
            "RESTORE <backup-name>",
            "safe_to_restore=false",
            "docker compose up console",
            "Docker 不是本地迁移的必需条件",
        ],
        source="migration doc",
    )

    makefile = read_text("Makefile")
    expect("validate-phase5-migration:" in makefile, "Makefile missing validate-phase5-migration target")
    expect("scripts/validate_phase5_migration.py" in makefile, "Makefile target must run migration validator")

    readme = read_text("README.md")
    expect("make validate-phase5-migration" in readme, "README missing migration validation command")
    expect("make validate-phase5-setup" in readme, "README missing setup validation command")
    expect("make validate-phase5-profiles" in readme, "README missing profile validation command")
    expect("make validate-phase5-job-queue" in readme, "README missing job queue validation command")
    expect("多设备迁移" in readme, "README missing migration note")

    roadmap = read_text("docs/IMPLEMENTATION_ROADMAP.md")
    expect("Step 3 已接入多设备迁移说明" in roadmap, "roadmap missing Phase 5 migration progress")
    expect("validate-phase5-migration" in roadmap, "roadmap missing migration validation target")
    expect("Step 4 已接入本地配置向导" in roadmap, "roadmap missing Phase 5 setup progress")
    expect("Step 5 已接入 worker/scheduler profiles" in roadmap, "roadmap missing Phase 5 profile progress")
    expect("Step 6 已接入 durable job queue" in roadmap, "roadmap missing Phase 5 job queue progress")

    runbook = read_text("docs/RUNBOOK.md")
    expect("docs/PHASE5_MIGRATION.md" in runbook, "runbook missing migration doc reference")
    expect("make validate-phase5-migration" in runbook, "runbook missing migration validation command")
    expect("make validate-phase5-setup" in runbook, "runbook missing setup validation command")
    expect("make validate-phase5-profiles" in runbook, "runbook missing profile validation command")
    expect("make validate-phase5-job-queue" in runbook, "runbook missing job queue validation command")

    base_validator = read_text("scripts/validate_v0.py")
    expect("scripts/validate_phase5_migration.py" in base_validator, "base validator missing migration script")
    expect("scripts/validate_phase5_setup_check.py" in base_validator, "base validator missing setup script")
    expect("scripts/validate_phase5_profiles.py" in base_validator, "base validator missing profile script")
    expect("scripts/validate_phase5_job_queue.py" in base_validator, "base validator missing job queue script")
    expect("docs/PHASE5_MIGRATION.md" in base_validator, "base validator missing migration doc")
    expect("validate-phase5-migration:" in base_validator, "base validator missing migration target")
    expect("validate-phase5-setup:" in base_validator, "base validator missing setup target")
    expect("validate-phase5-profiles:" in base_validator, "base validator missing profile target")
    expect("validate-phase5-job-queue:" in base_validator, "base validator missing job queue target")

    print("Phase 5 migration validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
