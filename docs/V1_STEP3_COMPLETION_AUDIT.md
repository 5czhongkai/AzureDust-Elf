# V1 Step 3 Completion Audit

Date: 2026-05-18

## Objective

实现 V1 第三步：接入 `topic-agent` 的真实 `run_agent(task_spec)` handler，让 `angle_pack.json` 从上游 `research_report.md` 派生，而不是继续使用 runner 的模板 fallback。

## Success Criteria

- `topic-agent` 被加入可执行 agent 列表。
- `run_agent(task_spec)` 能路由到 `topic-agent` handler。
- `topic-agent` 读取 `research_report.md`。
- `topic-agent` 生成 `angle_pack.json`。
- `angle_pack.json` 明确声明 `generated_by: topic-agent`、`agent_interface: run_agent(task_spec)`、`used_research_report: true`。
- `validate-run` 会拒绝旧 run 或任何 `topic_angles` 不是 `agent-local` 的 run。
- 全平台 workflow 仍能完成。
- 单平台 workflow 仍能完成，并继续正确跳过未选平台。
- 不触发模型调用、登录、cookie 刷新、上传或发布。

## Prompt-to-Artifact Checklist

| Requirement | Evidence | Verification |
| --- | --- | --- |
| 接入 `topic-agent` | `src/content_agent_os/agents.py` | `SUPPORTED_AGENTS` includes `topic-agent` |
| `run_agent` 路由到 topic handler | `src/content_agent_os/agents.py` | `run_agent` calls `_run_topic_agent` for `topic-agent` |
| 从研究报告生成角度包 | `src/content_agent_os/agents.py` | `_run_topic_agent` reads `research_report.md` and sets `used_research_report` |
| 输出 `angle_pack.json` | `src/content_agent_os/agents.py` | `_run_topic_agent` returns `outputs={"angle_pack.json": ...}` |
| 验证器覆盖 step 3 | `scripts/validate_run.py` | Requires `research`, `topic_angles`, `master_outline` to be `agent-local` |
| 验证 angle pack 来源 | `scripts/validate_run.py` | Checks `generated_by`, `agent_interface`, `used_research_report`, `source_artifacts`, and non-empty `angles` |
| 文档更新 | `docs/RUNBOOK.md`, `docs/IMPLEMENTATION_ROADMAP.md` | Describes V1 step 3 behavior |

## Verification Commands

```bash
python3 -m py_compile src/content_agent_os/agents.py src/content_agent_os/workflow.py src/content_agent_os/runner.py src/content_agent_os/cli.py scripts/validate_run.py scripts/validate_v0.py
make validate
make validate-run RUN_ID="run_20260518T101334Z"
make run TOPIC="AI内容创作自动化系统"
make validate-run RUN_ID="run_20260518T102313Z"
make run TOPIC="AI内容创作自动化系统" PLATFORMS="xiaohongshu"
make validate-run RUN_ID="run_20260518T102349Z"
```

Verified results:

```text
make validate
V0 validation passed.
Checked 33 required paths, 14 agents, 4 plugins.
```

Old V1 Step 2 run rejection:

```text
make validate-run RUN_ID="run_20260518T101334Z"
Run validation failed: topic_angles must run through run_agent(task_spec); got 'template'
```

This confirms the verifier no longer accepts a run where `topic_angles` is still template fallback.

Full platform run:

```text
make run TOPIC="AI内容创作自动化系统"
Created workflow run: outputs/runs/run_20260518T102313Z
Workflow state: outputs/runs/run_20260518T102313Z/workflow_run.json
Content package: outputs/runs/run_20260518T102313Z/final/content_package_manifest.json
```

Full platform validation:

```text
make validate-run RUN_ID="run_20260518T102313Z"
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T102313Z
Tasks: 10
Artifacts: 17
Agent-local steps: research, topic_angles, master_outline
```

Observed execution modes:

```text
research PASSED agent-local
topic_angles PASSED agent-local
master_outline PASSED agent-local
wechat_article PASSED template
xiaohongshu_note PASSED template
douyin_video PASSED template
bilibili_video PASSED template
fact_check PASSED template
compliance_check PASSED template
final_validation PASSED template
```

Full run `angle_pack.json` evidence:

```json
{
  "generated_by": "topic-agent",
  "agent_interface": "run_agent(task_spec)",
  "source_artifacts": ["research_report.md"],
  "used_research_report": true
}
```

Topic task log evidence:

```text
execution_mode: agent-local
agent_interface: run_agent(task_spec)
used_research_report: true
source_artifacts: research_report.md
angle_count: 4
```

Single-platform run:

```text
make run TOPIC="AI内容创作自动化系统" PLATFORMS="xiaohongshu"
Created workflow run: outputs/runs/run_20260518T102349Z
```

Single-platform validation:

```text
make validate-run RUN_ID="run_20260518T102349Z"
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T102349Z
Tasks: 10
Artifacts: 9
Agent-local steps: research, topic_angles, master_outline
```

Single-platform status check:

```text
research PASSED agent-local
topic_angles PASSED agent-local
master_outline PASSED agent-local
wechat_article SKIPPED
xiaohongshu_note PASSED template
douyin_video SKIPPED
bilibili_video SKIPPED
fact_check PASSED template
compliance_check PASSED template
final_validation PASSED template
```

Single-platform package check:

- `outputs/runs/run_20260518T102349Z/final/content_package_manifest.json` contains only `xiaohongshu` platform artifacts.
- `outputs/runs/run_20260518T102349Z/angle_pack.json` contains only one platform angle for `xiaohongshu`.

## Actual Output Evidence

Full run:

- `outputs/runs/run_20260518T102313Z/logs/tasks/topic_angles.json`
- `outputs/runs/run_20260518T102313Z/angle_pack.json`
- `outputs/runs/run_20260518T102313Z/research_report.md`
- `outputs/runs/run_20260518T102313Z/master_outline.md`
- `outputs/runs/run_20260518T102313Z/final/content_package_manifest.json`

Single-platform run:

- `outputs/runs/run_20260518T102349Z/logs/tasks/topic_angles.json`
- `outputs/runs/run_20260518T102349Z/angle_pack.json`
- `outputs/runs/run_20260518T102349Z/final/content_package_manifest.json`

## Known Limits

- `topic-agent` is local and structured; it does not call an LLM yet.
- Platform output agents still use template fallback.
- External research is still planned, not fetched live.
