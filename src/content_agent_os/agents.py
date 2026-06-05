from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifact_store import generate_artifact_store
from .asset_materialization import generate_materialized_assets
from .delivery_index import generate_delivery_index
from .edit_project import generate_edit_project
from .editor_project_mutation_sandbox import generate_editor_project_mutation_sandbox
from .editor_replacement_execution import generate_editor_replacement_execution
from .editor_replacement_instructions import generate_editor_replacement_instructions
from .editor_software_import_executor import generate_editor_software_import_executor
from .editor_software_real_runner_sandbox import generate_editor_software_real_runner_sandbox
from .editor_software_run_evidence import generate_editor_software_run_evidence
from .export_project import generate_export_project
from .external_mirror_plan import generate_external_mirror_plan
from .licensed_media_ingest import generate_licensed_media_ingest
from .licensed_media_proxy import generate_licensed_media_proxy
from .media_adapters import (
    GeneratedStoryboardFrame,
    generate_cover_image,
    generate_storyboard_frame_image,
    generate_storyboard_preview_sheet,
)
from .project_bundle import generate_project_bundle
from .subtitle_timing import align_subtitle_timeline, render_timed_subtitles_srt
from .voiceover_tts import generate_voiceover_tts
from .visual_asset_sources import resolve_visual_source


SUPPORTED_AGENTS = {
    "research-agent",
    "topic-agent",
    "outline-agent",
    "asset-agent",
    "asset-materialization-agent",
    "licensed-media-ingest-agent",
    "licensed-media-proxy-agent",
    "editor-replacement-instructions-agent",
    "editor-replacement-execution-agent",
    "editor-project-mutation-sandbox-agent",
    "editor-software-import-executor-agent",
    "editor-software-real-runner-sandbox-agent",
    "editor-software-run-evidence-agent",
    "cover-image-agent",
    "storyboard-preview-agent",
    "subtitle-timing-agent",
    "voiceover-tts-agent",
    "edit-project-agent",
    "export-project-agent",
    "project-bundle-agent",
    "delivery-index-agent",
    "artifact-store-agent",
    "external-mirror-plan-agent",
    "repair-agent",
    "wechat-article-agent",
    "xiaohongshu-note-agent",
    "douyin-video-agent",
    "shipinhao-video-agent",
    "bilibili-video-agent",
}


@dataclass(frozen=True)
class AgentExecutionContext:
    run_dir: Path
    topic: str
    platforms: list[str]
    produced_artifacts: list[dict[str, Any]]
    input_attachments: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AgentResult:
    outputs: dict[str, Any]
    metadata: dict[str, Any]
    notes: list[str]


VIDEO_PLATFORMS = {"douyin", "shipinhao", "bilibili"}


def supports_agent(agent_id: str) -> bool:
    return agent_id in SUPPORTED_AGENTS


def run_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    agent_id = str(task_spec["agent"])
    if agent_id == "research-agent":
        return _run_research_agent(task_spec, context)
    if agent_id == "topic-agent":
        return _run_topic_agent(task_spec, context)
    if agent_id == "outline-agent":
        return _run_outline_agent(task_spec, context)
    if agent_id == "asset-agent":
        return _run_asset_agent(task_spec, context)
    if agent_id == "asset-materialization-agent":
        return _run_asset_materialization_agent(task_spec, context)
    if agent_id == "licensed-media-ingest-agent":
        return _run_licensed_media_ingest_agent(task_spec, context)
    if agent_id == "licensed-media-proxy-agent":
        return _run_licensed_media_proxy_agent(task_spec, context)
    if agent_id == "editor-replacement-instructions-agent":
        return _run_editor_replacement_instructions_agent(task_spec, context)
    if agent_id == "editor-replacement-execution-agent":
        return _run_editor_replacement_execution_agent(task_spec, context)
    if agent_id == "editor-project-mutation-sandbox-agent":
        return _run_editor_project_mutation_sandbox_agent(task_spec, context)
    if agent_id == "editor-software-import-executor-agent":
        return _run_editor_software_import_executor_agent(task_spec, context)
    if agent_id == "editor-software-real-runner-sandbox-agent":
        return _run_editor_software_real_runner_sandbox_agent(task_spec, context)
    if agent_id == "editor-software-run-evidence-agent":
        return _run_editor_software_run_evidence_agent(task_spec, context)
    if agent_id == "cover-image-agent":
        return _run_cover_image_agent(task_spec, context)
    if agent_id == "storyboard-preview-agent":
        return _run_storyboard_preview_agent(task_spec, context)
    if agent_id == "subtitle-timing-agent":
        return _run_subtitle_timing_agent(task_spec, context)
    if agent_id == "voiceover-tts-agent":
        return _run_voiceover_tts_agent(task_spec, context)
    if agent_id == "edit-project-agent":
        return _run_edit_project_agent(task_spec, context)
    if agent_id == "export-project-agent":
        return _run_export_project_agent(task_spec, context)
    if agent_id == "project-bundle-agent":
        return _run_project_bundle_agent(task_spec, context)
    if agent_id == "delivery-index-agent":
        return _run_delivery_index_agent(task_spec, context)
    if agent_id == "artifact-store-agent":
        return _run_artifact_store_agent(task_spec, context)
    if agent_id == "external-mirror-plan-agent":
        return _run_external_mirror_plan_agent(task_spec, context)
    if agent_id == "repair-agent":
        return _run_repair_agent(task_spec, context)
    if agent_id == "wechat-article-agent":
        return _run_wechat_article_agent(task_spec, context)
    if agent_id == "xiaohongshu-note-agent":
        return _run_xiaohongshu_note_agent(task_spec, context)
    if agent_id == "douyin-video-agent":
        return _run_douyin_video_agent(task_spec, context)
    if agent_id == "shipinhao-video-agent":
        return _run_shipinhao_video_agent(task_spec, context)
    if agent_id == "bilibili-video-agent":
        return _run_bilibili_video_agent(task_spec, context)
    raise ValueError(f"No run_agent handler is registered for {agent_id}")


def _run_research_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    topic = context.topic.strip()
    platforms = context.platforms
    platform_labels = [_platform_label(platform) for platform in platforms]
    research_questions = [
        f"{topic} 的核心受众是谁，他们当前用什么方式完成内容生产？",
        f"{topic} 在 {', '.join(platform_labels)} 上分别需要解决什么表达差异？",
        f"{topic} 的内容生产流程中，哪些环节必须保留人工审核？",
        f"{topic} 需要哪些可验证来源，才能支撑正式发布？",
    ]
    opportunity_map = [
        {
            "platform": platform,
            "angle": _platform_research_angle(topic, platform),
            "evidence_needed": _platform_evidence_needed(platform),
        }
        for platform in platforms
    ]
    sources = {
        "topic": topic,
        "sources": [],
        "planned_sources": [
            {
                "type": "primary_or_authoritative",
                "query": f"{topic} 官方文档 案例 工作流",
                "reason": "用于补齐正式发布前的事实来源。",
            },
            {
                "type": "platform_examples",
                "query": f"{topic} 微信公众号 小红书 抖音 B站 案例",
                "reason": "用于比较不同平台的内容形态。",
            },
        ],
        "source_policy": "V1 step 2 local research-agent does not fetch external sources yet; it creates a source plan and research brief for downstream agents.",
        "review_required": True,
    }
    report = "\n".join(
        [
            "# Research Report",
            "",
            f"Topic: {topic}",
            "",
            "## Agent Summary",
            "",
            "This report was generated by `research-agent` through `run_agent(task_spec)`, not by the runner template.",
            "",
            "## Research Questions",
            "",
            *[f"- {question}" for question in research_questions],
            "",
            "## Platform Opportunity Map",
            "",
            *[
                f"- {_platform_label(item['platform'])}: {item['angle']} Evidence needed: {item['evidence_needed']}"
                for item in opportunity_map
            ],
            "",
            "## Initial Findings",
            "",
            f"- `{topic}` should be treated as one shared content idea with platform-specific packaging.",
            "- Research and outlining should be shared before platform agents branch into separate drafts.",
            "- Publication, login, upload, and cookie refresh remain outside this agent and require later human approval gates.",
            "- External sources are intentionally not fetched in this step; the next research iteration should add browser or API tools.",
            "",
            "## Handoff To Outline Agent",
            "",
            "- Use the platform opportunity map to build a reusable master outline.",
            "- Keep unsupported factual claims out of platform drafts until real sources are added.",
            "- Preserve a visible human-review requirement in downstream artifacts.",
            "",
        ]
    )
    return AgentResult(
        outputs={
            "research_report.md": report,
            "sources.json": sources,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "research_questions": research_questions,
            "external_sources_fetched": False,
        },
        notes=[
            "research-agent generated a structured research brief and source plan.",
            "No network research was performed in V1 step 2.",
        ],
    )


def _run_topic_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    topic = context.topic.strip()
    research_report_path = context.run_dir / "research_report.md"
    research_report = _read_text_if_exists(research_report_path)
    if not research_report:
        raise RuntimeError("topic-agent requires research_report.md from research-agent")

    opportunities = _extract_platform_opportunities(research_report, context.platforms)
    angles = [
        {
            "name": f"{platform}-adapted-angle",
            "platform": platform,
            "platform_label": _platform_label(platform),
            "audience": _platform_audience(platform),
            "hook": _platform_hook(topic, platform),
            "rationale": opportunities.get(platform) or _platform_research_angle(topic, platform),
            "content_promise": _platform_content_promise(topic, platform),
            "source_basis": "research_report.md",
            "review_required": True,
        }
        for platform in context.platforms
    ]
    angle_pack = {
        "topic": topic,
        "generated_by": "topic-agent",
        "agent_interface": "run_agent(task_spec)",
        "source_artifacts": ["research_report.md"],
        "used_research_report": True,
        "primary_angle": {
            "name": "shared-research-to-platform-packaging",
            "hook": f"把 `{topic}` 先做成一个共享研究与大纲，再分发给各平台 agent。",
            "audience": "自媒体创作者、内容运营、个人知识博主",
            "rationale": "Research report recommends sharing research and planning before platform-specific adaptation.",
        },
        "angles": angles,
        "handoff_to_outline": {
            "recommended_structure": [
                "creator pain",
                "unified orchestrator",
                "shared research and topic layer",
                "platform-specific adaptation",
                "human approval and validation",
            ],
            "guardrails": [
                "Do not add unsupported platform-rule claims.",
                "Keep publication actions behind human approval.",
                "Mark source gaps for later research-agent improvements.",
            ],
        },
        "review_required": True,
    }
    return AgentResult(
        outputs={"angle_pack.json": angle_pack},
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "used_research_report": True,
            "source_artifacts": ["research_report.md"],
            "angle_count": len(angles),
        },
        notes=[
            "topic-agent generated angle_pack.json from research_report.md.",
            "Angles are local structured outputs and still require human review before publication.",
        ],
    )


def _run_outline_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    topic = context.topic.strip()
    research_report = _read_text_if_exists(context.run_dir / "research_report.md")
    angle_pack = _read_json_if_exists(context.run_dir / "angle_pack.json")
    primary_angle = _primary_angle(angle_pack)
    platform_sections = [
        f"### {_platform_label(platform)}\n\n- Adaptation goal: {_platform_outline_goal(platform)}\n- Review gate: human review before publication or upload."
        for platform in context.platforms
    ]
    research_basis = "research_report.md is available" if research_report else "research_report.md is missing"
    outline = "\n".join(
        [
            "# Master Outline",
            "",
            f"Topic: {topic}",
            "",
            "## Agent Summary",
            "",
            "This outline was generated by `outline-agent` through `run_agent(task_spec)`, using available upstream artifacts.",
            "",
            "## Inputs Used",
            "",
            f"- Research basis: {research_basis}",
            f"- Primary angle: {primary_angle}",
            f"- Platforms: {', '.join(_platform_label(platform) for platform in context.platforms)}",
            "",
            "## Core Thesis",
            "",
            f"{topic} should be produced through a shared research and planning layer, then adapted by platform-specific agents.",
            "",
            "## Shared Narrative",
            "",
            "1. Start with the creator pain: one topic often needs many platform versions.",
            "2. Explain the system answer: one orchestrator controls workflow state and assigns expert agents.",
            "3. Show the modular split: research, outline, style, assets, fact-check, compliance, and platform output.",
            "4. Set the safety boundary: no automatic publishing without human approval.",
            "5. Close with the next build step: replace local agents with model-backed agents and source-aware research.",
            "",
            "## Platform Adaptation Notes",
            "",
            *platform_sections,
            "",
            "## Claims To Keep Source-Aware",
            "",
            "- Any factual claims about platform rules need authoritative sources before publishing.",
            "- Any performance or traffic claims need evidence before publishing.",
            "- Any tool or API recommendation should be checked against current documentation before publishing.",
            "",
        ]
    )
    return AgentResult(
        outputs={"master_outline.md": outline},
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "used_research_report": bool(research_report),
            "used_angle_pack": bool(angle_pack),
        },
        notes=[
            "outline-agent generated the master outline from upstream run artifacts.",
            "The outline keeps source-sensitive claims out of final platform drafts.",
        ],
    )


def _run_asset_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    topic = context.topic.strip()
    master_outline = _read_text_if_exists(context.run_dir / "master_outline.md")
    angle_pack = _read_json_if_exists(context.run_dir / "angle_pack.json")
    if not master_outline:
        raise RuntimeError("asset-agent requires master_outline.md from outline-agent")

    video_platforms = _selected_video_platforms(context.platforms)
    platform_plans = [
        _default_video_asset_plan(
            topic,
            platform,
            str(_platform_angle(angle_pack, platform).get("hook") or _platform_hook(topic, platform)),
        )
        for platform in video_platforms
    ]
    asset_plan = {
        "schema_version": "phase4.asset_plan.v1",
        "topic": topic,
        "generated_by": "asset-agent",
        "agent_interface": "run_agent(task_spec)",
        "source_artifacts": ["angle_pack.json", "master_outline.md"],
        "video_platforms": video_platforms,
        "platform_plans": platform_plans,
        "global_asset_policy": {
            "allowed_sources": [
                "self-recorded screen capture",
                "self-created UI mockups",
                "licensed stock footage with documented usage rights",
                "generated bitmap assets that pass human copyright review",
            ],
            "prohibited_sources": [
                "uncleared platform logos",
                "third-party creator footage without permission",
                "screenshots exposing private data",
                "music or sound effects without usage rights",
            ],
            "review_required": True,
        },
        "review_required": True,
    }
    asset_tasks = _build_asset_generation_tasks(topic, video_platforms, platform_plans)
    media_asset_manifest = _build_media_asset_manifest(topic, context.run_dir.name, asset_tasks)
    asset_ingest_guide = _asset_ingest_guide_markdown(topic, asset_tasks, media_asset_manifest)
    cover_lines = [
        "# Cover Prompts",
        "",
        f"Topic: {topic}",
        "",
        "These prompts are production directions only. Use cleared assets and keep human review before upload.",
        "",
    ]
    for plan in platform_plans:
        cover_lines.extend(
            [
                f"## {_platform_label(str(plan['platform']))}",
                "",
                str(plan["cover_prompt"]),
                "",
                f"- Aspect ratio: {plan['aspect_ratio']}",
                f"- Safe margin: {plan['safe_margin']}",
                "- Review note: confirm typography, copyright, and platform overlays before publishing.",
                "",
            ]
        )

    return AgentResult(
        outputs={
            "asset_plan.json": asset_plan,
            "cover_prompts.md": "\n".join(cover_lines),
            "assets/asset_generation_tasks.json": asset_tasks,
            "assets/media_asset_manifest.json": media_asset_manifest,
            "assets/asset_ingest_guide.md": asset_ingest_guide,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "used_angle_pack": isinstance(angle_pack, dict),
            "used_master_outline": True,
            "source_artifacts": ["angle_pack.json", "master_outline.md"],
            "video_platforms": video_platforms,
            "platform_plan_count": len(platform_plans),
            "asset_task_count": len(asset_tasks["tasks"]),
            "media_asset_count": len(media_asset_manifest["assets"]),
            "asset_clearance_required": True,
        },
        notes=[
            "asset-agent generated asset_plan.json, cover_prompts.md, asset_generation_tasks.json, media_asset_manifest.json, and asset_ingest_guide.md.",
            "The asset layer is a production task package only; it does not fetch, download, generate, license, or import media.",
        ],
    )


