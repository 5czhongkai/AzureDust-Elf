# V1 Step 5 Completion Audit

Date: 2026-05-18

## Objective

实现 V1 第五步：接入第二个平台产出 agent，优先实现 `wechat-article-agent`，让 `wechat/article.md` 和 `wechat/title_options.json` 从 `angle_pack.json`、`master_outline.md`、`research_report.md` 与 `sources.json` 派生，而不是继续使用 runner 模板 fallback。

## Success Criteria

- `wechat-article-agent` 被加入可执行 agent 列表。
- `run_agent(task_spec)` 能路由到 `wechat-article-agent` handler。
- `wechat-article-agent` 读取 `angle_pack.json`。
- `wechat-article-agent` 读取 `master_outline.md`。
- `wechat-article-agent` 读取 `research_report.md`。
- `wechat-article-agent` 读取 `sources.json` 的来源计划。
- `wechat-article-agent` 生成 `wechat/article.md`。
- `wechat-article-agent` 生成 `wechat/title_options.json`。
- `wechat/article.md` 包含来源状态、互动问题和人工审核标记。
- `wechat/title_options.json` 包含至少 3 个标题备选、摘要、来源说明和人工审核标记。
- 当平台包含 `wechat` 时，`validate-run` 会拒绝任何 `wechat_article` 不是 `agent-local` 的 run。
- 全平台 workflow 仍能完成。
- 微信单平台 workflow 仍能完成，并继续正确跳过未选平台。
- 不触发模型调用、登录、cookie 刷新、上传或发布。

## Prompt-to-Artifact Checklist

| Requirement | Evidence | Verification |
| --- | --- | --- |
| 接入 `wechat-article-agent` | `src/content_agent_os/agents.py` | `SUPPORTED_AGENTS` includes `wechat-article-agent` |
| `run_agent` 路由到 wechat handler | `src/content_agent_os/agents.py` | `run_agent` calls `_run_wechat_article_agent` |
| 从上游 artifact 生成公众号文章 | `src/content_agent_os/agents.py` | Handler reads `angle_pack.json`, `master_outline.md`, `research_report.md`, and `sources.json` |
| 输出微信文件 | `src/content_agent_os/agents.py` | Handler returns `wechat/article.md` and `wechat/title_options.json` |
| 验证器覆盖微信平台 agent | `scripts/validate_run.py` | Requires `wechat_article` to be `agent-local` when selected |
| 验证微信输出约束 | `scripts/validate_run.py` | Checks article body, source status, title options, source notes, review flag |
| 文档更新 | `docs/RUNBOOK.md`, `docs/IMPLEMENTATION_ROADMAP.md` | Describes V1 step 5 behavior |

## Verification Commands

### Static validation

```bash
python3 -m py_compile src/content_agent_os/cli.py src/content_agent_os/workflow.py src/content_agent_os/runner.py src/content_agent_os/agents.py scripts/validate_v0.py scripts/validate_run.py
make validate
```

Result:

```text
V0 validation passed.
Checked 35 required paths, 14 agents, 4 plugins.
```

### Regression guard

Validated that an older Step 4 run is rejected because it still used template mode for `wechat_article`.

```bash
make validate-run RUN_ID="run_20260518T104219Z"
```

Result:

```text
Run validation failed: wechat_article must run through run_agent(task_spec); got 'template'
```

### Full multi-platform run

```bash
make run TOPIC="AI内容创作自动化系统"
make validate-run RUN_ID="run_20260518T105614Z"
```

Result:

```text
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T105614Z
Tasks: 10
Artifacts: 17
Agent-local steps: research, topic_angles, master_outline, wechat_article, xiaohongshu_note
```

Execution evidence:

```text
research: PASSED, agent-local
topic_angles: PASSED, agent-local
master_outline: PASSED, agent-local
wechat_article: PASSED, agent-local
xiaohongshu_note: PASSED, agent-local
douyin_video: PASSED, template
bilibili_video: PASSED, template
fact_check: PASSED, template
compliance_check: PASSED, template
final_validation: PASSED, template
```

Package evidence:

```text
platforms: wechat, xiaohongshu, douyin, bilibili
platform artifact count: 10
wechat artifacts:
- wechat/article.md
- wechat/title_options.json
```

### WeChat-only run

```bash
make run TOPIC="AI内容创作自动化系统" PLATFORMS="wechat"
make validate-run RUN_ID="run_20260518T105632Z"
```

Result:

```text
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T105632Z
Tasks: 10
Artifacts: 9
Agent-local steps: research, topic_angles, master_outline, wechat_article
```

Execution evidence:

```text
research: PASSED, agent-local
topic_angles: PASSED, agent-local
master_outline: PASSED, agent-local
wechat_article: PASSED, agent-local
fact_check: PASSED, template
compliance_check: PASSED, template
final_validation: PASSED, template
```

Package evidence:

```text
platforms: wechat
platform artifact count: 2
artifacts:
- wechat/article.md
- wechat/title_options.json
```

WeChat article evidence:

```text
recommended_title: AI内容创作自动化系统：从选题到多平台内容包
title_count: 3
summary_length: 57
source_note_count: 2
article_length: 965
review_required: true
```

Task log metadata:

```json
{
  "execution_mode": "agent-local",
  "agent_interface": "run_agent(task_spec)",
  "used_angle_pack": true,
  "used_master_outline": true,
  "used_research_report": true,
  "used_sources": true,
  "source_artifacts": [
    "angle_pack.json",
    "master_outline.md",
    "research_report.md",
    "sources.json"
  ],
  "platform": "wechat",
  "title_count": 3,
  "source_note_count": 2,
  "article_length": 965
}
```

## Key Output Paths

- `outputs/runs/run_20260518T105614Z/wechat/article.md`
- `outputs/runs/run_20260518T105614Z/wechat/title_options.json`
- `outputs/runs/run_20260518T105614Z/logs/tasks/wechat_article.json`
- `outputs/runs/run_20260518T105632Z/wechat/article.md`
- `outputs/runs/run_20260518T105632Z/wechat/title_options.json`
- `outputs/runs/run_20260518T105632Z/logs/tasks/wechat_article.json`

## Known Limits

- `wechat-article-agent` is local and structured; it does not call an LLM yet.
- `sources.json` still contains a source plan, not fetched external references.
- It does not publish, upload assets, refresh cookies, or open a browser.
- Video platform output agents still use template fallback.
