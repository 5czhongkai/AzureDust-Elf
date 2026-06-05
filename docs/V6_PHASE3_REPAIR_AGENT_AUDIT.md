# Phase 3 Step 4 Repair Agent Audit

Date: 2026-05-20

## Objective

让不可自动重试的失败进入诊断与修复建议链路：总控在失败被 retry policy 阻止或普通 task 失败时调用 `repair-agent`，生成可审计的 repair plan 和 repair log，但不自动改写 task、产物或发布状态。

## Success Criteria

- `repair-agent` 接入真实 `run_agent(task_spec)` handler。
- 非自动重试失败会写入 `repair/repair_log.json`。
- 每个失败 step 会生成 `repair/{step_id}_repair_plan.md` 和 `repair/{step_id}_repair_plan.json`。
- repair plan 必须包含失败分类、失败消息、root cause hypothesis、recommended actions、manual_required、can_auto_patch。
- `monitor/supervision_snapshot.json`、`monitor/supervision_report.md`、`monitor/failure_dashboard.html` 展示 repair log 汇总和 plan 路径。
- clean run 的 repair 计数必须为 0。

## Evidence

- `src/content_agent_os/agents.py`
- `src/content_agent_os/runner.py`
- `src/content_agent_os/supervision.py`
- `src/content_agent_os/approval_gate.py`
- `schemas/supervision_snapshot.schema.json`
- `schemas/workflow_run.schema.json`
- `scripts/validate_repair_agent.py`
- `scripts/validate_human_approval_gate.py`
- `docs/RUNBOOK.md`

## Operator Commands

```bash
make validate-repair-agent
make validate-human-approval-gate
make approve-repair RUN_ID="run_..." REPAIR_ID="repair_..."
make monitor RUN_ID="run_..."
```

## Current Boundary

当前 `repair-agent` 只做诊断和建议，不自动 patch、不自动刷新 cookie、不自动上传或发布。`manual_required=true` 的 repair plan 已经接入 human approval gate，必须先人工确认再 resume。
