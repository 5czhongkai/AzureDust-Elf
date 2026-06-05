# V26 Phase 4 Editor Software Real Runner Sandbox Audit

## Scope

This audit covers the final safety layer before any real editing software could be launched by a human outside the automation process. It reads the editor software import executor outputs and creates a sandboxed manual-run handoff: environment snapshot, launch plan, command preview, audit log, evidence manifest, and human approval request.

This layer is intentionally non-executing. It does not spawn processes, open editing software, import a project, mutate project files, upload files, publish content, search for media, download media, or purchase licenses.

## Inputs

- `assets/{platform}/edit/software_import_executor/import_executor_manifest.json`
- `assets/{platform}/edit/software_import_executor/import_plan.json`
- `assets/{platform}/edit/software_import_executor/import_commands.json`
- `assets/{platform}/edit/software_import_executor/rollback_safety_report.json`
- Optional `assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval.json`

## Outputs

- `assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_environment_snapshot.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_audit_log.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json`
- `assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval_request.md`
- `assets/{platform}/edit/software_real_runner_sandbox/README.md`
- Optional `assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval.json`
- `final/editor_software_real_runner_manifest.json`

## Boundary

Default runs without an approval file must keep this boundary:

- `editor_software_real_runner_sandbox=blocked_pending_explicit_human_real_run_approval`
- `real_software_launch=not_performed`
- `software_import_execution=not_performed`
- `editing_software=not_opened`
- `project_file_mutation=not_performed_by_runner`
- `original_project_mutation=not_performed`
- `replacement_execution=not_performed`
- `requires_explicit_human_real_run_approval=true`
- `external_process_isolation=required_before_human_launch`
- `process_spawn=not_performed`
- `asset_download=not_performed`
- `external_asset_search=not_performed`
- `license_purchase=not_performed`
- `upload=not_performed`
- `publishing=not_performed`

When a valid `human_real_run_approval.json` is present and the patched project checksum matches, this layer may mark launch items as ready for a human-controlled external sandbox launch:

- `editor_software_real_runner_sandbox=approved_for_manual_external_sandbox_launch_not_executed`
- `real_software_launch=not_performed`
- `software_import_execution=not_performed`
- `editing_software=not_opened`
- `project_file_mutation=not_performed_by_runner`
- `process_spawn=not_performed`

Approval only changes the handoff status. It does not authorize the automation process to launch software, spawn a process, import a project, mutate files, upload, or publish.

## Approval Contract

The optional approval file must be created by a human and must include:

```json
{
  "approval_status": "approved_for_editor_software_real_runner_sandbox",
  "human_real_run_approval": true,
  "approved_patched_project_sha256": "<patched_project_sha256>",
  "approved_by": "human",
  "approval_note": "Reviewed import executor handoff and allow manual external sandbox launch planning."
}
```

## Verification

Run:

```bash
make validate-phase4-editor-software-real-runner-sandbox
```

The validation covers two paths:

- Default no-approval path: launch commands remain preview-only, runner items stay blocked pending explicit human real-run approval, and no process/editor launch occurs.
- Explicit approval path: a matching patched project can become `ready_for_manual_external_sandbox_launch`, but real software launch, process spawn, import execution, project mutation, upload, and publishing remain not performed.
