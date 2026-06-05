# V1 Step 8 Completion Audit

Date: 2026-05-19

## Objective

统一视频号 agent 命名为 `shipinhao-video-agent`，并把它纳入默认 workflow 与默认平台列表，保持 `shipinhao/` 输出契约不变。

## Success Criteria

- `shipinhao-video-agent` 被加入 agent registry。
- `run_agent(task_spec)` 能把 `shipinhao-video-agent` 路由到既有视频号 handler。
- `plugins/shipinhao/manifest.yaml` 声明 `shipinhao-video-agent`。
- `workflows/one_topic_multi_platform.yaml` 包含 `shipinhao_video` 这个默认平台步骤。
- `runner.py` 和 `cli.py` 的默认平台列表包含 `shipinhao`。
- `outline-agent` 的 handoffs 列表包含 `shipinhao-video-agent`。
- `make validate` 通过。
- 视频号内容仍写入 `shipinhao/` 目录，不改变现有输出契约。
- 现有 workflow 仍可正常运行，不影响其他平台输出。

## Prompt-to-Artifact Checklist

| Requirement | Evidence | Verification |
| --- | --- | --- |
| 视频号 canonical agent | `agents/platform/shipinhao-video-agent/manifest.yaml` | New manifest exists and matches platform agent schema |
| `run_agent` 路由到视频号 handler | `src/content_agent_os/agents.py` | `shipinhao-video-agent` is included in the video-channel handler set |
| Agent registry 更新 | `registry/agent_registry.yaml` | Registry contains `shipinhao-video-agent` |
| 默认 workflow 更新 | `workflows/one_topic_multi_platform.yaml` | Workflow includes the `shipinhao_video` step |
| 默认平台列表更新 | `src/content_agent_os/runner.py`, `src/content_agent_os/cli.py` | Default platforms include `shipinhao` |
| 插件清单更新 | `plugins/shipinhao/manifest.yaml` | Plugin lists `shipinhao-video-agent` |
| 总控 handoff 更新 | `agents/common/outline-agent/manifest.yaml` | Handoffs include `shipinhao-video-agent` |
| 验证脚本更新 | `scripts/validate_v0.py` | Required paths and required agents include the canonical agent |

## Verification Commands

```bash
python3 scripts/validate_v0.py
PYTHONPATH=src python3 -c "from content_agent_os.agents import supports_agent; print(supports_agent('shipinhao-video-agent'))"
PYTHONPATH=src python3 -c "from content_agent_os.runner import DEFAULT_PLATFORMS; print('shipinhao' in DEFAULT_PLATFORMS)"
```

## Key Output Paths

- `agents/platform/shipinhao-video-agent/manifest.yaml`
- `workflows/one_topic_multi_platform.yaml`
- `registry/agent_registry.yaml`
- `plugins/shipinhao/manifest.yaml`
- `agents/common/outline-agent/manifest.yaml`
- `src/content_agent_os/runner.py`
- `src/content_agent_os/cli.py`

## Known Limits

- `shipinhao-video-agent` is the canonical entry that reuses the existing视频号输出契约.
- It does not change publishing, upload, or login behavior.
