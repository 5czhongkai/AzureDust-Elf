# V27 Phase 4 Editor Software Run Evidence Audit

## Scope

This audit covers the evidence ingest and closeout layer after the real-runner sandbox handoff. It reads the real-runner sandbox manifest, launch plan, command preview, evidence manifest, and an optional human-provided real-run result file, then generates an auditable post-launch evidence package.

This layer is intentionally ingest-only. It does not spawn processes, open editing software, execute imports, mutate project files, upload files, publish content, search for media, download media, purchase licenses, or perform rollback actions.

## Inputs

- `assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json`
- Optional `assets/{platform}/edit/software_run_evidence/human_real_run_result.json`
- Optional evidence files referenced by `human_real_run_result.json`

## Outputs

- `assets/{platform}/edit/software_run_evidence/real_run_evidence_manifest.json`
- `assets/{platform}/edit/software_run_evidence/evidence_validation_report.json`
- `assets/{platform}/edit/software_run_evidence/rollback_decision_report.json`
- `assets/{platform}/edit/software_run_evidence/post_launch_evidence_checklist.md`
- `assets/{platform}/edit/software_run_evidence/README.md`
- Optional `assets/{platform}/edit/software_run_evidence/human_real_run_result.json`
- `final/editor_software_run_evidence_manifest.json`

## Boundary

Default runs without a human result file must keep this boundary:

- `editor_software_run_evidence=blocked_pending_human_real_run_result`
- `real_software_launch_by_automation=not_performed`
- `software_import_execution_by_automation=not_performed`
- `editing_software=not_opened_by_automation`
- `project_file_mutation=not_performed_by_evidence_ingest`
- `original_project_mutation=not_performed`
- `replacement_execution_by_automation=not_performed`
- `process_spawn=not_performed`
- `evidence_ingest_only=true`
- `requires_human_real_run_result=true`
- `asset_download=not_performed`
- `external_asset_search=not_performed`
- `license_purchase=not_performed`
- `upload=not_performed`
- `publishing=not_performed`

When a valid human result file is present and references the matching runner manifest checksum, this layer may mark evidence items as ingested:

- `editor_software_run_evidence=human_evidence_ingested_no_automation_execution`
- `real_software_launch_by_automation=not_performed`
- `software_import_execution_by_automation=not_performed`
- `editing_software=not_opened_by_automation`
- `project_file_mutation=not_performed_by_evidence_ingest`
- `process_spawn=not_performed`

Human evidence only changes closeout status. It does not authorize automation to launch software, spawn a process, import a project, mutate files, upload, publish, or roll back.

## Human Result Contract

The optional result file must be created by a human and must include:

```json
{
  "result_status": "human_real_run_completed",
  "human_real_run_completed": true,
  "completed_by": "human",
  "approved_runner_manifest_sha256": "<runner_sandbox_manifest_sha256>",
  "evidence_files": [
    "assets/douyin/edit/software_run_evidence/manual_screenshot.txt",
    "assets/douyin/edit/software_run_evidence/export_log.txt"
  ],
  "rollback_required": false,
  "rollback_reason": ""
}
```

If `rollback_required=true`, the generated `rollback_decision_report.json` records a human-only rollback review request. The automation layer still performs no rollback.

## Verification

Run:

```bash
make validate-phase4-editor-software-run-evidence
```

The validation covers two paths:

- Default no-result path: evidence items remain blocked pending a human result while no process/editor launch occurs.
- Human result path: a matching runner manifest checksum can mark evidence as ingested and include evidence files, while real software launch, process spawn, import execution, project mutation, upload, publishing, and rollback remain outside automation.