def _run_asset_materialization_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("asset-materialization-agent requires a selected video platform")

    asset_tasks = _read_json_if_exists(context.run_dir / "assets/asset_generation_tasks.json")
    broll_list = _read_json_if_exists(context.run_dir / platform / "broll_list.json")
    if not isinstance(asset_tasks, dict):
        raise RuntimeError("asset-materialization-agent requires assets/asset_generation_tasks.json")
    if not isinstance(broll_list, list):
        raise RuntimeError(f"asset-materialization-agent requires {platform}/broll_list.json")

    manifest_path = f"assets/{platform}/materials/material_manifest.json"
    readme_path = f"assets/{platform}/materials/README.md"
    generated = generate_materialized_assets(
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        asset_tasks=asset_tasks,
        broll_list=broll_list,
        manifest_path=manifest_path,
        readme_path=readme_path,
    )
    outputs: dict[str, Any] = {
        manifest_path: generated.manifest,
        readme_path: generated.readme_text,
    }
    outputs.update(generated.images)

    return AgentResult(
        outputs=outputs,
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "materialized_count": generated.manifest["summary"]["materialized_count"],
            "materialization_status": generated.manifest["validation"]["status"],
            "licensed_final_media_required": True,
            "manual_review_required": True,
        },
        notes=[
            f"asset-materialization-agent generated local B-roll reference assets for {platform}.",
            "Generated assets are review references only; no external asset search, download, import, upload, or publishing action was performed.",
        ],
    )


def _run_licensed_media_ingest_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("licensed-media-ingest-agent requires a selected video platform")

    material_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "materials" / "material_manifest.json"
    )
    human_media_registry_path = f"assets/{platform}/licensed_media/human_media_registry.json"
    human_media_registry = _read_json_if_exists(context.run_dir / human_media_registry_path)
    if not isinstance(material_manifest, dict):
        raise RuntimeError(f"licensed-media-ingest-agent requires assets/{platform}/materials/material_manifest.json")
    if not isinstance(human_media_registry, dict):
        human_media_registry = None

    manifest_path = f"assets/{platform}/licensed_media/ingest_manifest.json"
    readme_path = f"assets/{platform}/licensed_media/README.md"
    review_handoff_path = f"assets/{platform}/licensed_media/review_handoff.md"
    generated = generate_licensed_media_ingest(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        material_manifest=material_manifest,
        human_media_registry=human_media_registry,
        manifest_path=manifest_path,
        readme_path=readme_path,
        review_handoff_path=review_handoff_path,
        human_media_registry_path=human_media_registry_path,
    )

    return AgentResult(
        outputs={
            manifest_path: generated.manifest,
            readme_path: generated.readme_text,
            review_handoff_path: generated.review_handoff_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "required_final_media_count": generated.manifest["summary"]["required_final_media_count"],
            "pending_human_media_count": generated.manifest["summary"]["pending_human_media_count"],
            "candidate_media_count": generated.manifest["summary"]["candidate_media_count"],
            "ready_for_editor_replacement_count": generated.manifest["summary"]["ready_for_editor_replacement_count"],
            "licensed_media_ingest_status": generated.manifest["validation"]["status"],
            "intake_complete": generated.manifest["validation"]["intake_complete"],
            "manual_review_required": True,
        },
        notes=[
            f"licensed-media-ingest-agent generated a local review handoff for {platform}.",
            "No external media search, download, licensing purchase, upload, editing software, or publishing action was performed.",
        ],
    )


def _run_licensed_media_proxy_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("licensed-media-proxy-agent requires a selected video platform")

    licensed_media_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json"
    )
    if not isinstance(licensed_media_manifest, dict):
        raise RuntimeError(f"licensed-media-proxy-agent requires assets/{platform}/licensed_media/ingest_manifest.json")

    manifest_path = f"assets/{platform}/licensed_media/proxy_manifest.json"
    replacement_suggestions_path = f"assets/{platform}/licensed_media/replacement_suggestions.json"
    readme_path = f"assets/{platform}/licensed_media/proxy/README.md"
    proxy_dir = f"assets/{platform}/licensed_media/proxy"
    generated = generate_licensed_media_proxy(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        licensed_media_manifest=licensed_media_manifest,
        manifest_path=manifest_path,
        replacement_suggestions_path=replacement_suggestions_path,
        readme_path=readme_path,
        proxy_dir=proxy_dir,
    )

    for proxy_path, proxy_bytes in generated.proxy_files.items():
        destination = context.run_dir / proxy_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(proxy_bytes)

    return AgentResult(
        outputs={
            manifest_path: generated.manifest,
            replacement_suggestions_path: generated.replacement_suggestions,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "required_final_media_count": generated.manifest["summary"]["required_final_media_count"],
            "ready_source_media_count": generated.manifest["summary"]["ready_source_media_count"],
            "proxy_copied_count": generated.manifest["summary"]["proxy_copied_count"],
            "pending_human_media_count": generated.manifest["summary"]["pending_human_media_count"],
            "candidate_pending_review_count": generated.manifest["summary"]["candidate_pending_review_count"],
            "blocked_proxy_count": generated.manifest["summary"]["blocked_proxy_count"],
            "editor_replacement_ready_count": generated.manifest["summary"]["editor_replacement_ready_count"],
            "licensed_media_proxy_status": generated.manifest["validation"]["status"],
            "proxy_copy_complete_for_ready_media": generated.manifest["validation"]["proxy_copy_complete_for_ready_media"],
            "manual_review_required": True,
        },
        notes=[
            f"licensed-media-proxy-agent generated replacement suggestions for {platform}.",
            "Only local human-registered media that is approved for edit is copied to proxy; no external search, download, license purchase, upload, editing software, or publishing action was performed.",
        ],
    )


def _run_editor_replacement_instructions_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("editor-replacement-instructions-agent requires a selected video platform")

    replacement_suggestions = _read_json_if_exists(
        context.run_dir / "assets" / platform / "licensed_media" / "replacement_suggestions.json"
    )
    proxy_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json"
    )
    edit_timeline = _read_json_if_exists(context.run_dir / "assets" / platform / "edit" / "edit_timeline.json")
    offline_report = _read_json_if_exists(context.run_dir / "assets" / platform / "edit" / "offline_media_report.json")
    export_manifest = _read_json_if_exists(context.run_dir / "assets" / platform / "edit" / "export_manifest.json")
    if not isinstance(replacement_suggestions, dict):
        raise RuntimeError(
            f"editor-replacement-instructions-agent requires assets/{platform}/licensed_media/replacement_suggestions.json"
        )
    if not isinstance(proxy_manifest, dict):
        raise RuntimeError(f"editor-replacement-instructions-agent requires assets/{platform}/licensed_media/proxy_manifest.json")
    if not isinstance(edit_timeline, dict):
        raise RuntimeError(f"editor-replacement-instructions-agent requires assets/{platform}/edit/edit_timeline.json")
    if not isinstance(offline_report, dict):
        raise RuntimeError(f"editor-replacement-instructions-agent requires assets/{platform}/edit/offline_media_report.json")
    if not isinstance(export_manifest, dict):
        raise RuntimeError(f"editor-replacement-instructions-agent requires assets/{platform}/edit/export_manifest.json")

    base_dir = f"assets/{platform}/edit/replacement_instructions"
    manifest_path = f"{base_dir}/instruction_manifest.json"
    commands_path = f"{base_dir}/replacement_commands.json"
    import_template_path = f"{base_dir}/editor_import_template.fcpxml"
    checklist_path = f"{base_dir}/human_confirmation_checklist.md"
    readme_path = f"{base_dir}/README.md"
    generated = generate_editor_replacement_instructions(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        replacement_suggestions=replacement_suggestions,
        proxy_manifest=proxy_manifest,
        edit_timeline=edit_timeline,
        offline_report=offline_report,
        export_manifest=export_manifest,
        manifest_path=manifest_path,
        commands_path=commands_path,
        import_template_path=import_template_path,
        checklist_path=checklist_path,
        readme_path=readme_path,
    )

    return AgentResult(
        outputs={
            manifest_path: generated.manifest,
            commands_path: generated.replacement_commands,
            import_template_path: generated.import_template_fcpxml,
            checklist_path: generated.confirmation_checklist_md,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "instruction_count": generated.manifest["summary"]["instruction_count"],
            "ready_pending_human_confirmation_count": generated.manifest["summary"][
                "ready_pending_human_confirmation_count"
            ],
            "pending_human_media_count": generated.manifest["summary"]["pending_human_media_count"],
            "editor_replacement_instruction_status": generated.manifest["validation"]["status"],
            "human_confirmation_gate_active": generated.manifest["validation"]["human_confirmation_gate_active"],
            "replacement_execution_performed": generated.manifest["validation"]["replacement_execution_performed"],
            "manual_review_required": True,
            "human_confirmation_required": True,
        },
        notes=[
            f"editor-replacement-instructions-agent generated replacement import templates and dry-run commands for {platform}.",
            "No editing software was opened, no replacement was executed, and the human confirmation gate remains pending.",
        ],
    )


def _run_editor_replacement_execution_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("editor-replacement-execution-agent requires a selected video platform")

    instruction_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "replacement_instructions" / "instruction_manifest.json"
    )
    replacement_commands = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "replacement_instructions" / "replacement_commands.json"
    )
    approval_path = context.run_dir / "assets" / platform / "edit" / "replacement_execution" / "human_execution_approval.json"
    human_execution_approval = _read_json_if_exists(approval_path)
    if not isinstance(instruction_manifest, dict):
        raise RuntimeError(
            f"editor-replacement-execution-agent requires assets/{platform}/edit/replacement_instructions/instruction_manifest.json"
        )
    if not isinstance(replacement_commands, dict):
        raise RuntimeError(
            f"editor-replacement-execution-agent requires assets/{platform}/edit/replacement_instructions/replacement_commands.json"
        )
    if isinstance(human_execution_approval, dict):
        human_execution_approval = human_execution_approval | {
            "approval_path": f"assets/{platform}/edit/replacement_execution/human_execution_approval.json"
        }
    else:
        human_execution_approval = None

    base_dir = f"assets/{platform}/edit/replacement_execution"
    manifest_path = f"{base_dir}/execution_manifest.json"
    execution_plan_path = f"{base_dir}/execution_plan.json"
    audit_log_path = f"{base_dir}/execution_audit_log.json"
    approval_request_path = f"{base_dir}/human_execution_approval_request.md"
    readme_path = f"{base_dir}/README.md"
    generated = generate_editor_replacement_execution(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        instruction_manifest=instruction_manifest,
        replacement_commands=replacement_commands,
        human_execution_approval=human_execution_approval,
        manifest_path=manifest_path,
        execution_plan_path=execution_plan_path,
        audit_log_path=audit_log_path,
        approval_request_path=approval_request_path,
        readme_path=readme_path,
    )

    return AgentResult(
        outputs={
            manifest_path: generated.manifest,
            execution_plan_path: generated.execution_plan,
            audit_log_path: generated.audit_log,
            approval_request_path: generated.approval_request_md,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "command_count": generated.manifest["summary"]["command_count"],
            "blocked_pending_approval_count": generated.manifest["summary"]["blocked_pending_approval_count"],
            "executable_after_approval_count": generated.manifest["summary"]["executable_after_approval_count"],
            "editor_replacement_execution_status": generated.manifest["validation"]["status"],
            "human_execution_approval_required": generated.manifest["validation"]["human_execution_approval_required"],
            "human_execution_approval_present": generated.manifest["validation"]["human_execution_approval_present"],
            "human_execution_approval_valid": generated.manifest["validation"]["human_execution_approval_valid"],
            "replacement_execution_performed": generated.manifest["validation"]["replacement_execution_performed"],
            "editing_software_opened": generated.manifest["validation"]["editing_software_opened"],
            "project_file_mutation_performed": generated.manifest["validation"]["project_file_mutation_performed"],
            "manual_review_required": True,
        },
        notes=[
            f"editor-replacement-execution-agent generated an auditable execution adapter plan for {platform}.",
            "No editing software was opened, no project file was mutated, and no replacement was executed without explicit human approval.",
        ],
    )


def _run_editor_project_mutation_sandbox_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("editor-project-mutation-sandbox-agent requires a selected video platform")

    execution_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "replacement_execution" / "execution_manifest.json"
    )
    execution_plan = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "replacement_execution" / "execution_plan.json"
    )
    export_manifest = _read_json_if_exists(context.run_dir / "assets" / platform / "edit" / "export_manifest.json")
    edit_timeline = _read_json_if_exists(context.run_dir / "assets" / platform / "edit" / "edit_timeline.json")
    source_project_text = _read_text_if_exists(context.run_dir / "assets" / platform / "edit" / "project.fcpxml")
    approval_path = context.run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "human_mutation_approval.json"
    human_mutation_approval = _read_json_if_exists(approval_path)
    if not isinstance(execution_manifest, dict):
        raise RuntimeError(
            f"editor-project-mutation-sandbox-agent requires assets/{platform}/edit/replacement_execution/execution_manifest.json"
        )
    if not isinstance(execution_plan, dict):
        raise RuntimeError(
            f"editor-project-mutation-sandbox-agent requires assets/{platform}/edit/replacement_execution/execution_plan.json"
        )
    if not isinstance(export_manifest, dict):
        raise RuntimeError(f"editor-project-mutation-sandbox-agent requires assets/{platform}/edit/export_manifest.json")
    if not isinstance(edit_timeline, dict):
        raise RuntimeError(f"editor-project-mutation-sandbox-agent requires assets/{platform}/edit/edit_timeline.json")
    if not source_project_text:
        raise RuntimeError(f"editor-project-mutation-sandbox-agent requires assets/{platform}/edit/project.fcpxml")
    if isinstance(human_mutation_approval, dict):
        human_mutation_approval = human_mutation_approval | {
            "approval_path": f"assets/{platform}/edit/mutation_sandbox/human_mutation_approval.json"
        }
    else:
        human_mutation_approval = None

    base_dir = f"assets/{platform}/edit/mutation_sandbox"
    manifest_path = f"{base_dir}/mutation_manifest.json"
    patched_project_path = f"{base_dir}/patched_project.fcpxml"
    mutation_diff_path = f"{base_dir}/mutation_diff.json"
    rollback_manifest_path = f"{base_dir}/rollback_manifest.json"
    audit_log_path = f"{base_dir}/mutation_audit_log.json"
    final_review_checklist_path = f"{base_dir}/human_final_review_checklist.md"
    readme_path = f"{base_dir}/README.md"
    generated = generate_editor_project_mutation_sandbox(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        execution_manifest=execution_manifest,
        execution_plan=execution_plan,
        export_manifest=export_manifest,
        edit_timeline=edit_timeline,
        source_project_text=source_project_text,
        human_mutation_approval=human_mutation_approval,
        manifest_path=manifest_path,
        patched_project_path=patched_project_path,
        mutation_diff_path=mutation_diff_path,
        rollback_manifest_path=rollback_manifest_path,
        audit_log_path=audit_log_path,
        final_review_checklist_path=final_review_checklist_path,
        readme_path=readme_path,
    )

    return AgentResult(
        outputs={
            manifest_path: generated.manifest,
            patched_project_path: generated.patched_project_text,
            mutation_diff_path: generated.mutation_diff,
            rollback_manifest_path: generated.rollback_manifest,
            audit_log_path: generated.audit_log,
            final_review_checklist_path: generated.final_review_checklist_md,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "execution_item_count": generated.manifest["summary"]["execution_item_count"],
            "mutation_applied_count": generated.manifest["summary"]["mutation_applied_count"],
            "blocked_mutation_count": generated.manifest["summary"]["blocked_mutation_count"],
            "editor_project_mutation_status": generated.manifest["validation"]["status"],
            "human_mutation_approval_required": generated.manifest["validation"]["human_mutation_approval_required"],
            "human_mutation_approval_present": generated.manifest["validation"]["human_mutation_approval_present"],
            "human_mutation_approval_valid": generated.manifest["validation"]["human_mutation_approval_valid"],
            "original_project_mutated": generated.manifest["validation"]["original_project_mutated"],
            "patched_copy_generated": generated.manifest["validation"]["patched_copy_generated"],
            "editing_software_opened": generated.manifest["validation"]["editing_software_opened"],
            "replacement_execution_performed": generated.manifest["validation"]["replacement_execution_performed"],
            "manual_review_required": True,
        },
        notes=[
            f"editor-project-mutation-sandbox-agent generated a patched FCPXML sandbox copy for {platform}.",
            "The original project was not mutated, no editing software was opened, and no upload or publishing action was performed.",
        ],
    )


