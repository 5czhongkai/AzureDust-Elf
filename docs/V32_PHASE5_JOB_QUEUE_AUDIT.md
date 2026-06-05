# V32 Phase 5 Durable Job Queue Audit

This audit covers the Phase 5 durable job queue and worker handoff.

## Scope

- `src/content_agent_os/job_queue.py`
- `src/content_agent_os/worker.py`
- `src/content_agent_os/scheduler.py`
- `src/content_agent_os/console_server.py`
- `docker-compose.yml`
- `Makefile`
- `scripts/validate_phase5_job_queue.py`

## Capability

The console, worker, and scheduler now share a durable job queue:

- Console run/resume requests are written to `outputs/runs/_state/console_jobs.sqlite`.
- Console can still execute jobs inline for local development when `CONTENT_AGENT_CONSOLE_INLINE_JOBS=1`.
- Worker consumes queued jobs through `content_agent_os.worker`.
- `make worker-once` claims and executes one queued job.
- Scheduler dry-run still writes only scheduler tick records.
- Scheduler execute mode enqueues a run job instead of running workflow logic directly.

This makes the worker profile an actual handoff target rather than a standalone duplicate of `make run`.

## Boundary

- The durable job queue is local SQLite under `outputs/runs/_state/`.
- Worker claim uses job status transitions so a queued job is claimed by one worker at a time.
- The scheduler remains dry-run by default and does not enqueue unless dry-run is explicitly disabled.
- The queue stores job metadata, topic, platform list, run id, status, worker id, and errors; it does not store secret values.
- Docker Compose live startup still requires a host with Docker installed.

## Verification

```bash
make validate-phase5-job-queue
```

The validation checks static registration, console enqueue persistence across runtime restart, worker consumption of queued run and resume jobs, scheduler dry-run no-enqueue behavior, and scheduler execute-mode enqueue handoff.

## 2026-06-03 Closeout Notes

- `make worker` now runs the durable worker loop.
- `make worker-once` consumes one queued job and exits.
- `make scheduler-once` remains dry-run by default.
- `make validate-phase5-job-queue` uses a temporary one-step workflow so the queue handoff is tested without running the full five-platform production workflow.
