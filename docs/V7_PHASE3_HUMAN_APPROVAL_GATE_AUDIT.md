# V7 Phase 3 Human Approval Gate Audit

## Goal

Make `manual_required=true` repair plans stop the workflow at a human approval gate, then allow replay only after explicit approval.

## What Changed

- Repair plans now carry approval state.
- `resume` pauses the workflow at `NEEDS_HUMAN` when a manual repair is pending.
- `make approve-repair RUN_ID="..." REPAIR_ID="..."` records approval metadata.
- A later `make resume` replays the failed step only after approval is present.

## Acceptance

- Pending manual repair blocks replay.
- Approval metadata is persisted in `workflow_run.json`, `repair/repair_log.json`, and the supervision snapshot.
- Supervision output shows pending and approved repair counts.
- Final resume completes successfully after approval.