def _run_editor_software_import_executor_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("editor-software-import-executor-agent requires a selected video platform")

    mutation_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "mutation_manifest.json"
    )
    mutation_diff = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "mutation_diff.json"
    )
    rollback_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "rollback_manifest.json"
    )
    patched_project_text = _read_text_if_exists(
        context.run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "patched_project.fcpxml"
    )
    approval_path = (
        context.run_dir
        / "assets"
        / platform
        / "edit"
        / "software_import_executor"
        / "human_software_import_approval.json"
    )
    human_software_import_approval = _read_json_if_exists(approval_path)
    if not isinstance(mutation_manifest, dict):
        raise RuntimeError(
            f"editor-software-import-executor-agent requires assets/{platform}/edit/mutation_sandbox/mutation_manifest.json"
        )
    if not isinstance(mutation_diff, dict):
        raise RuntimeError(
            f"editor-software-import-executor-agent requires assets/{platform}/edit/mutation_sandbox/mutation_diff.json"
        )
    if not isinstance(rollback_manifest, dict):
        raise RuntimeError(
            f"editor-software-import-executor-agent requires assets/{platform}/edit/mutation_sandbox/rollback_manifest.json"
        )
    if not patched_project_text:
        raise RuntimeError(
            f"editor-software-import-executor-agent requires assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml"
        )
    if isinstance(human_software_import_approval, dict):
        human_software_import_approval = human_software_import_approval | {
            "approval_path": f"assets/{platform}/edit/software_import_executor/human_software_import_approval.json"
        }
    else:
        human_software_import_approval = None

    base_dir = f"assets/{platform}/edit/software_import_executor"
    manifest_path = f"{base_dir}/import_executor_manifest.json"
    import_plan_path = f"{base_dir}/import_plan.json"
    import_commands_path = f"{base_dir}/import_commands.json"
    audit_log_path = f"{base_dir}/software_import_audit_log.json"
    rollback_safety_report_path = f"{base_dir}/rollback_safety_report.json"
    execution_request_path = f"{base_dir}/isolated_execution_request.md"
    readme_path = f"{base_dir}/README.md"
    generated = generate_editor_software_import_executor(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        mutation_manifest=mutation_manifest,
        mutation_diff=mutation_diff,
        rollback_manifest=rollback_manifest,
        patched_project_text=patched_project_text,
        human_software_import_approval=human_software_import_approval,
        manifest_path=manifest_path,
        import_plan_path=import_plan_path,
        import_commands_path=import_commands_path,
        audit_log_path=audit_log_path,
        rollback_safety_report_path=rollback_safety_report_path,
        execution_request_path=execution_request_path,
        readme_path=readme_path,
    )

    return AgentResult(
        outputs={
            manifest_path: generated.manifest,
            import_plan_path: generated.import_plan,
            import_commands_path: generated.import_commands,
            audit_log_path: generated.audit_log,
            rollback_safety_report_path: generated.rollback_safety_report,
            execution_request_path: generated.execution_request_md,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "import_item_count": generated.manifest["summary"]["import_item_count"],
            "ready_for_isolated_manual_import_count": generated.manifest["summary"][
                "ready_for_isolated_manual_import_count"
            ],
            "blocked_import_count": generated.manifest["summary"]["blocked_import_count"],
            "editor_software_import_status": generated.manifest["validation"]["status"],
            "human_software_import_approval_required": generated.manifest["validation"][
                "human_software_import_approval_required"
            ],
            "human_software_import_approval_present": generated.manifest["validation"][
                "human_software_import_approval_present"
            ],
            "human_software_import_approval_valid": generated.manifest["validation"][
                "human_software_import_approval_valid"
            ],
            "software_import_execution_performed": generated.manifest["validation"][
                "software_import_execution_performed"
            ],
            "editing_software_opened": generated.manifest["validation"]["editing_software_opened"],
            "project_file_mutation_performed": generated.manifest["validation"][
                "project_file_mutation_performed"
            ],
            "manual_review_required": True,
        },
        notes=[
            f"editor-software-import-executor-agent generated an isolated import executor package for {platform}.",
            "No editing software was opened, no import was executed, and no project file was mutated.",
        ],
    )


def _run_editor_software_real_runner_sandbox_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("editor-software-real-runner-sandbox-agent requires a selected video platform")

    import_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "software_import_executor" / "import_executor_manifest.json"
    )
    import_plan = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "software_import_executor" / "import_plan.json"
    )
    import_commands = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "software_import_executor" / "import_commands.json"
    )
    rollback_safety_report = _read_json_if_exists(
        context.run_dir
        / "assets"
        / platform
        / "edit"
        / "software_import_executor"
        / "rollback_safety_report.json"
    )
    approval_path = (
        context.run_dir
        / "assets"
        / platform
        / "edit"
        / "software_real_runner_sandbox"
        / "human_real_run_approval.json"
    )
    human_real_run_approval = _read_json_if_exists(approval_path)
    if not isinstance(import_manifest, dict):
        raise RuntimeError(
            f"editor-software-real-runner-sandbox-agent requires assets/{platform}/edit/software_import_executor/import_executor_manifest.json"
        )
    if not isinstance(import_plan, dict):
        raise RuntimeError(
            f"editor-software-real-runner-sandbox-agent requires assets/{platform}/edit/software_import_executor/import_plan.json"
        )
    if not isinstance(import_commands, dict):
        raise RuntimeError(
            f"editor-software-real-runner-sandbox-agent requires assets/{platform}/edit/software_import_executor/import_commands.json"
        )
    if not isinstance(rollback_safety_report, dict):
        raise RuntimeError(
            f"editor-software-real-runner-sandbox-agent requires assets/{platform}/edit/software_import_executor/rollback_safety_report.json"
        )
    if isinstance(human_real_run_approval, dict):
        human_real_run_approval = human_real_run_approval | {
            "approval_path": f"assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval.json"
        }
    else:
        human_real_run_approval = None

    base_dir = f"assets/{platform}/edit/software_real_runner_sandbox"
    manifest_path = f"{base_dir}/runner_sandbox_manifest.json"
    environment_snapshot_path = f"{base_dir}/runner_environment_snapshot.json"
    launch_plan_path = f"{base_dir}/runner_launch_plan.json"
    command_preview_path = f"{base_dir}/runner_command_preview.json"
    audit_log_path = f"{base_dir}/runner_audit_log.json"
    evidence_manifest_path = f"{base_dir}/runner_evidence_manifest.json"
    approval_request_path = f"{base_dir}/human_real_run_approval_request.md"
    readme_path = f"{base_dir}/README.md"
    generated = generate_editor_software_real_runner_sandbox(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        import_manifest=import_manifest,
        import_plan=import_plan,
        import_commands=import_commands,
        rollback_safety_report=rollback_safety_report,
        human_real_run_approval=human_real_run_approval,
        manifest_path=manifest_path,
        environment_snapshot_path=environment_snapshot_path,
        launch_plan_path=launch_plan_path,
        command_preview_path=command_preview_path,
        audit_log_path=audit_log_path,
        evidence_manifest_path=evidence_manifest_path,
        approval_request_path=approval_request_path,
        readme_path=readme_path,
    )

    return AgentResult(
        outputs={
            manifest_path: generated.manifest,
            environment_snapshot_path: generated.environment_snapshot,
            launch_plan_path: generated.launch_plan,
            command_preview_path: generated.command_preview,
            audit_log_path: generated.audit_log,
            evidence_manifest_path: generated.evidence_manifest,
            approval_request_path: generated.approval_request_md,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "runner_item_count": generated.manifest["summary"]["runner_item_count"],
            "ready_for_manual_external_sandbox_launch_count": generated.manifest["summary"][
                "ready_for_manual_external_sandbox_launch_count"
            ],
            "blocked_runner_count": generated.manifest["summary"]["blocked_runner_count"],
            "editor_software_real_runner_status": generated.manifest["validation"]["status"],
            "human_real_run_approval_required": generated.manifest["validation"][
                "human_real_run_approval_required"
            ],
            "human_real_run_approval_present": generated.manifest["validation"]["human_real_run_approval_present"],
            "human_real_run_approval_valid": generated.manifest["validation"]["human_real_run_approval_valid"],
            "real_software_launch_performed": generated.manifest["validation"]["real_software_launch_performed"],
            "software_import_execution_performed": generated.manifest["validation"][
                "software_import_execution_performed"
            ],
            "editing_software_opened": generated.manifest["validation"]["editing_software_opened"],
            "project_file_mutation_performed": generated.manifest["validation"][
                "project_file_mutation_performed"
            ],
            "process_spawned": generated.manifest["validation"]["process_spawned"],
            "manual_review_required": True,
        },
        notes=[
            f"editor-software-real-runner-sandbox-agent generated a real-runner sandbox package for {platform}.",
            "No editing software was opened, no process was spawned, no import was executed, and no project file was mutated.",
        ],
    )


def _run_editor_software_run_evidence_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("editor-software-run-evidence-agent requires a selected video platform")

    base_runner_dir = context.run_dir / "assets" / platform / "edit" / "software_real_runner_sandbox"
    runner_manifest = _read_json_if_exists(base_runner_dir / "runner_sandbox_manifest.json")
    launch_plan = _read_json_if_exists(base_runner_dir / "runner_launch_plan.json")
    command_preview = _read_json_if_exists(base_runner_dir / "runner_command_preview.json")
    runner_evidence_manifest = _read_json_if_exists(base_runner_dir / "runner_evidence_manifest.json")
    result_path = context.run_dir / "assets" / platform / "edit" / "software_run_evidence" / "human_real_run_result.json"
    human_real_run_result = _read_json_if_exists(result_path)
    if not isinstance(runner_manifest, dict):
        raise RuntimeError(
            f"editor-software-run-evidence-agent requires assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json"
        )
    if not isinstance(launch_plan, dict):
        raise RuntimeError(
            f"editor-software-run-evidence-agent requires assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json"
        )
    if not isinstance(command_preview, dict):
        raise RuntimeError(
            f"editor-software-run-evidence-agent requires assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json"
        )
    if not isinstance(runner_evidence_manifest, dict):
        raise RuntimeError(
            f"editor-software-run-evidence-agent requires assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json"
        )
    if isinstance(human_real_run_result, dict):
        human_real_run_result = human_real_run_result | {
            "result_path": f"assets/{platform}/edit/software_run_evidence/human_real_run_result.json"
        }
    else:
        human_real_run_result = None

    base_dir = f"assets/{platform}/edit/software_run_evidence"
    manifest_path = f"{base_dir}/real_run_evidence_manifest.json"
    validation_report_path = f"{base_dir}/evidence_validation_report.json"
    rollback_decision_report_path = f"{base_dir}/rollback_decision_report.json"
    checklist_path = f"{base_dir}/post_launch_evidence_checklist.md"
    readme_path = f"{base_dir}/README.md"
    generated = generate_editor_software_run_evidence(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        runner_manifest=runner_manifest,
        launch_plan=launch_plan,
        command_preview=command_preview,
        runner_evidence_manifest=runner_evidence_manifest,
        human_real_run_result=human_real_run_result,
        manifest_path=manifest_path,
        validation_report_path=validation_report_path,
        rollback_decision_report_path=rollback_decision_report_path,
        checklist_path=checklist_path,
        readme_path=readme_path,
    )

    return AgentResult(
        outputs={
            manifest_path: generated.manifest,
            validation_report_path: generated.validation_report,
            rollback_decision_report_path: generated.rollback_decision_report,
            checklist_path: generated.checklist_md,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "evidence_item_count": generated.manifest["summary"]["evidence_item_count"],
            "human_real_run_evidence_ingested_count": generated.manifest["summary"][
                "human_real_run_evidence_ingested_count"
            ],
            "blocked_evidence_count": generated.manifest["summary"]["blocked_evidence_count"],
            "editor_software_run_evidence_status": generated.manifest["validation"]["status"],
            "human_real_run_result_required": generated.manifest["validation"][
                "human_real_run_result_required"
            ],
            "human_real_run_result_present": generated.manifest["validation"]["human_real_run_result_present"],
            "human_real_run_result_valid": generated.manifest["validation"]["human_real_run_result_valid"],
            "real_software_launch_performed_by_automation": generated.manifest["validation"][
                "real_software_launch_performed_by_automation"
            ],
            "software_import_execution_performed_by_automation": generated.manifest["validation"][
                "software_import_execution_performed_by_automation"
            ],
            "editing_software_opened_by_automation": generated.manifest["validation"][
                "editing_software_opened_by_automation"
            ],
            "project_file_mutation_performed_by_automation": generated.manifest["validation"][
                "project_file_mutation_performed_by_automation"
            ],
            "process_spawned_by_automation": generated.manifest["validation"]["process_spawned_by_automation"],
            "manual_review_required": True,
        },
        notes=[
            f"editor-software-run-evidence-agent generated a post-launch evidence ingest package for {platform}.",
            "No editing software was opened, no process was spawned, no import was executed, and no project file was mutated by automation.",
        ],
    )


def _run_cover_image_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("cover-image-agent requires a selected video platform")

    asset_tasks = _read_json_if_exists(context.run_dir / "assets/asset_generation_tasks.json")
    if not isinstance(asset_tasks, dict):
        raise RuntimeError("cover-image-agent requires assets/asset_generation_tasks.json from asset-agent")

    cover_task = _cover_task_for_platform(asset_tasks, platform)
    if not cover_task:
        raise RuntimeError(f"cover-image-agent could not find cover_image task for platform {platform}")

    aspect_ratio = str(cover_task.get("aspect_ratio") or ("16:9" if platform == "bilibili" else "9:16"))
    target_path = str(cover_task.get("target_path") or f"assets/{platform}/cover/cover.png")
    target_size = (1280, 720) if aspect_ratio == "16:9" else (720, 1280)
    resolved_source = resolve_visual_source(
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        asset_type="cover_image",
        prompt=str(cover_task.get("prompt") or _platform_hook(context.topic, platform)),
        aspect_ratio=aspect_ratio,
        task=cover_task,
        target_size=target_size,
    )
    generated = generate_cover_image(
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        prompt=str(cover_task.get("prompt") or _platform_hook(context.topic, platform)),
        aspect_ratio=aspect_ratio,
        target_path=target_path,
        source_image_bytes=resolved_source.image_bytes if resolved_source else None,
        source_artifacts=[
            "assets/asset_generation_tasks.json",
            *( [resolved_source.source_reference or resolved_source.source_path or resolved_source.provider] if resolved_source else [] ),
        ],
    )
    metadata_path = f"assets/{platform}/cover/cover_metadata.json"
    source_metadata = (
        {
            "source_mode": resolved_source.mode,
            "source_provider": resolved_source.provider,
            "source_reference": resolved_source.source_reference,
            "source_library_root": resolved_source.source_library_root,
            "source_content_type": resolved_source.content_type,
            "source_revised_prompt": resolved_source.revised_prompt,
        }
        if resolved_source
        else {
            "source_mode": "local_pillow_fallback",
            "source_provider": "local-pillow-cover-adapter",
            "source_reference": None,
            "source_library_root": None,
            "source_content_type": "image/png",
            "source_revised_prompt": None,
        }
    )
    metadata = generated.metadata | {
        "task_id": cover_task.get("task_id"),
        "used_by": _asset_usage_targets(platform, "cover_image"),
        **source_metadata,
    }

    return AgentResult(
        outputs={
            target_path: generated.image_bytes,
            metadata_path: metadata,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": metadata["adapter"],
            "adapter_version": metadata["adapter_version"],
            "platform": platform,
            "asset_type": "cover_image",
            "generation_status": "generated_pending_review",
            "rights_status": "pending_human_review",
            "manual_review_required": True,
            "source_artifacts": ["assets/asset_generation_tasks.json"],
        },
        notes=[
            f"cover-image-agent generated a local PNG cover draft for {platform}.",
            "The generated cover is pending human review and was not uploaded or published.",
        ],
    )


