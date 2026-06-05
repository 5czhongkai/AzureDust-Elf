# Content Agent OS V0 搭建方案

## 1. 建设目标

搭建一套内容创作自动化系统的基础骨架，用于后续实现多 agent 协作生产：

- 微信公众号文章
- 小红书内容
- 抖音短视频脚本与素材包
- 视频号短视频脚本与素材包
- B站长视频脚本与素材包

系统采用“工作流编排 + 专家 agent”的方式。总控统一，通用能力模块化，平台差异插件化。

## 2. 设计原则

### 2.1 一个总控，不做多套系统

每个平台不单独配置一套完整系统，而是在同一个 Agent OS 中配置不同平台产出 Agent。

```text
共享层：研究、选题、资料、素材、事实核查、风格控制
差异层：公众号长文、小红书笔记、抖音短视频、视频号短视频、B站长视频
```

### 2.2 Workflow 管边界，Agent 管认知

工作流负责任务顺序、状态、重试、验收和恢复。Agent 负责具体的研究、写作、改写、核查、修复。

### 2.3 所有中间产物必须落盘

每一次运行都必须保留：

- 输入 brief
- research report
- sources
- master outline
- 平台产物
- validator report
- repair log
- final export

这样系统可以复盘、重跑和修复。

### 2.4 发布前人工确认

V0 不做自动发布。后续即使接入发布，也必须经过人工审批。

需要审批的动作：

- 平台登录
- cookie 刷新
- 发布内容
- 批量互动
- 使用未经确认版权的素材
- 涉及法律、金融、医疗等高风险主题的最终发布

## 3. 总体架构

```text
Content Agent OS
  ├── Global Orchestrator
  ├── Agent Registry
  ├── Workflow Engine
  ├── Skill Runtime
  ├── Task Ledger
  ├── Artifact Store
  ├── Validator Layer
  ├── Repair Layer
  ├── Human Approval Gate
  └── Platform Plugins
```

### 3.1 Global Orchestrator

总控 Agent 是唯一的全局负责人。

职责：

- 理解用户目标
- 生成 workflow run
- 拆分 TaskSpec
- 查询 Agent Registry
- 向 worker agent 分配任务
- 监控运行状态
- 验收输出
- 对失败进行分类
- 调用 repair-agent 修复
- 请求人工确认
- 输出最终内容包
- 写入运行复盘

总控不直接承担所有写作，而是负责“计划、派发、监督、修复、收口”。

### 3.2 Agent Registry

注册所有 agent 的能力、输入、输出、权限和适用场景。

V0 已提供：

- `registry/agent_registry.yaml`
- `registry/plugin_registry.yaml`

### 3.3 Platform Plugins

每个平台插件包含：

- manifest
- prompts
- templates
- validators
- output schema

V0 平台插件：

- `plugins/wechat`
- `plugins/xiaohongshu`
- `plugins/douyin`
- `plugins/shipinhao`
- `plugins/bilibili`

## 4. Agent 分层

### 4.1 通用专家 Agent

```text
research-agent       资料检索、来源整理、竞品分析
topic-agent          选题池、内容角度、受众痛点
outline-agent        总体大纲、内容结构、视频分镜框架
style-agent          账号语气、人设、表达一致性
asset-agent          图片、截图、封面提示词、素材包
fact-check-agent     数据、引用、政策、事实核查
compliance-agent     平台规则、敏感风险、版权风险
validator-agent      schema、质量、完整性验收
repair-agent         失败诊断、修复建议、重跑策略
```

### 4.2 平台产出 Agent

```text
wechat-article-agent       微信公众号长文
xiaohongshu-note-agent     小红书笔记
douyin-video-agent         抖音短视频脚本
shipinhao-video-agent      视频号短视频脚本
bilibili-video-agent       B站长视频脚本
```

## 5. 工作流状态机

```text
PENDING
ASSIGNED
RUNNING
VALIDATING
PASSED
FAILED
REPAIRING
NEEDS_HUMAN
DONE
ARCHIVED
```

失败分类：

```text
ENV_ERROR          环境、依赖、浏览器、cookie
DATA_ERROR         抓取失败、来源不足、素材缺失
SCHEMA_ERROR       输出格式不合法
QUALITY_ERROR      内容空泛、不符合平台风格
POLICY_ERROR       敏感、版权、事实风险
PERMISSION_ERROR   需要人工登录或确认发布
```

## 6. V0 工作流

`workflows/one_topic_multi_platform.yaml` 是 V0 主示例：

```text
input brief
  -> research-agent
  -> topic-agent
  -> outline-agent
  -> parallel platform agents
  -> fact-check-agent
  -> compliance-agent
  -> validator-agent
  -> export
```

V0 不调用真实模型。后续 V1 会把每个 workflow step 绑定到 OpenAI Agents SDK 或 LangGraph node。

## 7. 数据契约

系统的核心对象：

- `TaskSpec`: 总控下发给 worker agent 的任务包
- `AgentManifest`: 每个 agent 的能力说明
- `PluginManifest`: 平台插件说明
- `Workflow`: 工作流定义
- `WorkflowRun`: 一次实际运行的状态记录
- `ArtifactManifest`: 运行产物索引

对应文件在 `schemas/` 目录下。

平台输出 schema：

- `schemas/platform_outputs/wechat_article.schema.json`
- `schemas/platform_outputs/xiaohongshu_note.schema.json`
- `schemas/platform_outputs/video_package.schema.json`
- `schemas/content_package.schema.json`

## 8. 运行和部署

V0 本地命令：

```bash
make validate
make run-demo TOPIC="AI内容创作自动化系统"
```

后续 Docker Compose 目标形态：

```text
api          FastAPI 控制接口
worker       agent 执行器
scheduler    监督、重试、定时任务
db           Postgres 或 SQLite
redis        队列
browser      Playwright 浏览器运行环境
webui        本地控制台
```

V0 的 `docker-compose.yml` 先提供服务占位，避免过早绑定具体实现。

## 9. 里程碑

### V0: 骨架

- 目录结构
- 方案文档
- schema
- registry
- 示例 workflow
- 校验脚本

### V1: 最小闭环

- 输入主题
- 调用模型生成 research、outline、五平台初稿
- 输出内容包
- validator 进行基础检查

### V2: 监督与修复

- task ledger
- workflow resume
- failure classification
- repair-agent
- retry policy

### V3: 素材与视频

- 封面提示词
- 图片生成/采集接口
- 视频分镜
- 旁白稿
- 字幕稿
- 剪辑工具接口预留

### V4: 控制台与部署

- Web UI
- Docker Compose 完整部署
- 多设备同步
- 运行历史查询

## 10. V0 验收标准

V0 完成时必须满足：

- 当前目录存在清晰项目骨架
- 有完整方案文档
- 有 agent registry 和 plugin registry
- 有五个平台插件
- 有五个平台产出 agent
- 有核心 JSON Schema
- 有一条一题多平台示例 workflow
- `make validate` 能通过
- `make run-demo TOPIC="..."` 能生成 demo run 文件
