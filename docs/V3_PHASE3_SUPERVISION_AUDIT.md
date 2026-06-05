# Phase 3 Step 1 Supervision Audit

Date: 2026-05-20

## Objective

把 Phase 2 的持久化状态升级成可观察的运行监督层，让总控和使用者都能快速看到一次 workflow 的进度、失败点、缺失产物和恢复建议。

## Success Criteria

- 每次 `make run` / `make resume` 自动刷新监督文件。
- 支持 `make monitor RUN_ID="..."` 和 `make logs RUN_ID="..."` 单独刷新指定 run。
- `monitor/supervision_snapshot.json` 作为结构化状态快照，可供后续 Web UI 或告警系统读取。
- `monitor/supervision_report.md` 包含状态汇总、task timeline、Mermaid failure map 和恢复建议。
- `monitor/failure_dashboard.html` 提供可本地打开的故障看板。
- 监督快照同时利用 `workflow_run.json` 与 SQLite `task_ledger`，保留历史 attempts。

## Evidence

- `src/content_agent_os/supervision.py`
- `src/content_agent_os/runner.py`
- `src/content_agent_os/cli.py`
- `schemas/supervision_snapshot.schema.json`
- `Makefile`
- `docs/RUNBOOK.md`

## Operator Commands

```bash
make run TOPIC="Phase 3 监督验证"
make monitor RUN_ID="run_..."
make logs RUN_ID="run_..."
```

## Output Contract

```text
outputs/runs/{run_id}/monitor/
  ├── supervision_snapshot.json
  ├── supervision_report.md
  └── failure_dashboard.html
```

## Notes

- 当前 Step 1 只做可观察性和故障呈现，不自动重试、不调用 repair-agent。
- 下一步应接入 stale task detector，把长时间 RUNNING 或中断的任务升级为可修复故障。
