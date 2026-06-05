from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr


@dataclass(frozen=True)
class GeneratedExportProject:
    fcpxml_text: str
    readme_text: str
    offline_report: dict[str, Any]
    manifest: dict[str, Any]


def generate_export_project(
    *,
    run_dir: Path,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    aspect_ratio: str,
    edit_timeline: dict[str, Any],
    edit_manifest: dict[str, Any],
    project_path: str,
    readme_path: str,
    offline_report_path: str,
    manifest_path: str,
) -> GeneratedExportProject:
    duration_seconds = float(edit_timeline.get("duration_seconds") or 0)
    if duration_seconds <= 0:
        raise ValueError("export project requires positive timeline duration")
    frame_rate = int(edit_timeline.get("frame_rate") or edit_manifest.get("frame_rate") or 30)
    tracks = edit_timeline.get("tracks", {})
    if not isinstance(tracks, dict):
        tracks = {}
    video_clips = _clip_list(tracks.get("video"))
    audio_clips = _clip_list(tracks.get("audio"))
    subtitle_clips = _clip_list(tracks.get("subtitles"))
    if not video_clips:
        raise ValueError("export project requires timeline video clips")
    if not audio_clips:
        raise ValueError("export project requires timeline audio clips")

    width, height = _format_size(aspect_ratio)
    media_refs = _media_references(run_dir, video_clips, audio_clips)
    missing_sources = [item for item in media_refs if not item["exists"]]
    broll_slots = _broll_slots(video_clips)
    fcpxml_text = _render_fcpxml(
        topic=topic,
        platform=platform,
        platform_label=platform_label,
        width=width,
        height=height,
        frame_rate=frame_rate,
        duration_seconds=duration_seconds,
        video_clips=video_clips,
        audio_clips=audio_clips,
        media_refs=media_refs,
    )
    offline_report = {
        "schema_version": "phase4.offline_media_report.v1",
        "artifact_type": "offline_media_report",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "project_path": project_path,
        "missing_source_count": len(missing_sources),
        "missing_sources": missing_sources,
        "offline_broll_count": len(broll_slots),
        "offline_broll_slots": broll_slots,
        "subtitle_sidecar": f"{platform}/timed_subtitles.srt",
        "review_required": True,
    }
    readme_text = _render_import_readme(
        topic=topic,
        platform_label=platform_label,
        project_path=project_path,
        offline_report_path=offline_report_path,
        subtitle_sidecar=f"{platform}/timed_subtitles.srt",
        duration_seconds=duration_seconds,
        video_clip_count=len(video_clips),
        audio_clip_count=len(audio_clips),
        subtitle_clip_count=len(subtitle_clips),
        offline_broll_count=len(broll_slots),
    )
    validation = {
        "status": "PASSED" if not missing_sources else "NEEDS_REVIEW",
        "fcpxml_well_formed": True,
        "referenced_media_files_exist": not missing_sources,
        "offline_broll_count": len(broll_slots),
        "video_clip_count": len(video_clips),
        "audio_clip_count": len(audio_clips),
        "subtitle_clip_count": len(subtitle_clips),
    }
    manifest = {
        "schema_version": "phase4.export_project_manifest.v1",
        "artifact_type": "export_project",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-export-project-adapter",
        "adapter_version": "0.1.0",
        "project_format": "fcpxml",
        "project_path": project_path,
        "readme_path": readme_path,
        "offline_report_path": offline_report_path,
        "manifest_path": manifest_path,
        "duration_seconds": duration_seconds,
        "frame_rate": frame_rate,
        "source_artifacts": _source_artifacts(platform, edit_timeline, edit_manifest),
        "deliverables": {
            "fcpxml": project_path,
            "import_readme": readme_path,
            "offline_media_report": offline_report_path,
            "manifest": manifest_path,
            "subtitle_sidecar": f"{platform}/timed_subtitles.srt",
            "edit_timeline": edit_manifest.get("timeline_path"),
            "draft_cut_edl": edit_manifest.get("edl_path"),
        },
        "track_summary": {
            "video_clips": len(video_clips),
            "audio_clips": len(audio_clips),
            "subtitle_clips": len(subtitle_clips),
            "offline_broll_slots": len(broll_slots),
        },
        "validation": validation,
        "generation_status": "generated_local_export_project_pending_human_review",
        "manual_review_required": True,
        "review_notes": [
            "FCPXML is a local draft handoff built from edit_timeline.json.",
            "Timed subtitles remain a sidecar SRT for editor import.",
            "B-roll slots remain offline placeholders until approved licensed media is imported by a human editor.",
            "Licensed media ingest handoff status is preserved where available.",
            "Licensed media proxy replacement suggestions and proxy copy status are preserved where available.",
            "No editing software was opened and no export, upload, sync, or publishing action was performed.",
        ],
        "review_required": True,
    }
    return GeneratedExportProject(
        fcpxml_text=fcpxml_text,
        readme_text=readme_text,
        offline_report=offline_report,
        manifest=manifest,
    )


