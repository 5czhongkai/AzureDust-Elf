# Phase 2 Persistence Audit

Date: 2026-05-19

## Objective

把 workflow 执行从“只写 run 目录”升级为“run 目录 + SQLite 状态库”，让失败 run 可以 resume，且每次 task 尝试都有 ledger 记录。

## Success Criteria

- `outputs/runs/_state/workflow_state.sqlite` 可创建并持久化运行状态。
- SQLite 至少包含 `workflow_run` 和 `task_ledger` 两张表。
- `make resume RUN_ID="..."` 可以恢复失败 run。
- 失败会被分类到 `DATA_ERROR` / `SCHEMA_ERROR` / `QUALITY_ERROR` / `POLICY_ERROR` / `PERMISSION_ERROR` / `ENV_ERROR`。
- 完整 workflow 的既有校验仍然通过。

## Verification

```bash
make run TOPIC="Phase 2 持久化验证"
python3 scripts/validate_run.py run_20260519T111650Z
make resume RUN_ID="run_20260519T111026Z"
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect("outputs/runs/_state/workflow_state.sqlite")
print(conn.execute("select count(*) from workflow_run").fetchone()[0])
print(conn.execute("select count(*) from task_ledger").fetchone()[0])
PY
```

## Evidence

- `src/content_agent_os/state_store.py`
- `src/content_agent_os/failure.py`
- `src/content_agent_os/runner.py`
- `src/content_agent_os/cli.py`
- `Makefile`
- `docs/RUNBOOK.md`

## Notes

- `workflow_run.json` remains the portable snapshot for each run directory.
- SQLite stores the history of attempts so resume can continue from the first incomplete step.
