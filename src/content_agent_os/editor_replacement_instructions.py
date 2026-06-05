from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr


@dataclass(frozen=True)
class GeneratedEditorReplacementInstructions:
    manifest: dict[str, Any]
    replacement_commands: dict[str, Any]
    import_template_fcpxml: str
    confirmation_checklist_md: str
    readme_text: str


INSTRUCTION_BOUNDARY = "performed_locally_template_and_instruction_only"


def generate_editor_replacement_instructions(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    replacement_suggestions: dict[str, Any],
    proxy_manifest: dict[str, Any],
    edit_timeline: dict[str, Any],
    offline_report: dict[str, Any],
    export_manifest: dict[str, Any],
    manifest_path: str,
    commands_path: str,
    import_template_path: str,
    checklist_path: str,
    readme_path: str,
) -> GeneratedEditorReplacementInstructions:
    suggestions = [
        item
        for item in replacement_suggestions.get("suggestions", [])
        if isinstance(item, dict) and item.get("asset_id")
    ]
    offline_slots = _offline_slots_by_asset_id(offline_report)
    timeline_clips = _timeline_clips_by_asset_id(edit_timeline)
    proxy_assets = _proxy_assets_by_asset_id(proxy_manifest)

    instructions = [
        _instruction_for_suggestion(
            run_dir=run_dir,
            platform=platform,
            suggestion=suggestion,
            slot=offline_slots.get(str(suggestion["asset_id"])),
            clip=timeline_clips.get(str(suggestion["asset_id"])),
            proxy_asset=proxy_assets.get(str(suggestion["asset_id"])),
        )
        for suggestion in suggestions
    ]

    ready_count = len([item for item in instructions if item["instruction_status"] == "ready_pending_human_confirmation"])
    pending_count = len([item for item in instructions if item["instruction_status"] == "pending_human_media"])
    blocked_count = len([item for item in instructions if item["instruction_status"].startswith("blocked_")])
    executable_after_confirmation_count = len(
        [item for item in instructions if item.get("can_execute_after_human_confirmation") is True]
    )
    all_confirmation_gated = all(item.get("human_confirmation_required") is True for item in instructions)
    no_execution = all(item.get("execution_status") == "not_executed" for item in instructions)

    source_artifacts = _dedupe(
        [
            replacement_suggestions.get("replacement_suggestions_path"),
            proxy_manifest.get("manifest_path"),
            proxy_manifest.get("readme_path"),
            export_manifest.get("project_path"),
            export_manifest.get("manifest_path"),
            offline_report.get("project_path"),
            *[
                value
                for instruction in instructions
                for value in [
                    instruction.get("proxy_media_path"),
                    instruction.get("licensed_media_path"),
                    instruction.get("reference_path"),
                ]
                if isinstance(value, str) and value
            ],
            manifest_path,
            commands_path,
            import_template_path,
            checklist_path,
            readme_path,
        ]
    )

    export_boundary = {
        "editor_replacement_instructions": INSTRUCTION_BOUNDARY,
        "replacement_execution": "not_performed",
        "editing_software": "not_opened",
        "project_file_mutation": "not_performed",
        "asset_download": "not_performed",
        "external_asset_search": "not_performed",
        "license_purchase": "not_performed",
        "upload": "not_performed",
        "publishing": "not_performed",
    }
    validation = {
        "status": "PASSED" if bool(instructions) and all_confirmation_gated and no_execution else "NEEDS_REVIEW",
        "instruction_count": len(instructions),
        "ready_pending_human_confirmation_count": ready_count,
        "pending_human_media_count": pending_count,
        "blocked_instruction_count": blocked_count,
        "executable_after_human_confirmation_count": executable_after_confirmation_count,
        "human_confirmation_gate_active": all_confirmation_gated,
        "replacement_execution_performed": False,
        "editing_software_opened": False,
    }
    summary = {
        "instruction_count": len(instructions),
        "ready_pending_human_confirmation_count": ready_count,
        "pending_human_media_count": pending_count,
        "blocked_instruction_count": blocked_count,
        "executable_after_human_confirmation_count": executable_after_confirmation_count,
        "import_template_asset_count": ready_count,
        "human_confirmation_required_count": len([item for item in instructions if item["human_confirmation_required"]]),
    }
    manifest = {
        "schema_version": "phase4.editor_replacement_instruction_manifest.v1",
        "artifact_type": "editor_replacement_instructions",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-editor-replacement-instruction-adapter",
        "adapter_version": "0.1.0",
        "manifest_path": manifest_path,
        "replacement_commands_path": commands_path,
        "editor_import_template_path": import_template_path,
        "human_confirmation_checklist_path": checklist_path,
        "readme_path": readme_path,
        "source_replacement_suggestions_path": replacement_suggestions.get("replacement_suggestions_path"),
        "source_proxy_manifest_path": proxy_manifest.get("manifest_path"),
        "source_export_project_path": export_manifest.get("project_path"),
        "source_artifacts": source_artifacts,
        "instructions": instructions,
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "generation_status": "generated_local_editor_replacement_templates_pending_human_confirmation",
        "manual_review_required": True,
        "human_confirmation_required": True,
        "review_required": True,
    }
    replacement_commands = {
        "schema_version": "phase4.editor_replacement_commands.v1",
        "artifact_type": "editor_replacement_commands",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "manifest_path": manifest_path,
        "replacement_commands_path": commands_path,
        "commands": [_command_for_instruction(item) for item in instructions],
        "summary": summary,
        "export_boundary": export_boundary,
        "validation": validation,
        "manual_review_required": True,
        "human_confirmation_required": True,
        "review_required": True,
    }
    return GeneratedEditorReplacementInstructions(
        manifest=manifest,
        replacement_commands=replacement_commands,
        import_template_fcpxml=_render_import_template_fcpxml(
            topic=topic,
            platform_label=platform_label,
            frame_rate=int(edit_timeline.get("frame_rate") or 30),
            instructions=instructions,
            run_dir=run_dir,
        ),
        confirmation_checklist_md=_render_confirmation_checklist(
            topic=topic,
            platform_label=platform_label,
            manifest=manifest,
        ),
        readme_text=_render_readme(topic=topic, platform_label=platform_label, manifest=manifest),
    )


