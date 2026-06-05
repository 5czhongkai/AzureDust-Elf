# V18 Phase 4 Delivery Index Audit

## Scope

Add a local delivery index after project bundle generation. This turns the three platform ZIP bundles into a single handoff map with paths, byte sizes, SHA-256 checksums, validation status, and a human-readable delivery README.

## Changes

- Added `delivery-index-agent`.
- Added `src/content_agent_os/delivery_index.py`.
- Added workflow step:
  - `delivery_index`
- Added schema:
  - `schemas/delivery_index.schema.json`
- Added outputs:
  - `final/delivery_index.json`
  - `final/delivery_readme.md`
- Added `make validate-phase4-delivery-index`.
- Updated the content package to reference the delivery index and delivery README.

## Output Contract

The delivery index produces:

- `final/delivery_index.json`
- `final/delivery_readme.md`

Each indexed bundle records:

- platform and platform label
- bundle path
- byte size
- SHA-256 checksum
- validation status
- required file presence
- offline B-roll count

## Boundary

The current adapter is a local index generator.

- No files are uploaded.
- No external storage sync is performed.
- No publishing action is performed.
- Human review remains required before moving any bundle outside the workspace.

## Verification

```bash
make validate
make validate-phase4-project-bundle
make validate-phase4-delivery-index
make validate-run RUN_ID="run_20260525T000000Z"
```

The new validation checks:

- `delivery_index` exists in the workflow and uses `delivery-index-agent`
- the step depends on all selected video platform project bundles
- `final/delivery_index.json` validates bundle count, paths, sizes, and checksums
- `final/delivery_readme.md` includes a delivery table
- content package references the delivery index and README
- no external sync, upload, or publishing action is performed

## Result

Phase 4 delivery indexing is complete. The system now has a local handoff index on top of the project bundles, so generated ZIP packages can be reviewed, verified, and moved deliberately by a human.
