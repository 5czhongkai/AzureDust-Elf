from __future__ import annotations

import re
from typing import Any


TIMECODE_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def align_subtitle_timeline(
    *,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    storyboard: list[dict[str, Any]],
    shot_list: list[dict[str, Any]],
    source_srt: str,
    source_artifacts: list[str],
) -> dict[str, Any]:
    if not storyboard:
        raise ValueError("subtitle timing requires at least one storyboard scene")

    source_blocks = _parse_srt(source_srt)
    shot_by_index = {
        index: shot
        for index, shot in enumerate(shot_list, start=1)
        if isinstance(shot, dict)
    }
    subtitles: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []
    cursor = 0.0
    subtitle_index = 1

    for shot_index, scene in enumerate(storyboard, start=1):
        shot = shot_by_index.get(shot_index, {})
        duration = _safe_duration(scene.get("duration_seconds") or shot.get("duration_seconds"))
        shot_start = cursor
        shot_end = cursor + duration
        source_block = source_blocks[shot_index - 1] if shot_index - 1 < len(source_blocks) else None
        source_text = _source_text(source_block, scene)
        text_parts = _split_subtitle_text(source_text, _max_chars_per_block(platform), duration)
        shot_id = str(shot.get("shot_id") or f"{platform}_{shot_index:02d}")

        if source_block is None:
            corrections.append(
                {
                    "shot_id": shot_id,
                    "type": "filled_missing_source_subtitle",
                    "detail": "Source SRT did not include a matching block; storyboard voiceover was used.",
                }
            )
        elif not _matches_window(source_block["start_seconds"], source_block["end_seconds"], shot_start, shot_end):
            corrections.append(
                {
                    "shot_id": shot_id,
                    "type": "realigned_to_storyboard",
                    "detail": "Source SRT timing was adjusted to match the storyboard shot window.",
                    "source_start_seconds": source_block["start_seconds"],
                    "source_end_seconds": source_block["end_seconds"],
                    "aligned_start_seconds": shot_start,
                    "aligned_end_seconds": shot_end,
                }
            )
        if len(text_parts) > 1:
            corrections.append(
                {
                    "shot_id": shot_id,
                    "type": "split_long_text",
                    "detail": f"Long caption text was split into {len(text_parts)} readable blocks inside the shot boundary.",
                }
            )

        for split_index, part in enumerate(text_parts, start=1):
            start, end = _segment_window(shot_start, shot_end, len(text_parts), split_index)
            subtitles.append(
                {
                    "index": subtitle_index,
                    "shot_index": shot_index,
                    "shot_id": shot_id,
                    "scene": str(scene.get("scene") or shot.get("scene") or shot_id),
                    "start_seconds": start,
                    "end_seconds": end,
                    "duration_seconds": round(end - start, 3),
                    "start_timecode": srt_timestamp(start),
                    "end_timecode": srt_timestamp(end),
                    "text": part,
                    "source_text": source_text,
                    "source_block_index": source_block["index"] if source_block else None,
                    "split_index": split_index,
                    "split_count": len(text_parts),
                    "review_required": True,
                }
            )
            subtitle_index += 1

        cursor = shot_end

    total_duration = round(cursor, 3)
    return {
        "schema_version": "phase4.timed_subtitles.v1",
        "artifact_type": "timed_subtitles",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "local-subtitle-timing-adapter",
        "adapter_version": "0.1.0",
        "source_artifacts": source_artifacts,
        "source_subtitle_blocks": len(source_blocks),
        "storyboard_scene_count": len(storyboard),
        "subtitle_count": len(subtitles),
        "total_duration_seconds": total_duration,
        "timeline_policy": {
            "alignment": "storyboard_shot_boundaries",
            "no_cross_shot_subtitles": True,
            "long_text_split": True,
            "tts_ready": True,
        },
        "corrections": corrections,
        "subtitles": subtitles,
        "validation": _validate_timeline(subtitles, total_duration),
        "review_required": True,
    }