def _instruction_for_suggestion(
    *,
    run_dir: Path,
    platform: str,
    suggestion: dict[str, Any],
    slot: dict[str, Any] | None,
    clip: dict[str, Any] | None,
    proxy_asset: dict[str, Any] | None,
) -> dict[str, Any]:
    asset_id = str(suggestion["asset_id"])
    proxy_media_path = _optional_string(suggestion.get("proxy_media_path"))
    if not proxy_media_path and isinstance(proxy_asset, dict):
        proxy_media_path = _optional_string(proxy_asset.get("proxy_media_path"))
    proxy_file = _resolve_local_path(run_dir, proxy_media_path)
    proxy_exists = bool(proxy_file and proxy_file.exists() and proxy_file.is_file())
    replacement_status = str(suggestion.get("replacement_status") or "")
    editor_ready = suggestion.get("editor_replacement_ready") is True

    if editor_ready and proxy_media_path and proxy_exists:
        instruction_status = "ready_pending_human_confirmation"
        can_execute = True
        action = "replace_broll_placeholder_with_proxy_media"
        instruction = "After human confirmation, replace the offline B-roll placeholder with the proxy media path."
    elif editor_ready and proxy_media_path and not proxy_exists:
        instruction_status = "blocked_proxy_media_missing"
        can_execute = False
        action = "fix_missing_proxy_media_before_replacement"
        instruction = "Proxy media is registered but missing on disk; regenerate proxy copy or fix the path."
    elif replacement_status == "candidate_registered_pending_review":
        instruction_status = "blocked_pending_rights_or_editor_review"
        can_execute = False
        action = "complete_human_review_before_replacement"
        instruction = "Complete human rights and editor review before generating an executable replacement command."
    else:
        instruction_status = "pending_human_media"
        can_execute = False
        action = "collect_approved_local_media_before_replacement"
        instruction = "Provide approved local media in human_media_registry.json, then rerun ingest and proxy."

    return {
        "asset_id": asset_id,
        "platform": platform,
        "shot_id": (slot or {}).get("shot_id") or (clip or {}).get("id"),
        "timeline_track": (clip or {}).get("track") or "V1",
        "start_seconds": (slot or {}).get("start_seconds") if isinstance(slot, dict) else (clip or {}).get("start_seconds"),
        "end_seconds": (slot or {}).get("end_seconds") if isinstance(slot, dict) else (clip or {}).get("end_seconds"),
        "duration_seconds": (slot or {}).get("duration_seconds") if isinstance(slot, dict) else (clip or {}).get("duration_seconds"),
        "placeholder_source_path": (clip or {}).get("source_path"),
        "reference_path": suggestion.get("reference_path"),
        "licensed_media_path": suggestion.get("licensed_media_path") or (proxy_asset or {}).get("licensed_media_path"),
        "proxy_media_path": proxy_media_path,
        "proxy_media_exists": proxy_exists,
        "proxy_media_sha256": (proxy_asset or {}).get("proxy_media_sha256"),
        "source_media_sha256": (proxy_asset or {}).get("source_media_sha256"),
        "replacement_status": replacement_status or instruction_status,
        "instruction_status": instruction_status,
        "automation_action": action,
        "automation_instruction": instruction,
        "can_execute_after_human_confirmation": can_execute,
        "human_confirmation_required": True,
        "confirmation_gate_status": "pending_human_confirmation",
        "execution_status": "not_executed",
        "editing_software_opened": False,
    }


