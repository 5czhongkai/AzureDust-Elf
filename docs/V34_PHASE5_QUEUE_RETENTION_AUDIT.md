# V34 Phase 5 Queue Retention Audit

This audit covers Phase 5 queue history retention and cleanup.

## Scope

- `src/content_agent_os/job_queue.py`
- `src/content_agent_os/console_server.py`
- `.env.example`
- `scripts/validate_phase5_queue_retention.py`

## Capability

The durable job queue now supports retention cleanup:

- `CONTENT_AGENT_JOB_RETENTION_DAYS` controls terminal job history retention.
- `CONTENT_AGENT_AUDIT_RETENTION_DAYS` controls audit log retention.
- `POST /api/jobs/cleanup-dry-run` previews eligible cleanup.
- `POST /api/jobs/cleanup` performs cleanup only with exact `CLEANUP JOBS` confirmation.
- Console Jobs panel shows retention settings and cleanup controls.

## Boundary

- Cleanup only deletes terminal jobs: `DONE`, `FAILED`, and `CANCELED`.
- Cleanup never deletes `QUEUED` or `RUNNING` jobs.
- Dry-run does not delete anything.
- Confirmed cleanup writes a local audit entry.
- Audit cleanup removes old audit rows and does not expose secret values.

## Verification

```bash
make validate-phase5-queue-retention
```

The validation checks dry-run behavior, confirmation enforcement, protected queued/running jobs, audit cleanup, HTTP endpoints, and console HTML coverage.

## 2026-06-03 Closeout Notes

- Default retention is 30 days for terminal jobs and 90 days for audit logs.
- Cleanup confirmation phrase is `CLEANUP JOBS`.
- Cleanup remains local to `outputs/runs/_state/console_jobs.sqlite`.
