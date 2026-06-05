# V1 Step 7 Completion Audit

Date: 2026-05-18

## Objective

实现 V1 第七步：接入第四个平台产出 agent，实现 `bilibili-video-agent`，让 `bilibili/script.md`、`bilibili/chapters.json` 和 `bilibili/description.md` 从 `angle_pack.json`、`master_outline.md` 与 `research_report.md` 派生，而不是继续使用 runner 模板 fallback。

## Success Criteria

- `bilibili-video-agent` 被加入可执行 agent 列表。
- `run_agent(task_spec)` 能路由到 `bilibili-video-agent` handler。
- `bilibili-video-agent` 读取 `angle_pack.json`。
- `bilibili-video-agent` 读取 `master_outline.md`。
- `bilibili-video-agent` 读取 `research_report.md`。
- `bilibili-video-agent` 生成 `bilibili/script.md`。
- `bilibili-video-agent` 生成 `bilibili/chapters.json`。
- `bilibili-video-agent` 生成 `bilibili/description.md`。
- `bilibili/script.md` 包含标题备选、开场、观众预期、章节、完整脚本、封面方向和人工审核边界。
- `bilibili/chapters.json` 包含至少 5 个章节，并从 `00:00` 开始。
- `bilibili/description.md` 包含时间轴、标签、发布前检查和人工审核标记。
- 当平台包含 `bilibili` 时，`validate-run` 会拒绝任何 `bilibili_video` 不是 `agent-local` 的 run。
- 全平台 workflow 仍能完成。
- B站单平台 workflow 仍能完成，并继续正确跳过未选平台。
- 不触发模型调用、登录、cookie 刷新、上传或发布。

## Prompt-to-Artifact Checklist

| Requirement | Evidence | Verification |
| --- | --- | --- |
| 接入 `bilibili-video-agent` | `src/content_agent_os/agents.py` | `SUPPORTED_AGENTS` includes `bilibili-video-agent` |
| `run_agent` 路由到 bilibili handler | `src/content_agent_os/agents.py` | `run_agent` calls `_run_bilibili_video_agent` |
| 从上游 artifact 生成 B站视频包 | `src/content_agent_os/agents.py` | Handler reads `angle_pack.json`, `master_outline.md`, and `research_report.md` |
| 输出 B站文件 | `src/content_agent_os/agents.py` | Handler returns `bilibili/script.md`, `bilibili/chapters.json`, and `bilibili/description.md` |
| 验证器覆盖 B站平台 agent | `scripts/validate_run.py` | Requires `bilibili_video` to be `agent-local` when selected |
| 验证 B站输出约束 | `scripts/validate_run.py` | Checks script sections, chapter count, first timestamp, description tags, no upload/publish boundary |
| 文档更新 | `docs/RUNBOOK.md`, `docs/IMPLEMENTATION_ROADMAP.md` | Describes V1 step 7 behavior |

## Verification Commands

### Static validation

```bash
python3 -m py_compile src/content_agent_os/cli.py src/content_agent_os/workflow.py src/content_agent_os/runner.py src/content_agent_os/agents.py scripts/validate_v0.py scripts/validate_run.py
make validate
```

Result:

```text
V0 validation passed.
Checked 37 required paths, 14 agents, 4 plugins.
```

### Regression guard

Validated that an older Step 6 run is rejected because it still used template mode for `bilibili_video`.

```bash
make validate-run RUN_ID="run_20260518T110334Z"
```

Result:

```text
Run validation failed: bilibili_video must run through run_agent(task_spec); got 'template'
```

### Full multi-platform run

```bash
make run TOPIC="AI内容创作自动化系统"
make validate-run RUN_ID="run_20260518T111205Z"
```

Result:

```text
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T111205Z
Tasks: 10
Artifacts: 17
Agent-local steps: research, topic_angles, master_outline, wechat_article, xiaohongshu_note, douyin_video, bilibili_video
```

Execution evidence:

```text
research: PASSED, agent-local
topic_angles: PASSED, agent-local
master_outline: PASSED, agent-local
wechat_article: PASSED, agent-local
xiaohongshu_note: PASSED, agent-local
douyin_video: PASSED, agent-local
bilibili_video: PASSED, agent-local
fact_check: PASSED, template
compliance_check: PASSED, template
final_validation: PASSED, template
```

Package evidence:

```text
platforms: wechat, xiaohongshu, douyin, bilibili
platform artifact count: 10
bilibili artifacts:
- bilibili/script.md
- bilibili/chapters.json
- bilibili/description.md
```

### Bilibili-only run

```bash
make run TOPIC="AI内容创作自动化系统" PLATFORMS="bilibili"
make validate-run RUN_ID="run_20260518T111223Z"
```

Result:

```text
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T111223Z
Tasks: 10
Artifacts: 10
Agent-local steps: research, topic_angles, master_outline, bilibili_video
```

Execution evidence:

```text
research: PASSED, agent-local
topic_angles: PASSED, agent-local
master_outline: PASSED, agent-local
bilibili_video: PASSED, agent-local
fact_check: PASSED, template
compliance_check: PASSED, template
final_validation: PASSED, template
```

Package evidence:

```text
platforms: bilibili
platform artifact count: 3
artifacts:
- bilibili/script.md
- bilibili/chapters.json
- bilibili/description.md
```

Bilibili video evidence:

```text
chapter_count: 6
first_chapter_time: 00:00
script_length: 1522
description_length: 473
hook: 从零拆解 AI内容创作自动化系统：总控 agent 如何分配内容生产任务。
```

Task log metadata:

```json
{
  "execution_mode": "agent-local",
  "agent_interface": "run_agent(task_spec)",
  "used_angle_pack": true,
  "used_master_outline": true,
  "used_research_report": true,
  "source_artifacts": [
    "angle_pack.json",
    "master_outline.md",
    "research_report.md"
  ],
  "platform": "bilibili",
  "chapter_count": 6,
  "script_length": 1522,
  "description_length": 473,
  "hook": "从零拆解 AI内容创作自动化系统：总控 agent 如何分配内容生产任务。"
}
```

## Key Output Paths

- `outputs/runs/run_20260518T111205Z/bilibili/script.md`
- `outputs/runs/run_20260518T111205Z/bilibili/chapters.json`
- `outputs/runs/run_20260518T111205Z/bilibili/description.md`
- `outputs/runs/run_20260518T111205Z/logs/tasks/bilibili_video.json`
- `outputs/runs/run_20260518T111223Z/bilibili/script.md`
- `outputs/runs/run_20260518T111223Z/bilibili/chapters.json`
- `outputs/runs/run_20260518T111223Z/bilibili/description.md`
- `outputs/runs/run_20260518T111223Z/logs/tasks/bilibili_video.json`

## Known Limits

- `bilibili-video-agent` is local and structured; it does not call an LLM yet.
- It does not generate actual video files, upload assets, refresh cookies, or publish.
- External source fetching is still not implemented; `research_report.md` remains a local source plan.
