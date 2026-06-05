# V25 Phase 4 Editor Software Import Executor Audit

## Scope

This audit covers the editor software import executor layer after the editor project mutation sandbox. It reads the sandbox mutation manifest, patched FCPXML copy, mutation diff, rollback manifest, and optional human software import approval, then generates an isolated import plan and dry-run command preview for a real editing software handoff.

This layer is intentionally non-executing. It does not open editing software, does not import the project, does not mutate project files, does not upload files, does not publish content, does not search for media, does not download media, and does not purchase licenses.

## Inputs

- `assets/{platform}/edit/mutation_sandbox/mutation_manifest.json`
- `assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml`
- `assets/{platform}/edit/mutation_sandbox/mutation_diff.json`
- `assets/{platform}/edit/mutation_sandbox/rollback_manifest.json`
- Optional `assets/{platform}/edit/software_import_executor/human_software_import_approval.json`

## Outputs

- `assets/{platform}/edit/software_import_executor/import_executor_manifest.json`
- `assets/{platform}/edit/software_import_executor/import_plan.json`
- `assets/{platform}/edit/software_import_executor/import_commands.json`
- `assets/{platform}/edit/software_import_executor/software_import_audit_log.json`
- `assets/{platform}/edit/software_import_executor/rollback_safety_report.json`
- `assets/{platform}/edit/software_import_executor/isolated_execution_request.md`
- `assets/{platform}/edit/software_import_executor/README.md`
- Optional `assets/{platform}/edit/software_import_executor/human_software_import_approval.json`
- `final/editor_software_import_manifest.json`

## Boundary

Default runs without an approval file must keep this boundary:

- `editor_software_import_executor=blocked_pending_explicit_human_software_import_approval`
- `software_import_execution=not_performed`
- `editing_software=not_opened`
- `project_file_mutation=not_performed_by_executor`
- `original_project_mutation=not_performed`
- `replacement_execution=not_performed`
- `requires_explicit_human_software_import_approval=true`
- `external_software_isolation=required_before_manual_launch`
- `asset_download=not_performed`
- `external_asset_search=not_performed`
- `license_purchase=not_performed`
- `upload=not_performed`
- `publishing=not_performed`

When a valid `human_software_import_approval.json` is present and the patched project checksum matches, this layer may mark items as ready for isolated manual import:

- `editor_software_import_executor=approved_for_isolated_manual_import_not_executed`
- `software_import_execution=not_performed`
- `editing_software=not_opened`
- `project_file_mutation=not_performed_by_executor`
- `original_project_mutation=not_performed`
- `replacement_execution=not_performed`

The approval only moves the import plan to a ready-for-manual-import state. It does not authorize automatic software launch, automatic import, project mutation, upload, or publishing.

## Approval Contract

The optional software import approval file must be created by a human and must include:

```json
{
  "approval_status": "approved_for_editor_software_import",
  "human_software_import_approval": true,
  "approved_patched_project_sha256": "<patched_project_sha256>",
  "approved_by": "human",
  "approval_note": "Reviewed sandbox patched project and allow isolated manual import planning."
}
```

## Verification

Run:

```bash
make validate-phase4-editor-software-import-executor
```

The validation covers two paths:

- Default no-approval path: import commands remain dry-run, all import items stay blocked pending explicit human software import approval, and no editor software is opened.
- Explicit approval path: the matching patched project can become `ready_for_isolated_manual_import`, but import execution, editor launch, project file mutation, upload, and publishing remain not performed.
