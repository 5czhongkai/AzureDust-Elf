# V20 Phase 4 Licensed Media Ingest Audit

## Scope

Add a local licensed media ingest and review handoff layer after B-roll reference materialization. This layer turns each reference asset into a final-media intake slot, records whether a human supplied approved media, and hands editors a clear review checklist.

## Changes

- Added `licensed-media-ingest-agent`.
- Added `src/content_agent_os/licensed_media_ingest.py`.
- Added workflow steps:
  - `douyin_licensed_media_ingest`
  - `shipinhao_licensed_media_ingest`
  - `bilibili_licensed_media_ingest`
- Added schemas:
  - `schemas/licensed_media_ingest_manifest.schema.json`
  - `schemas/licensed_media_ingest_bundle_manifest.schema.json`
- Added outputs:
  - `assets/{platform}/licensed_media/ingest_manifest.json`
  - `assets/{platform}/licensed_media/README.md`
  - `assets/{platform}/licensed_media/review_handoff.md`
  - `final/licensed_media_ingest_manifest.json`
- Added `make validate-phase4-licensed-media-ingest`.
- Updated edit/export/project bundle/video package wiring to carry ingest status through the handoff.

## Output Contract

Each platform ingest manifest records:

- the source B-roll reference asset
- the optional human media registry path
- required final media count
- pending human media count
- candidate media count
- editor-ready media count
- per-asset intake status and rights confirmation
- required human actions before replacement

The final ingest manifest summarizes all video platforms and is referenced by both `final/video_production_package.json` and `final/content_package_manifest.json`.

## Human Registry

The optional local registry is:

```text
assets/{platform}/licensed_media/human_media_registry.json
```

Expected fields per media record:

- `asset_id`
- `licensed_media_path`
- `license_source`
- `rights_confirmation`
- `review_status`

An item is editor-ready only when the registered media file exists, `review_status` is `approved_for_edit`, and `rights_confirmation` is one of:

- `licensed_confirmed`
- `self_created_confirmed`
- `licensed_or_self_created_confirmed`

## Boundary

The current adapter is a local review handoff generator.

- No external asset search is performed.
- No asset download is performed.
- No license purchase or rights transaction is performed.
- No editing software is opened.
- No upload or publishing action is performed.
- Pending ingest media is not final footage; licensed or self-created final media is still required.

## Verification

```bash
make validate
make validate-phase4-licensed-media-ingest
make validate-phase4-video-package
make validate-run RUN_ID="run_20260526T000000Z"
```

The new validation checks:

- workflow ingest steps exist and use `licensed-media-ingest-agent`
- edit project steps depend on licensed media ingest
- ingest manifests, READMEs, and review handoff files are generated
- no external search, download, purchase, upload, publishing, or editing software action is performed
- edit timelines attach ingest manifest and review handoff paths to B-roll placeholders
- offline media reports mark B-roll slots as pending human licensed media
- project bundle ZIPs include licensed media handoff files under `licensed_media/`
- final video/content packages reference `final/licensed_media_ingest_manifest.json`

## Result

Phase 4 now has a review handoff layer between local B-roll references and final editor replacement. The system can tell an editor exactly which final media files are still needed while preserving the core boundary: no external retrieval, no rights transaction, no editing software, no upload, and no publishing.
