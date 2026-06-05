# V30 Phase 5 Console Audit

This audit covers the first Phase 5 deployment and console slice.

## Scope

- `src/content_agent_os/console_server.py`
- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `Makefile`
- `scripts/validate_phase5_console.py`
- `scripts/validate_phase5_setup_check.py`

## Capability

The Phase 5 console provides a local Web UI and JSON API for:

- service health
- safe environment status
- workflow run creation
- workflow run resume
- run list and run summary inspection
- in-process job status
- local ZIP backup creation for `outputs/runs/`
- restore dry-run preview for a selected backup ZIP
- explicit-confirm restore execution for safe backup ZIP entries
- local setup check for Python, workflow, platform set, migration directories, resume state, backups, and secret presence

Run creation currently requires the full workflow platform set. Partial platform selection is rejected by the console because the Phase 4 artifact store and external mirror chain expects all video platform bundles.

## Boundary

- Secret variables are presence-only in the API and UI.
- Setup Check reports only secret names and presence, never secret values.
- Secret values are not written into backups.
- The console does not log in to platforms, upload files, publish content, run external mirror sync, or perform platform actions.
- The backup step is local filesystem packaging only.
- Restore dry-run only reads a backup ZIP manifest and file list; it does not extract or overwrite files.
- Confirmed restore requires the exact `RESTORE <backup-name>` phrase, rejects unsafe ZIP paths, restores only `outputs/runs/` files, and writes a local restore log.

## Verification

```bash
make validate-phase5-console
make validate-phase5-setup
```

The validation starts the console against a temporary output root, checks HTTP endpoints, verifies backup ZIP contents, confirms secret redaction, and checks the Compose/Docker/Makefile entrypoints.

The setup validation creates a ready local fixture, checks `GET /api/setup-check`, verifies the Setup Check HTML panel, confirms recommended local commands are listed, and asserts a sentinel secret value is never returned.

## 2026-06-03 Closeout Notes

- Playwright bundled browser execution was not available on this machine because the local Chrome distribution was missing. Step 1 UI coverage was closed with HTTP, HTML, and JSON API checks instead of browser screenshots/click automation.
- Docker is not installed in this environment, so `docker compose up console` is still pending live verification. The validation checks the Compose file, Dockerfile, and Makefile entrypoints statically.
- Backup filenames now include microseconds plus a short UUID suffix to prevent same-second backup overwrites.
- Step 2 now includes restore dry-run plus explicit-confirm restore execution. Restore is never automatic and requires the exact confirmation phrase for the selected backup name.
- Step 3 now includes `docs/PHASE5_MIGRATION.md` and `make validate-phase5-migration` for multi-device migration guidance and validation.
- Step 4 now includes `GET /api/setup-check`, a console Setup Check panel, and `make validate-phase5-setup` for local configuration and migration preflight.