def _command_for_instruction(instruction: dict[str, Any]) -> dict[str, Any]:
    return {
        "command_id": f"replace_{instruction['asset_id']}",
        "command_type": "nle_broll_replacement",
        "target_editor": "fcpxml_compatible_editor",
        "asset_id": instruction["asset_id"],
        "shot_id": instruction.get("shot_id"),
        "timeline_track": instruction.get("timeline_track"),
        "start_seconds": instruction.get("start_seconds"),
        "end_seconds": instruction.get("end_seconds"),
        "placeholder_source_path": instruction.get("placeholder_source_path"),
        "proxy_media_path": instruction.get("proxy_media_path"),
        "proxy_media_sha256": instruction.get("proxy_media_sha256"),
        "instruction_status": instruction.get("instruction_status"),
        "can_execute_after_human_confirmation": instruction.get("can_execute_after_human_confirmation") is True,
        "human_confirmation_required": True,
        "confirmation_gate_status": "pending_human_confirmation",
        "execution_status": "not_executed",
        "dry_run_only": True,
    }


def _offline_slots_by_asset_id(offline_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    slots: dict[str, dict[str, Any]] = {}
    for slot in offline_report.get("offline_broll_slots", []):
        if not isinstance(slot, dict):
            continue
        placeholder = slot.get("placeholder")
        asset_id = slot.get("asset_id")
        if not asset_id and isinstance(placeholder, dict):
            asset_id = placeholder.get("asset_id")
        if asset_id:
            slots[str(asset_id)] = slot
    return slots


def _timeline_clips_by_asset_id(edit_timeline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    clips: dict[str, dict[str, Any]] = {}
    tracks = edit_timeline.get("tracks", {})
    video_clips = tracks.get("video") if isinstance(tracks, dict) else []
    if not isinstance(video_clips, list):
        return clips
    for clip in video_clips:
        if not isinstance(clip, dict):
            continue
        placeholder = clip.get("broll_placeholder")
        if isinstance(placeholder, dict) and placeholder.get("asset_id"):
            clips[str(placeholder["asset_id"])] = clip
    return clips


def _proxy_assets_by_asset_id(proxy_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = proxy_manifest.get("proxy_assets")
    if not isinstance(assets, list):
        return {}
    return {str(item["asset_id"]): item for item in assets if isinstance(item, dict) and item.get("asset_id")}


def _render_import_template_fcpxml(
    *,
    topic: str,
    platform_label: str,
    frame_rate: int,
    instructions: list[dict[str, Any]],
    run_dir: Path,
) -> str:
    ready = [item for item in instructions if item.get("can_execute_after_human_confirmation") is True]
    frame_duration = f"1/{frame_rate}s"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.10">',
        "  <resources>",
    ]
    for index, item in enumerate(ready, start=1):
        proxy_path = str(item.get("proxy_media_path") or "")
        source = _resolve_local_path(run_dir, proxy_path)
        uri = source.resolve().as_uri() if source else ""
        duration = _fcpxml_time(float(item.get("duration_seconds") or 1), frame_rate)
        lines.append(
            "    "
            f'<asset id={quoteattr(f"replacement_{index}")} name={quoteattr(Path(proxy_path).name or item["asset_id"])} '
            f'src={quoteattr(uri)} start="0s" duration={quoteattr(duration)} hasVideo="1"/>'
        )
    lines.extend(
        [
            "  </resources>",
            "  <library>",
            f"    <event name={quoteattr(platform_label + ' replacement import candidates')}>",
            f"      <project name={quoteattr(topic + ' - replacement candidates')}>",
            f'        <sequence duration={quoteattr(_fcpxml_time(sum(float(item.get("duration_seconds") or 1) for item in ready), frame_rate))} tcStart="0s" tcFormat="NDF">',
            "          <spine>",
        ]
    )
    cursor = 0.0
    for index, item in enumerate(ready, start=1):
        duration = float(item.get("duration_seconds") or 1)
        lines.append(
            "            "
            f'<asset-clip name={quoteattr(str(item.get("asset_id")))} ref={quoteattr(f"replacement_{index}")} '
            f'offset={quoteattr(_fcpxml_time(cursor, frame_rate))} duration={quoteattr(_fcpxml_time(duration, frame_rate))} start="0s">'
        )
        lines.append(
            "              "
            f"<note>{escape('Candidate only. Replace original B-roll after human confirmation gate is approved.')}</note>"
        )
        lines.append("            </asset-clip>")
        cursor += duration
    lines.extend(
        [
            "          </spine>",
            "        </sequence>",
            "      </project>",
            "    </event>",
            "  </library>",
            "</fcpxml>",
            "",
        ]
    )
    return "\n".join(lines)


def _render_confirmation_checklist(*, topic: str, platform_label: str, manifest: dict[str, Any]) -> str:
    lines = [
        "# Human Confirmation Gate",
        "",
        f"- Topic: {topic}",
        f"- Platform: {platform_label}",
        f"- Manifest: `{manifest['manifest_path']}`",
        f"- Commands: `{manifest['replacement_commands_path']}`",
        f"- Import template: `{manifest['editor_import_template_path']}`",
        "",
        "Confirm every item before any editor replacement is executed:",
        "",
    ]
    for item in manifest.get("instructions", []):
        lines.extend(
            [
                f"- [ ] `{item['asset_id']}` status `{item['instruction_status']}`",
                f"  - Proxy media: `{item.get('proxy_media_path')}`",
                f"  - Timeline target: `{item.get('shot_id')}` from {item.get('start_seconds')}s to {item.get('end_seconds')}s",
                "  - Confirm rights, visual match, audio/subtitle sync, and final editor approval.",
            ]
        )
    lines.extend(
        [
            "",
            "This checklist is a confirmation gate only. No editing software was opened, no replacement was executed, and no upload or publishing action was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_readme(*, topic: str, platform_label: str, manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    return "\n".join(
        [
            "# Editor Replacement Instructions",
            "",
            f"- Topic: {topic}",
            f"- Platform: {platform_label}",
            f"- Replacement commands: `{manifest['replacement_commands_path']}`",
            f"- Editor import template: `{manifest['editor_import_template_path']}`",
            f"- Human confirmation checklist: `{manifest['human_confirmation_checklist_path']}`",
            f"- Instructions: {summary['instruction_count']}",
            f"- Ready after human confirmation: {summary['ready_pending_human_confirmation_count']}",
            f"- Pending human media: {summary['pending_human_media_count']}",
            "",
            "Use the FCPXML import template to stage replacement candidates in an editor that supports FCPXML.",
            "Use replacement_commands.json only as a dry-run automation contract until a human approves every checklist item.",
            "This layer does not open editing software, mutate project files, execute replacements, upload, publish, search, download, or purchase media.",
            "",
        ]
    )


def _resolve_local_path(run_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return run_dir / path


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _fcpxml_time(seconds: float, frame_rate: int) -> str:
    frames = max(0, int(round(seconds * frame_rate)))
    return "0s" if frames == 0 else f"{frames}/{frame_rate}s"


def _dedupe(paths: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not path:
            continue
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result
