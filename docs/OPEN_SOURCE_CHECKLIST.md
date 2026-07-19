# Open Source Checklist

## Repository Publication

- [x] MIT license exists for the Reweave repository.
- [x] `.gitignore` ignores local caches and virtual environments.
- [x] `SECURITY.md` describes security boundaries and reporting.
- [x] Public README files exist in English and Chinese.
- [x] CI workflow exists and checks the supported public CLI and frontend.
- [x] Public Source Box examples and screenshots exist.
- [x] Public scripts contain no hardcoded private workspace paths.
- [x] Issue templates, contributing guidance, and a PR template exist.
- [x] GitHub About and topics are set on the repository page.

## Release Status

- [x] The current published baseline is `v0.3.0`.
- [x] `v0.3.0` points to the Stage G release merge commit `e9b2ccd`.
- [x] The Tag has not moved for post-tag mainline work.
- [x] Documentation distinguishes published `v0.3.0` from additional current
  mainline capabilities.
- [x] Historical `v0.1.x` notes are retained as historical records, not named as
  the latest release or current architecture.

## Current Mainline Architecture

- [x] One SQLite warehouse is the only formal Capsule IR.
- [x] `module_native` is the single composer for both delivery modes.
- [x] Standalone generation produces a new application-state product with
  manifest, provenance, quality/runtime evidence, and exact usage.
- [x] Static Web target integration uses the same warehouse and composer and
  returns a deterministic review-only Plan, Patch, Diff, and evidence.
- [x] The desktop has separate standalone and target entries with
  simple/developer review modes and an in-memory confirmation.
- [x] The service-backed formal CLI remains the only public CLI product entry;
  it has no target-integration command.

## Safety and Claim Boundaries

- [x] Source projects and selected target projects remain read-only.
- [x] Static Web target review performs no target, product-store, usage, or
  warehouse writes.
- [x] Final target confirmation makes no bridge call and is not write
  authorization.
- [x] Current documentation does not claim isolated target-copy application or
  validation, real-worktree apply, commit, or rollback.
- [x] Current documentation does not claim React + Vite or Node target
  integration, a general Target Adapter, or arbitrary-project support.
- [x] Current documentation does not claim automatic legal-license or
  distribution authorization.
- [x] Stage G evidence is not expanded beyond its frozen computation and real
  product acceptance scope.
