# V19 Phase 4 Asset Materialization Audit

## Scope

Add a local asset materialization layer for B-roll planning. The layer generates self-created reference PNGs from existing B-roll tasks so editors can review visual intent before replacing placeholders with licensed final media.

## Changes

- Added `asset-materialization-agent`.
- Added `src/content_agent_os/asset_materialization.py`.
- Added workflow steps:
  - `douyin_asset_materialization`
  - `shipinhao_asset_materialization`
  - `bilibili_asset_materialization`
- Added schemas:
  - `schemas/materialized_assets_manifest.schema.json`
  - `schemas/materialization_bundle_manifest.schema.json`
- Added outputs:
  - `assets/{platform}/materials/material_manifest.json`
  - `assets/{platform}/materials/README.md`
  - `assets/{platform}/materials/{asset_id}_reference.png`
  - `final/materialization_manifest.json`
- Added `make validate-phase4-asset-materialization`.
- Updated edit/export/project bundle/video package wiring to carry reference paths through the handoff.

## Output Contract

Each platform materialization manifest records:

- materialized B-roll reference assets
- reference PNG path, size, and SHA-256
- planned final B-roll target path
- rights status and manual review requirement
- local-only generation boundary

The final materialization manifest summarizes all video platforms and is referenced by both `final/video_production_package.json` and `final/content_package_manifest.json`.

## Boundary

The current adapter is a local reference generator.

- No external asset search is performed.
- No asset download is performed.
- No editing software is opened.
- No upload or publishing action is performed.
- Reference PNGs are not final footage; licensed final media is still required.

## Verification

```bash
make validate
make validate-phase4-asset-materialization
make validate-phase4-video-package
make validate-run RUN_ID="run_20260525T000000Z"
```

The new validation checks:

- workflow materialization steps exist and use `asset-materialization-agent`
- edit project steps depend on materialization
- material manifests, READMEs, and reference PNGs are generated
- reference PNGs are valid images with platform-appropriate orientation
- edit timelines attach `reference_path` to B-roll placeholders
- offline media reports mark B-roll slots as reference-generated pending licensed media
- project bundle ZIPs include reference PNGs under `materials/`
- final video/content packages reference `final/materialization_manifest.json`

## Result

Phase 4 now has a local asset materialization layer between B-roll planning and edit/export handoff. The system is less abstract for editors while still preserving the safety boundary: no external media retrieval, no publishing action, and final licensed media remains a human responsibility.
