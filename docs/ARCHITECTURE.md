# Reweave-lite Architecture

Reweave-lite is a local, read-only old-project reuse path.

```mermaid
flowchart LR
  A[Source Box] --> B[Read-only intake]
  B --> C[Capsule draft]
  C --> D[Capsule Warehouse]
  D --> E[Task Pack preview]
  E --> F[capsules_used.json]
  E --> G[provenance.json]
```

## Chain

- **Source Box**: an old project folder registered by path metadata.
- **Read-only intake**: source files are read only for bounded scanning,
  graph inspection, and snippet extraction. Reweave does not write to the
  Source Box.
- **Capsule draft**: rule-based candidates from scan metadata.
- **Capsule Warehouse**: local app-state store for approved capsules.
- **Task Pack preview**: local preview output with capsule usage and provenance.

## Boundary

- Source project writes are off by default.
- Source content reads are bounded and used only to build capsules, project
  graph metadata, snippets, and provenance.
- No automatic multi-file apply.
- No overwrite or delete path in the public frontend.
- Public demos write only to the requested output directory.

## Local Model Boundary

The local model is an explicit opt-in enhancement. It may rewrite bounded,
static copy slots while Reweave preserves the selected capsule's files,
DOM ids, events, scripts, and runtime behavior.

The current evidence supports **bounded copy migration plus behavior reuse**.
It does not prove field-semantic migration, unit-aware calculation changes,
or arbitrary workflow conversion. Text attached to dynamic ids is not exposed
as a model-writable slot.

See [P10 Bounded Copy and Behavior Migration](reports/P10_BOUNDED_COPY_BEHAVIOR_MIGRATION.md).

## Runtime State

The desktop shell reads a bounded local runtime state file when one is provided through `REWEAVE_RUNTIME_STATE_PATH`.

Without that file, the public repo still runs the local demo path from `examples/source_boxes/` and writes preview output to the selected demo output directory.

## Privacy / Path Redaction

Public demo provenance redacts local source paths by default.

`provenance.json` stores:

- `path_policy: "redacted"`
- Source Box id and label

Use `--include-local-paths` only for local debugging output that will not be shared.
