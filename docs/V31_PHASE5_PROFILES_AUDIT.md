# V31 Phase 5 Worker and Scheduler Profiles Audit

This audit covers the Phase 5 worker and scheduler deployment profiles.

## Scope

- `docker-compose.yml`
- `.env.example`
- `Makefile`
- `src/content_agent_os/scheduler.py`
- `scripts/validate_phase5_profiles.py`

## Capability

Phase 5 now has three local deployment shapes:

- `console`: runs the Web console and JSON API.
- `worker`: consumes queued durable jobs and executes the claimed job.
- `scheduler`: writes periodic scheduler ticks and can enqueue workflow run jobs on an interval.

The scheduler defaults to dry-run mode through `CONTENT_AGENT_SCHEDULER_DRY_RUN=1`. In dry-run mode it writes `outputs/runs/_scheduler/scheduler_tick_*.json` records and does not enqueue jobs or create workflow run directories. Operators must explicitly set `CONTENT_AGENT_SCHEDULER_DRY_RUN=0` or pass `--execute` before scheduler ticks enqueue real workflow runs for worker consumption.

## Boundary

- The worker profile executes only jobs it can claim from the durable job queue; it does not upload, publish, log in to platforms, or run external mirror sync.
- The scheduler profile is dry-run by default and only enqueues runs after explicit operator opt-in.
- Scheduler tick records are local JSON files under `outputs/runs/_scheduler/`.
- Docker Compose live startup still requires a host with Docker installed.

## Verification

```bash
make validate-phase5-profiles
```

The validation checks Compose profiles, Makefile targets, `.env.example` variables, base validator registration, documentation references, and a real scheduler dry-run tick against a temporary output root.

## 2026-06-03 Closeout Notes

- `worker` and `scheduler` Compose profiles are present, but Compose live startup was not run on this machine because Docker is not installed.
- `scheduler-once` provides a local dry-run target for checking scheduler tick output without starting an infinite loop.
- `make validate-phase5-profiles` proves the scheduler dry-run path writes a tick record and does not create `run_*` workflow directories.
