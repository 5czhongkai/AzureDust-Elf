# Phase 3 Step 3 Retry Policy Audit

Date: 2026-05-20

## Objective

把 stale detector 标记出来的可恢复故障升级为可控的自动补跑机制，让总控在预算范围内自动恢复 `stale` / `interrupted` task，同时保留完整决策记录，避免无限重试。

## Success Criteria

- `retry_policy` 有明确配置：默认开启、每个 step 默认最多自动重试 1 次。
- 只有 `recoverable=true`、`failure_category=ENV_ERROR`、`recovery_state=stale|interrupted` 的故障允许自动补跑。
- `resume` 遇到可恢复故障时，会记录 `scheduled`、`started`、`passed` 或 `failed` retry events。
- 超出预算后不会继续自动补跑，会保留 `blocked` 事件和 `budget_exhausted` 决策。
- `monitor/supervision_snapshot.json`、`monitor/supervision_report.md`、`monitor/failure_dashboard.html` 展示 retry policy 汇总与事件。
- clean run 的 retry 计数必须为 0。

## Evidence

- `src/content_agent_os/retry_policy.py`
- `src/content_agent_os/runner.py`
- `src/content_agent_os/supervision.py`
- `schemas/supervision_snapshot.schema.json`
- `schemas/workflow_run.schema.json`
- `scripts/validate_retry_policy.py`
- `docs/RUNBOOK.md`

## Operator Controls

```bash
CONTENT_AGENT_OS_MAX_AUTO_RETRIES=2 make resume RUN_ID="run_..."
CONTENT_AGENT_OS_RETRY_POLICY_ENABLED=0 make resume RUN_ID="run_..."
make validate-retry-policy
```

## Current Boundary

当前 step 只做自动补跑策略，不调用 `repair-agent`，也不会改写 task 输入或产物。后续 repair-agent 会基于失败分类和 retry events 决定是否生成修复建议或补齐数据。
