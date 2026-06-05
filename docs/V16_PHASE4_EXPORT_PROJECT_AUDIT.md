# V16 Phase 4 Export Project Audit

## Scope

Connect the edit timeline layer to a local editor handoff package. The first adapter is a deterministic export project layer that turns `edit_timeline.json` and `edit_manifest.json` into a draft FCPXML project, import notes, offline media report, and export manifest.

## Changes

- Added `export-project-agent`.
- Added `src/content_agent_os/export_project.py`.
- Added workflow steps:
  - `douyin_export_project`
  - `shipinhao_export_project`
  - `bilibili_export_project`
- Added schemas:
  - `schemas/export_project_manifest.schema.json`
  - `schemas/export_project_bundle_manifest.schema.json`
- Updated `final/video_production_package.json` to include:
  - FCPXML project path
  - import readme path
  - offline media report path
  - export manifest path
  - export project validation summary
  - export project boundary metadata
- Added `final/export_project_manifest.json` as the cross-platform export handoff index.
- Added `make validate-phase4-export-project`.

## Output Contract

Each selected video platform now produces:

- `assets/{platform}/edit/project.fcpxml`
- `assets/{platform}/edit/import_readme.md`
- `assets/{platform}/edit/offline_media_report.json`
- `assets/{platform}/edit/export_manifest.json`

The final package also produces:

- `final/export_project_manifest.json`

The FCPXML draft references generated storyboard keyframes and the local voiceover WAV. Timed subtitles remain a sidecar SRT for editor import. B-roll slots remain offline placeholders until licensed media is imported.

## Boundary

The current adapter is a local draft export generator.

- No editing software is opened.
- No rendered video is exported.
- No upload, sync, or publishing action is performed.
- B-roll remains placeholder slots until licensed footage is imported.
- Human review remains required before final editing or platform upload.

## Verification

```bash
make validate
make validate-phase4-export-project
make validate-phase4-video-package
make validate-run RUN_ID="run_20260525T000000Z"
```

The new validation checks:

- export project steps exist in the workflow and use `export-project-agent`
- each export project step depends on its platform edit project
- FCPXML is well-formed XML
- storyboard keyframe and voiceover references exist
- offline B-roll slots are reported
- final video production package includes export deliverables and boundary metadata

## Result

Phase 4 export project generation is complete. The system now produces a local editor handoff package after storyboard, subtitle timing, voiceover, and edit timeline generation.
