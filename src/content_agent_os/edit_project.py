from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedEditProject:
    timeline: dict[str, Any]
    manifest: dict[str, Any]
    edl_text: str


def generate_edit_project(
    *,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    aspect_ratio: str,
    storyboard: list[dict[str, Any]],
    shot_list: list[dict[str, Any]],
    timed_subtitles: dict[str, Any],
    voiceover_manifest: dict[str, Any],
    storyboard_preview_metadata: dict[str, Any],
    broll_list: list[dict[str, Any]],
    material_manifest: dict[str, Any] | None = None,
    licensed_media_manifest: dict[str, Any] | None = None,
    licensed_media_proxy_manifest: dict[str, Any] | None = None,
    timeline_path: str,
    manifest_path: str,
    edl_path: str,
) -> GeneratedEditProject:
    total_duration = float(timed_subtitles.get("total_duration_seconds") or 0)
    if total_duration <= 0:
        raise ValueError("edit project requires positive timed subtitle duration")

    frames_by_shot = _frames_by_shot(storyboard_preview_metadata)
    broll_by_index = _broll_by_index(broll_list)
    materialized_by_asset_id = _materialized_by_asset_id(material_manifest)
    licensed_media_by_asset_id = _licensed_media_by_asset_id(licensed_media_manifest)
    proxy_by_asset_id = _proxy_by_asset_id(licensed_media_proxy_manifest)
    video_clips = _video_clips(
        storyboard,
        shot_list,
        frames_by_shot,
        broll_by_index,
        materialized_by_asset_id,
        licensed_media_by_asset_id,
        proxy_by_asset_id,
    )
    subtitle_clips = _subtitle_clips(timed_subtitles)
    audio_clips = [
        {
            "id": f"{platform}_voiceover_main",
            "type": "voiceover",
            "track": "A1",
            "source_path": voiceover_manifest.get("audio_path"),
            "start_seconds": 0.0,
            "end_seconds": total_duration,
            "duration_seconds": total_duration,
            "provider": voiceover_manifest.get("provider"),
            "voice_id": voiceover_manifest.get("voice_id"),
            "review_required": True,
        }
    ]
    timeline = {
        "schema_version": "phase4.edit_timeline.v1",
        "artifact_type": "edit_timeline",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "aspect_ratio": aspect_ratio,
        "frame_rate": 30,
        "duration_seconds": total_duration,
        "tracks": {
            "video": video_clips,
            "audio": audio_clips,
            "subtitles": subtitle_clips,
        },
        "markers": _timeline_markers(video_clips),
        "edit_policy": {
            "primary_video_track": "V1",
            "primary_audio_track": "A1",
            "subtitle_track": "S1",
            "broll_slots_are_placeholders": True,
            "broll_references_are_local_review_assets": bool(materialized_by_asset_id),
            "licensed_media_ingest_attached": bool(licensed_media_by_asset_id),
            "licensed_media_proxy_attached": bool(proxy_by_asset_id),
            "human_review_required": True,
        },
        "validation": _validate_timeline(video_clips, audio_clips, subtitle_clips, total_duration),
        "review_required": True,
    }
    edl_text = _render_edl(timeline)
    source_artifacts = _source_artifacts(
        platform=platform,
        material_manifest=material_manifest,
        materialized_by_asset_id=materialized_by_asset_id,
        licensed_media_manifest=licensed_media_manifest,
        licensed_media_by_asset_id=licensed_media_by_asset_id,
        licensed_media_proxy_manifest=licensed_media_proxy_manifest,
        proxy_by_asset_id=proxy_by_asset_id,
    )
    manifest = {
        "schema_version": "phase4.edit_project_manifest.v1",
        "artifact_type": "edit_project",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-edit-project-adapter",
        "adapter_version": "0.1.0",
        "timeline_path": timeline_path,
        "edl_path": edl_path,
        "manifest_path": manifest_path,
        "duration_seconds": total_duration,
        "frame_rate": 30,
        "source_artifacts": source_artifacts,
        "deliverables": {
            "timeline": timeline_path,
            "edl": edl_path,
            "manifest": manifest_path,
        },
        "track_summary": {
            "video_clips": len(video_clips),
            "audio_clips": len(audio_clips),
            "subtitle_clips": len(subtitle_clips),
            "markers": len(timeline["markers"]),
        },
        "validation": timeline["validation"],
        "generation_status": "generated_local_edit_timeline_pending_human_review",
        "manual_review_required": True,
        "review_notes": [
            "Edit timeline is a local deterministic draft for handoff to an editor.",
            "Local B-roll reference PNGs are attached where available; licensed final media is still required.",
            "Licensed media ingest status is attached where available; B-roll placeholders remain offline until approved media is imported by a human editor.",
            "Licensed media proxy replacement suggestions are attached where available; proxy copies still require final editor review before replacement.",
            "No editing software was opened and no export, upload, sync, or publishing action was performed.",
        ],
        "review_required": True,
    }
    return GeneratedEditProject(timeline=timeline, manifest=manifest, edl_text=edl_text)


