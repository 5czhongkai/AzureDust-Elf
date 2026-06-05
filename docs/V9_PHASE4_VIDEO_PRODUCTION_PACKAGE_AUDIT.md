# V9 Phase 4 Video Production Package Audit

## Goal

Upgrade the existing text-first content package into a video production package that an editor can use before manual review and publishing.

## Implemented Scope

- Added a real `asset-agent` `run_agent(task_spec)` handler.
- Added a `visual_assets` workflow step that produces:
  - `asset_plan.json`
  - `cover_prompts.md`
- Extended video platform agents so selected video platforms produce:
  - `script.md`
  - `storyboard.json`
  - `subtitles.srt`
  - `shot_list.json`
  - `broll_list.json`
  - `cover_prompt.md`
- Extended Bilibili output with storyboard and subtitle artifacts in addition to chapters and description.
- Added `final/video_production_package.json` as the Phase 4 export package.
- Added `schemas/video_production_package.schema.json`.
- Added `make validate-phase4-video-package`.

## Production Boundaries

- No asset download.
- No video editing.
- No login or cookie refresh.
- No upload, sync, or publishing.
- Asset copyright status remains `human_review_required`.

## Validation

```bash
python3 -m compileall src scripts
make validate-phase4-video-package
make validate
```

The validation checks:

- Workflow has the `visual_assets` step.
- Video platform agents depend on `visual_assets`.
- `asset-agent` generates platform-specific shot lists, B-roll lists, cover prompts, and asset clearance notes.
- Douyin, Shipinhao, and Bilibili each produce script, storyboard, subtitles, shot list, B-roll list, and cover prompt artifacts.
- `final/video_production_package.json` references all video deliverables and preserves the no-upload/no-publish boundary.

## Status

Phase 4 step 1 is complete. The system now exports a video production package, while actual media generation, TTS, editing project export, and publishing remain future work.
