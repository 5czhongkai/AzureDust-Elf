# V13 Phase 4 Subtitle Timing Audit

## Scope

Introduce deterministic subtitle timing correction in Phase 4: convert platform subtitle drafts into shot-aligned timed subtitle artifacts for Douyin, Shipinhao, and Bilibili.

## Changes

- Added `subtitle-timing-agent`.
- Added `src/content_agent_os/subtitle_timing.py` for local SRT parsing, shot-window alignment, long caption splitting, and SRT rendering.
- Added workflow steps:
  - `douyin_subtitle_timing`
  - `shipinhao_subtitle_timing`
  - `bilibili_subtitle_timing`
- Added `schemas/timed_subtitles.schema.json`.
- Updated `final/video_production_package.json` to include:
  - timed subtitle JSON path
  - corrected SRT path
  - timing validation summary
  - subtitle timing export boundary
- Added `make validate-phase4-subtitle-timing`.

## Output Contract

Each selected video platform now produces:

- `{platform}/timed_subtitles.json`
- `{platform}/timed_subtitles.srt`

The timed subtitle JSON includes source artifacts, per-block start/end seconds, SRT timecodes, linked `shot_id`, split metadata, corrections, and validation status.

## Boundary

The adapter is local and deterministic.

- No TTS provider is called.
- No audio is generated.
- No editing project is exported.
- No login, upload, sync, or publishing action is performed.
- Human review remains required before final editing or platform upload.

## Verification

```bash
make validate
make validate-phase4-subtitle-timing
make validate-phase4-storyboard-adapter
make validate-phase4-video-package
make validate-run RUN_ID="run_20260525T031408Z"
```

The new validation checks:

- subtitle timing steps exist in the workflow and use `subtitle-timing-agent`
- each timing step depends on the video output and storyboard preview
- timed subtitles align to storyboard total duration
- each subtitle block stays inside its linked shot window
- corrected SRT block count matches the JSON subtitle count
- final video production package includes timed subtitle deliverables and boundary metadata

## Result

Phase 4 subtitle timing correction is complete. The system now has a TTS-ready timing layer that can be reused by a future voiceover adapter without requiring external provider credentials.

Reference run: `outputs/runs/run_20260525T031408Z`.
