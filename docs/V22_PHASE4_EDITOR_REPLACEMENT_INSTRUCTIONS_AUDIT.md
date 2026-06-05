# V22 Phase 4 Editor Replacement Instructions Audit

## Scope

This audit covers the layer that converts `replacement_suggestions.json` into editor-facing import templates, dry-run automation commands, and a human confirmation checklist.

The layer starts after `licensed-media-proxy-agent` has generated replacement suggestions and any local proxy media copies. It does not open editing software, mutate project files, execute replacements, upload files, publish content, search for media, download media, or purchase licenses.

## Inputs

- `assets/{platform}/licensed_media/replacement_suggestions.json`
- `assets/{platform}/licensed_media/proxy_manifest.json`
- `assets/{platform}/edit/edit_timeline.json`
- `assets/{platform}/edit/offline_media_report.json`
- `assets/{platform}/edit/export_manifest.json`

## Outputs

- `assets/{platform}/edit/replacement_instructions/instruction_manifest.json`
- `assets/{platform}/edit/replacement_instructions/replacement_commands.json`
- `assets/{platform}/edit/replacement_instructions/editor_import_template.fcpxml`
- `assets/{platform}/edit/replacement_instructions/human_confirmation_checklist.md`
- `assets/{platform}/edit/replacement_instructions/README.md`
- `final/editor_replacement_instruction_manifest.json`

The FCPXML file is an import template for staging replacement candidates. The JSON commands are a dry-run automation contract only. They are not executed by this layer.

## Boundary

The editor replacement instruction layer must keep this boundary:

- `editor_replacement_instructions=performed_locally_template_and_instruction_only`
- `replacement_execution=not_performed`
- `editing_software=not_opened`
- `project_file_mutation=not_performed`
- `asset_download=not_performed`
- `external_asset_search=not_performed`
- `license_purchase=not_performed`
- `upload=not_performed`
- `publishing=not_performed`

Every instruction and command must keep:

- `dry_run_only=true`
- `human_confirmation_required=true`
- `confirmation_gate_status=pending_human_confirmation`
- `execution_status=not_executed`

## Human Confirmation Gate

Ready proxy media can produce `ready_pending_human_confirmation` instructions, but those instructions are still gated. A human editor must confirm rights, visual fit, timeline placement, audio/subtitle sync, and final replacement approval before any future execution adapter may mutate an editor project.

Pending or blocked media produce non-executable instructions that explain the missing prerequisite.

## Verification

Run:

```bash
make validate-phase4-editor-replacement-instructions
```

The validation covers two paths:

- Default no-registry path: pending dry-run instructions, valid FCPXML, commands all `dry_run_only=true`, and no replacement execution.
- Human registry path: a local ready proxy creates ready editor instructions and an FCPXML import candidate, but replacement execution remains `not_executed` and the human gate remains active.