def render_timed_subtitles_srt(timed_subtitles: dict[str, Any]) -> str:
    blocks = []
    subtitles = timed_subtitles.get("subtitles", [])
    if not isinstance(subtitles, list):
        return ""
    for item in subtitles:
        if not isinstance(item, dict):
            continue
        blocks.append(
            "\n".join(
                [
                    str(item.get("index") or len(blocks) + 1),
                    f"{item.get('start_timecode')} --> {item.get('end_timecode')}",
                    str(item.get("text") or ""),
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def srt_timestamp(seconds: float) -> str:
    total_milliseconds = int(round(max(0.0, seconds) * 1000))
    hours = total_milliseconds // 3_600_000
    total_milliseconds %= 3_600_000
    minutes = total_milliseconds // 60_000
    total_milliseconds %= 60_000
    whole_seconds = total_milliseconds // 1000
    milliseconds = total_milliseconds % 1000
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def _parse_srt(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw_block in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in raw_block.splitlines() if line.strip()]
        if not lines:
            continue
        index = len(blocks) + 1
        if lines[0].isdigit():
            index = int(lines.pop(0))
        if not lines:
            continue
        match = TIMECODE_RE.search(lines[0])
        if not match:
            continue
        body_lines = lines[1:]
        blocks.append(
            {
                "index": index,
                "start_seconds": _parse_timecode(match.group("start")),
                "end_seconds": _parse_timecode(match.group("end")),
                "text": " ".join(body_lines).strip(),
            }
        )
    return blocks


def _parse_timecode(value: str) -> float:
    hours_text, minutes_text, rest = value.replace(",", ".").split(":")
    seconds_text, milliseconds_text = rest.split(".")
    return (
        int(hours_text) * 3600
        + int(minutes_text) * 60
        + int(seconds_text)
        + int(milliseconds_text) / 1000
    )


def _source_text(source_block: dict[str, Any] | None, scene: dict[str, Any]) -> str:
    if source_block and source_block.get("text"):
        return str(source_block["text"]).strip()
    return str(scene.get("voiceover") or scene.get("subtitle") or "").strip()


def _split_subtitle_text(text: str, max_chars: int, duration_seconds: float) -> list[str]:
    cleaned = " ".join(str(text).split())
    if not cleaned:
        return [""]
    if _display_length(cleaned) <= max_chars:
        return [cleaned]

    chunks = _sentence_chunks(cleaned)
    parts: list[str] = []
    current = ""
    for chunk in chunks:
        candidate = current + chunk if current else chunk
        if current and _display_length(candidate) > max_chars:
            parts.extend(_hard_split(current, max_chars))
            current = chunk
        else:
            current = candidate
    if current:
        parts.extend(_hard_split(current, max_chars))

    max_parts = max(1, int(duration_seconds // 1.4) or 1)
    if len(parts) <= max_parts:
        return parts
    return _merge_to_limit(parts, max_parts)


def _sentence_chunks(text: str) -> list[str]:
    pieces = re.findall(r"[^，。！？；、,.!?;]+[，。！？；、,.!?;]?", text)
    return [piece.strip() for piece in pieces if piece.strip()] or [text]


def _hard_split(text: str, max_chars: int) -> list[str]:
    if _display_length(text) <= max_chars + 6:
        return [text]
    parts: list[str] = []
    current = ""
    current_len = 0
    for char in text:
        char_len = 1 if ord(char) < 128 else 2
        if current and current_len + char_len > max_chars:
            parts.append(current)
            current = char
            current_len = char_len
        else:
            current += char
            current_len += char_len
    if current:
        parts.append(current)
    if len(parts) > 1 and _display_length(parts[-1]) < 6:
        parts[-2] += parts[-1]
        parts.pop()
    return parts


def _merge_to_limit(parts: list[str], max_parts: int) -> list[str]:
    if max_parts <= 1:
        return ["".join(parts)]
    buckets = ["" for _ in range(max_parts)]
    for index, part in enumerate(parts):
        bucket = min(index * max_parts // len(parts), max_parts - 1)
        buckets[bucket] = (buckets[bucket] + part).strip()
    return [bucket for bucket in buckets if bucket]


def _segment_window(shot_start: float, shot_end: float, total_parts: int, part_index: int) -> tuple[float, float]:
    duration = shot_end - shot_start
    start = shot_start + duration * (part_index - 1) / total_parts
    end = shot_end if part_index == total_parts else shot_start + duration * part_index / total_parts
    return round(start, 3), round(end, 3)


def _validate_timeline(subtitles: list[dict[str, Any]], total_duration: float) -> dict[str, Any]:
    no_overlap = True
    no_cross_shot = True
    last_end = 0.0
    for item in subtitles:
        start = float(item["start_seconds"])
        end = float(item["end_seconds"])
        if start < last_end - 0.001:
            no_overlap = False
        if start >= end:
            no_overlap = False
        if float(item["duration_seconds"]) <= 0:
            no_overlap = False
        last_end = max(last_end, end)
    shot_ids = [item.get("shot_id") for item in subtitles]
    for shot_id in set(shot_ids):
        windows = [item for item in subtitles if item.get("shot_id") == shot_id]
        shot_indexes = {item.get("shot_index") for item in windows}
        if len(shot_indexes) != 1:
            no_cross_shot = False
    return {
        "status": "PASSED" if no_overlap and no_cross_shot else "FAILED",
        "no_overlap": no_overlap,
        "no_cross_shot_subtitles": no_cross_shot,
        "starts_at_zero": bool(subtitles) and float(subtitles[0]["start_seconds"]) == 0.0,
        "ends_at_total_duration": bool(subtitles) and abs(float(subtitles[-1]["end_seconds"]) - total_duration) < 0.001,
    }


def _safe_duration(value: Any) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return 3.0
    return duration if duration > 0 else 3.0


def _matches_window(source_start: float, source_end: float, shot_start: float, shot_end: float) -> bool:
    return abs(source_start - shot_start) < 0.001 and abs(source_end - shot_end) < 0.001


def _max_chars_per_block(platform: str) -> int:
    return 42 if platform == "bilibili" else 36


def _display_length(text: str) -> int:
    return sum(1 if ord(char) < 128 else 2 for char in text)
