# V15 Phase 4 Edit Project Audit

## Scope

Connect the video production package to an executable edit timeline. The first adapter is a local deterministic edit project layer that turns storyboard keyframes, timed subtitles, voiceover audio, shot list, and B-roll slots into timeline JSON plus an EDL draft.

## Changes

- Added `edit-project-agent`.
- Added `src/content_agent_os/edit_project.py`.
- Added workflow steps:
  - `douyin_edit_project`
  - `shipinhao_edit_project`
  - `bilibili_edit_project`
- Added schemas:
  - `schemas/edit_timeline.schema.json`
  - `schemas/edit_project_manifest.schema.json`
  - `schemas/edit_project_bundle_manifest.schema.json`
- Updated `final/video_production_package.json` to include:
  - edit timeline path
  - edit manifest path
  - draft EDL path
  - track summary
  - edit project validation summary
  - final edit project manifest path
  - edit project export boundary
- Added `final/edit_project_manifest.json` as the cross-platform edit handoff index.
- Added `make validate-phase4-edit-project`.

## Output Contract

Each selected video platform now produces:

- `assets/{platform}/edit/edit_timeline.json`
- `assets/{platform}/edit/edit_manifest.json`
- `assets/{platform}/edit/draft_cut.edl`

The final package also produces:

- `final/edit_project_manifest.json`

The timeline contains video, audio, and subtitle tracks. Video clips map to storyboard keyframes, audio clips map to the generated voiceover WAV, and subtitle clips map to timed subtitle blocks.

## Boundary

The current adapter is a local draft edit timeline generator.

- No editing software is opened.
- No rendered video is exported.
- B-roll remains placeholder slots until licensed footage is imported.
- No upload, sync, or publishing action is performed.
- Human review remains required before final editing or platform upload.

## Verification

```bash
make validate
make validate-phase4-edit-project
make validate-phase4-video-package
make validate-run RUN_ID="run_20260525T033550Z"
```

The new validation checks:

- edit project steps exist in the workflow and use `edit-project-agent`
- each edit project step depends on storyboard preview and voiceover TTS
- timeline video clip count matches storyboard count
- audio and subtitle tracks match timed subtitle duration
- EDL draft is generated
- `final/edit_project_manifest.json` references all video platform edit deliverables
- final video production package includes edit deliverables and boundary metadata

## Result

Phase 4 edit project generation is complete. The system now produces a practical edit handoff package after storyboard, subtitle timing, and voiceover generation.
