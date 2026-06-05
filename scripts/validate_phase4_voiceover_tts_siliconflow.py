from __future__ import annotations

import json
import os
import sys
import wave
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.voiceover_tts import generate_voiceover_tts  # noqa: E402


MODEL = "fnlp/MOSS-TTSD-v0.5"
VOICE = f"{MODEL}:alex"
PROVIDER = "siliconflow-audio-speech-api"
MODE = "siliconflow_speech_api"


def fail(message: str) -> None:
    print(f"Phase 4 SiliconFlow voiceover TTS validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def _resolve_api_key() -> tuple[str, str]:
    env_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if env_key:
        return env_key, "SILICONFLOW_API_KEY"

    generic_env_key = os.environ.get("CONTENT_AGENT_OS_TTS_API_KEY", "").strip()
    if generic_env_key:
        return generic_env_key, "CONTENT_AGENT_OS_TTS_API_KEY"

    fail(
        "missing SiliconFlow API key; set SILICONFLOW_API_KEY in the workflow environment "
        "or CONTENT_AGENT_OS_TTS_API_KEY for this validation"
    )
    raise AssertionError("unreachable")


def _timed_subtitles() -> dict[str, Any]:
    return {
        "schema_version": "phase4.timed_subtitles.v1",
        "source_artifacts": ["smoke/timed_subtitles.json"],
        "subtitle_count": 1,
        "total_duration_seconds": 1.5,
        "validation": {"status": "PASSED"},
        "subtitles": [
            {
                "index": 1,
                "shot_id": "smoke_001",
                "scene": "SiliconFlow MOSS-TTSD smoke test",
                "start_seconds": 0.0,
                "end_seconds": 1.5,
                "duration_seconds": 1.5,
                "text": "你好，这是一次硅基流动配音接口测试。",
            }
        ],
    }


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("provider_external") is not True:
        fail(f"provider_external must be true; got provider={manifest.get('provider')!r}")
    if manifest.get("provider") != PROVIDER:
        fail(f"provider must be {PROVIDER}")
    if manifest.get("audio_generation_mode") != MODE:
        fail(f"audio_generation_mode must be {MODE}")
    if manifest.get("generation_status") != "generated_external_tts_pending_human_review":
        fail("generation_status must mark external TTS generation")
    if manifest.get("rights_status") != "ai_generated_pending_human_review":
        fail("rights_status must mark AI-generated voiceover")

    metadata = manifest.get("provider_metadata")
    if not isinstance(metadata, dict):
        fail("provider_metadata must be present")
    expected_metadata = {
        "model": MODEL,
        "voice_id": VOICE,
        "endpoint": "https://api.siliconflow.cn/v1/audio/speech",
        "response_format": "wav",
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            fail(f"provider_metadata.{key} mismatch")
    if metadata.get("timeline_alignment_status") not in {
        "unchanged",
        "padded_with_trailing_silence",
        "truncated_to_timeline",
    }:
        fail("provider_metadata.timeline_alignment_status mismatch")


def _validate_wav(audio_bytes: bytes) -> dict[str, Any]:
    if audio_bytes[:4] != b"RIFF":
        fail("generated audio is not a RIFF/WAV file")
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            duration = wav.getnframes() / sample_rate
    except wave.Error as exc:
        fail(f"invalid WAV file: {exc}")
    if channels != 1:
        fail("generated WAV must be mono")
    if sample_width != 2:
        fail("generated WAV must be 16-bit")
    if sample_rate != 16000:
        fail("generated WAV sample rate must be 16000 Hz")
    if abs(duration - 1.5) >= 0.01:
        fail("generated WAV duration must match the 1.5s smoke timeline")
    return {
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate": sample_rate,
        "duration_seconds": round(duration, 3),
    }


def validate_siliconflow_voiceover_tts() -> None:
    api_key, key_source = _resolve_api_key()
    os.environ["SILICONFLOW_API_KEY"] = api_key
    os.environ["CONTENT_AGENT_OS_TTS_PROVIDER"] = "siliconflow"
    os.environ["CONTENT_AGENT_OS_TTS_MODEL"] = MODEL
    os.environ["CONTENT_AGENT_OS_TTS_VOICE"] = VOICE
    os.environ["CONTENT_AGENT_OS_TTS_SAMPLE_RATE"] = "16000"

    with TemporaryDirectory() as tmp:
        output_path = Path(tmp) / "siliconflow_voiceover_smoke.wav"
        result = generate_voiceover_tts(
            run_id="run_siliconflow_tts_smoke",
            topic="SiliconFlow MOSS-TTSD smoke test",
            platform="douyin",
            platform_label="抖音",
            timed_subtitles=_timed_subtitles(),
            target_path=str(output_path),
        )
        _validate_manifest(result.manifest)
        wav_summary = _validate_wav(result.audio_bytes)
        output_path.write_bytes(result.audio_bytes)

    metadata = result.manifest.get("provider_metadata", {})
    print(
        json.dumps(
            {
                "status": "PASSED",
                "provider": result.manifest.get("provider"),
                "provider_external": result.manifest.get("provider_external"),
                "audio_generation_mode": result.manifest.get("audio_generation_mode"),
                "model": metadata.get("model"),
                "voice_id": metadata.get("voice_id"),
                "endpoint": metadata.get("endpoint"),
                "response_format": metadata.get("response_format"),
                "original_duration_seconds": metadata.get("original_duration_seconds"),
                "timeline_alignment_status": metadata.get("timeline_alignment_status"),
                "audio_bytes": len(result.audio_bytes),
                "wav": wav_summary,
                "key_source": key_source,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    validate_siliconflow_voiceover_tts()
    print("Phase 4 SiliconFlow voiceover TTS validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
