from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from io import BytesIO
from typing import Any


@dataclass(frozen=True)
class GeneratedVoiceoverTTS:
    audio_bytes: bytes
    manifest: dict[str, Any]


def generate_voiceover_tts(
    *,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    timed_subtitles: dict[str, Any],
    target_path: str,
    sample_rate: int = 16000,
) -> GeneratedVoiceoverTTS:
    subtitles = timed_subtitles.get("subtitles", [])
    if not isinstance(subtitles, list) or not subtitles:
        raise ValueError("voiceover TTS requires timed_subtitles.subtitles")
    total_duration = float(timed_subtitles.get("total_duration_seconds") or 0)
    if total_duration <= 0:
        raise ValueError("voiceover TTS requires positive total_duration_seconds")

    external_provider = _resolve_external_speech(
        topic=topic,
        platform=platform,
        platform_label=platform_label,
        subtitles=subtitles,
    )
    if external_provider is not None:
        audio_bytes, provider_metadata = external_provider
        aligned = _align_wav_to_duration(audio_bytes, total_duration)
        if aligned is not None:
            audio_bytes, audio_metadata = aligned
            provider_metadata = provider_metadata | audio_metadata
            sample_rate = int(audio_metadata["sample_rate"])
            duration_seconds = float(audio_metadata["duration_seconds"])
            segments = _segments_from_subtitles(
                subtitles,
                sample_rate=sample_rate,
                total_duration=duration_seconds,
            )
            manifest = _build_manifest(
                run_id=run_id,
                topic=topic,
                platform=platform,
                platform_label=platform_label,
                timed_subtitles=timed_subtitles,
                target_path=target_path,
                sample_rate=sample_rate,
                total_duration=duration_seconds,
                segments=segments,
                provider=provider_metadata["provider"],
                provider_external=True,
                voice_id=provider_metadata["voice_id"],
                generation_status="generated_external_tts_pending_human_review",
                rights_status="ai_generated_pending_human_review",
                audio_generation_mode=provider_metadata["audio_generation_mode"],
                provider_metadata=provider_metadata,
                review_notes=[
                    f"Generated voiceover uses {provider_metadata['provider_label']} and is aligned to timed_subtitles.json through the edit timeline.",
                    "End users must receive clear disclosure that the voice is AI-generated and not a human voice.",
                    "No editing, upload, sync, or publishing action was performed.",
                ],
            )
            return GeneratedVoiceoverTTS(audio_bytes=audio_bytes, manifest=manifest)

    total_samples = max(1, int(round(total_duration * sample_rate)))
    mix = [0.0] * total_samples
    segments = []
    for item in subtitles:
        if not isinstance(item, dict):
            continue
        start_seconds = float(item.get("start_seconds") or 0)
        end_seconds = float(item.get("end_seconds") or 0)
        start_sample = max(0, min(total_samples, int(round(start_seconds * sample_rate))))
        end_sample = max(start_sample, min(total_samples, int(round(end_seconds * sample_rate))))
        if end_sample <= start_sample:
            continue
        text = str(item.get("text") or "")
        voice_samples = _synthesize_text_samples(
            text=text,
            sample_count=end_sample - start_sample,
            sample_rate=sample_rate,
            platform=platform,
        )
        for offset, value in enumerate(voice_samples):
            mix[start_sample + offset] = _clamp(mix[start_sample + offset] + value)
        segments.append(_segment_from_subtitle(item, len(segments) + 1, start_sample, end_sample))

    audio_bytes = _write_wav(mix, sample_rate)
    requested_provider = os.environ.get("CONTENT_AGENT_OS_TTS_PROVIDER", "").strip().lower()
    provider_metadata: dict[str, Any] = {"sample_rate": sample_rate}
    if requested_provider:
        provider_metadata["requested_provider"] = requested_provider
        provider_metadata["fallback_reason"] = "external_provider_unavailable_or_invalid_response"
    manifest = _build_manifest(
        run_id=run_id,
        topic=topic,
        platform=platform,
        platform_label=platform_label,
        timed_subtitles=timed_subtitles,
        target_path=target_path,
        sample_rate=sample_rate,
        total_duration=total_samples / sample_rate,
        segments=segments,
        provider="local-deterministic-draft",
        provider_external=False,
        voice_id=_voice_id(platform),
        generation_status="generated_local_draft_pending_human_review",
        rights_status="self_generated_pending_human_review",
        audio_generation_mode="local_deterministic_draft",
        provider_metadata=provider_metadata,
        review_notes=[
            "Generated voiceover is a local deterministic draft aligned to timed_subtitles.json.",
            "No external TTS provider, upload, sync, or publishing action was performed.",
            "Set CONTENT_AGENT_OS_TTS_PROVIDER=openai or siliconflow to use a natural voice provider when an API key is available.",
        ],
    )
    return GeneratedVoiceoverTTS(audio_bytes=audio_bytes, manifest=manifest)


