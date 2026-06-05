# V1 Step 6 Completion Audit

Date: 2026-05-18

## Objective

实现 V1 第六步：接入第三个平台产出 agent，优先实现 `douyin-video-agent`，让 `douyin/script.md`、`douyin/storyboard.json` 和 `douyin/subtitles.srt` 从 `angle_pack.json` 与 `master_outline.md` 派生，而不是继续使用 runner 模板 fallback。

## Success Criteria

- `douyin-video-agent` 被加入可执行 agent 列表。
- `run_agent(task_spec)` 能路由到 `douyin-video-agent` handler。
- `douyin-video-agent` 读取 `angle_pack.json`。
- `douyin-video-agent` 读取 `master_outline.md`。
- `douyin-video-agent` 生成 `douyin/script.md`。
- `douyin-video-agent` 生成 `douyin/storyboard.json`。
- `douyin-video-agent` 生成 `douyin/subtitles.srt`。
- `douyin/script.md` 包含前三秒 hook、核心承诺、口播脚本、分镜清单、封面方向和素材边界。
- `douyin/storyboard.json` 包含可执行分镜，第一段必须是 3 秒 hook。
- `douyin/subtitles.srt` 字幕块数量匹配分镜数量。
- 当平台包含 `douyin` 时，`validate-run` 会拒绝任何 `douyin_video` 不是 `agent-local` 的 run。
- 全平台 workflow 仍能完成。
- 抖音单平台 workflow 仍能完成，并继续正确跳过未选平台。
- 不触发模型调用、登录、cookie 刷新、剪辑、上传或发布。

## Prompt-to-Artifact Checklist

| Requirement | Evidence | Verification |
| --- | --- | --- |
| 接入 `douyin-video-agent` | `src/content_agent_os/agents.py` | `SUPPORTED_AGENTS` includes `douyin-video-agent` |
| `run_agent` 路由到 douyin handler | `src/content_agent_os/agents.py` | `run_agent` calls `_run_douyin_video_agent` |
| 从上游 artifact 生成抖音视频包 | `src/content_agent_os/agents.py` | Handler reads `angle_pack.json` and `master_outline.md` |
| 输出抖音文件 | `src/content_agent_os/agents.py` | Handler returns `douyin/script.md`, `douyin/storyboard.json`, and `douyin/subtitles.srt` |
| 验证器覆盖抖音平台 agent | `scripts/validate_run.py` | Requires `douyin_video` to be `agent-local` when selected |
| 验证抖音输出约束 | `scripts/validate_run.py` | Checks script sections, 3-second hook, storyboard scenes, subtitles block count |
| 文档更新 | `docs/RUNBOOK.md`, `docs/IMPLEMENTATION_ROADMAP.md` | Describes V1 step 6 behavior |

## Verification Commands

### Static validation

```bash
python3 -m py_compile src/content_agent_os/cli.py src/content_agent_os/workflow.py src/content_agent_os/runner.py src/content_agent_os/agents.py scripts/validate_v0.py scripts/validate_run.py
make validate
```

Result:

```text
V0 validation passed.
Checked 36 required paths, 14 agents, 4 plugins.
```

### Regression guard

Validated that an older Step 5 run is rejected because it still used template mode for `douyin_video`.

```bash
make validate-run RUN_ID="run_20260518T105614Z"
```

Result:

```text
Run validation failed: douyin_video must run through run_agent(task_spec); got 'template'
```

### Full multi-platform run

```bash
make run TOPIC="AI内容创作自动化系统"
make validate-run RUN_ID="run_20260518T110334Z"
```

Result:

```text
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T110334Z
Tasks: 10
Artifacts: 17
Agent-local steps: research, topic_angles, master_outline, wechat_article, xiaohongshu_note, douyin_video
```

Execution evidence:

```text
research: PASSED, agent-local
topic_angles: PASSED, agent-local
master_outline: PASSED, agent-local
wechat_article: PASSED, agent-local
xiaohongshu_note: PASSED, agent-local
douyin_video: PASSED, agent-local
bilibili_video: PASSED, template
fact_check: PASSED, template
compliance_check: PASSED, template
final_validation: PASSED, template
```

Package evidence:

```text
platforms: wechat, xiaohongshu, douyin, bilibili
platform artifact count: 10
douyin artifacts:
- douyin/script.md
- douyin/storyboard.json
- douyin/subtitles.srt
```

### Douyin-only run

```bash
make run TOPIC="AI内容创作自动化系统" PLATFORMS="douyin"
make validate-run RUN_ID="run_20260518T110351Z"
```

Result:

```text
Run validation passed: /Volumes/D/自媒体内容创作/outputs/runs/run_20260518T110351Z
Tasks: 10
Artifacts: 10
Agent-local steps: research, topic_angles, master_outline, douyin_video
```

Execution evidence:

```text
research: PASSED, agent-local
topic_angles: PASSED, agent-local
master_outline: PASSED, agent-local
douyin_video: PASSED, agent-local
fact_check: PASSED, template
compliance_check: PASSED, template
final_validation: PASSED, template
```

Package evidence:

```text
platforms: douyin
platform artifact count: 3
artifacts:
- douyin/script.md
- douyin/storyboard.json
- douyin/subtitles.srt
```

Douyin video evidence:

```text
scene_count: 6
duration_seconds: 29
first_scene_duration: 3
subtitle_blocks: 6
script_length: 1123
hook: 一个选题，四个平台版本，怎么自动拆出来？
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
  "platform": "douyin",
  "scene_count": 6,
  "subtitle_blocks": 6,
  "duration_seconds": 29,
  "hook": "一个选题，四个平台版本，怎么自动拆出来？"
}
```

## Key Output Paths

- `outputs/runs/run_20260518T110334Z/douyin/script.md`
- `outputs/runs/run_20260518T110334Z/douyin/storyboard.json`
- `outputs/runs/run_20260518T110334Z/douyin/subtitles.srt`
- `outputs/runs/run_20260518T110334Z/logs/tasks/douyin_video.json`
- `outputs/runs/run_20260518T110351Z/douyin/script.md`
- `outputs/runs/run_20260518T110351Z/douyin/storyboard.json`
- `outputs/runs/run_20260518T110351Z/douyin/subtitles.srt`
- `outputs/runs/run_20260518T110351Z/logs/tasks/douyin_video.json`

## Known Limits

- `douyin-video-agent` is local and structured; it does not call an LLM yet.
- It does not generate actual video files, cut footage, upload assets, refresh cookies, or publish.
- Bilibili platform output still uses template fallback.
