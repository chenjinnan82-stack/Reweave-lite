# Reweave Architecture Coupling Record

## Current product path

`PySide6/QWebChannel -> ReweaveAppService -> LumoLiteReweaveEngine -> Source Box / Capsule Warehouse -> Task Intent -> Task Plan -> Preview Renderer -> Quality Gate`

`build_preview_package()` is the single Small Project Pack generation core. The default product path reads the bound source project and writes only Reweave app state and local preview output.

## Coupling addressed in this checkpoint

1. The old `read_only_runtime_artifact_viewer` label hid the fact that Source Box intake and preview generation are active. The product mode is now `source_read_only_preview_write`: source projects stay read-only while app-state and preview output writes are explicit.
2. Task Intent and Task Plan were recomputed by the pack builder and renderer. They are now computed once per preview run and passed to the renderer, quality gate, and Task Pack.
3. `LumoLiteReweaveEngine.generate_preview()` rewrote `task_pack.json` after the preview core had already produced it. The engine now returns the core result without a second writer.

## Known coupling retained

- `reweave_frontend/app.js` remains a large desktop controller. It is stable and covered by static/desktop smoke tests; splitting it now would add risk without improving the product flow.
- `isLumoLiteReadOnly()` remains as a compatibility helper name. Its product meaning is source-project read-only, not no-write-everywhere.
- Local preview, app state, audit, and capsule authoring writes remain separate from source-project writes.

## Hard boundaries

- No writes to the bound source project.
- No overwrite or delete path.
- No automatic multi-file apply.
- No new backend or template system.
- No push from this checkpoint.

## Required evidence

- Task Intent, Task Plan, Task Pack, Quality Gate, provenance, and rendered review page agree on one generation contract.
- A real desktop flow can bind a temporary Source Box, scan, store capsules, describe a natural-language task, generate a Small Project Pack, and view provenance.
- The source fixture digest remains unchanged throughout the desktop flow.
