# V17 Phase 4 Project Bundle Audit

## Scope

Add a final local handoff bundle after `export-project-agent`. The first adapter is a deterministic ZIP packaging layer that collects the FCPXML draft, import notes, offline media report, export manifest, edit timeline, EDL, subtitle sidecar, voiceover audio, and storyboard keyframes into a reviewable project bundle.

## Changes

- Added `project-bundle-agent` to the Phase 4 validation surface.
- Added `make validate-phase4-project-bundle`.
- Added schemas:
  - `schemas/project_bundle_manifest.schema.json`
  - `schemas/project_bundle_bundle_manifest.schema.json`
- Updated video and content package contracts to include `final/project_bundle_manifest.json`.
- Added per-platform bundle deliverables to `final/video_production_package.json`.

## Output Contract

Each selected video platform now produces:

- `assets/{platform}/bundle/project_bundle.zip`
- `assets/{platform}/bundle/project_bundle_manifest.json`
- `assets/{platform}/bundle/file_manifest.json`
- `assets/{platform}/bundle/README.md`

The final package also produces:

- `final/project_bundle_manifest.json`

The ZIP bundle contains the local editor handoff files under stable archive paths such as `project/project.fcpxml`, `subtitles/timed_subtitles.srt`, `audio/voiceover.wav`, `metadata/edit_timeline.json`, and `reports/offline_media_report.json`.

## Boundary

The current adapter is a local handoff packager.

- No editing software is opened.
- No rendered video is exported.
- No upload, sync, or publishing action is performed.
- B-roll remains placeholder slots until licensed footage is imported.
- Human review remains required before final editing or platform upload.

## Verification

```bash
make validate
make validate-phase4-export-project
make validate-phase4-project-bundle
make validate-phase4-video-package
make validate-run RUN_ID="run_20260525T000000Z"
```

The new validation checks:

- project bundle steps exist in the workflow and use `project-bundle-agent`
- each bundle step depends on its platform export project
- bundle ZIPs are valid and contain the required editor handoff files
- file manifests list every bundled source
- final video and content packages reference `final/project_bundle_manifest.json`
- no editing software, upload, sync, or publishing action is performed

## Result

Phase 4 project bundle generation is complete. The system now produces a local ZIP handoff package after export project generation, so each video platform has a portable review bundle for a human editor.