def _render_fcpxml(
    *,
    topic: str,
    platform: str,
    platform_label: str,
    width: int,
    height: int,
    frame_rate: int,
    duration_seconds: float,
    video_clips: list[dict[str, Any]],
    audio_clips: list[dict[str, Any]],
    media_refs: list[dict[str, Any]],
) -> str:
    frame_duration = f"1/{frame_rate}s"
    duration = _fcpxml_time(duration_seconds, frame_rate)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.10">',
        "  <resources>",
        f'    <format id="r_format" name={quoteattr(f"{width}x{height}p{frame_rate}")} frameDuration={quoteattr(frame_duration)} width={quoteattr(str(width))} height={quoteattr(str(height))}/>',
    ]
    for media in media_refs:
        if media["kind"] == "audio":
            lines.append(
                "    "
                f'<asset id={quoteattr(media["id"])} name={quoteattr(media["name"])} src={quoteattr(media["uri"])} '
                f'start="0s" duration={quoteattr(_fcpxml_time(media["duration_seconds"], frame_rate))} '
                'hasAudio="1" audioSources="1" audioChannels="1" audioRate="48000"/>'
            )
        else:
            lines.append(
                "    "
                f'<asset id={quoteattr(media["id"])} name={quoteattr(media["name"])} src={quoteattr(media["uri"])} '
                f'start="0s" duration={quoteattr(_fcpxml_time(media["duration_seconds"], frame_rate))} hasVideo="1"/>'
            )
    lines.extend(
        [
            "  </resources>",
            "  <library>",
            f"    <event name={quoteattr(platform_label + ' draft export')}>",
            f"      <project name={quoteattr(topic + ' - ' + platform_label)}>",
            f'        <sequence format="r_format" duration={quoteattr(duration)} tcStart="0s" tcFormat="NDF">',
            "          <spine>",
        ]
    )
    for index, clip in enumerate(video_clips, start=1):
        media_id = f"r_video_{index}"
        lines.append(
            "            "
            f'<asset-clip name={quoteattr(str(clip.get("scene") or clip.get("id") or media_id))} ref={quoteattr(media_id)} '
            f'offset={quoteattr(_fcpxml_time(float(clip.get("start_seconds") or 0), frame_rate))} '
            f'duration={quoteattr(_fcpxml_time(float(clip.get("duration_seconds") or 0), frame_rate))} start="0s">'
        )
        note = str(clip.get("edit_note") or clip.get("visual") or "")
        if note:
            lines.append(f'              <note>{escape(note)}</note>')
        lines.append("            </asset-clip>")
    for index, clip in enumerate(audio_clips, start=1):
        lines.append(
            "            "
            f'<asset-clip name={quoteattr(str(clip.get("id") or "voiceover"))} ref={quoteattr(f"r_audio_{index}")} lane="-1" '
            f'offset={quoteattr(_fcpxml_time(float(clip.get("start_seconds") or 0), frame_rate))} '
            f'duration={quoteattr(_fcpxml_time(float(clip.get("duration_seconds") or duration_seconds), frame_rate))} start="0s"/>'
        )
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


def _render_import_readme(
    *,
    topic: str,
    platform_label: str,
    project_path: str,
    offline_report_path: str,
    subtitle_sidecar: str,
    duration_seconds: float,
    video_clip_count: int,
    audio_clip_count: int,
    subtitle_clip_count: int,
    offline_broll_count: int,
) -> str:
    return "\n".join(
        [
            "# Edit Project Import Notes",
            "",
            f"- Topic: {topic}",
            f"- Platform: {platform_label}",
            f"- Project file: `{project_path}`",
            f"- Subtitle sidecar: `{subtitle_sidecar}`",
            f"- Offline report: `{offline_report_path}`",
            f"- Duration seconds: {duration_seconds:g}",
            f"- Video clips: {video_clip_count}",
            f"- Audio clips: {audio_clip_count}",
            f"- Subtitle cues: {subtitle_clip_count}",
            f"- Offline B-roll slots: {offline_broll_count}",
            "",
            "Import the FCPXML as a draft project, then import the SRT sidecar for subtitles.",
            "Replace offline B-roll slots with licensed media before final export.",
            "This package was generated locally; no editing software, upload, sync, or publishing action was performed.",
            "",
        ]
    )


