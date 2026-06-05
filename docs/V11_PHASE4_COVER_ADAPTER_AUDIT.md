# V11 Phase 4 Cover Adapter Audit

## Goal

Introduce the first real media adapter in Phase 4: local cover image generation for the three video platforms.

## Implemented Scope

- Added `cover-image-agent`.
- Added a local Pillow-based cover generation adapter.
- Added workflow steps:
  - `douyin_cover_image`
  - `shipinhao_cover_image`
  - `bilibili_cover_image`
- Added schemas:
  - `schemas/cover_image_metadata.schema.json`
- Extended `video_production_package.json` to include:
  - generated cover image path
  - generated cover metadata path
  - local cover generation boundary
  - generated asset metadata

## Output Contract

Each selected video platform now produces:

- `assets/{platform}/cover/cover.png`
- `assets/{platform}/cover/cover_metadata.json`

The generated image is a local draft only.

- generation status: `generated_pending_review`
- rights status: `pending_human_review`
- upload: not performed
- publish: not performed

## Validation

```bash
python3 -m compileall src scripts
make validate-phase4-cover-adapter
make validate-phase4-assets
make validate-phase4-video-package
make validate
```

The validation checks:

- cover steps exist in the workflow and use `cover-image-agent`
- cover PNGs are created locally for the selected video platforms
- cover metadata marks the assets as pending human review
- generated cover assets are embedded in the final video production package

## Status

Phase 4 step 3 is complete. The system can now generate local cover drafts as the first true media adapter while preserving the manual review boundary.
