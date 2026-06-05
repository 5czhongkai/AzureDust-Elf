# Phase 3 Step 2 Stale Detector Audit

Date: 2026-05-20

## Objective

让总控自动识别卡住或中断的 `RUNNING` task，并把它们标记为可恢复故障，供后续 retry policy、repair-agent 和人工恢复流程使用。

## Success Criteria

- `monitor/supervision_snapshot.json` 包含 `stale_detector` 汇总和每个 task 的 `health` 字段。
- 超过阈值的 `RUNNING` task 会被标记为 `stale`，并进入 `failures` / `recoverable_faults`。
- `resume` 会把遗留的 `RUNNING` attempt 识别为 `stale` 或 `interrupted`，落成 `ENV_ERROR` 可恢复失败后继续重跑。
- `monitor/supervision_report.md` 和 `monitor/failure_dashboard.html` 会显示 stale threshold、watch/stale/interrupted 计数、recoverable 标记和建议操作。
- clean run 的 stale/watch/recoverable 计数必须为 0。

## Evidence

- `src/content_agent_os/stale_detector.py`
- `src/content_agent_os/supervision.py`
- `src/content_agent_os/runner.py`
- `schemas/supervision_snapshot.schema.json`
- `scripts/validate_run.py`
- `scripts/validate_stale_detector.py`
- `docs/RUNBOOK.md`

## Operator Controls

```bash
CONTENT_AGENT_OS_STALE_AFTER_MINUTES=15 make monitor RUN_ID="run_..."
make resume RUN_ID="run_..."
make validate-stale-detector
```

## Current Boundary

当前 step 只做识别与可恢复失败标记，不自动重试、不调用 `repair-agent`。下一步应接入 retry policy，把可恢复故障按策略自动补跑。
