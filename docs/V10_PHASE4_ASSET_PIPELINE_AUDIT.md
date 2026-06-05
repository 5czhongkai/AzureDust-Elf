# V10 Phase 4 Asset Pipeline Audit

## Goal

Turn Phase 4 visual planning into a structured media generation/import layer without automatically creating, downloading, importing, editing, uploading, or publishing media.

## Implemented Scope

- Extended `asset-agent` to produce:
  - `assets/asset_generation_tasks.json`
  - `assets/media_asset_manifest.json`
  - `assets/asset_ingest_guide.md`
- Added schemas:
  - `schemas/asset_generation_tasks.schema.json`
  - `schemas/media_asset_manifest.schema.json`
- Updated `final/video_production_package.json` to reference and embed:
  - global asset task package path
  - media asset manifest path
  - per-platform asset tasks
  - per-platform media assets
- Added `make validate-phase4-assets`.

## Boundary

This step creates planned tasks and import slots only. Storyboard keyframes are still planned here, but they are materialized later by the storyboard preview adapter in Phase 4 step 4.

- Asset generation: not performed
- Asset download: not performed
- Asset import: not performed
- Video editing: not performed
- Rights clearance: human review required

## Validation

```bash
python3 -m compileall src scripts
make validate-phase4-assets
make validate-phase4-video-package
make validate
```

The validation checks:

- `visual_assets` declares all asset pipeline outputs.
- `asset_generation_tasks.json` keeps every task in `planned` status.
- `media_asset_manifest.json` keeps every asset in `planned` status with `pending_human_review` rights state.
- B-roll target media paths are not created by the runner.
- Storyboard keyframe paths are created later by the storyboard preview adapter and remain pending human review.
- The final video production package embeds per-platform task and media asset entries.

## Status

Phase 4 step 2 is complete. The system now has a safe asset generation/import task layer ready for later adapters such as image generation, screen recording capture, stock media import, TTS, and editing project export.