def _run_storyboard_preview_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("storyboard-preview-agent requires a selected video platform")

    asset_tasks = _read_json_if_exists(context.run_dir / "assets/asset_generation_tasks.json")
    if not isinstance(asset_tasks, dict):
        raise RuntimeError("storyboard-preview-agent requires assets/asset_generation_tasks.json from asset-agent")

    storyboard = _read_json_if_exists(context.run_dir / platform / "storyboard.json")
    shot_list = _read_json_if_exists(context.run_dir / platform / "shot_list.json")
    if not isinstance(storyboard, list):
        raise RuntimeError(f"storyboard-preview-agent requires {platform}/storyboard.json")
    if not isinstance(shot_list, list):
        raise RuntimeError(f"storyboard-preview-agent requires {platform}/shot_list.json")

    expected_outputs = {str(path) for path in task_spec.get("outputs", [])}
    frame_tasks = [
        task
        for task in _storyboard_frame_tasks_for_platform(asset_tasks, platform)
        if str(task.get("target_path")) in expected_outputs
    ]
    if not frame_tasks:
        raise RuntimeError(f"storyboard-preview-agent could not find storyboard_frame tasks for platform {platform}")

    source_artifacts = [
        "assets/asset_generation_tasks.json",
        f"{platform}/storyboard.json",
        f"{platform}/shot_list.json",
    ]
    shot_by_id = {
        str(shot["shot_id"]): shot
        for shot in shot_list
        if isinstance(shot, dict) and shot.get("shot_id")
    }
    outputs: dict[str, Any] = {}
    generated_frames: list[GeneratedStoryboardFrame] = []
    for index, task in enumerate(frame_tasks, start=1):
        target_path = str(task["target_path"])
        shot_id = str(task.get("linked_shot_id") or Path(target_path).stem)
        shot = shot_by_id.get(shot_id)
        scene = storyboard[index - 1] if index - 1 < len(storyboard) and isinstance(storyboard[index - 1], dict) else {}
        if not isinstance(shot, dict):
            shot = scene
        aspect_ratio = str(task.get("aspect_ratio") or ("16:9" if platform == "bilibili" else "9:16"))
        resolved_source = resolve_visual_source(
            topic=context.topic,
            platform=platform,
            platform_label=_platform_label(platform),
            asset_type="storyboard_frame",
            prompt=str(task.get("prompt") or shot.get("visual") or scene.get("visual") or "Storyboard frame"),
            aspect_ratio=aspect_ratio,
            task=task,
            target_size=(1280, 720) if aspect_ratio == "16:9" else (720, 1280),
        )
        generated = generate_storyboard_frame_image(
            run_id=context.run_dir.name,
            topic=context.topic,
            platform=platform,
            platform_label=_platform_label(platform),
            frame_index=index,
            shot_id=shot_id,
            scene=str(shot.get("scene") or scene.get("scene") or shot_id),
            purpose=str(shot.get("purpose") or scene.get("scene") or "storyboard_frame"),
            visual=str(shot.get("visual") or scene.get("visual") or task.get("prompt") or ""),
            voiceover=str(shot.get("voiceover") or scene.get("voiceover") or shot.get("voiceover_hint") or ""),
            duration_seconds=_safe_int(shot.get("duration_seconds") or scene.get("duration_seconds"), default=0),
            aspect_ratio=aspect_ratio,
            target_path=target_path,
            source_image_bytes=resolved_source.image_bytes if resolved_source else None,
            source_artifacts=[
                "assets/asset_generation_tasks.json",
                f"{platform}/storyboard.json",
                f"{platform}/shot_list.json",
                *( [resolved_source.source_reference or resolved_source.source_path or resolved_source.provider] if resolved_source else [] ),
            ],
        )
        frame_metadata = generated.metadata | {
            "task_id": task.get("task_id"),
            "source_prompt": task.get("prompt"),
            "used_by": _asset_usage_targets(platform, "storyboard_frame"),
            "source_mode": resolved_source.mode if resolved_source else "local_pillow_fallback",
            "source_provider": resolved_source.provider if resolved_source else "local-pillow-storyboard-preview-adapter",
            "source_reference": resolved_source.source_reference if resolved_source else None,
            "source_library_root": resolved_source.source_library_root if resolved_source else None,
            "source_content_type": resolved_source.content_type if resolved_source else "image/png",
            "source_revised_prompt": resolved_source.revised_prompt if resolved_source else None,
        }
        enriched_frame = GeneratedStoryboardFrame(
            image_bytes=generated.image_bytes,
            metadata=frame_metadata,
        )
        outputs[target_path] = enriched_frame.image_bytes
        generated_frames.append(enriched_frame)

    preview_path = f"assets/{platform}/storyboard/storyboard_preview.png"
    preview_metadata_path = f"assets/{platform}/storyboard/storyboard_preview_metadata.json"
    preview = generate_storyboard_preview_sheet(
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        aspect_ratio=str(frame_tasks[0].get("aspect_ratio") or ("16:9" if platform == "bilibili" else "9:16")),
        target_path=preview_path,
        frames=generated_frames,
    )
    preview_metadata = preview.metadata | {
        "source_artifacts": source_artifacts,
        "frame_paths": [frame.metadata["path"] for frame in generated_frames],
        "frame_task_ids": [frame.metadata.get("task_id") for frame in generated_frames],
        "used_by": ["final/video_production_package.json"],
        "review_required": True,
        "source_modes": [frame.metadata.get("source_mode") for frame in generated_frames],
        "source_providers": [frame.metadata.get("source_provider") for frame in generated_frames],
    }
    outputs[preview_path] = preview.image_bytes
    outputs[preview_metadata_path] = preview_metadata

    return AgentResult(
        outputs=outputs,
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": preview_metadata["adapter"],
            "adapter_version": preview_metadata["adapter_version"],
            "platform": platform,
            "asset_type": "storyboard_preview",
            "frame_count": len(generated_frames),
            "generation_status": "generated_pending_review",
            "rights_status": "pending_human_review",
            "manual_review_required": True,
            "source_artifacts": source_artifacts,
        },
        notes=[
            f"storyboard-preview-agent generated local storyboard keyframe previews for {platform}.",
            "Generated storyboard previews are pending human review and were not edited, uploaded, synced, or published.",
        ],
    )


def _run_subtitle_timing_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("subtitle-timing-agent requires a selected video platform")

    storyboard = _read_json_if_exists(context.run_dir / platform / "storyboard.json")
    shot_list = _read_json_if_exists(context.run_dir / platform / "shot_list.json")
    source_srt = _read_text_if_exists(context.run_dir / platform / "subtitles.srt")
    if not isinstance(storyboard, list):
        raise RuntimeError(f"subtitle-timing-agent requires {platform}/storyboard.json")
    if not isinstance(shot_list, list):
        raise RuntimeError(f"subtitle-timing-agent requires {platform}/shot_list.json")
    if not source_srt:
        raise RuntimeError(f"subtitle-timing-agent requires {platform}/subtitles.srt")

    source_artifacts = [
        f"{platform}/storyboard.json",
        f"{platform}/shot_list.json",
        f"{platform}/subtitles.srt",
    ]
    storyboard_metadata_path = f"assets/{platform}/storyboard/storyboard_preview_metadata.json"
    if (context.run_dir / storyboard_metadata_path).exists():
        source_artifacts.append(storyboard_metadata_path)

    timed_subtitles = align_subtitle_timeline(
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        storyboard=storyboard,
        shot_list=shot_list,
        source_srt=source_srt,
        source_artifacts=source_artifacts,
    )
    timed_subtitles_srt = render_timed_subtitles_srt(timed_subtitles)
    split_blocks = [
        item
        for item in timed_subtitles.get("subtitles", [])
        if isinstance(item, dict) and item.get("split_count", 1) > 1
    ]

    return AgentResult(
        outputs={
            f"{platform}/timed_subtitles.json": timed_subtitles,
            f"{platform}/timed_subtitles.srt": timed_subtitles_srt,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": timed_subtitles["adapter"],
            "adapter_version": timed_subtitles["adapter_version"],
            "platform": platform,
            "source_artifacts": source_artifacts,
            "storyboard_scene_count": timed_subtitles["storyboard_scene_count"],
            "subtitle_count": timed_subtitles["subtitle_count"],
            "split_subtitle_count": len(split_blocks),
            "total_duration_seconds": timed_subtitles["total_duration_seconds"],
            "timeline_status": timed_subtitles.get("validation", {}).get("status"),
            "tts_ready": True,
        },
        notes=[
            f"subtitle-timing-agent aligned {platform} subtitles to storyboard shot windows.",
            "Timed subtitles are local deterministic timing artifacts; no TTS, editing, upload, or publishing action was performed.",
        ],
    )


def _run_voiceover_tts_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("voiceover-tts-agent requires a selected video platform")

    timed_subtitles_path = context.run_dir / platform / "timed_subtitles.json"
    timed_subtitles = _read_json_if_exists(timed_subtitles_path)
    if not isinstance(timed_subtitles, dict):
        raise RuntimeError(f"voiceover-tts-agent requires {platform}/timed_subtitles.json")
    validation = timed_subtitles.get("validation")
    if isinstance(validation, dict) and validation.get("status") != "PASSED":
        raise RuntimeError(f"voiceover-tts-agent requires validated timed subtitles for {platform}")

    audio_path = f"assets/{platform}/voiceover/voiceover.wav"
    manifest_path = f"assets/{platform}/voiceover/voiceover_manifest.json"
    generated = generate_voiceover_tts(
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        timed_subtitles=timed_subtitles,
        target_path=audio_path,
    )
    manifest = generated.manifest | {
        "manifest_path": manifest_path,
        "source_artifacts": [f"{platform}/timed_subtitles.json", f"{platform}/timed_subtitles.srt"],
        "used_by": ["final/video_production_package.json"],
    }

    return AgentResult(
        outputs={
            audio_path: generated.audio_bytes,
            manifest_path: manifest,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": manifest["adapter"],
            "adapter_version": manifest["adapter_version"],
            "provider": manifest["provider"],
            "provider_external": manifest.get("provider_external") is True,
            "audio_generation_mode": manifest.get("audio_generation_mode"),
            "provider_metadata": manifest.get("provider_metadata", {}),
            "platform": platform,
            "source_artifacts": manifest["source_artifacts"],
            "segment_count": manifest["segment_count"],
            "duration_seconds": manifest["duration_seconds"],
            "voiceover_status": manifest["validation"]["status"],
            "manual_review_required": True,
        },
        notes=[
            f"voiceover-tts-agent generated a voiceover WAV for {platform} from timed_subtitles.json.",
            "The voiceover is aligned to the subtitle timeline; no editing, upload, sync, or publishing action was performed.",
        ],
    )


def _run_edit_project_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("edit-project-agent requires a selected video platform")

    storyboard = _read_json_if_exists(context.run_dir / platform / "storyboard.json")
    shot_list = _read_json_if_exists(context.run_dir / platform / "shot_list.json")
    timed_subtitles = _read_json_if_exists(context.run_dir / platform / "timed_subtitles.json")
    voiceover_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "voiceover" / "voiceover_manifest.json"
    )
    storyboard_preview_metadata = _read_json_if_exists(
        context.run_dir / "assets" / platform / "storyboard" / "storyboard_preview_metadata.json"
    )
    broll_list = _read_json_if_exists(context.run_dir / platform / "broll_list.json")
    material_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "materials" / "material_manifest.json"
    )
    licensed_media_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json"
    )
    licensed_media_proxy_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json"
    )
    if not isinstance(storyboard, list):
        raise RuntimeError(f"edit-project-agent requires {platform}/storyboard.json")
    if not isinstance(shot_list, list):
        raise RuntimeError(f"edit-project-agent requires {platform}/shot_list.json")
    if not isinstance(timed_subtitles, dict):
        raise RuntimeError(f"edit-project-agent requires {platform}/timed_subtitles.json")
    if not isinstance(voiceover_manifest, dict):
        raise RuntimeError(f"edit-project-agent requires assets/{platform}/voiceover/voiceover_manifest.json")
    if not isinstance(storyboard_preview_metadata, dict):
        raise RuntimeError(f"edit-project-agent requires assets/{platform}/storyboard/storyboard_preview_metadata.json")
    if not isinstance(broll_list, list):
        broll_list = []
    if not isinstance(material_manifest, dict):
        material_manifest = None
    if not isinstance(licensed_media_manifest, dict):
        licensed_media_manifest = None
    if not isinstance(licensed_media_proxy_manifest, dict):
        licensed_media_proxy_manifest = None

    timeline_path = f"assets/{platform}/edit/edit_timeline.json"
    manifest_path = f"assets/{platform}/edit/edit_manifest.json"
    edl_path = f"assets/{platform}/edit/draft_cut.edl"
    generated = generate_edit_project(
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        aspect_ratio="16:9" if platform == "bilibili" else "9:16",
        storyboard=storyboard,
        shot_list=shot_list,
        timed_subtitles=timed_subtitles,
        voiceover_manifest=voiceover_manifest,
        storyboard_preview_metadata=storyboard_preview_metadata,
        broll_list=broll_list,
        material_manifest=material_manifest,
        licensed_media_manifest=licensed_media_manifest,
        licensed_media_proxy_manifest=licensed_media_proxy_manifest,
        timeline_path=timeline_path,
        manifest_path=manifest_path,
        edl_path=edl_path,
    )

    return AgentResult(
        outputs={
            timeline_path: generated.timeline,
            manifest_path: generated.manifest,
            edl_path: generated.edl_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "source_artifacts": generated.manifest["source_artifacts"],
            "duration_seconds": generated.manifest["duration_seconds"],
            "video_clip_count": generated.manifest["track_summary"]["video_clips"],
            "audio_clip_count": generated.manifest["track_summary"]["audio_clips"],
            "subtitle_clip_count": generated.manifest["track_summary"]["subtitle_clips"],
            "timeline_status": generated.manifest["validation"]["status"],
            "manual_review_required": True,
        },
        notes=[
            f"edit-project-agent generated a local executable edit timeline for {platform}.",
            "The edit project is a draft handoff package; no editing software, export, upload, sync, or publishing action was performed.",
        ],
    )


def _run_export_project_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("export-project-agent requires a selected video platform")

    edit_timeline = _read_json_if_exists(context.run_dir / "assets" / platform / "edit" / "edit_timeline.json")
    edit_manifest = _read_json_if_exists(context.run_dir / "assets" / platform / "edit" / "edit_manifest.json")
    if not isinstance(edit_timeline, dict):
        raise RuntimeError(f"export-project-agent requires assets/{platform}/edit/edit_timeline.json")
    if not isinstance(edit_manifest, dict):
        raise RuntimeError(f"export-project-agent requires assets/{platform}/edit/edit_manifest.json")

    project_path = f"assets/{platform}/edit/project.fcpxml"
    readme_path = f"assets/{platform}/edit/import_readme.md"
    offline_report_path = f"assets/{platform}/edit/offline_media_report.json"
    manifest_path = f"assets/{platform}/edit/export_manifest.json"
    generated = generate_export_project(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        aspect_ratio="16:9" if platform == "bilibili" else "9:16",
        edit_timeline=edit_timeline,
        edit_manifest=edit_manifest,
        project_path=project_path,
        readme_path=readme_path,
        offline_report_path=offline_report_path,
        manifest_path=manifest_path,
    )

    return AgentResult(
        outputs={
            project_path: generated.fcpxml_text,
            readme_path: generated.readme_text,
            offline_report_path: generated.offline_report,
            manifest_path: generated.manifest,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "project_format": generated.manifest["project_format"],
            "source_artifacts": generated.manifest["source_artifacts"],
            "duration_seconds": generated.manifest["duration_seconds"],
            "video_clip_count": generated.manifest["track_summary"]["video_clips"],
            "audio_clip_count": generated.manifest["track_summary"]["audio_clips"],
            "offline_broll_slots": generated.manifest["track_summary"]["offline_broll_slots"],
            "export_status": generated.manifest["validation"]["status"],
            "manual_review_required": True,
        },
        notes=[
            f"export-project-agent generated a local FCPXML draft handoff for {platform}.",
            "The export project is a draft handoff package; no editing software, upload, sync, or publishing action was performed.",
        ],
    )


def _run_project_bundle_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    platform = _task_platform(task_spec)
    if platform not in VIDEO_PLATFORMS:
        raise RuntimeError("project-bundle-agent requires a selected video platform")

    export_manifest = _read_json_if_exists(context.run_dir / "assets" / platform / "edit" / "export_manifest.json")
    offline_report = _read_json_if_exists(context.run_dir / "assets" / platform / "edit" / "offline_media_report.json")
    editor_replacement_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "replacement_instructions" / "instruction_manifest.json"
    )
    editor_replacement_execution_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "replacement_execution" / "execution_manifest.json"
    )
    editor_project_mutation_manifest = _read_json_if_exists(
        context.run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "mutation_manifest.json"
    )
    editor_software_import_manifest = _read_json_if_exists(
        context.run_dir
        / "assets"
        / platform
        / "edit"
        / "software_import_executor"
        / "import_executor_manifest.json"
    )
    editor_software_real_runner_manifest = _read_json_if_exists(
        context.run_dir
        / "assets"
        / platform
        / "edit"
        / "software_real_runner_sandbox"
        / "runner_sandbox_manifest.json"
    )
    editor_software_run_evidence_manifest = _read_json_if_exists(
        context.run_dir
        / "assets"
        / platform
        / "edit"
        / "software_run_evidence"
        / "real_run_evidence_manifest.json"
    )
    if not isinstance(export_manifest, dict):
        raise RuntimeError(f"project-bundle-agent requires assets/{platform}/edit/export_manifest.json")
    if not isinstance(offline_report, dict):
        raise RuntimeError(f"project-bundle-agent requires assets/{platform}/edit/offline_media_report.json")
    if not isinstance(editor_replacement_manifest, dict):
        editor_replacement_manifest = None
    if not isinstance(editor_replacement_execution_manifest, dict):
        editor_replacement_execution_manifest = None
    if not isinstance(editor_project_mutation_manifest, dict):
        editor_project_mutation_manifest = None
    if not isinstance(editor_software_import_manifest, dict):
        editor_software_import_manifest = None
    if not isinstance(editor_software_real_runner_manifest, dict):
        editor_software_real_runner_manifest = None
    if not isinstance(editor_software_run_evidence_manifest, dict):
        editor_software_run_evidence_manifest = None

    bundle_path = f"assets/{platform}/bundle/project_bundle.zip"
    manifest_path = f"assets/{platform}/bundle/project_bundle_manifest.json"
    file_manifest_path = f"assets/{platform}/bundle/file_manifest.json"
    readme_path = f"assets/{platform}/bundle/README.md"
    generated = generate_project_bundle(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platform=platform,
        platform_label=_platform_label(platform),
        export_manifest=export_manifest,
        offline_report=offline_report,
        editor_replacement_manifest=editor_replacement_manifest,
        editor_replacement_execution_manifest=editor_replacement_execution_manifest,
        editor_project_mutation_manifest=editor_project_mutation_manifest,
        editor_software_import_manifest=editor_software_import_manifest,
        editor_software_real_runner_manifest=editor_software_real_runner_manifest,
        editor_software_run_evidence_manifest=editor_software_run_evidence_manifest,
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        file_manifest_path=file_manifest_path,
        readme_path=readme_path,
    )

    return AgentResult(
        outputs={
            bundle_path: generated.bundle_bytes,
            manifest_path: generated.manifest,
            file_manifest_path: generated.file_manifest,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": generated.manifest["adapter"],
            "adapter_version": generated.manifest["adapter_version"],
            "platform": platform,
            "bundle_format": generated.manifest["bundle_format"],
            "bundle_path": generated.manifest["bundle_path"],
            "source_artifacts": generated.manifest["source_artifacts"],
            "file_count": generated.manifest["bundle_summary"]["file_count"],
            "bundle_bytes": generated.manifest["bundle_summary"]["bundle_bytes"],
            "bundle_status": generated.manifest["validation"]["status"],
            "manual_review_required": True,
        },
        notes=[
            f"project-bundle-agent generated a local ZIP handoff bundle for {platform}.",
            "The project bundle is a draft handoff package; no editing software, upload, sync, or publishing action was performed.",
        ],
    )


