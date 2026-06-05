# V23 Phase 4 Editor Replacement Execution Audit

## Scope

This audit covers the execution-adapter preflight layer that sits after editor replacement instructions. It reads dry-run replacement commands and prepares an auditable execution plan, audit log, approval request, and README.

This layer is intentionally non-executing. It does not open editing software, mutate project files, execute replacements, upload files, publish content, search for media, download media, or purchase licenses.

## Inputs

- `assets/{platform}/edit/replacement_instructions/instruction_manifest.json`
- `assets/{platform}/edit/replacement_instructions/replacement_commands.json`
- Optional `assets/{platform}/edit/replacement_execution/human_execution_approval.json`

## Outputs

- `assets/{platform}/edit/replacement_execution/execution_manifest.json`
- `assets/{platform}/edit/replacement_execution/execution_plan.json`
- `assets/{platform}/edit/replacement_execution/execution_audit_log.json`
- `assets/{platform}/edit/replacement_execution/human_execution_approval_request.md`
- `assets/{platform}/edit/replacement_execution/README.md`
- Optional `assets/{platform}/edit/replacement_execution/human_execution_approval.json`
- `final/editor_replacement_execution_manifest.json`

## Boundary

Default runs without an approval file must keep this boundary:

- `editor_replacement_execution=blocked_pending_explicit_human_approval`
- `replacement_execution=not_performed`
- `editing_software=not_opened`
- `project_file_mutation=not_performed`
- `requires_explicit_human_approval=true`
- `asset_download=not_performed`
- `external_asset_search=not_performed`
- `license_purchase=not_performed`
- `upload=not_performed`
- `publishing=not_performed`

When a valid `human_execution_approval.json` is present, approved items may be marked `ready_for_manual_execution`, but the adapter still keeps replacement execution off by default:

- `editor_replacement_execution=approved_but_not_executed_by_default`
- `replacement_execution=not_performed`
- `editing_software=not_opened`
- `project_file_mutation=not_performed`

## Approval Contract

The optional approval file must be created by a human and must include:

```json
{
  "approval_status": "approved_for_execution",
  "human_execution_approval": true,
  "approved_asset_ids": ["asset_id_or_*"],
  "approved_by": "human",
  "approval_note": "Reviewed rights, timeline, and final editor replacement scope."
}
```

The file only changes readiness status. It does not authorize this layer to open editing software or mutate a project file.

## Verification

Run:

```bash
make validate-phase4-editor-replacement-execution
```

The validation covers two paths:

- Default no-approval path: every command remains blocked pending explicit human approval, no editor is opened, and no replacement is executed.
- Explicit approval path: a ready proxy can become `ready_for_manual_execution`, but no replacement execution, editor open, or project mutation occurs.
