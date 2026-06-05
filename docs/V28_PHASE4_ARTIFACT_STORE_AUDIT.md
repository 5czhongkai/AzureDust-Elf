# V28 Phase 4 Artifact Store Audit

## Scope

This audit covers the local artifact store layer after the delivery index. It reads `final/delivery_index.json`, copies each indexed project bundle into a stable local download directory, and generates a store manifest, download index, checksum file, README, and a copy of the source delivery index.

This layer is intentionally local-only. It does not sync external storage, log in to any account, upload files, publish content, call platform APIs, open editing software, spawn editor processes, download media, purchase licenses, or mutate project files.

## Inputs

- `final/delivery_index.json`
- `final/delivery_readme.md`
- `assets/douyin/bundle/project_bundle.zip`
- `assets/shipinhao/bundle/project_bundle.zip`
- `assets/bilibili/bundle/project_bundle.zip`

## Outputs

- `artifact_store/artifact_store_manifest.json`
- `artifact_store/README.md`
- `artifact_store/download_index.md`
- `artifact_store/checksums.sha256`
- `artifact_store/manifests/delivery_index.json`
- `artifact_store/downloads/douyin_project_bundle.zip`
- `artifact_store/downloads/shipinhao_project_bundle.zip`
- `artifact_store/downloads/bilibili_project_bundle.zip`

## Boundary

Artifact store generation must keep this boundary:

- `artifact_store_generation=performed_locally_file_copy`
- `local_download_directory=generated`
- `external_storage_sync=not_performed`
- `upload=not_performed`
- `publishing=not_performed`
- `login=not_performed`
- `platform_action=not_performed`

The store creates local downloadable files only. Human review is required before distributing any bundle outside the workspace.

## Verification

Run:

```bash
make validate-phase4-artifact-store
```

The validation covers:

- The workflow has an `artifact_store` step after `delivery_index`.
- `fact_check` depends on both `delivery_index` and `artifact_store`.
- The artifact store copies all three platform project bundle ZIPs into `artifact_store/downloads/`.
- Copied bundle bytes and SHA-256 values match the source delivery index.
- `content_package_manifest.json` references the artifact store manifest, README, download index, and checksum file.
- No external storage sync, login, upload, publishing, or platform action is performed.
