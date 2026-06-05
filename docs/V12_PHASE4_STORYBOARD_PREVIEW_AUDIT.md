# V12 Phase 4 Storyboard Preview Audit

## Goal

Introduce the storyboard preview adapter in Phase 4: local generation of storyboard keyframe PNGs and a preview sheet for the three video platforms.

## Implemented Scope

- Added `storyboard-preview-agent`.
- Added a local Pillow-based storyboard preview adapter.
- Added workflow steps:
  - `douyin_storyboard_preview`
  - `shipinhao_storyboard_preview`
  - `bilibili_storyboard_preview`
- Added schema:
  - `schemas/storyboard_preview_metadata.schema.json`
- Extended `video_production_package.json` to include:
  - storyboard preview sheet path
  - storyboard preview metadata path
  - storyboard keyframe assets
  - storyboard preview export boundary

## Output Contract

Each selected video platform now produces:

- `assets/{platform}/storyboard/storyboard_preview.png`
- `assets/{platform}/storyboard/storyboard_preview_metadata.json`
- `assets/{platform}/storyboard/{shot_id}.png`

The generated storyboard assets are local drafts only.

- generation status: `generated_pending_review`
- rights status: `pending_human_review`
- upload: not performed
- publish: not performed

## Validation

```bash
python3 -m compileall src scripts
make validate-phase4-storyboard-adapter
make validate-phase4-cover-adapter
make validate-phase4-assets
make validate-phase4-video-package
make validate
```

The validation checks:

- storyboard preview steps exist in the workflow and use `storyboard-preview-agent`
- storyboard preview PNGs are created locally for the selected video platforms
- preview metadata marks the assets as pending human review
- generated storyboard assets are embedded in the final video production package

## Status

Phase 4 step 4 is complete. The system can now generate local storyboard preview sheets and keyframe PNGs while preserving the manual review boundary.