def _run_delivery_index_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    index_path = "final/delivery_index.json"
    readme_path = "final/delivery_readme.md"
    generated = generate_delivery_index(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        platforms=context.platforms,
        index_path=index_path,
        readme_path=readme_path,
    )

    return AgentResult(
        outputs={
            index_path: generated.index,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": "local-delivery-index-adapter",
            "adapter_version": "0.1.0",
            "delivery_status": generated.index["validation"]["status"],
            "bundle_count": generated.index["archive_summary"]["bundle_count"],
            "total_bundle_bytes": generated.index["archive_summary"]["total_bundle_bytes"],
            "download_items": generated.index["download_items"],
            "manual_review_required": True,
        },
        notes=[
            "delivery-index-agent generated a local delivery index for project bundle handoff.",
            "No external storage sync, upload, login, or publishing action was performed.",
        ],
    )


def _run_artifact_store_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    delivery_index = _read_json_if_exists(context.run_dir / "final" / "delivery_index.json")
    if not isinstance(delivery_index, dict):
        raise RuntimeError("artifact-store-agent requires final/delivery_index.json")

    manifest_path = "artifact_store/artifact_store_manifest.json"
    readme_path = "artifact_store/README.md"
    download_index_path = "artifact_store/download_index.md"
    checksums_path = "artifact_store/checksums.sha256"
    delivery_index_copy_path = "artifact_store/manifests/delivery_index.json"
    generated = generate_artifact_store(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        delivery_index=delivery_index,
        manifest_path=manifest_path,
        readme_path=readme_path,
        download_index_path=download_index_path,
        checksums_path=checksums_path,
        delivery_index_copy_path=delivery_index_copy_path,
    )
    outputs: dict[str, Any] = {
        manifest_path: generated.manifest,
        readme_path: generated.readme_text,
        download_index_path: generated.download_index_text,
        checksums_path: generated.checksums_text,
        delivery_index_copy_path: generated.delivery_index_copy,
    }
    outputs.update(generated.download_files)

    return AgentResult(
        outputs=outputs,
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": "local-artifact-store-adapter",
            "adapter_version": "0.1.0",
            "artifact_store_status": generated.manifest["validation"]["status"],
            "download_count": generated.manifest["store_summary"]["download_count"],
            "expected_download_count": generated.manifest["store_summary"]["expected_download_count"],
            "checksum_match_count": generated.manifest["store_summary"]["checksum_match_count"],
            "total_download_bytes": generated.manifest["store_summary"]["total_download_bytes"],
            "source_artifacts": generated.manifest["source_artifacts"],
            "download_paths": [item["store_path"] for item in generated.manifest["downloads"]],
            "external_storage_sync_performed": False,
            "upload_performed": False,
            "publishing_performed": False,
            "manual_review_required": True,
        },
        notes=[
            "artifact-store-agent generated a local downloadable artifact store from the delivery index.",
            "No external storage sync, upload, login, platform action, or publishing action was performed.",
        ],
    )


def _run_external_mirror_plan_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    artifact_store_manifest = _read_json_if_exists(
        context.run_dir / "artifact_store" / "artifact_store_manifest.json"
    )
    if not isinstance(artifact_store_manifest, dict):
        raise RuntimeError("external-mirror-plan-agent requires artifact_store/artifact_store_manifest.json")

    plan_path = "artifact_store/external_mirror_plan.json"
    sync_command_preview_path = "artifact_store/sync_command_preview.md"
    approval_request_path = "artifact_store/human_distribution_approval_request.md"
    readme_path = "artifact_store/external_mirror_readme.md"
    generated = generate_external_mirror_plan(
        run_dir=context.run_dir,
        run_id=context.run_dir.name,
        topic=context.topic,
        artifact_store_manifest=artifact_store_manifest,
        plan_path=plan_path,
        sync_command_preview_path=sync_command_preview_path,
        approval_request_path=approval_request_path,
        readme_path=readme_path,
    )

    return AgentResult(
        outputs={
            plan_path: generated.plan,
            sync_command_preview_path: generated.sync_command_preview_md,
            approval_request_path: generated.approval_request_md,
            readme_path: generated.readme_text,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "adapter": "local-external-mirror-plan-adapter",
            "adapter_version": "0.1.0",
            "external_mirror_plan_status": generated.plan["validation"]["status"],
            "mirror_item_count": generated.plan["mirror_summary"]["mirror_item_count"],
            "ready_source_count": generated.plan["mirror_summary"]["ready_source_count"],
            "approved_mirror_count": generated.plan["mirror_summary"]["approved_mirror_count"],
            "source_artifacts": generated.plan["source_artifacts"],
            "external_storage_sync_performed": False,
            "upload_performed": False,
            "publishing_performed": False,
            "login_performed": False,
            "platform_action_performed": False,
            "network_access_performed": False,
            "human_distribution_approval_required": True,
            "manual_review_required": True,
        },
        notes=[
            "external-mirror-plan-agent generated a plan-only external mirror handoff for artifact store downloads.",
            "No external storage sync, upload, login, network access, platform action, or publishing action was performed.",
        ],
    )


def _run_repair_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    inputs = task_spec.get("inputs", {})
    failure = inputs.get("failure") if isinstance(inputs, dict) else {}
    failed_task_spec = inputs.get("failed_task_spec") if isinstance(inputs, dict) else {}
    retry_decision = inputs.get("retry_decision") if isinstance(inputs, dict) else {}
    if not isinstance(failure, dict):
        failure = {}
    if not isinstance(failed_task_spec, dict):
        failed_task_spec = {}
    if not isinstance(retry_decision, dict):
        retry_decision = {}

    category = str(failure.get("failure_type") or failure.get("category") or "ENV_ERROR")
    step_id = str(failure.get("step_id") or _metadata_step_id(failed_task_spec) or "unknown")
    agent_id = str(failure.get("agent") or failed_task_spec.get("agent") or "unknown-agent")
    message = str(failure.get("message") or "No failure message was provided.")
    root_cause = _repair_root_cause(category, message)
    recommended_actions = _repair_actions(category, step_id)
    manual_required = category in {"POLICY_ERROR", "PERMISSION_ERROR", "QUALITY_ERROR", "DATA_ERROR", "SCHEMA_ERROR"}
    retry_reason = str(retry_decision.get("reason") or "Retry policy did not provide a decision.")
    plan = {
        "generated_by": "repair-agent",
        "agent_interface": "run_agent(task_spec)",
        "topic": context.topic,
        "failed_step_id": step_id,
        "failed_agent": agent_id,
        "failure_category": category,
        "failure_message": message,
        "root_cause_hypothesis": root_cause,
        "recommended_actions": recommended_actions,
        "retry_policy_decision": retry_decision,
        "manual_required": manual_required,
        "can_auto_patch": False,
        "safe_to_rerun_after_fix": category not in {"POLICY_ERROR", "PERMISSION_ERROR"},
        "review_required": True,
    }
    markdown = "\n".join(
        [
            "# Repair Plan",
            "",
            f"- Failed step: {step_id}",
            f"- Failed agent: {agent_id}",
            f"- Failure category: {category}",
            f"- Manual required: {'yes' if manual_required else 'no'}",
            f"- Retry policy: {retry_reason}",
            "",
            "## Failure Message",
            "",
            message,
            "",
            "## Root Cause Hypothesis",
            "",
            root_cause,
            "",
            "## Recommended Actions",
            "",
            *[f"{index}. {action}" for index, action in enumerate(recommended_actions, start=1)],
            "",
            "## Boundary",
            "",
            "repair-agent only produced a diagnosis and repair plan. It did not modify task inputs, artifacts, cookies, browser state, or platform content.",
            "",
        ]
    )
    return AgentResult(
        outputs={
            "repair_plan.md": markdown,
            "repair_plan.json": plan,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "failure_category": category,
            "failed_step_id": step_id,
            "failed_agent": agent_id,
            "manual_required": manual_required,
            "can_auto_patch": False,
        },
        notes=[
            "repair-agent generated a diagnostic repair plan.",
            "No automatic patching or publishing action was performed.",
        ],
    )


def _run_wechat_article_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    topic = context.topic.strip()
    angle_pack = _read_json_if_exists(context.run_dir / "angle_pack.json")
    master_outline = _read_text_if_exists(context.run_dir / "master_outline.md")
    research_report = _read_text_if_exists(context.run_dir / "research_report.md")
    sources = _read_json_if_exists(context.run_dir / "sources.json")
    if not isinstance(angle_pack, dict):
        raise RuntimeError("wechat-article-agent requires angle_pack.json from topic-agent")
    if not master_outline:
        raise RuntimeError("wechat-article-agent requires master_outline.md from outline-agent")
    if not research_report:
        raise RuntimeError("wechat-article-agent requires research_report.md from research-agent")

    wechat_angle = _platform_angle(angle_pack, "wechat")
    hook = str(wechat_angle.get("hook") or f"{topic} 不是多写几个 prompt，而是把内容生产变成可复盘的工作流。")
    content_promise = str(wechat_angle.get("content_promise") or f"讲清 {topic} 的架构、流程、边界和落地路径。")
    title = _wechat_title(topic)
    title_options = _wechat_title_options(topic)
    source_notes = _wechat_source_notes(sources)
    article = _wechat_article_markdown(topic, title, hook, content_promise, source_notes)
    title_options_payload = {
        "platform": "wechat",
        "generated_by": "wechat-article-agent",
        "agent_interface": "run_agent(task_spec)",
        "title_options": title_options,
        "recommended_title": title,
        "summary": _wechat_summary(topic),
        "source_notes": source_notes,
        "review_required": True,
    }
    return AgentResult(
        outputs={
            "wechat/article.md": article,
            "wechat/title_options.json": title_options_payload,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "used_angle_pack": True,
            "used_master_outline": True,
            "used_research_report": True,
            "used_sources": isinstance(sources, dict),
            "source_artifacts": ["angle_pack.json", "master_outline.md", "research_report.md", "sources.json"],
            "platform": "wechat",
            "title_count": len(title_options),
            "source_note_count": len(source_notes),
            "article_length": len(article),
        },
        notes=[
            "wechat-article-agent generated article.md and title_options.json from upstream artifacts.",
            "The article marks source gaps and requires human review before publication.",
        ],
    )


def _run_xiaohongshu_note_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    topic = context.topic.strip()
    angle_pack = _read_json_if_exists(context.run_dir / "angle_pack.json")
    master_outline = _read_text_if_exists(context.run_dir / "master_outline.md")
    if not isinstance(angle_pack, dict):
        raise RuntimeError("xiaohongshu-note-agent requires angle_pack.json from topic-agent")
    if not master_outline:
        raise RuntimeError("xiaohongshu-note-agent requires master_outline.md from outline-agent")

    xhs_angle = _platform_angle(angle_pack, "xiaohongshu")
    hook = str(xhs_angle.get("hook") or f"同一个选题不用改五遍，先搭一套 {topic} 工作流。")
    content_promise = str(xhs_angle.get("content_promise") or f"给出 {topic} 的轻量搭建思路和可收藏清单。")
    note = {
        "title": _xiaohongshu_title(topic),
        "content": _xiaohongshu_content(topic, hook, content_promise),
        "tags": _xiaohongshu_tags(topic),
        "cover_prompt": _xiaohongshu_cover_prompt(topic, hook),
        "best_time": "周二/周四/周六 19:00-20:00",
        "cta": "你想先自动化哪个平台？评论区告诉我。",
        "review_required": True,
    }
    cover_prompt = "\n".join(
        [
            "# Xiaohongshu Cover Prompt",
            "",
            f"Topic: {topic}",
            "",
            note["cover_prompt"],
            "",
            "Format: 3:4 vertical cover, large readable Chinese title, clean workflow board, five platform cards, no platform logos.",
            "",
            "Review note: use only cleared visual assets before publishing.",
        ]
    )
    return AgentResult(
        outputs={
            "xiaohongshu/note.json": note,
            "xiaohongshu/cover_prompt.md": cover_prompt + "\n",
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "used_angle_pack": True,
            "used_master_outline": True,
            "source_artifacts": ["angle_pack.json", "master_outline.md"],
            "platform": "xiaohongshu",
            "tag_count": len(note["tags"]),
            "title_length": len(note["title"]),
        },
        notes=[
            "xiaohongshu-note-agent generated note.json from angle_pack.json and master_outline.md.",
            "The note requires human review and includes #AI生成内容.",
        ],
    )


def _run_douyin_video_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    topic = context.topic.strip()
    angle_pack = _read_json_if_exists(context.run_dir / "angle_pack.json")
    master_outline = _read_text_if_exists(context.run_dir / "master_outline.md")
    asset_plan = _read_json_if_exists(context.run_dir / "asset_plan.json")
    if not isinstance(angle_pack, dict):
        raise RuntimeError("douyin-video-agent requires angle_pack.json from topic-agent")
    if not master_outline:
        raise RuntimeError("douyin-video-agent requires master_outline.md from outline-agent")

    douyin_angle = _platform_angle(angle_pack, "douyin")
    hook = str(douyin_angle.get("hook") or f"一个选题，五个平台版本，怎么自动拆出来？")
    content_promise = str(douyin_angle.get("content_promise") or f"用快节奏脚本展示 {topic} 如何把一个主题拆成多平台产物。")
    storyboard = _douyin_storyboard(topic, hook)
    subtitles = _douyin_subtitles(storyboard)
    script = _douyin_script_markdown(topic, hook, content_promise, storyboard)
    platform_asset_plan = _platform_asset_plan(asset_plan, "douyin", topic, hook)
    shot_list = _shot_list_from_storyboard(storyboard, "douyin", platform_asset_plan)
    broll_list = _broll_list_from_plan(platform_asset_plan)
    cover_prompt = _platform_cover_prompt_markdown(topic, "douyin", hook, platform_asset_plan)
    return AgentResult(
        outputs={
            "douyin/script.md": script,
            "douyin/storyboard.json": storyboard,
            "douyin/subtitles.srt": subtitles,
            "douyin/shot_list.json": shot_list,
            "douyin/broll_list.json": broll_list,
            "douyin/cover_prompt.md": cover_prompt,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "used_angle_pack": True,
            "used_master_outline": True,
            "used_asset_plan": isinstance(asset_plan, dict),
            "source_artifacts": ["angle_pack.json", "master_outline.md", "asset_plan.json"],
            "platform": "douyin",
            "scene_count": len(storyboard),
            "shot_count": len(shot_list),
            "broll_count": len(broll_list),
            "subtitle_blocks": len(storyboard),
            "duration_seconds": sum(scene["duration_seconds"] for scene in storyboard),
            "hook": hook,
        },
        notes=[
            "douyin-video-agent generated script.md, storyboard.json, subtitles.srt, shot_list.json, broll_list.json, and cover_prompt.md from upstream artifacts.",
            "The package does not upload, edit, publish, or use uncleared assets.",
        ],
    )


