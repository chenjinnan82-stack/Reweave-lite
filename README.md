<div align="center">

<img src="assets/logo.svg" alt="Reweave" width="420">

# 再织 Reweave

**Turn old projects into reusable capsules for new web work.**

Old project -> Source Box -> Capsules -> Task Pack -> New Web

[简体中文](README.zh-CN.md)

![Local first](https://img.shields.io/badge/local--first-yes-2f855a)
![CI](https://github.com/chenjinnan82-stack/Reweave-lite/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Source writes](https://img.shields.io/badge/source%20writes-off-1f2937)
![Task Pack](https://img.shields.io/badge/task%20pack-preview-f59e0b)
![Desktop](https://img.shields.io/badge/app-desktop-334155)

</div>

## Why

Small local models can write code, but they often lose the project memory that makes code useful: naming, layout, patterns, copy, and tiny business rules.

Reweave treats an old project folder as a **Source Box**, cleans it into reusable **Capsules**, then lets a task use those capsules to build a previewable **Task Pack** with provenance.

The inspiration is a spider spinning silk: old project threads are cleaned, joined, and woven into something new.

## What It Does Today

- Binds an old project folder as a local Source Box.
- Scans and drafts capsule candidates without writing to the source project.
- Stores approved capsules in a local Capsule Warehouse.
- Lets the desktop workbench select capsules for a task.
- Builds a Task Pack preview with:
  - `task_pack.json`
  - `capsules_used.json`
  - `provenance.json`
- Keeps real source project writes off by default.

## Screenshots

### Source Box

Bind an old project folder. Reweave reads it as context, not as a write target.

![Reweave Source Box onboarding](assets/reweave-source-box.png)

### Capsule Workbench

Use local capsules to plan a new web task while keeping trace and source-write status visible.

![Reweave desktop workbench](assets/reweave-workbench.png)

## Quick Start

```bash
./start_reweave_static.sh
```

Try a public Source Box:

```text
examples/source_boxes/customer-quote-widget
examples/source_boxes/ops-status-card
```

In the desktop app, choose one of those folders from **Bind Source Box**.

Run the public checks:

```bash
python3 -m pip install pytest
python3 -m pytest tests/test_reweave*.py -q
node --check reweave_frontend/app.js
```

Optional: point the desktop bridge at your own Lumo Lite runtime state:

```bash
REWEAVE_LUMO_LITE_STATE_PATH=/path/to/frontend_runtime_state.json \
./start_reweave_static.sh
```

## Public Reproducibility

- GitHub Actions runs the Reweave test suite and frontend syntax check.
- Local default launch does not depend on private workspace paths.
- Source project writes stay off by default.

Development notes from the original Lumo Lite workbench are intentionally not required for this public repo.

## Boundaries

Reweave is not a full autopilot IDE.

It does **not** currently promise arbitrary production-grade project generation, automatic multi-file writes, overwrites, deletes, or frontend write buttons.

This repo publishes the safe Reweave-lite release surface for old-project reuse. It is not the full internal PIMOS/Lumo workspace.

The safe write direction remains manual, single-file, create-only, and rollback-aware.

## Project Shape

```text
reweave_frontend/                  Desktop UI
pimos_lite/reweave_engine/         Local and Lumo Lite engines
pimos_lite/reweave_*               Source Box, capsule, preview, bridge logic
examples/source_boxes/             Small public Source Box samples
tests/test_reweave*.py             Release and bridge checks
```

## Roadmap

- Source Box intake polish
- Better capsule review and selection
- Stronger Task Pack planning
- More public Source Boxes and task-pack walkthroughs
- Manual create-only write flow with rollback receipts

## License

MIT