def _video_clips(
    storyboard: list[dict[str, Any]],
    shot_list: list[dict[str, Any]],
    frames_by_shot: dict[str, dict[str, Any]],
    broll_by_index: dict[int, dict[str, Any]],
    materialized_by_asset_id: dict[str, dict[str, Any]],
    licensed_media_by_asset_id: dict[str, dict[str, Any]],
    proxy_by_asset_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    cursor = 0.0
    for index, scene in enumerate(storyboard, start=1):
        shot = shot_list[index - 1] if index - 1 < len(shot_list) and isinstance(shot_list[index - 1], dict) else {}
        duration = _safe_duration(scene.get("duration_seconds") or shot.get("duration_seconds"))
        shot_id = str(shot.get("shot_id") or f"shot_{index:02d}")
        frame = frames_by_shot.get(shot_id, {})
        broll = _enrich_broll_placeholder(
            broll_by_index.get(index),
            materialized_by_asset_id,
            licensed_media_by_asset_id,
            proxy_by_asset_id,
        )
        clips.append(
            {
                "id": shot_id,
                "type": "storyboard_shot",
                "track": "V1",
                "start_seconds": round(cursor, 3),
                "end_seconds": round(cursor + duration, 3),
                "duration_seconds": duration,
                "source_path": frame.get("path"),
                "scene": scene.get("scene") or shot.get("scene"),
                "visual": scene.get("visual") or shot.get("visual"),
                "edit_note": shot.get("edit_note") or "Cut to this shot and keep timing aligned with voiceover.",
                "broll_placeholder": broll,
                "transition_in": "cut" if index == 1 else "match_cut",
                "transition_out": "cut",
                "review_required": True,
            }
        )
        cursor += duration
    return clips


def _materialized_by_asset_id(material_manifest: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(material_manifest, dict):
        return {}
    assets = material_manifest.get("materialized_assets")
    if not isinstance(assets, list):
        return {}
    return {
        str(asset["asset_id"]): asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("asset_id")
    }


def _licensed_media_by_asset_id(licensed_media_manifest: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(licensed_media_manifest, dict):
        return {}
    assets = licensed_media_manifest.get("licensed_media")
    if not isinstance(assets, list):
        return {}
    return {
        str(asset["asset_id"]): asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("asset_id")
    }


def _proxy_by_asset_id(licensed_media_proxy_manifest: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(licensed_media_proxy_manifest, dict):
        return {}
    assets = licensed_media_proxy_manifest.get("proxy_assets")
    if not isinstance(assets, list):
        return {}
    return {
        str(asset["asset_id"]): asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("asset_id")
    }


def _enrich_broll_placeholder(
    broll: dict[str, Any] | None,
    materialized_by_asset_id: dict[str, dict[str, Any]],
    licensed_media_by_asset_id: dict[str, dict[str, Any]],
    proxy_by_asset_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(broll, dict):
        return None
    enriched = dict(broll)
    asset_id = str(enriched.get("asset_id") or "")
    materialized = materialized_by_asset_id.get(asset_id)
    enriched["licensed_final_media_required"] = True
    if isinstance(materialized, dict):
        enriched["reference_path"] = materialized.get("reference_path")
        enriched["reference_status"] = materialized.get("generation_status")
        enriched["rights_status"] = materialized.get("rights_status")
        enriched["material_manifest_path"] = materialized.get("manifest_path") or None
        enriched["licensed_final_media_required"] = materialized.get("licensed_final_media_required") is not False
    licensed_media = licensed_media_by_asset_id.get(asset_id)
    if isinstance(licensed_media, dict):
        enriched["licensed_media_ingest_manifest_path"] = licensed_media.get("manifest_path")
        enriched["licensed_media_review_handoff_path"] = licensed_media.get("review_handoff_path")
        enriched["licensed_media_path"] = licensed_media.get("licensed_media_path")
        enriched["license_proof_path"] = licensed_media.get("license_proof_path")
        enriched["licensed_media_intake_status"] = licensed_media.get("intake_status")
        enriched["licensed_media_review_status"] = licensed_media.get("review_status")
        enriched["rights_confirmation"] = licensed_media.get("rights_confirmation")
        enriched["ready_for_editor_replacement"] = licensed_media.get("ready_for_editor_replacement") is True
        enriched["licensed_final_media_required"] = licensed_media.get("licensed_final_media_required") is not False
    proxy_asset = proxy_by_asset_id.get(asset_id)
    if isinstance(proxy_asset, dict):
        enriched["licensed_media_proxy_manifest_path"] = proxy_asset.get("manifest_path")
        enriched["licensed_media_replacement_suggestions_path"] = proxy_asset.get("replacement_suggestions_path")
        enriched["licensed_media_proxy_readme_path"] = proxy_asset.get("readme_path")
        enriched["proxy_media_path"] = proxy_asset.get("proxy_media_path")
        enriched["proxy_copy_status"] = proxy_asset.get("proxy_copy_status")
        enriched["replacement_status"] = proxy_asset.get("replacement_status")
        enriched["editor_replacement_ready"] = proxy_asset.get("editor_replacement_ready") is True
        enriched["proxy_media_sha256"] = proxy_asset.get("proxy_media_sha256")
        enriched["source_media_sha256"] = proxy_asset.get("source_media_sha256")
    return enriched


def _source_artifacts(
    *,
    platform: str,
    material_manifest: dict[str, Any] | None,
    materialized_by_asset_id: dict[str, dict[str, Any]],
    licensed_media_manifest: dict[str, Any] | None,
    licensed_media_by_asset_id: dict[str, dict[str, Any]],
    licensed_media_proxy_manifest: dict[str, Any] | None,
    proxy_by_asset_id: dict[str, dict[str, Any]],
) -> list[str]:
    artifacts = [
        f"{platform}/storyboard.json",
        f"{platform}/shot_list.json",
        f"{platform}/timed_subtitles.json",
        f"assets/{platform}/voiceover/voiceover_manifest.json",
        f"assets/{platform}/storyboard/storyboard_preview_metadata.json",
        f"{platform}/broll_list.json",
    ]
    if isinstance(material_manifest, dict):
        manifest_path = material_manifest.get("manifest_path")
        readme_path = material_manifest.get("readme_path")
        if isinstance(manifest_path, str) and manifest_path:
            artifacts.append(manifest_path)
        if isinstance(readme_path, str) and readme_path:
            artifacts.append(readme_path)
    for asset in materialized_by_asset_id.values():
        reference_path = asset.get("reference_path")
        if isinstance(reference_path, str) and reference_path:
            artifacts.append(reference_path)
    if isinstance(licensed_media_manifest, dict):
        for key in ["manifest_path", "readme_path", "review_handoff_path"]:
            path = licensed_media_manifest.get(key)
            if isinstance(path, str) and path:
                artifacts.append(path)
        registry_path = licensed_media_manifest.get("human_media_registry_path")
        if licensed_media_manifest.get("human_media_registry_exists") is True and isinstance(registry_path, str):
            artifacts.append(registry_path)
    for asset in licensed_media_by_asset_id.values():
        for key in ["licensed_media_path", "license_proof_path"]:
            path = asset.get(key)
            if isinstance(path, str) and path:
                artifacts.append(path)
    if isinstance(licensed_media_proxy_manifest, dict):
        for key in ["manifest_path", "replacement_suggestions_path", "readme_path"]:
            path = licensed_media_proxy_manifest.get(key)
            if isinstance(path, str) and path:
                artifacts.append(path)
    for asset in proxy_by_asset_id.values():
        for key in ["proxy_media_path"]:
            path = asset.get(key)
            if isinstance(path, str) and path:
                artifacts.append(path)
    return _dedupe(artifacts)


def _subtitle_clips(timed_subtitles: dict[str, Any]) -> list[dict[str, Any]]:
    subtitles = timed_subtitles.get("subtitles", [])
    if not isinstance(subtitles, list):
        return []
    return [
        {
            "id": f"subtitle_{int(item.get('index') or index):03d}",
            "type": "subtitle",
            "track": "S1",
            "start_seconds": item.get("start_seconds"),
            "end_seconds": item.get("end_seconds"),
            "duration_seconds": item.get("duration_seconds"),
            "text": item.get("text"),
            "shot_id": item.get("shot_id"),
            "review_required": True,
        }
        for index, item in enumerate(subtitles, start=1)
        if isinstance(item, dict)
    ]


def _timeline_markers(video_clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers = [
        {
            "time_seconds": clip["start_seconds"],
            "label": str(clip.get("scene") or clip["id"]),
            "shot_id": clip["id"],
        }
        for clip in video_clips
    ]
    if video_clips:
        markers.append(
            {
                "time_seconds": video_clips[-1]["end_seconds"],
                "label": "timeline_end",
                "shot_id": None,
            }
        )
    return markers


def _validate_timeline(
    video_clips: list[dict[str, Any]],
    audio_clips: list[dict[str, Any]],
    subtitle_clips: list[dict[str, Any]],
    total_duration: float,
) -> dict[str, Any]:
    video_duration = video_clips[-1]["end_seconds"] if video_clips else 0
    audio_duration = audio_clips[-1]["end_seconds"] if audio_clips else 0
    subtitles_end = subtitle_clips[-1]["end_seconds"] if subtitle_clips else 0
    video_ok = abs(float(video_duration) - total_duration) < 0.01
    audio_ok = abs(float(audio_duration) - total_duration) < 0.01
    subtitles_ok = abs(float(subtitles_end) - total_duration) < 0.01
    return {
        "status": "PASSED" if video_ok and audio_ok and subtitles_ok else "FAILED",
        "video_duration_matches": video_ok,
        "audio_duration_matches": audio_ok,
        "subtitle_duration_matches": subtitles_ok,
        "video_clip_count": len(video_clips),
        "audio_clip_count": len(audio_clips),
        "subtitle_clip_count": len(subtitle_clips),
    }


def _render_edl(timeline: dict[str, Any]) -> str:
    lines = [
        f"TITLE: {timeline['platform']} draft cut",
        "FCM: NON-DROP FRAME",
        "",
    ]
    for index, clip in enumerate(timeline["tracks"]["video"], start=1):
        start = _edl_timecode(float(clip["start_seconds"]), timeline["frame_rate"])
        end = _edl_timecode(float(clip["end_seconds"]), timeline["frame_rate"])
        reel = _reel_name(str(clip.get("id") or f"shot_{index:02d}"))
        source = str(clip.get("source_path") or "MISSING_SOURCE")
        lines.extend(
            [
                f"{index:03d}  {reel:<8} V     C        {start} {end} {start} {end}",
                f"* FROM CLIP NAME: {source}",
                f"* COMMENT: {clip.get('edit_note') or ''}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _frames_by_shot(storyboard_preview_metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    frames = storyboard_preview_metadata.get("frames")
    if not isinstance(frames, list):
        return {}
    return {
        str(frame.get("shot_id") or frame.get("linked_shot_id")): frame
        for frame in frames
        if isinstance(frame, dict) and (frame.get("shot_id") or frame.get("linked_shot_id"))
    }


def _broll_by_index(broll_list: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(broll_list, start=1):
        if isinstance(item, dict):
            result[index] = item
    return result


def _safe_duration(value: Any) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return 3.0
    return duration if duration > 0 else 3.0


def _edl_timecode(seconds: float, frame_rate: int) -> str:
    total_frames = int(round(seconds * frame_rate))
    hours = total_frames // (frame_rate * 3600)
    total_frames %= frame_rate * 3600
    minutes = total_frames // (frame_rate * 60)
    total_frames %= frame_rate * 60
    whole_seconds = total_frames // frame_rate
    frames = total_frames % frame_rate
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}:{frames:02d}"


def _reel_name(value: str) -> str:
    return "".join(char for char in value.upper() if char.isalnum())[:8] or "REEL"


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result
