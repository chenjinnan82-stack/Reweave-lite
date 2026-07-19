# Release Notes

## Published Baseline: v0.3.0

`v0.3.0` is the current published Reweave Static Web V1 baseline. The Tag
points to the Stage G release merge commit `e9b2ccd` and has not moved.

This release closes Stage G with:

- hosted Ubuntu, Windows, and CodeQL checks;
- one formal SQLite Capsule Warehouse and immutable capsule versions;
- one `module_native` composer for standalone three-file products;
- three frozen third-party JavaScript computation positive validations;
- a real QWebEngine product business interaction with manifest, provenance,
  and exact capsule-version usage; and
- the sealed retirement path for new `computation_adapter.v1` creation.

The release does not prove arbitrary-project extraction, automatic external
presentation/interaction decomposition, framework targets, or target-project
writes. The frozen local and corpus evidence is recorded in
[REWEAVE_STAGE_G_ACCEPTANCE.json](reports/REWEAVE_STAGE_G_ACCEPTANCE.json).
That historical record was sealed before the final push and therefore still
states that hosted final-byte CI had not run; the later hosted checks and Tag
closure are release facts and the historical record is intentionally not
rewritten.

## Current Main After v0.3.0

Current `main` contains additional completed work that is not part of the
existing `v0.3.0` Tag:

- **Plan 2 — legacy cleanup and North-Star calibration:** the unreachable old
  `scripts/run_public_stage4_demo.py` entry was removed, and the product North
  Star became the single roadmap. The service-backed
  `scripts/run_public_reweave_demo.py` remains the formal CLI.
- **Plan 3 — Static Web review-only Patch backend:** one explicit build-free
  Static Web entry can be analyzed as a stable read-only target snapshot and
  mapped through the same `module_native` composer to a deterministic Weave
  Plan, complete structured Patch, Diff, provenance, and rejection evidence.
- **Plan 4 — desktop target review:** the desktop now provides separate
  standalone/target entries, simple/developer modes, eligible capsule cards,
  text Diffs, binary metadata, validation/rejection evidence, and an in-memory
  confirmation bound to `plan_id` and the target snapshot.

Plan 3 and Plan 4 preserve zero target, product-store, usage, and warehouse
writes. The Plan 4 confirmation makes no bridge call and grants no write
authority. Their evidence is recorded in
[REWEAVE_STATIC_WEB_TARGET_PATCH_ACCEPTANCE.json](reports/REWEAVE_STATIC_WEB_TARGET_PATCH_ACCEPTANCE.json)
and
[REWEAVE_STATIC_WEB_TARGET_UI_ACCEPTANCE.json](reports/REWEAVE_STATIC_WEB_TARGET_UI_ACCEPTANCE.json).

No new release Tag has published Plans 2–4. They are current mainline
capabilities, not `v0.3.0` release claims.

## Current Architecture

Reweave has one formal SQLite warehouse, one capsule model, one
`module_native` composer, and two delivery modes:

1. Standalone product generation writes a new three-file product plus manifest,
   provenance, quality/runtime evidence, and exact capsule-version usage into Reweave
   application state.
2. Static Web target integration currently stops at a review-only Weave Plan
   and Patch shown in the desktop. It does not modify the target.

See [Architecture](ARCHITECTURE.md) and
[Reweave Product North Star](REWEAVE_PRODUCT_NORTH_STAR.md).

## Not Yet Implemented

- Applying and validating a Patch in an isolated target copy, including target
  build, test, and post-Patch behavior checks.
- Apply, commit, or rollback in a user's real worktree.
- React + Vite or Node target integration.
- A general Target Adapter or arbitrary-project compatibility planner.
- Automatic legal-license or distribution authorization.

Historical `v0.1.x` notes remain under [`docs/releases/`](releases/) as records
of their original scope. They are not the current release baseline or current
architecture description.