def _build_manifest(
    *,
    run_id: str,
    topic: str,
    platform: str,
    platform_label: str,
    timed_subtitles: dict[str, Any],
    target_path: str,
    sample_rate: int,
    total_duration: float,
    segments: list[dict[str, Any]],
    provider: str,
    provider_external: bool,
    voice_id: str,
    generation_status: str,
    rights_status: str,
    audio_generation_mode: str,
    provider_metadata: dict[str, Any],
    review_notes: list[str],
) -> dict[str, Any]:
    subtitles = timed_subtitles.get("subtitles", [])
    return {
        "schema_version": "phase4.voiceover_tts_manifest.v1",
        "artifact_type": "voiceover_tts",
        "run_id": run_id,
        "topic": topic,
        "platform": platform,
        "platform_label": platform_label,
        "adapter": "hybrid-voiceover-tts-adapter",
        "adapter_version": "0.1.0",
        "provider": provider,
        "provider_external": provider_external,
        "voice_id": voice_id,
        "language": "zh-CN",
        "audio_path": target_path,
        "audio_format": "wav",
        "sample_rate": sample_rate,
        "channels": 1,
        "bit_depth": 16,
        "duration_seconds": round(total_duration, 3),
        "source_timed_subtitles": timed_subtitles.get("source_artifacts", []) + [
            f"{platform}/timed_subtitles.json"
        ],
        "timed_subtitle_count": len(subtitles),
        "segment_count": len(segments),
        "segments": segments,
        "generation_status": generation_status,
        "rights_status": rights_status,
        "audio_generation_mode": audio_generation_mode,
        "provider_metadata": provider_metadata,
        "manual_review_required": True,
        "validation": {
            "status": "PASSED",
            "audio_duration_matches_timeline": abs(total_duration - float(timed_subtitles.get("total_duration_seconds") or 0)) < 0.01,
            "segments_match_timed_subtitles": len(segments) == len(subtitles),
            "source_validation_status": timed_subtitles.get("validation", {}).get("status")
            if isinstance(timed_subtitles.get("validation"), dict)
            else None,
        },
        "review_notes": review_notes,
        "review_required": True,
    }


def _segments_from_subtitles(
    subtitles: list[Any],
    *,
    sample_rate: int,
    total_duration: float,
) -> list[dict[str, Any]]:
    total_samples = max(1, int(round(total_duration * sample_rate)))
    segments: list[dict[str, Any]] = []
    for item in subtitles:
        if not isinstance(item, dict):
            continue
        start_seconds = float(item.get("start_seconds") or 0)
        end_seconds = float(item.get("end_seconds") or 0)
        start_sample = max(0, min(total_samples, int(round(start_seconds * sample_rate))))
        end_sample = max(start_sample, min(total_samples, int(round(end_seconds * sample_rate))))
        if end_sample <= start_sample:
            continue
        segments.append(_segment_from_subtitle(item, len(segments) + 1, start_sample, end_sample))
    return segments


def _segment_from_subtitle(
    item: dict[str, Any],
    index: int,
    start_sample: int,
    end_sample: int,
) -> dict[str, Any]:
    start_seconds = float(item.get("start_seconds") or 0)
    end_seconds = float(item.get("end_seconds") or 0)
    return {
        "index": index,
        "subtitle_index": item.get("index"),
        "shot_id": item.get("shot_id"),
        "scene": item.get("scene"),
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "duration_seconds": round(end_seconds - start_seconds, 3),
        "text": str(item.get("text") or ""),
        "track_start_sample": start_sample,
        "track_end_sample": end_sample,
        "source_timed_subtitle": item.get("index"),
    }