def _run_shipinhao_video_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    topic = context.topic.strip()
    angle_pack = _read_json_if_exists(context.run_dir / "angle_pack.json")
    master_outline = _read_text_if_exists(context.run_dir / "master_outline.md")
    asset_plan = _read_json_if_exists(context.run_dir / "asset_plan.json")
    if not isinstance(angle_pack, dict):
        raise RuntimeError("shipinhao-video-agent requires angle_pack.json from topic-agent")
    if not master_outline:
        raise RuntimeError("shipinhao-video-agent requires master_outline.md from outline-agent")

    shipinhao_angle = _platform_angle(angle_pack, "shipinhao")
    hook = str(shipinhao_angle.get("hook") or f"一个选题，怎么变成能被朋友转发的视频号内容？")
    content_promise = str(
        shipinhao_angle.get("content_promise")
        or f"用更适合微信社交场景的短视频脚本讲清 {topic} 的核心价值。"
    )
    storyboard = _shipinhao_storyboard(topic, hook)
    subtitles = _douyin_subtitles(storyboard)
    script = _shipinhao_script_markdown(topic, hook, content_promise, storyboard)
    platform_asset_plan = _platform_asset_plan(asset_plan, "shipinhao", topic, hook)
    shot_list = _shot_list_from_storyboard(storyboard, "shipinhao", platform_asset_plan)
    broll_list = _broll_list_from_plan(platform_asset_plan)
    cover_prompt = _platform_cover_prompt_markdown(topic, "shipinhao", hook, platform_asset_plan)
    return AgentResult(
        outputs={
            "shipinhao/script.md": script,
            "shipinhao/storyboard.json": storyboard,
            "shipinhao/subtitles.srt": subtitles,
            "shipinhao/cover_prompt.md": cover_prompt,
            "shipinhao/shot_list.json": shot_list,
            "shipinhao/broll_list.json": broll_list,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "used_angle_pack": True,
            "used_master_outline": True,
            "used_asset_plan": isinstance(asset_plan, dict),
            "source_artifacts": ["angle_pack.json", "master_outline.md", "asset_plan.json"],
            "platform": "shipinhao",
            "scene_count": len(storyboard),
            "shot_count": len(shot_list),
            "broll_count": len(broll_list),
            "subtitle_blocks": len(storyboard),
            "duration_seconds": sum(scene["duration_seconds"] for scene in storyboard),
            "hook": hook,
        },
        notes=[
            "shipinhao-video-agent generated script.md, storyboard.json, subtitles.srt, cover_prompt.md, shot_list.json, and broll_list.json from upstream artifacts.",
            "The package does not login, upload, forward, sync, publish, or use uncleared assets.",
        ],
    )


def _run_bilibili_video_agent(task_spec: dict[str, Any], context: AgentExecutionContext) -> AgentResult:
    topic = context.topic.strip()
    angle_pack = _read_json_if_exists(context.run_dir / "angle_pack.json")
    master_outline = _read_text_if_exists(context.run_dir / "master_outline.md")
    research_report = _read_text_if_exists(context.run_dir / "research_report.md")
    asset_plan = _read_json_if_exists(context.run_dir / "asset_plan.json")
    if not isinstance(angle_pack, dict):
        raise RuntimeError("bilibili-video-agent requires angle_pack.json from topic-agent")
    if not master_outline:
        raise RuntimeError("bilibili-video-agent requires master_outline.md from outline-agent")
    if not research_report:
        raise RuntimeError("bilibili-video-agent requires research_report.md from research-agent")

    bilibili_angle = _platform_angle(angle_pack, "bilibili")
    hook = str(bilibili_angle.get("hook") or f"从零拆解 {topic}：总控 agent 如何分配内容生产任务。")
    content_promise = str(bilibili_angle.get("content_promise") or f"用章节化方式展示 {topic} 的设计逻辑和后续开发路线。")
    chapters = _bilibili_chapters()
    storyboard = _bilibili_storyboard(topic, hook, chapters)
    script = _bilibili_script_markdown(topic, hook, content_promise, chapters)
    description = _bilibili_description_markdown(topic, hook, chapters)
    subtitles = _douyin_subtitles(storyboard)
    platform_asset_plan = _platform_asset_plan(asset_plan, "bilibili", topic, hook)
    shot_list = _shot_list_from_storyboard(storyboard, "bilibili", platform_asset_plan)
    broll_list = _broll_list_from_plan(platform_asset_plan)
    cover_prompt = _platform_cover_prompt_markdown(topic, "bilibili", hook, platform_asset_plan)
    return AgentResult(
        outputs={
            "bilibili/script.md": script,
            "bilibili/chapters.json": chapters,
            "bilibili/description.md": description,
            "bilibili/storyboard.json": storyboard,
            "bilibili/subtitles.srt": subtitles,
            "bilibili/shot_list.json": shot_list,
            "bilibili/broll_list.json": broll_list,
            "bilibili/cover_prompt.md": cover_prompt,
        },
        metadata={
            "execution_mode": "agent-local",
            "agent_interface": "run_agent(task_spec)",
            "used_angle_pack": True,
            "used_master_outline": True,
            "used_research_report": True,
            "used_asset_plan": isinstance(asset_plan, dict),
            "source_artifacts": ["angle_pack.json", "master_outline.md", "research_report.md", "asset_plan.json"],
            "platform": "bilibili",
            "chapter_count": len(chapters),
            "scene_count": len(storyboard),
            "shot_count": len(shot_list),
            "broll_count": len(broll_list),
            "subtitle_blocks": len(storyboard),
            "script_length": len(script),
            "description_length": len(description),
            "hook": hook,
        },
        notes=[
            "bilibili-video-agent generated script.md, chapters.json, description.md, storyboard.json, subtitles.srt, shot_list.json, broll_list.json, and cover_prompt.md from upstream artifacts.",
            "The package supports human editing and does not upload or publish.",
        ],
    )


def _platform_label(platform: str) -> str:
    return {
        "wechat": "微信公众号",
        "xiaohongshu": "小红书",
        "douyin": "抖音",
        "shipinhao": "视频号",
        "bilibili": "B站",
    }.get(platform, platform)


def _selected_video_platforms(platforms: list[str]) -> list[str]:
    return [platform for platform in platforms if platform in VIDEO_PLATFORMS]


def _task_platform(task_spec: dict[str, Any]) -> str:
    metadata = task_spec.get("metadata")
    if isinstance(metadata, dict) and metadata.get("platform"):
        return str(metadata["platform"])
    inputs = task_spec.get("inputs")
    if isinstance(inputs, dict) and inputs.get("platform"):
        return str(inputs["platform"])
    return ""


def _cover_task_for_platform(asset_tasks: dict[str, Any], platform: str) -> dict[str, Any] | None:
    tasks = asset_tasks.get("tasks")
    if not isinstance(tasks, list):
        return None
    for task in tasks:
        if (
            isinstance(task, dict)
            and task.get("platform") == platform
            and task.get("asset_type") == "cover_image"
        ):
            return task
    return None


def _storyboard_frame_tasks_for_platform(asset_tasks: dict[str, Any], platform: str) -> list[dict[str, Any]]:
    tasks = asset_tasks.get("tasks")
    if not isinstance(tasks, list):
        return []
    return [
        task
        for task in tasks
        if (
            isinstance(task, dict)
            and task.get("platform") == platform
            and task.get("asset_type") == "storyboard_frame"
        )
    ]


def _default_video_asset_plan(topic: str, platform: str, hook: str) -> dict[str, Any]:
    formats = {
        "douyin": {
            "aspect_ratio": "9:16",
            "safe_margin": "top 12%, bottom 18%",
            "duration_seconds": 29,
            "visual_style": "fast vertical workflow reveal, high contrast captions, mobile-first framing",
        },
        "shipinhao": {
            "aspect_ratio": "9:16",
            "safe_margin": "top 12%, bottom 20%",
            "duration_seconds": 29,
            "visual_style": "clean WeChat social context, calm motion, strong share/save cues",
        },
        "bilibili": {
            "aspect_ratio": "16:9",
            "safe_margin": "title-safe center 80%",
            "duration_seconds": 720,
            "visual_style": "chaptered desktop recording, architecture board, readable code/workflow panels",
        },
    }
    format_spec = formats.get(
        platform,
        {
            "aspect_ratio": "16:9",
            "safe_margin": "title-safe center 80%",
            "duration_seconds": 60,
            "visual_style": "clear production visuals with readable on-screen text",
        },
    )
    shot_list = _default_shot_list(topic, platform, hook)
    broll_list = _default_broll_list(topic, platform)
    return {
        "platform": platform,
        "platform_label": _platform_label(platform),
        "aspect_ratio": format_spec["aspect_ratio"],
        "safe_margin": format_spec["safe_margin"],
        "recommended_duration_seconds": format_spec["duration_seconds"],
        "visual_style": format_spec["visual_style"],
        "cover_prompt": _video_cover_prompt(topic, platform, hook, format_spec["aspect_ratio"]),
        "shot_list": shot_list,
        "broll_list": broll_list,
        "asset_clearance": {
            "copyright_status": "human_review_required",
            "allowed_asset_types": ["self-recorded", "self-designed", "licensed", "human-reviewed-generated"],
            "blocked_asset_types": ["uncleared logos", "private screenshots", "third-party creator clips"],
            "review_required": True,
        },
        "production_notes": [
            "Keep all text large enough for the target viewport.",
            "Use cleared footage, self-created UI boards, or generated images after human copyright review.",
            "Do not upload, sync, publish, or trigger platform interactions from the agent runner.",
        ],
        "review_required": True,
    }


def _build_asset_generation_tasks(
    topic: str,
    video_platforms: list[str],
    platform_plans: list[dict[str, Any]],
) -> dict[str, Any]:
    plans_by_platform = {str(plan["platform"]): plan for plan in platform_plans if plan.get("platform")}
    tasks: list[dict[str, Any]] = []
    for platform in video_platforms:
        plan = plans_by_platform.get(platform, {})
        aspect_ratio = str(plan.get("aspect_ratio") or ("16:9" if platform == "bilibili" else "9:16"))
        platform_label = _platform_label(platform)
        cover_task_id = f"{platform}_cover_generate"
        tasks.append(
            {
                "task_id": cover_task_id,
                "platform": platform,
                "platform_label": platform_label,
                "asset_type": "cover_image",
                "task_type": "generate_or_design",
                "status": "planned",
                "prompt": str(plan.get("cover_prompt") or _video_cover_prompt(topic, platform, "", aspect_ratio)),
                "target_path": f"assets/{platform}/cover/cover.png",
                "aspect_ratio": aspect_ratio,
                "rights_status": "pending_human_review",
                "manual_review_required": True,
                "acceptance_criteria": [
                    "Readable title at target viewport size.",
                    "No real platform logos or private data.",
                    "Asset source and rights status are recorded before use.",
                ],
            }
        )

        shot_list = plan.get("shot_list")
        if isinstance(shot_list, list):
            for index, shot in enumerate(shot_list, start=1):
                if not isinstance(shot, dict):
                    continue
                shot_id = str(shot.get("shot_id") or f"{platform}_shot_{index:02d}")
                tasks.append(
                    {
                        "task_id": f"{platform}_{shot_id}_frame",
                        "platform": platform,
                        "platform_label": platform_label,
                        "asset_type": "storyboard_frame",
                        "task_type": "generate_or_capture",
                        "status": "planned",
                        "prompt": str(shot.get("visual") or shot.get("purpose") or "Storyboard frame for the video beat."),
                        "target_path": f"assets/{platform}/storyboard/{shot_id}.png",
                        "aspect_ratio": aspect_ratio,
                        "linked_shot_id": shot_id,
                        "rights_status": "pending_human_review",
                        "manual_review_required": True,
                        "acceptance_criteria": [
                            "Frame clearly matches the linked shot purpose.",
                            "On-screen text is readable.",
                            "No uncleared third-party footage or private screenshots.",
                        ],
                    }
                )

        broll_list = plan.get("broll_list")
        if isinstance(broll_list, list):
            for item in broll_list:
                if not isinstance(item, dict):
                    continue
                asset_id = str(item.get("asset_id") or f"{platform}_broll")
                tasks.append(
                    {
                        "task_id": f"{platform}_{asset_id}_import",
                        "platform": platform,
                        "platform_label": platform_label,
                        "asset_type": "broll",
                        "task_type": "record_or_import",
                        "status": "planned",
                        "prompt": str(item.get("description") or "B-roll asset for the video package."),
                        "target_path": f"assets/{platform}/broll/{asset_id}.mp4",
                        "usage": str(item.get("usage") or "Use as supporting visual footage."),
                        "rights_status": "pending_human_review",
                        "manual_review_required": True,
                        "acceptance_criteria": [
                            "Imported asset has documented rights or is self-recorded.",
                            "No private data is visible.",
                            "Clip supports the declared usage beat.",
                        ],
                    }
                )

    return {
        "schema_version": "phase4.asset_generation_tasks.v1",
        "topic": topic,
        "generated_by": "asset-agent",
        "agent_interface": "run_agent(task_spec)",
        "video_platforms": video_platforms,
        "tasks": tasks,
        "execution_boundary": {
            "asset_generation": "not_performed",
            "asset_download": "not_performed",
            "asset_import": "not_performed",
            "rights_clearance": "human_review_required",
        },
        "review_required": True,
    }


def _build_media_asset_manifest(
    topic: str,
    run_id: str,
    asset_tasks: dict[str, Any],
) -> dict[str, Any]:
    assets = []
    for task in asset_tasks.get("tasks", []):
        if not isinstance(task, dict):
            continue
        assets.append(
            {
                "asset_id": str(task["task_id"]).replace("_generate", "").replace("_import", ""),
                "task_id": task["task_id"],
                "platform": task["platform"],
                "asset_type": task["asset_type"],
                "path": task["target_path"],
                "status": "planned",
                "source_type": task["task_type"],
                "rights_status": "pending_human_review",
                "manual_review_required": True,
                "used_by": _asset_usage_targets(str(task["platform"]), str(task["asset_type"])),
            }
        )
    return {
        "schema_version": "phase4.media_asset_manifest.v1",
        "run_id": run_id,
        "topic": topic,
        "generated_by": "asset-agent",
        "source_artifacts": ["asset_plan.json", "cover_prompts.md", "assets/asset_generation_tasks.json"],
        "assets": assets,
        "summary": {
            "asset_count": len(assets),
            "planned_count": len([asset for asset in assets if asset["status"] == "planned"]),
            "pending_rights_review_count": len(
                [asset for asset in assets if asset["rights_status"] == "pending_human_review"]
            ),
        },
        "review_required": True,
    }


def _asset_usage_targets(platform: str, asset_type: str) -> list[str]:
    if asset_type == "cover_image":
        return [f"{platform}/cover_prompt.md", "final/video_production_package.json"]
    if asset_type == "storyboard_frame":
        return [f"{platform}/storyboard.json", f"{platform}/shot_list.json", "final/video_production_package.json"]
    return [f"{platform}/broll_list.json", "final/video_production_package.json"]


def _asset_ingest_guide_markdown(
    topic: str,
    asset_tasks: dict[str, Any],
    media_asset_manifest: dict[str, Any],
) -> str:
    task_lines = [
        f"- {task['task_id']}: {task['asset_type']} -> {task['target_path']} ({task['status']})"
        for task in asset_tasks.get("tasks", [])
        if isinstance(task, dict)
    ]
    return "\n".join(
        [
            "# Asset Ingest Guide",
            "",
            f"Topic: {topic}",
            "",
            "This guide turns Phase 4 asset planning into concrete generation or import tasks.",
            "The runner does not generate, download, import, edit, upload, or publish media.",
            "",
            "## Required Boundary",
            "",
            "- Generate or import assets manually or through a later approved media adapter.",
            "- Record the source and rights status for every asset before using it.",
            "- Keep private data, platform logos, third-party creator clips, and uncleared music out of the package.",
            "",
            "## Planned Tasks",
            "",
            *task_lines,
            "",
            "## Manifest Summary",
            "",
            f"- Assets planned: {media_asset_manifest.get('summary', {}).get('asset_count', 0)}",
            f"- Pending rights review: {media_asset_manifest.get('summary', {}).get('pending_rights_review_count', 0)}",
            "",
            "Review required: true",
            "",
        ]
    )


