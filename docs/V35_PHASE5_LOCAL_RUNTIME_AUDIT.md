# V35 Phase 5 Local Runtime Audit

This audit covers the Phase 5 local runtime enhancement.

## Scope

Phase 5 local runtime is the primary path for this machine. Docker is optional.

Local runtime support now includes:

- `GET /api/local-runtime` for console, worker, scheduler, queue, and Docker optional status.
- Console Local Runtime panel with `make console`, `make worker-once`, `make worker`, `make scheduler-once`, and `make scheduler`.
- Setup Check entry for local runtime readiness.
- Docker availability shown as optional, not required.

## Boundaries

- Secret values are never returned.
- Docker absence does not block local runtime readiness.
- Scheduler remains dry-run by default.
- Worker readiness is based on the durable queue state directory.

## Validation

```bash
make validate-phase5-local-runtime
```

The validator covers static registration, runtime payload, HTTP API, console HTML, Docker optional semantics, and secret redaction.
