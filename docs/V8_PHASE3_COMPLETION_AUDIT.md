# Phase 3 Completion Audit

Date: 2026-05-22

## Objective

收口 Phase 3 的监督与修复闭环，确认总控可以把运行故障从发现、分类、补跑、诊断、人工确认一路推进到恢复完成。

## Completion Scope

- 运行监督与故障可视化
- stale / interrupted task detector
- retry policy 自动补跑
- retry budget blocked repair
- repair-agent + repair log
- `manual_required=true` human approval gate
- approval 后的 resume replay

## End-to-End Drills

`make validate-phase3` 会串联以下演练：

1. stale health classification
2. stale supervision exposure
3. stale resume conversion
4. retry policy decisions
5. retry auto replay
6. retry budget blocked repair
7. repair-agent handler
8. repair log exposure
9. human approval gate

这些演练都会使用临时 run 目录、SQLite state store 和真实 `resume_workflow` 路径，不依赖固定输出模板快照。

## Operator Commands

```bash
make validate-phase3
make validate-stale-detector
make validate-retry-policy
make validate-repair-agent
make validate-human-approval-gate
```

## Acceptance

- recoverable stale / interrupted failure can be replayed automatically within retry budget.
- retry budget exhaustion keeps workflow blocked and visible in supervision.
- non-auto-retry failure generates repair plan and repair log.
- `manual_required=true` pauses workflow at `NEEDS_HUMAN`.
- `make approve-repair` records approval and moves workflow to `REPAIRING`.
- a later `make resume` completes the failed step and keeps approval evidence.

## Boundary

Phase 3 still does not auto-patch task inputs, refresh cookies, upload files, or publish content. Those actions remain outside the automation boundary until a future explicit approval and execution layer is designed.
