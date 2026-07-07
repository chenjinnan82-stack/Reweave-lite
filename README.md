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

## 30-Second Demo

```bash
python scripts/run_public_reweave_demo.py
```

The JSON result prints the output folder and files. Expected output includes `task_pack.json`, `capsules_used.json`, and `provenance.json`.

**Boundary:** source projects are read-only by default. Reweave-lite previews task packs; it does not auto-write or overwrite your project.

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

Run the public Task Pack demo:

```bash
python scripts/run_public_reweave_demo.py \
  --source examples/source_boxes/customer-quote-widget \
  --task "Build a quote summary card"
```

Windows PowerShell:

```powershell
py -3 scripts\run_public_reweave_demo.py `
  --source examples\source_boxes\customer-quote-widget `
  --task "Build a quote summary card"
```

The script writes to your system temp folder by default, for example `/tmp/reweave_public_demo` on macOS/Linux or `%TEMP%\reweave_public_demo` on Windows.

Try a public Source Box in the desktop app:

```text
examples/source_boxes/customer-quote-widget
examples/source_boxes/ops-status-card
```

Run the public checks:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
node --check reweave_frontend/app.js
```

Optional desktop shell on macOS/Linux:

```bash
./start_reweave_static.sh
```

Windows desktop shell support is experimental; the CLI demo and tests are CI-checked on Windows.

Optional runtime bridge:

```bash
REWEAVE_RUNTIME_STATE_PATH=/path/to/frontend_runtime_state.json \
./start_reweave_static.sh
```

## Public Reproducibility

- GitHub Actions runs the Reweave test suite.
- GitHub Actions runs the public Task Pack demo on Ubuntu and Windows.
- GitHub Actions checks `task_pack.json`, `capsules_used.json`, and `provenance.json`.
- GitHub Actions checks frontend JavaScript syntax.
- Local default launch does not depend on private workspace paths.
- Source project writes stay off by default.

Historical internal workbench notes are not required for this public repo.

## Boundaries

Reweave is not a full autopilot IDE.

It does **not** currently promise arbitrary production-grade project generation, automatic multi-file writes, overwrites, deletes, or frontend write buttons.

This repo publishes the safe Reweave-lite release surface for old-project reuse, not a full autopilot IDE.

The safe write direction remains manual, single-file, create-only, and rollback-aware.

## Project Shape

```text
Desktop UI                         reweave_frontend/
Runtime bridge                     pimos_lite/reweave_engine/lumo_lite.py
Source Box intake                  pimos_lite/reweave_source_registry.py
Source Box scanner                 pimos_lite/reweave_source_scanner.py
Capsules                           pimos_lite/reweave_capsule_draft.py
Warehouse                          pimos_lite/reweave_capsule_warehouse.py
Task Pack / provenance             pimos_lite/reweave_preview_pack.py
Public samples                     examples/source_boxes/
Public demo                        scripts/run_public_reweave_demo.py
Tests                              tests/
```

See [Architecture](docs/ARCHITECTURE.md) for the Source Box -> Capsule -> Task Pack chain.

## Roadmap

- More public Source Box demos
- Better desktop packaging
- More stable Task Pack previews

See [Roadmap](ROADMAP.md).

## License

MIT