def _resolve_external_speech(
    *,
    topic: str,
    platform: str,
    platform_label: str,
    subtitles: list[Any],
) -> tuple[bytes, dict[str, Any]] | None:
    provider = os.environ.get("CONTENT_AGENT_OS_TTS_PROVIDER", "").strip().lower()
    if provider in {"openai", "openai-speech", "openai_speech"}:
        return _resolve_openai_speech(
            topic=topic,
            platform=platform,
            platform_label=platform_label,
            subtitles=subtitles,
        )
    if provider in {"siliconflow", "siliconflow-speech", "siliconflow_speech"}:
        return _resolve_siliconflow_speech(
            platform=platform,
            subtitles=subtitles,
        )
    return None


def _resolve_openai_speech(
    *,
    topic: str,
    platform: str,
    platform_label: str,
    subtitles: list[Any],
) -> tuple[bytes, dict[str, Any]] | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.environ.get("CONTENT_AGENT_OS_TTS_MODEL", "").strip() or "gpt-4o-mini-tts"
    voice = os.environ.get("CONTENT_AGENT_OS_TTS_VOICE", "").strip() or _openai_voice_id(platform)
    input_text = _openai_speech_input(subtitles)
    if not input_text:
        return None
    request_body = {
        "model": model,
        "voice": voice,
        "input": input_text,
        "instructions": _openai_speech_instructions(platform_label=platform_label, topic=topic),
        "response_format": "wav",
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            audio_bytes = response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if audio_bytes[:4] != b"RIFF":
        return None
    return audio_bytes, {
        "provider": "openai-speech-api",
        "provider_label": "OpenAI Speech API",
        "audio_generation_mode": "openai_speech_api",
        "model": model,
        "voice_id": voice,
        "endpoint": "https://api.openai.com/v1/audio/speech",
        "response_format": "wav",
        "input_character_count": len(input_text),
    }


def _resolve_siliconflow_speech(
    *,
    platform: str,
    subtitles: list[Any],
) -> tuple[bytes, dict[str, Any]] | None:
    api_key = (
        os.environ.get("SILICONFLOW_API_KEY", "").strip()
        or os.environ.get("CONTENT_AGENT_OS_TTS_API_KEY", "").strip()
    )
    if not api_key:
        return None

    model = os.environ.get("CONTENT_AGENT_OS_TTS_MODEL", "").strip() or "fnlp/MOSS-TTSD-v0.5"
    voice = os.environ.get("CONTENT_AGENT_OS_TTS_VOICE", "").strip() or _siliconflow_voice_id(platform, model)
    input_text = _openai_speech_input(subtitles)
    if not input_text:
        return None
    request_body = {
        "model": model,
        "voice": voice,
        "input": input_text,
        "response_format": "wav",
        "sample_rate": int(os.environ.get("CONTENT_AGENT_OS_TTS_SAMPLE_RATE", "").strip() or "16000"),
        "stream": False,
    }
    request = urllib.request.Request(
        "https://api.siliconflow.cn/v1/audio/speech",
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            audio_bytes = response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if audio_bytes[:4] != b"RIFF":
        return None
    return audio_bytes, {
        "provider": "siliconflow-audio-speech-api",
        "provider_label": "SiliconFlow Audio Speech API",
        "audio_generation_mode": "siliconflow_speech_api",
        "model": model,
        "voice_id": voice,
        "endpoint": "https://api.siliconflow.cn/v1/audio/speech",
        "response_format": "wav",
        "input_character_count": len(input_text),
    }


def _align_wav_to_duration(audio_bytes: bytes, total_duration: float) -> tuple[bytes, dict[str, Any]] | None:
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            original_frames = wav.getnframes()
            pcm = wav.readframes(original_frames)
    except (wave.Error, EOFError, OSError):
        return None
    if sample_width != 2 or channels < 1 or sample_rate <= 0:
        return None

    mono_pcm = _to_mono_16bit_pcm(pcm, channels)
    original_frames_from_bytes = len(mono_pcm) // 2
    target_frames = max(1, int(round(total_duration * sample_rate)))
    target_bytes = target_frames * 2
    if len(mono_pcm) < target_bytes:
        mono_pcm = mono_pcm + (b"\x00" * (target_bytes - len(mono_pcm)))
        alignment_status = "padded_with_trailing_silence"
    elif len(mono_pcm) > target_bytes:
        mono_pcm = mono_pcm[:target_bytes]
        alignment_status = "truncated_to_timeline"
    else:
        alignment_status = "unchanged"

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(mono_pcm)
    return buffer.getvalue(), {
        "sample_rate": sample_rate,
        "channels": 1,
        "bit_depth": 16,
        "duration_seconds": round(target_frames / sample_rate, 3),
        "original_channels": channels,
        "original_sample_rate": sample_rate,
        "original_duration_seconds": round(original_frames_from_bytes / sample_rate, 3),
        "timeline_alignment_status": alignment_status,
    }


def _to_mono_16bit_pcm(pcm: bytes, channels: int) -> bytes:
    if channels == 1:
        return pcm
    frame_width = channels * 2
    output = bytearray()
    for offset in range(0, len(pcm) - frame_width + 1, frame_width):
        total = 0
        for channel in range(channels):
            start = offset + channel * 2
            total += int.from_bytes(pcm[start : start + 2], byteorder="little", signed=True)
        value = int(total / channels)
        output.extend(value.to_bytes(2, byteorder="little", signed=True))
    return bytes(output)


def _openai_speech_input(subtitles: list[Any]) -> str:
    lines = []
    for item in subtitles:
        if isinstance(item, dict):
            text = " ".join(str(item.get("text") or "").split())
            if text:
                lines.append(text)
    return "\n".join(lines)


def _openai_speech_instructions(*, platform_label: str, topic: str) -> str:
    return (
        "Speak Mandarin Chinese in a clear, natural creator voice. "
        f"Tone should fit {platform_label} content about {topic}. "
        "Keep pacing concise and suitable for subtitle-aligned video narration."
    )


def _siliconflow_voice_id(platform: str, model: str) -> str:
    return os.environ.get("CONTENT_AGENT_OS_TTS_VOICE", "").strip() or f"{model}:alex"


def _synthesize_text_samples(
    *,
    text: str,
    sample_count: int,
    sample_rate: int,
    platform: str,
) -> list[float]:
    clean_text = "".join(char for char in text if not char.isspace()) or "voiceover"
    units = [ord(char) for char in clean_text]
    base_frequency = _base_frequency(platform)
    samples: list[float] = []
    for index in range(sample_count):
        t = index / sample_rate
        progress = index / max(1, sample_count - 1)
        unit = units[min(len(units) - 1, int(progress * len(units)))]
        frequency = base_frequency + (unit % 29) * 5.5
        syllable_gate = 0.62 + 0.38 * math.sin(2 * math.pi * (5.5 + (unit % 5)) * t)
        envelope = _envelope(index, sample_count, sample_rate)
        value = (
            math.sin(2 * math.pi * frequency * t)
            + 0.38 * math.sin(2 * math.pi * frequency * 2.0 * t)
            + 0.16 * math.sin(2 * math.pi * frequency * 3.0 * t)
        )
        samples.append(_clamp(0.13 * envelope * syllable_gate * value))
    return samples


def _write_wav(samples: list[float], sample_rate: int) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        pcm = bytearray()
        for sample in samples:
            value = int(_clamp(sample) * 32767)
            pcm.extend(value.to_bytes(2, byteorder="little", signed=True))
        wav.writeframes(bytes(pcm))
    return buffer.getvalue()


def _envelope(index: int, sample_count: int, sample_rate: int) -> float:
    attack = max(1, int(sample_rate * 0.035))
    release = max(1, int(sample_rate * 0.05))
    if index < attack:
        return index / attack
    remaining = sample_count - index - 1
    if remaining < release:
        return max(0.0, remaining / release)
    return 1.0


def _base_frequency(platform: str) -> float:
    return {
        "douyin": 178.0,
        "shipinhao": 164.0,
        "bilibili": 148.0,
    }.get(platform, 168.0)


def _voice_id(platform: str) -> str:
    return {
        "douyin": "local-tone-cn-fast",
        "shipinhao": "local-tone-cn-warm",
        "bilibili": "local-tone-cn-clear",
    }.get(platform, "local-tone-cn")


def _openai_voice_id(platform: str) -> str:
    return {
        "douyin": "marin",
        "shipinhao": "cedar",
        "bilibili": "coral",
    }.get(platform, "marin")


def _clamp(value: float) -> float:
    return max(-0.98, min(0.98, value))