def _default_shot_list(topic: str, platform: str, hook: str) -> list[dict[str, Any]]:
    if platform == "bilibili":
        return [
            {
                "shot_id": "bili_01",
                "purpose": "opening_context",
                "visual": "16:9 desktop recording with the workflow graph and five platform branches visible.",
                "voiceover_hint": hook,
                "duration_seconds": 80,
            },
            {
                "shot_id": "bili_02",
                "purpose": "architecture_walkthrough",
                "visual": "Zoom through orchestrator, common agents, platform agents, validator, and repair layer.",
                "voiceover_hint": f"Break down how {topic} turns one idea into production-ready platform packages.",
                "duration_seconds": 140,
            },
            {
                "shot_id": "bili_03",
                "purpose": "shared_layer",
                "visual": "Show research_report, angle_pack, and master_outline side by side as reusable upstream artifacts.",
                "voiceover_hint": "The shared layer aligns research, angle, and structure before platform adaptation.",
                "duration_seconds": 150,
            },
            {
                "shot_id": "bili_04",
                "purpose": "production_package_demo",
                "visual": "Show script, storyboard, subtitles, shot list, B-roll list, cover prompt, and review gates side by side.",
                "voiceover_hint": "The video package is what an editor can actually execute.",
                "duration_seconds": 160,
            },
            {
                "shot_id": "bili_05",
                "purpose": "review_boundary",
                "visual": "Checklist overlay for sources, asset rights, manual approval, and no auto-upload.",
                "voiceover_hint": "Publishing still stays behind human review.",
                "duration_seconds": 110,
            },
            {
                "shot_id": "bili_06",
                "purpose": "chapter_recap",
                "visual": "Chapter timeline recaps the major production package deliverables.",
                "voiceover_hint": "The final package connects the edit plan, assets, and review boundary.",
                "duration_seconds": 80,
            },
        ]
    return [
        {
            "shot_id": f"{platform}_01",
            "purpose": "hook",
            "visual": "Vertical close-up on five platform drafts splitting from one topic card.",
            "voiceover_hint": hook,
            "duration_seconds": 3,
        },
        {
            "shot_id": f"{platform}_02",
            "purpose": "pain",
            "visual": "Fast cuts of copy-paste, rewriting, and repeated formatting across platform windows.",
            "voiceover_hint": "The pain is repeated adaptation, not the first draft.",
            "duration_seconds": 5,
        },
        {
            "shot_id": f"{platform}_03",
            "purpose": "workflow_reveal",
            "visual": "Central orchestrator dispatching to research, topic, outline, asset, and platform agents.",
            "voiceover_hint": f"{topic} becomes a shared workflow before platform adaptation.",
            "duration_seconds": 10,
        },
        {
            "shot_id": f"{platform}_04",
            "purpose": "platform_branch",
            "visual": "Platform cards light up one by one for article, note, short video, social video, and long video.",
            "voiceover_hint": "Platform agents keep expression differences isolated from the shared workflow.",
            "duration_seconds": 6,
        },
        {
            "shot_id": f"{platform}_05",
            "purpose": "review_gate",
            "visual": "Human review gate with source, asset, and platform compliance checks.",
            "voiceover_hint": "No upload or publishing happens without human approval.",
            "duration_seconds": 6,
        },
        {
            "shot_id": f"{platform}_06",
            "purpose": "cta",
            "visual": "Freeze on the workflow overview with a clear next-step prompt.",
            "voiceover_hint": "Invite viewers to choose the next platform or adapter to automate.",
            "duration_seconds": 4,
        },
    ]


def _default_broll_list(topic: str, platform: str) -> list[dict[str, str]]:
    common = [
        {
            "asset_id": "workflow_board",
            "description": f"Self-created workflow board showing how {topic} moves from research to platform outputs.",
            "usage": "Use behind architecture explanation and final recap.",
            "rights_status": "self_created_or_human_review_required",
        },
        {
            "asset_id": "task_ledger_closeup",
            "description": "Close-up of task status, logs, artifacts, retry policy, and repair approval gate.",
            "usage": "Use when explaining reliability and recovery.",
            "rights_status": "self_created_or_human_review_required",
        },
    ]
    if platform == "bilibili":
        return common + [
            {
                "asset_id": "chapter_timeline",
                "description": "16:9 timeline with chapter markers and production package deliverables.",
                "usage": "Use between long-form sections.",
                "rights_status": "self_created_or_human_review_required",
            }
        ]
    return common + [
        {
            "asset_id": "vertical_caption_overlay",
            "description": "9:16 caption overlay with large Chinese text and clear safe margins.",
            "usage": "Use for hook, CTA, and checklist beats.",
            "rights_status": "self_created_or_human_review_required",
        }
    ]


def _video_cover_prompt(topic: str, platform: str, hook: str, aspect_ratio: str) -> str:
    if platform == "bilibili":
        return (
            f"Create a {aspect_ratio} Bilibili cover for `{topic}`. Show a central orchestrator panel connected to "
            "research, outline, asset plan, and three video platform production cards. Use large Chinese title text, "
            "clean technical composition, and no real platform logos. "
            f"Title idea: {hook}"
        )
    return (
        f"Create a {aspect_ratio} vertical cover for `{topic}`. Show one topic card branching into script, storyboard, "
        "subtitles, shot list, B-roll, and cover prompt deliverables. Use large readable Chinese title text, "
        "mobile-safe margins, bright neutral colors, and no real platform logos. "
        f"Title idea: {hook}"
    )


def _platform_asset_plan(asset_plan: Any, platform: str, topic: str, hook: str) -> dict[str, Any]:
    if isinstance(asset_plan, dict):
        plans = asset_plan.get("platform_plans")
        if isinstance(plans, list):
            for plan in plans:
                if isinstance(plan, dict) and plan.get("platform") == platform:
                    return plan
    return _default_video_asset_plan(topic, platform, hook)


