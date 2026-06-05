# V14 Phase 4 Voiceover TTS Audit

## Scope

Connect voiceover generation directly to `timed_subtitles.json` in Phase 4. The current adapter defaults to a local deterministic draft voiceover layer and can optionally call OpenAI Speech or SiliconFlow Speech when explicitly configured.

## Changes

- Added `voiceover-tts-agent`.
- Added `src/content_agent_os/voiceover_tts.py` for WAV generation from timed subtitles, with default local draft output and optional OpenAI Speech or SiliconFlow Speech output.
- Added workflow steps:
  - `douyin_voiceover_tts`
  - `shipinhao_voiceover_tts`
  - `bilibili_voiceover_tts`
- Added `schemas/voiceover_tts_manifest.schema.json`.
- Updated `final/video_production_package.json` to include:
  - voiceover WAV path
  - voiceover manifest path
  - provider metadata
  - duration validation summary
  - voiceover TTS export boundary
- Added `make validate-phase4-voiceover-tts`.

## Output Contract

Each selected video platform now produces:

- `assets/{platform}/voiceover/voiceover.wav`
- `assets/{platform}/voiceover/voiceover_manifest.json`

The manifest includes source timed subtitles, provider metadata, voice id, sample rate, segment timing, subtitle linkage, validation status, rights status, and review notes.

## Boundary

The current adapter is a hybrid voiceover generator.

- By default, no external TTS provider is called.
- Set `CONTENT_AGENT_OS_TTS_PROVIDER=openai` with `OPENAI_API_KEY` to call OpenAI Speech and record `provider_external=true`.
- Set `CONTENT_AGENT_OS_TTS_PROVIDER=siliconflow` with `SILICONFLOW_API_KEY` or `CONTENT_AGENT_OS_TTS_API_KEY` to call SiliconFlow Speech and record `provider_external=true`.
- The SiliconFlow validation reads its key from the workflow environment, prefers `SILICONFLOW_API_KEY` when present, and does not read desktop files or print secrets.
- No login, upload, sync, or publishing action is performed.
- Audio duration is forced to match `timed_subtitles.json`.
- Human review remains required before final editing or platform upload.
- The manifest records provider, provider mode, audio generation mode, rights status, and provider metadata so local and external voiceover output share the same contract.

## Verification

```bash
make validate
make validate-phase4-voiceover-tts
make validate-phase4-voiceover-tts-siliconflow
make validate-phase4-subtitle-timing
make validate-phase4-video-package
make validate-run RUN_ID="run_20260525T033550Z"
```

The new validation checks:

- voiceover steps exist in the workflow and use `voiceover-tts-agent`
- each voiceover step depends on `{platform}_subtitle_timing`
- WAV files are valid mono 16-bit audio
- WAV duration matches timed subtitles
- manifest segment count matches timed subtitle count
- final video production package includes voiceover deliverables and provider boundary metadata
- SiliconFlow smoke validation proves the external TTS provider returns aligned WAV audio and provider metadata

## Result

Phase 4 voiceover TTS generation is complete. The video production package now has a timed subtitle layer and an aligned voiceover audio layer for each video platform, defaulting to local draft audio unless external TTS is explicitly requested.

Reference run: `outputs/runs/run_20260525T033550Z`.
