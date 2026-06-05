# V29 Phase 4 External Mirror Plan Audit

## Scope

This audit covers the plan-only external mirror handoff after the local artifact store. It reads `artifact_store/artifact_store_manifest.json`, verifies the local downloadable bundles, and generates an external mirror plan, sync command preview, human distribution approval request, and README.

This layer is intentionally plan-only. It does not sync external storage, log in to any account, upload files, publish content, call platform APIs, access the network, open editing software, spawn editor processes, download media, purchase licenses, or mutate project files.

## Inputs

- `artifact_store/artifact_store_manifest.json`
- `artifact_store/download_index.md`
- `artifact_store/checksums.sha256`
- `artifact_store/downloads/douyin_project_bundle.zip`
- `artifact_store/downloads/shipinhao_project_bundle.zip`
- `artifact_store/downloads/bilibili_project_bundle.zip`

## Outputs

- `artifact_store/external_mirror_plan.json`
- `artifact_store/sync_command_preview.md`
- `artifact_store/human_distribution_approval_request.md`
- `artifact_store/external_mirror_readme.md`

## Boundary

External mirror plan generation must keep this boundary:

- `external_mirror_plan_generation=performed_locally_plan_only`
- `external_storage_sync=not_performed`
- `upload=not_performed`
- `publishing=not_performed`
- `login=not_performed`
- `platform_action=not_performed`
- `network_access=not_performed`
- `requires_human_distribution_approval=true`

The generated sync commands are comment-only previews for human review. They are not executed by automation.

## Verification

Run:

```bash
make validate-phase4-external-mirror-plan
```

The validation covers:

- The workflow has an `external_mirror_plan` step after `artifact_store`.
- `fact_check` depends on both `artifact_store` and `external_mirror_plan`.
- Every artifact store download has one blocked mirror plan item.
- Each mirror item revalidates the local file checksum.
- The command preview is explicitly comment-only and not executed.
- `content_package_manifest.json` references the external mirror plan, sync preview, approval request, and README.
- No external storage sync, login, upload, publishing, network access, or platform action is performed.
