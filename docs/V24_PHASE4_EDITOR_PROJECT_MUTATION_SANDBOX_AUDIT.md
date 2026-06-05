# V24 Phase 4 Editor Project Mutation Sandbox Audit

## Scope

This audit covers the editor project mutation sandbox layer that sits after editor replacement execution preflight. It reads the execution manifest, execution plan, export manifest, edit timeline, and source FCPXML project, then generates a reversible patched FCPXML copy for human final review.

This layer is intentionally sandboxed. It does not open editing software, does not mutate the original `assets/{platform}/edit/project.fcpxml`, does not execute replacements, does not upload files, does not publish content, does not search for media, does not download media, and does not purchase licenses.

## Inputs

- `assets/{platform}/edit/replacement_execution/execution_manifest.json`
- `assets/{platform}/edit/replacement_execution/execution_plan.json`
- `assets/{platform}/edit/export_manifest.json`
- `assets/{platform}/edit/edit_timeline.json`
- `assets/{platform}/edit/project.fcpxml`
- Optional `assets/{platform}/edit/mutation_sandbox/human_mutation_approval.json`

## Outputs

- `assets/{platform}/edit/mutation_sandbox/mutation_manifest.json`
- `assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml`
- `assets/{platform}/edit/mutation_sandbox/mutation_diff.json`
- `assets/{platform}/edit/mutation_sandbox/rollback_manifest.json`
- `assets/{platform}/edit/mutation_sandbox/mutation_audit_log.json`
- `assets/{platform}/edit/mutation_sandbox/human_final_review_checklist.md`
- `assets/{platform}/edit/mutation_sandbox/README.md`
- Optional `assets/{platform}/edit/mutation_sandbox/human_mutation_approval.json`
- `final/editor_project_mutation_manifest.json`

## Boundary

Default runs without an approval file must keep this boundary:

- `editor_project_mutation_sandbox=blocked_pending_explicit_human_mutation_approval`
- `original_project_mutation=not_performed`
- `replacement_execution=not_performed`
- `editing_software=not_opened`
- `project_file_mutation=patched_copy_only_original_not_mutated`
- `requires_explicit_human_mutation_approval=true`
- `asset_download=not_performed`
- `external_asset_search=not_performed`
- `license_purchase=not_performed`
- `upload=not_performed`
- `publishing=not_performed`

When a valid `human_mutation_approval.json` is present and execution items are ready, this layer may generate a patched sandbox copy:

- `editor_project_mutation_sandbox=sandbox_patch_generated_from_explicit_human_approval`
- `original_project_mutation=not_performed`
- `sandbox_project_mutation=performed_on_patched_copy_only`
- `replacement_execution=not_performed`
- `editing_software=not_opened`
- `project_file_mutation=patched_copy_only_original_not_mutated`

The original project remains the rollback source. The patched copy is review material, not an automatically published or imported project.

## Approval Contract

The optional mutation approval file must be created by a human and must include:

```json
{
  "approval_status": "approved_for_project_mutation_sandbox",
  "human_mutation_approval": true,
  "approved_asset_ids": ["asset_id_or_*"],
  "approved_by": "human",
  "approval_note": "Reviewed execution plan and allow sandbox patched project generation."
}
```

The approval only authorizes generating `patched_project.fcpxml` in the sandbox directory. It does not authorize opening editing software, changing the original project, executing replacements, uploading, or publishing.

## Verification

Run:

```bash
make validate-phase4-editor-project-mutation-sandbox
```

The validation covers two paths:

- Default no-approval path: a patched copy is generated as an unchanged sandbox copy, every mutation item remains blocked, the original project is unchanged, and no editor or execution action occurs.
- Explicit approval path: approved ready items can be patched into the sandbox FCPXML copy, the diff and rollback manifest are generated, and the original FCPXML remains unchanged.
