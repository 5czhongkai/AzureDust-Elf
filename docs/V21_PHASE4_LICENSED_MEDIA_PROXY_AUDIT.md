# V21 Phase 4 Licensed Media Proxy Audit

## Scope

This audit covers the layer that promotes local human-registered media from `human_media_registry.json` into editor replacement suggestions and local proxy copies.

The layer starts after `licensed-media-ingest-agent` has created `assets/{platform}/licensed_media/ingest_manifest.json`. It does not search for assets, download assets, buy licenses, open editing software, upload files, or publish content.

## Inputs

- `assets/{platform}/licensed_media/ingest_manifest.json`
- Optional `assets/{platform}/licensed_media/human_media_registry.json`
- Local media paths referenced by the human registry

The registry can reference either run-relative paths or absolute local paths. A media item is eligible for proxy copy only when all of these are true:

- `licensed_media_path` points to an existing local file
- `review_status` is `approved_for_edit`
- `rights_confirmation` is one of `licensed_confirmed`, `self_created_confirmed`, or `licensed_or_self_created_confirmed`

## Outputs

- `assets/{platform}/licensed_media/proxy_manifest.json`
- `assets/{platform}/licensed_media/replacement_suggestions.json`
- `assets/{platform}/licensed_media/proxy/README.md`
- `assets/{platform}/licensed_media/proxy/{asset_id}_proxy.*` when approved local media exists
- `final/licensed_media_proxy_manifest.json`

The proxy file is an editor handoff copy. It is not an automatic final export and still requires editor review before final replacement.

## Boundary

The proxy layer must keep this boundary:

- `licensed_media_proxy=performed_locally_from_human_registered_media_only`
- `asset_download=not_performed`
- `external_asset_search=not_performed`
- `license_purchase=not_performed`
- `editing_software=not_opened`
- `upload=not_performed`
- `publishing=not_performed`

## Verification

Run:

```bash
make validate-phase4-licensed-media-proxy
```

The validation covers two paths:

- Default no-registry path: proxy manifest, replacement suggestions, and proxy README are generated, but no proxy media is copied.
- Human registry path: a local test media file is registered, ingest marks it ready, proxy copies it locally, replacement suggestions become editor-ready, edit/export artifacts receive `proxy_media_path`, and the project bundle includes `licensed_media/proxy/{asset_id}_proxy.*`.
