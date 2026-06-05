# V1 Step 4 Completion Audit

Date: 2026-05-18

## Objective

实现 V1 第四步：接入第一个平台产出 agent，优先实现 `xiaohongshu-note-agent`，让 `xiaohongshu/note.json` 和 `xiaohongshu/cover_prompt.md` 从 `angle_pack.json` 与 `master_outline.md` 派生，而不是继续使用 runner 模板 fallback。

## Success Criteria

- `xiaohongshu-note-agent` 被加入可执行 agent 列表。
- `run_agent(task_spec)` 能路由到 `xiaohongshu-note-agent` handler。
- `xiaohongshu-note-agent` 读取 `angle_pack.json`。
- `xiaohongshu-note-agent` 读取 `master_outline.md`。
- `xiaohongshu-note-agent` 生成 `xiaohongshu/note.json`。
- `xiaohongshu-note-agent` 生成 `xiaohongshu/cover_prompt.md`。
- `xiaohongshu/note.json` 包含标题、正文、标签、封面提示词、建议发布时间、CTA、人工审核标记。
- 小红书标签包含 `#AI生成内容`。
- 当平台包含 `xiaohongshu` 时，`validate-run` 会拒绝任何 `xiaohongshu_note` 不是 `agent-local` 的 run。
- 全平台 workflow 仍能完成。
- 小红书单平台 workflow 仍能完成，并继续正确跳过未选平台。
- 不触发模型调用、登录、cookie 刷新、上传或发布。

## Prompt-to-Artifact Checklist

| Requirement | Evidence | Verification |
| --- | --- | --- |
| 接入 `xiaohongshu-note-agent` | `src/content_agent_os/agents.py` | `SUPPORTED_AGENTS` includes `xiaohongshu-note-agent` |
| `run_agent` 路由到 xhs handler | `src/content_agent_os/agents.py` | `run_agent` calls `_run_xiaohongshu_note_agent` |
| 从角度包和大纲生成小红书笔记 | `src/content_agent_os/agents.py` | Handler reads `angle_pack.json` and `master_outline.md` |
| 输出小红书文件 | `src/content_agent_os/agents.py` | Handler returns `xiaohongshu/note.json` and `xiaohongshu/cover_prompt.md` |
| 验证器覆盖 xhs 平台 agent | `scripts/validate_run.py` | Requires `xiaohongshu_note` to be `agent-local` when selected |
| 验证小红书输出约束 | `scripts/validate_run.py` | Checks title, content, 5-8 tags, `#AI生成内容`, review flag, cover prompt |
| 文档更新 | `docs/RUNBOOK.md`, `docs/IMPLEMENTATION_ROADMAP.md` | Describes V1 step 4 behavior |

## Verification Commands

### Static validation

```bash
python3 -m py_compile src/content_agent_os/cli.py src/content_agent_os/workflow.py src/content_agent_os/runner.py src/content_agent_os/agents.py scripts/validate_v0.py scripts/validate_run.py
make validate
```

Result:

```text
Checked 34 required paths, 14 agents, 4 plugins.
V0 project skeleton validation passed.
```

### Regression guard

Validated that an older Step 3 run is rejected because it still used template mode for `xiaohongshu_note`.

```bash
make validate-run RUN_ID="run_20260518T102313Z"
```

Result:

```text
ValueError: xiaohongshu_note must run through run_agent(task_spec); got 'template'
```

### Full multi-platform run

```bash
make run TOPIC="AI内容创作自动化系统"
make validate-run RUN_ID="run_20260518T104219Z"
```

Result:

```text
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T104219Z
Tasks: 10
Artifacts: 17
Agent-local steps: research, topic_angles, master_outline, xiaohongshu_note
```

Execution evidence:

```text
research: PASSED, agent-local
topic_angles: PASSED, agent-local
master_outline: PASSED, agent-local
wechat_article: PASSED, template
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
xiaohongshu artifacts:
- xiaohongshu/note.json
- xiaohongshu/cover_prompt.md
```

### Xiaohongshu-only run

```bash
make run TOPIC="AI内容创作自动化系统" PLATFORMS="xiaohongshu"
make validate-run RUN_ID="run_20260518T104302Z"
```

Result:

```text
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T104302Z
Tasks: 10
Artifacts: 9
Agent-local steps: research, topic_angles, master_outline, xiaohongshu_note
```

Execution evidence:

```text
research: PASSED, agent-local
topic_angles: PASSED, agent-local
master_outline: PASSED, agent-local
xiaohongshu_note: PASSED, agent-local
fact_check: PASSED, template
compliance_check: PASSED, template
final_validation: PASSED, template
```

Package evidence:

```text
platforms: xiaohongshu
platform artifact count: 2
artifacts:
- xiaohongshu/note.json
- xiaohongshu/cover_prompt.md
```

Xiaohongshu note evidence:

```text
title: AI内容创作自动化
title_length: 9
tag_count: 6
required tag: #AI生成内容
content_length: 347
review_required: true
```

Task log metadata:

```json
{
  "execution_mode": "agent-local",
  "agent_interface": "run_agent(task_spec)",
  "used_angle_pack": true,
  "used_master_outline": true,
  "source_artifacts": [
    "angle_pack.json",
    "master_outline.md"
  ],
  "platform": "xiaohongshu",
  "tag_count": 6,
  "title_length": 9
}
```

## Key Output Paths

- `outputs/runs/run_20260518T104219Z/xiaohongshu/note.json`
- `outputs/runs/run_20260518T104219Z/xiaohongshu/cover_prompt.md`
- `outputs/runs/run_20260518T104219Z/logs/tasks/xiaohongshu_note.json`
- `outputs/runs/run_20260518T104302Z/xiaohongshu/note.json`
- `outputs/runs/run_20260518T104302Z/xiaohongshu/cover_prompt.md`
- `outputs/runs/run_20260518T104302Z/logs/tasks/xiaohongshu_note.json`

## Known Limits

- `xiaohongshu-note-agent` is local and structured; it does not call an LLM yet.
- It does not publish, upload images, refresh cookies, or open a browser.
- Other platform output agents still use template fallback.