def _shot_list_from_storyboard(
    storyboard: list[dict[str, Any]],
    platform: str,
    platform_asset_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    planned_shots = platform_asset_plan.get("shot_list")
    if not isinstance(planned_shots, list):
        planned_shots = []
    shots: list[dict[str, Any]] = []
    for index, scene in enumerate(storyboard, start=1):
        planned = planned_shots[index - 1] if index - 1 < len(planned_shots) and isinstance(planned_shots[index - 1], dict) else {}
        shots.append(
            {
                "shot_id": str(planned.get("shot_id") or f"{platform}_{index:02d}"),
                "scene": scene.get("scene"),
                "purpose": planned.get("purpose") or scene.get("scene"),
                "duration_seconds": scene.get("duration_seconds"),
                "visual": scene.get("visual"),
                "voiceover": scene.get("voiceover"),
                "edit_note": planned.get("visual") or "Keep pacing aligned with the storyboard beat.",
                "asset_requirements": [
                    "self-created workflow UI or screen recording",
                    "large readable captions",
                    "human-reviewed visuals only",
                ],
            }
        )
    return shots


def _broll_list_from_plan(platform_asset_plan: dict[str, Any]) -> list[dict[str, str]]:
    broll = platform_asset_plan.get("broll_list")
    if isinstance(broll, list):
        return [item for item in broll if isinstance(item, dict)]
    return []


def _platform_cover_prompt_markdown(
    topic: str,
    platform: str,
    hook: str,
    platform_asset_plan: dict[str, Any],
) -> str:
    title = {
        "douyin": "Douyin",
        "shipinhao": "Shipinhao",
        "bilibili": "Bilibili",
    }.get(platform, platform.title())
    cover_prompt = str(platform_asset_plan.get("cover_prompt") or _video_cover_prompt(topic, platform, hook, "16:9"))
    return "\n".join(
        [
            f"# {title} Cover Prompt",
            "",
            f"Topic: {topic}",
            "",
            cover_prompt,
            "",
            f"Aspect ratio: {platform_asset_plan.get('aspect_ratio', 'unknown')}",
            f"Safe margin: {platform_asset_plan.get('safe_margin', 'unknown')}",
            "",
            "Review note: use only cleared, self-created, licensed, or human-reviewed generated assets before publishing.",
            "",
        ]
    )


def _platform_audience(platform: str) -> str:
    return {
        "wechat": "需要系统化解释和完整方法论的读者",
        "xiaohongshu": "想快速收藏、复用方法的内容创作者",
        "douyin": "需要短时间理解一个工作流亮点的观众",
        "shipinhao": "愿意在微信社交关系中转发、收藏或私聊讨论的观众",
        "bilibili": "愿意看完整搭建过程和技术细节的观众",
    }.get(platform, "该平台的目标用户")


def _metadata_step_id(task_spec: Any) -> str | None:
    if not isinstance(task_spec, dict):
        return None
    metadata = task_spec.get("metadata")
    if not isinstance(metadata, dict):
        return None
    step_id = metadata.get("step_id")
    return str(step_id) if step_id else None


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _repair_root_cause(category: str, message: str) -> str:
    if category == "DATA_ERROR":
        return "A required upstream artifact, input file, or dependency appears to be missing or unreadable."
    if category == "SCHEMA_ERROR":
        return "The agent output likely failed the declared output contract or JSON shape."
    if category == "QUALITY_ERROR":
        return "The generated artifact likely failed a quality gate such as length, hook strength, title quality, or draft completeness."
    if category == "POLICY_ERROR":
        return "The failure indicates a policy, copyright, sensitive-content, or compliance concern that needs human review."
    if category == "PERMISSION_ERROR":
        return "The failure indicates an action requiring human permission, such as login, cookie refresh, upload, sync, or publishing."
    if "retry policy" in message.lower() or "budget" in message.lower():
        return "Automatic retry budget was exhausted; repeated execution should pause until the operator reviews the task state."
    return "The task failed with an environment or runtime issue that needs operator inspection before another resume."


def _repair_actions(category: str, step_id: str) -> list[str]:
    if category == "DATA_ERROR":
        return [
            f"Inspect upstream outputs required by `{step_id}` and confirm they exist in the run directory.",
            "Regenerate or restore missing artifacts before running resume again.",
            "Keep the current failure log for audit before any manual edits.",
        ]
    if category == "SCHEMA_ERROR":
        return [
            "Open the task log and compare the agent outputs with the declared workflow outputs.",
            "Fix the agent handler or output schema mismatch.",
            "Run validate-run after resume to confirm the contract is restored.",
        ]
    if category == "QUALITY_ERROR":
        return [
            "Review the generated draft against platform-specific quality gates.",
            "Adjust the agent prompt/handler or manually revise the weak artifact.",
            "Resume only after the revised artifact or handler can satisfy validation.",
        ]
    if category == "POLICY_ERROR":
        return [
            "Manually review the flagged content for compliance, copyright, or sensitive-content risk.",
            "Remove or rewrite risky claims before any rerun or publication.",
            "Keep human approval notes with the repair log.",
        ]
    if category == "PERMISSION_ERROR":
        return [
            "Confirm whether login, cookie refresh, upload, sync, or publish was requested.",
            "Perform any required permission-gated action manually outside the agent runner.",
            "Resume only after the permission boundary is explicitly satisfied.",
        ]
    return [
        f"Inspect the task log for `{step_id}` and verify local dependencies and file permissions.",
        "If retry budget was exhausted, confirm no external process is still running before any manual resume.",
        "Resume after the environment issue is fixed or intentionally accepted.",
    ]


def _platform_hook(topic: str, platform: str) -> str:
    return {
        "wechat": f"{topic} 不是多写几个 prompt，而是把内容生产变成可复盘的工作流。",
        "xiaohongshu": f"同一个选题不用改五遍，先搭一套 {topic} 工作流。",
        "douyin": f"一个选题，五个平台版本，怎么自动拆出来？",
        "shipinhao": f"一个选题，怎么变成能被朋友转发的视频号内容？",
        "bilibili": f"从零拆解 {topic}：总控 agent 如何分配内容生产任务。",
    }.get(platform, f"用 {topic} 改善内容生产流程。")


def _platform_content_promise(topic: str, platform: str) -> str:
    return {
        "wechat": f"讲清 {topic} 的架构、流程、边界和落地路径。",
        "xiaohongshu": f"给出 {topic} 的轻量搭建思路和可收藏清单。",
        "douyin": f"用快节奏脚本展示 {topic} 如何把一个主题拆成多平台产物。",
        "shipinhao": f"用更适合微信社交场景的短视频脚本讲清 {topic} 的核心价值。",
        "bilibili": f"用章节化方式展示 {topic} 的设计逻辑和后续开发路线。",
    }.get(platform, f"输出适合平台的 {topic} 内容角度。")


def _platform_research_angle(topic: str, platform: str) -> str:
    return {
        "wechat": f"Use `{topic}` as a long-form explanation with structure, examples, and clear takeaways.",
        "xiaohongshu": f"Turn `{topic}` into a concise, experience-led note with a save-worthy checklist.",
        "douyin": f"Frame `{topic}` as a short hook-driven workflow reveal with fast visual progression.",
        "shipinhao": f"Frame `{topic}` as a social-sharing video that can trigger WeChat conversation and private-domain follow-up.",
        "bilibili": f"Explain `{topic}` as a chaptered build log with enough depth for long-form viewers.",
    }.get(platform, f"Adapt `{topic}` to this platform's native format.")


def _platform_evidence_needed(platform: str) -> str:
    return {
        "wechat": "authoritative references and source notes for factual claims",
        "xiaohongshu": "platform format examples and labeling requirements",
        "douyin": "short-video pacing examples and asset clearance",
        "shipinhao": "WeChat Channels format examples, asset clearance, and private-domain CTA review",
        "bilibili": "chapter structure examples and technical detail checks",
    }.get(platform, "platform-specific examples and source checks")


def _platform_outline_goal(platform: str) -> str:
    return {
        "wechat": "turn the shared thesis into a structured article with clear sections and source notes",
        "xiaohongshu": "turn the shared thesis into a short note with a concrete hook, tags, and cover direction",
        "douyin": "turn the shared thesis into a quick script with a strong first-three-second hook",
        "shipinhao": "turn the shared thesis into a WeChat Channels script with a social hook and private-domain CTA",
        "bilibili": "turn the shared thesis into a deeper video outline with chapters and context",
    }.get(platform, "adapt the shared thesis into the platform's native output format")


def _platform_angle(angle_pack: Any, platform: str) -> dict[str, Any]:
    if not isinstance(angle_pack, dict):
        return {}
    angles = angle_pack.get("angles")
    if not isinstance(angles, list):
        return {}
    for angle in angles:
        if isinstance(angle, dict) and angle.get("platform") == platform:
            return angle
    return {}


def _wechat_title(topic: str) -> str:
    return f"{topic}：从选题到多平台内容包"


def _wechat_title_options(topic: str) -> list[str]:
    return [
        f"{topic}：一套系统生成多平台内容",
        "内容创作者为什么需要自己的 Agent 工作流",
        "从选题到发布前审核：多平台内容生产线怎么搭",
    ]


def _wechat_summary(topic: str) -> str:
    return f"一篇面向微信公众号读者的系统化说明，解释如何用统一 agent 框架搭建 {topic} 的内容生产闭环。"


def _wechat_source_notes(sources: Any) -> list[dict[str, str]]:
    planned_sources: list[dict[str, Any]] = []
    if isinstance(sources, dict):
        raw_planned_sources = sources.get("planned_sources")
        if isinstance(raw_planned_sources, list):
            planned_sources = [item for item in raw_planned_sources if isinstance(item, dict)]

    if not planned_sources:
        return [
            {
                "claim": "正式发布前需要补充平台规则、工具文档或案例来源。",
                "source": "sources.json 尚未包含真实外部来源；V1 当前只生成来源计划。",
            }
        ]

    notes = []
    for item in planned_sources[:3]:
        query = str(item.get("query") or "待补充来源查询")
        reason = str(item.get("reason") or "用于正式发布前核查。")
        notes.append({"claim": reason, "source": f"planned source query: {query}"})
    return notes


def _wechat_article_markdown(
    topic: str,
    title: str,
    hook: str,
    content_promise: str,
    source_notes: list[dict[str, str]],
) -> str:
    source_lines = [f"- {item['claim']} 来源状态：{item['source']}" for item in source_notes]
    return "\n".join(
        [
            f"# {title}",
            "",
            f"> {hook}",
            "",
            "## 为什么先做统一框架",
            "",
            "很多内容创作者真正消耗时间的地方，不是写出第一版，而是把同一个选题反复改成公众号、小红书、抖音、视频号和B站五种表达。",
            "",
            f"`{topic}` 的价值在于：先把研究、选题、总大纲和审核做成共享层，再让不同平台 agent 负责各自的表达格式。",
            "",
            "## 这套工作流怎么分层",
            "",
            "第一层是总控 agent。它负责读取 workflow，判断依赖关系，生成 task_spec，并记录每一步的运行状态。",
            "",
            "第二层是通用专家 agent。research-agent 负责研究简报，topic-agent 负责选题角度，outline-agent 负责主线大纲。",
            "",
            "第三层是平台 agent。微信公众号文章需要更完整的结构、上下文和来源说明；小红书笔记则更重标题、收藏价值、标签和封面。",
            "",
            "## 微信公众号这一版怎么写",
            "",
            f"{content_promise}",
            "",
            "所以公众号稿不追求短平快，而是要把系统设计讲清楚：为什么要统一总控，哪些能力应该模块化，哪些动作必须留给人工审批。",
            "",
            "对读者来说，最有用的不是看到一个漂亮概念，而是能照着拆出自己的第一条工作流：输入主题，生成研究报告，拆角度，出总大纲，再分发到平台产出 agent。",
            "",
            "## 现在的边界",
            "",
            "当前版本仍是本地 agent 生成稿，没有调用外部模型，也没有打开浏览器、登录平台、刷新 cookie、上传或发布内容。",
            "",
            "正式发布前，还需要补齐真实来源、核查平台规则、确认素材版权，并经过人工审核。",
            "",
            "## 参考来源状态",
            "",
            *source_lines,
            "",
            "## 互动问题",
            "",
            "如果你先落地这套系统，会优先自动化微信公众号、小红书，还是短视频脚本？",
            "",
            "---",
            "",
            "人工审核标记：本文为 agent-local 草稿，发布前必须人工复核。",
            "",
        ]
    )


def _xiaohongshu_title(topic: str) -> str:
    compact = topic.replace("系统", "").replace("自动化", "自动化")
    if "AI内容创作" in compact:
        return "AI内容创作自动化"
    return (compact[:18] or "内容工作流搭建")


def _xiaohongshu_content(topic: str, hook: str, content_promise: str) -> str:
    return (
        f"{hook}\n\n"
        "我现在的搭建思路是：先让 research-agent 做共享研究，再让 topic-agent 把角度拆出来，"
        "outline-agent 生成总大纲，最后交给平台 agent 分别改写。\n\n"
        f"小红书这一版重点不是长篇讲原理，而是把 `{topic}` 讲成可以收藏的流程："
        "一个总控负责派发任务，通用 agent 负责研究和大纲，平台 agent 负责标题、正文、标签和封面。\n\n"
        f"{content_promise}\n\n"
        "目前这还是本地 agent 生成稿，没有自动发布，也没有登录或上传动作。正式发布前我会补来源、做事实核查，再人工确认。\n\n"
        "简单说：先把内容生产变成工作流，再让不同平台各自说人话。"
    )


def _xiaohongshu_tags(topic: str) -> list[str]:
    tags = ["#内容创作", "#AI工具", "#自媒体运营", "#工作流", "#小红书运营", "#AI生成内容"]
    if "Agent" in topic or "agent" in topic:
        tags.insert(2, "#Agent")
    return tags[:8]


def _xiaohongshu_cover_prompt(topic: str, hook: str) -> str:
    return (
        f"Create a clean Xiaohongshu-style 3:4 vertical cover for `{topic}`. "
        "Use a bright, organized desktop workflow scene with one central orchestrator panel branching into research, topic, outline, and Xiaohongshu note cards. "
        f"Main cover text idea: {hook} Keep the composition readable on mobile."
    )


def _douyin_storyboard(topic: str, hook: str) -> list[dict[str, Any]]:
    return [
        {
            "scene": "opening_hook",
            "visual": "手机屏幕上同时出现公众号、小红书、抖音、视频号和B站五个待改写草稿，画面快速推近。",
            "voiceover": hook,
            "duration_seconds": 3,
        },
        {
            "scene": "pain_point",
            "visual": "创作者在四个窗口之间来回复制粘贴，时间轴快速跳动。",
            "voiceover": "最累的不是写第一版，而是同一个主题被迫改成五种表达。",
            "duration_seconds": 5,
        },
        {
            "scene": "workflow_reveal",
            "visual": "一个总控面板把任务分发给 research、topic、outline 和平台 agent。",
            "voiceover": f"我的做法是把 {topic} 拆成共享研究层和平台产出层。",
            "duration_seconds": 6,
        },
        {
            "scene": "platform_branch",
            "visual": "四张平台卡片依次亮起：长文、笔记、短视频脚本、长视频脚本。",
            "voiceover": "总控负责任务顺序，专家 agent 负责具体内容，平台 agent 只处理表达差异。",
            "duration_seconds": 6,
        },
        {
            "scene": "safety_gate",
            "visual": "发布按钮前出现人工审核、来源核查、素材版权三个检查项。",
            "voiceover": "最后一步必须人工审核，不自动登录、不自动上传、不自动发布。",
            "duration_seconds": 5,
        },
        {
            "scene": "cta",
            "visual": "画面停在工作流总览图，突出下一步接入真实模型生成。",
            "voiceover": "想看我继续把抖音脚本接入真实 agent，评论区告诉我。",
            "duration_seconds": 4,
        },
    ]


def _douyin_script_markdown(
    topic: str,
    hook: str,
    content_promise: str,
    storyboard: list[dict[str, Any]],
) -> str:
    shot_lines = [
        f"- {index}. {scene['scene']} ({scene['duration_seconds']}s): {scene['visual']} VO: {scene['voiceover']}"
        for index, scene in enumerate(storyboard, start=1)
    ]
    return "\n".join(
        [
            "# Douyin Script",
            "",
            f"Topic: {topic}",
            "",
            "## First 3 Seconds Hook",
            "",
            hook,
            "",
            "## Core Promise",
            "",
            content_promise,
            "",
            "## Voiceover Script",
            "",
            *[f"{index}. {scene['voiceover']}" for index, scene in enumerate(storyboard, start=1)],
            "",
            "## Shot List",
            "",
            *shot_lines,
            "",
            "## Cover Direction",
            "",
            "竖版 9:16，中心是一个内容工作流总控面板，五个平台卡片向外分发。标题强调“一个选题自动拆五版”。",
            "",
            "## Asset Notes",
            "",
            "- 只使用自有录屏、自制 UI 示意图或已授权素材。",
            "- 当前产物是 agent-local 脚本包，不执行自动剪辑、上传或发布。",
            "- 发布前需要人工复核事实、素材版权和平台表达合规。",
            "",
            "Review required: true",
            "",
        ]
    )


def _douyin_subtitles(storyboard: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    cursor = 0
    for index, scene in enumerate(storyboard, start=1):
        duration = int(scene["duration_seconds"])
        start = _srt_timestamp(cursor)
        cursor += duration
        end = _srt_timestamp(cursor)
        blocks.append(f"{index}\n{start} --> {end}\n{scene['voiceover']}")
    return "\n\n".join(blocks) + "\n"


def _srt_timestamp(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d},000"


def _shipinhao_storyboard(topic: str, hook: str) -> list[dict[str, Any]]:
    return [
        {
            "scene": "social_hook",
            "visual": "微信聊天窗口里弹出一个视频号卡片，标题强调一个选题如何拆成多平台内容。",
            "voiceover": hook,
            "duration_seconds": 3,
        },
        {
            "scene": "shared_pain",
            "visual": "创作者面对公众号、小红书、抖音、视频号、B站五张内容卡片，逐个勾选。",
            "voiceover": "做内容最容易卡住的，是同一个主题在不同场景里反复改写。",
            "duration_seconds": 5,
        },
        {
            "scene": "workflow_answer",
            "visual": "中心总控面板向 research、topic、outline 和平台 agent 分发任务。",
            "voiceover": f"我的做法是用 {topic} 工作流，先共享研究和大纲，再分平台表达。",
            "duration_seconds": 6,
        },
        {
            "scene": "wechat_channels_angle",
            "visual": "视频号画面切到朋友圈、群聊和公众号入口，展示社交转发路径。",
            "voiceover": "视频号这一版不只追求快，还要适合转发、收藏和私聊讨论。",
            "duration_seconds": 6,
        },
        {
            "scene": "human_review_gate",
            "visual": "上传按钮前出现来源核查、素材版权、人工审核三个检查项。",
            "voiceover": "发布前必须人工确认，不自动登录、不自动上传、不自动同步朋友圈。",
            "duration_seconds": 5,
        },
        {
            "scene": "private_domain_cta",
            "visual": "画面停在工作流总览，底部出现“想要流程图，评论区留言”。",
            "voiceover": "如果你也想要这套内容工作流，评论区留一个想先自动化的平台。",
            "duration_seconds": 4,
        },
    ]


def _shipinhao_script_markdown(
    topic: str,
    hook: str,
    content_promise: str,
    storyboard: list[dict[str, Any]],
) -> str:
    shot_lines = [
        f"- {index}. {scene['scene']} ({scene['duration_seconds']}s): {scene['visual']} VO: {scene['voiceover']}"
        for index, scene in enumerate(storyboard, start=1)
    ]
    return "\n".join(
        [
            "# Shipinhao Script",
            "",
            f"Topic: {topic}",
            "",
            "## First 3 Seconds Social Hook",
            "",
            hook,
            "",
            "## Core Promise",
            "",
            content_promise,
            "",
            "## Voiceover Script",
            "",
            *[f"{index}. {scene['voiceover']}" for index, scene in enumerate(storyboard, start=1)],
            "",
            "## Storyboard",
            "",
            *shot_lines,
            "",
            "## Cover Direction",
            "",
            "竖版 9:16，微信社交语境，中心是内容工作流面板，周围有公众号、小红书、抖音、视频号、B站五个平台卡片。标题强调“一个选题拆成五个平台内容”。",
            "",
            "## Private Domain CTA",
            "",
            "评论区留言你想先自动化的平台；正式发布前可引导到私聊或社群领取流程图，但不自动触发互动或群发。",
            "",
            "## Asset Notes",
            "",
            "- 只使用自有录屏、自制 UI 示意图或已授权素材。",
            "- 当前产物是 agent-local 脚本包，不执行自动剪辑、登录、上传、同步朋友圈或发布。",
            "- 发布前需要人工复核事实、素材版权和微信生态表达边界。",
            "",
            "Review required: true",
            "",
        ]
    )


def _shipinhao_cover_prompt(topic: str, hook: str) -> str:
    return "\n".join(
        [
            "# Shipinhao Cover Prompt",
            "",
            f"Topic: {topic}",
            "",
            f"Create a 9:16 WeChat Channels cover for `{topic}` with a clean workflow board, five platform cards, and a social-sharing feel.",
            f"Main title idea: {hook}",
            "Use large readable Chinese typography, bright neutral colors, no real platform logos, and leave safe margins for mobile UI overlays.",
            "",
            "Review note: use only cleared visual assets before publishing.",
            "",
        ]
    )


def _bilibili_chapters() -> list[dict[str, str]]:
    return [
        {"time": "00:00", "title": "开场：为什么一个选题会变成四份重复劳动"},
        {"time": "01:20", "title": "总控 agent：负责 workflow、依赖和任务日志"},
        {"time": "03:40", "title": "通用专家层：研究、选题和主线大纲如何复用"},
        {"time": "06:10", "title": "平台产出层：公众号、小红书、抖音、视频号、B站各自怎么表达"},
        {"time": "09:00", "title": "安全边界：来源核查、素材版权和人工审批"},
        {"time": "11:30", "title": "下一步：接入真实模型、持久化和失败修复"},
    ]


def _bilibili_storyboard(topic: str, hook: str, chapters: list[dict[str, str]]) -> list[dict[str, Any]]:
    chapter_titles = [chapter["title"] for chapter in chapters]
    return [
        {
            "scene": "opening_context",
            "visual": "16:9 桌面画面展示一个选题被拆成公众号、小红书、抖音、视频号和B站五个内容出口。",
            "voiceover": hook,
            "duration_seconds": 80,
        },
        {
            "scene": "orchestrator_walkthrough",
            "visual": "放大 workflow graph：research、topic、outline、asset、platform、review、repair 依次亮起。",
            "voiceover": f"这一期用 {topic} 拆解一套可追踪、可重跑、可审核的内容生产系统。",
            "duration_seconds": 140,
        },
        {
            "scene": "shared_layer",
            "visual": "并排展示 research_report、angle_pack、master_outline 三个共享产物。",
            "voiceover": "共享层先统一研究、角度和主线，平台 agent 后面只处理表达差异。",
            "duration_seconds": 150,
        },
        {
            "scene": "video_package_layer",
            "visual": "展示视频生产包六件套：脚本、分镜、字幕、shot list、B-roll list、封面提示。",
            "voiceover": "Phase 4 的关键，是让视频产物能直接交给剪辑，而不是只给一段文字。",
            "duration_seconds": 160,
        },
        {
            "scene": "human_review_boundary",
            "visual": "最终检查表突出来源核查、素材版权、人工审批和不自动上传。",
            "voiceover": "所有上传、发布、素材版权和平台规则判断，都保留人工确认。",
            "duration_seconds": 110,
        },
        {
            "scene": "chapter_recap",
            "visual": "时间轴列出章节：" + "；".join(chapter_titles[:4]),
            "voiceover": "最后把这些产物放进 final/video_production_package.json，形成可验收的视频生产包。",
            "duration_seconds": 80,
        },
    ]


def _bilibili_title_options(topic: str) -> list[str]:
    return [
        f"{topic}：从零搭一套多平台内容 Agent 工作流",
        "我把公众号、小红书、抖音、视频号、B站内容生产拆成了一套 Agent 系统",
        "一个选题如何自动变成五个平台内容包？完整架构拆解",
    ]


def _bilibili_script_markdown(
    topic: str,
    hook: str,
    content_promise: str,
    chapters: list[dict[str, str]],
) -> str:
    chapter_lines = [f"- {chapter['time']} {chapter['title']}" for chapter in chapters]
    return "\n".join(
        [
            "# Bilibili Video Script",
            "",
            "## Title Options",
            "",
            *[f"- {title}" for title in _bilibili_title_options(topic)],
            "",
            "## Opening",
            "",
            hook,
            "",
            "这一期不讲单个 prompt，而是从工程视角拆一套可以持续运行、可以复盘、可以扩展的平台内容生产系统。",
            "",
            "## Viewer Expectation",
            "",
            content_promise,
            "",
            "看完之后，你应该能判断：哪些 agent 该做成通用能力，哪些必须做成平台插件，哪些动作必须留给人工审批。",
            "",
            "## Chapters",
            "",
            *chapter_lines,
            "",
            "## Full Script",
            "",
            "### 1. 开场：重复劳动的问题",
            "",
            f"如果你正在做 `{topic}`，最容易低估的不是写作本身，而是同一个选题在不同平台上的二次、三次、四次改写。",
            "",
            "公众号要完整结构，小红书要强钩子和标签，抖音要前三秒，B站要上下文、章节和技术细节。",
            "",
            "### 2. 总控 agent 的职责",
            "",
            "总控不是替每个平台写内容，而是负责读取 workflow、判断依赖、生成 task_spec、记录 task log，并把任务交给合适的专家 agent。",
            "",
            "这样每一步都有输入、输出、状态和失败边界。后续做重跑、修复和人工审批时，系统才不会变成一团不可追踪的自动化脚本。",
            "",
            "### 3. 通用专家层如何复用",
            "",
            "research-agent 先产出研究简报和来源计划，topic-agent 再拆平台角度，outline-agent 负责生成共享主线。",
            "",
            "这三个能力不应该被每个平台重复实现。它们是内容生产线的公共底座。",
            "",
            "### 4. 平台产出层如何分工",
            "",
            "平台 agent 只负责表达差异：微信公众号输出长文，小红书输出笔记和封面提示词，抖音输出短视频脚本、分镜和字幕，B站输出长视频结构、章节和简介。",
            "",
            "这也是插件化的价值：总控统一，能力模块化，平台差异插件化。",
            "",
            "### 5. 安全边界",
            "",
            "现在这个版本不会自动登录、不会刷新 cookie、不会上传视频，也不会发布内容。",
            "",
            "真实发布前，必须补齐来源核查、素材版权确认、平台规则检查和人工复核。",
            "",
            "### 6. 下一步",
            "",
            "后续可以继续接入真实模型调用、持久化 task ledger、失败修复 agent 和一键部署脚本。",
            "",
            "但在那之前，先把每个平台的本地 agent handler 全部接通，是更稳的第一步。",
            "",
            "## Cover Direction",
            "",
            "16:9 横版封面，一个中心总控面板连接五个平台内容卡片，左侧放标题“一个选题生成五个平台内容包”，右侧展示 workflow 节点。",
            "",
            "## Review Boundary",
            "",
            "Review required: true. This is an agent-local draft package; no upload, no publish, and no uncleared assets.",
            "",
        ]
    )


def _bilibili_description_markdown(topic: str, hook: str, chapters: list[dict[str, str]]) -> str:
    chapter_lines = [f"- {chapter['time']} {chapter['title']}" for chapter in chapters]
    tags = ["#内容创作", "#AI工具", "#Agent", "#自动化工作流", "#自媒体运营"]
    return "\n".join(
        [
            f"# {topic}：多平台内容 Agent 工作流拆解",
            "",
            hook,
            "",
            "这期视频用一个本地 V1 项目拆解内容自动化系统：总控负责工作流，通用 agent 负责研究和大纲，平台 agent 负责不同平台的表达。",
            "",
            "## 时间轴",
            "",
            *chapter_lines,
            "",
            "## 标签",
            "",
            " ".join(tags),
            "",
            "## 发布前检查",
            "",
            "- 本简介为 agent-local 草稿。",
            "- 未执行上传或发布。",
            "- 正式投稿前需要人工复核来源、素材版权和平台规则。",
            "",
            "review_required: true",
            "",
        ]
    )


def _extract_platform_opportunities(research_report: str, platforms: list[str]) -> dict[str, str]:
    opportunities: dict[str, str] = {}
    labels = {_platform_label(platform): platform for platform in platforms}
    for line in research_report.splitlines():
        clean = line.strip()
        if not clean.startswith("- "):
            continue
        for label, platform in labels.items():
            prefix = f"- {label}:"
            if clean.startswith(prefix):
                opportunities[platform] = clean.removeprefix(prefix).strip()
    return opportunities


def _primary_angle(angle_pack: Any) -> str:
    if not isinstance(angle_pack, dict):
        return "workflow-first content creation"
    primary_angle = angle_pack.get("primary_angle")
    if isinstance(primary_angle, dict):
        return str(primary_angle.get("name") or primary_angle.get("hook") or "workflow-first content creation")
    angles = angle_pack.get("angles")
    if not isinstance(angles, list) or not angles:
        return "workflow-first content creation"
    first = angles[0]
    if isinstance(first, dict):
        return str(first.get("name") or first.get("hook") or "workflow-first content creation")
    return str(first)


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