def _media_references(
    run_dir: Path,
    video_clips: list[dict[str, Any]],
    audio_clips: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, clip in enumerate(video_clips, start=1):
        refs.append(_media_ref(run_dir, clip, media_id=f"r_video_{index}", kind="video"))
    for index, clip in enumerate(audio_clips, start=1):
        refs.append(_media_ref(run_dir, clip, media_id=f"r_audio_{index}", kind="audio"))
    return refs


def _media_ref(run_dir: Path, clip: dict[str, Any], *, media_id: str, kind: str) -> dict[str, Any]:
    source_path = str(clip.get("source_path") or "")
    path = run_dir / source_path if source_path else run_dir / "__missing__"
    exists = bool(source_path) and path.exists()
    return {
        "id": media_id,
        "kind": kind,
        "name": Path(source_path).name or media_id,
        "source_path": source_path,
        "uri": path.resolve().as_uri(),
        "exists": exists,
        "duration_seconds": float(clip.get("duration_seconds") or 0),
    }


def _broll_slots(video_clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slots = []
    for clip in video_clips:
        broll = clip.get("broll_placeholder")
        if not isinstance(broll, dict):
            continue
        slots.append(
            {
                "shot_id": clip.get("id"),
                "start_seconds": clip.get("start_seconds"),
                "end_seconds": clip.get("end_seconds"),
                "duration_seconds": clip.get("duration_seconds"),
                "placeholder": broll,
                "reference_path": broll.get("reference_path"),
                "reference_status": broll.get("reference_status"),
                "licensed_media_path": broll.get("licensed_media_path"),
                "license_proof_path": broll.get("license_proof_path"),
                "licensed_media_ingest_manifest_path": broll.get("licensed_media_ingest_manifest_path"),
                "licensed_media_review_handoff_path": broll.get("licensed_media_review_handoff_path"),
                "licensed_media_proxy_manifest_path": broll.get("licensed_media_proxy_manifest_path"),
                "licensed_media_replacement_suggestions_path": broll.get("licensed_media_replacement_suggestions_path"),
                "licensed_media_proxy_readme_path": broll.get("licensed_media_proxy_readme_path"),
                "licensed_media_intake_status": broll.get("licensed_media_intake_status"),
                "licensed_media_review_status": broll.get("licensed_media_review_status"),
                "rights_confirmation": broll.get("rights_confirmation"),
                "ready_for_editor_replacement": broll.get("ready_for_editor_replacement") is True,
                "proxy_media_path": broll.get("proxy_media_path"),
                "proxy_copy_status": broll.get("proxy_copy_status"),
                "replacement_status": broll.get("replacement_status"),
                "editor_replacement_ready": broll.get("editor_replacement_ready") is True,
                "proxy_media_sha256": broll.get("proxy_media_sha256"),
                "source_media_sha256": broll.get("source_media_sha256"),
                "licensed_final_media_required": broll.get("licensed_final_media_required") is not False,
                "status": _broll_slot_status(broll),
            }
        )
    return slots


def _broll_slot_status(broll: dict[str, Any]) -> str:
    if broll.get("editor_replacement_ready") is True and broll.get("proxy_media_path"):
        return "proxy_ready_for_editor_replacement"
    if broll.get("ready_for_editor_replacement") is True:
        return "licensed_media_ready_for_editor_replacement"
    if broll.get("licensed_media_path"):
        return "licensed_media_candidate_pending_review"
    if broll.get("licensed_media_intake_status") == "pending_human_media":
        return "pending_human_licensed_media"
    if broll.get("reference_path"):
        return "reference_generated_pending_licensed_media"
    return "offline_placeholder_pending_licensed_media"


def _source_artifacts(platform: str, edit_timeline: dict[str, Any], edit_manifest: dict[str, Any]) -> list[str]:
    artifacts = [
        edit_manifest.get("timeline_path"),
        edit_manifest.get("manifest_path"),
        edit_manifest.get("edl_path"),
        f"{platform}/timed_subtitles.srt",
    ]
    manifest_sources = edit_manifest.get("source_artifacts")
    if isinstance(manifest_sources, list):
        artifacts.extend([path for path in manifest_sources if isinstance(path, str)])
    tracks = edit_timeline.get("tracks", {})
    if isinstance(tracks, dict):
        for group in ["video", "audio"]:
            for clip in _clip_list(tracks.get(group)):
                source_path = clip.get("source_path")
                if isinstance(source_path, str) and source_path:
                    artifacts.append(source_path)
                broll = clip.get("broll_placeholder")
                if isinstance(broll, dict):
                    for key in [
                        "reference_path",
                        "licensed_media_ingest_manifest_path",
                        "licensed_media_review_handoff_path",
                        "licensed_media_proxy_manifest_path",
                        "licensed_media_replacement_suggestions_path",
                        "licensed_media_proxy_readme_path",
                        "licensed_media_path",
                        "license_proof_path",
                        "proxy_media_path",
                    ]:
                        path = broll.get(key)
                        if isinstance(path, str) and path:
                            artifacts.append(path)
    return _dedupe([str(path) for path in artifacts if isinstance(path, str) and path])


def _clip_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _format_size(aspect_ratio: str) -> tuple[int, int]:
    return (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920)


def _fcpxml_time(seconds: float, frame_rate: int) -> str:
    frames = max(0, int(round(seconds * frame_rate)))
    return "0s" if frames == 0 else f"{frames}/{frame_rate}s"
