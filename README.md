<div align="center">

<img src="assets/logo.svg" alt="Reweave" width="420">

# 再织 Reweave

**Turn old projects into reusable capsules for new web work.**

Old project -> Source Box -> Capsules -> Small Project Pack -> New Web

[简体中文](README.zh-CN.md)

![Local first](https://img.shields.io/badge/local--first-yes-2f855a)
![CI](https://github.com/chenjinnan82-stack/Reweave-lite/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Source writes](https://img.shields.io/badge/source%20writes-off-1f2937)
![Small Project Pack](https://img.shields.io/badge/small%20project%20pack-preview-f59e0b)
![Desktop](https://img.shields.io/badge/app-desktop-334155)

</div>

## 30-Second Start

Use the desktop Capsule Warehouse first: bind a Source Box, refresh it, review the cleaned candidates, and publish the required capsules to the formal SQLite warehouse. Then generate from explicit active capsule IDs:

```bash
python3 scripts/run_public_reweave_demo.py \
  --task "Build a quote summary card" \
  --capsule-id cap_11111111111111111111111111111111 \
  --capsule-id cap_22222222222222222222222222222222 \
  --capsule-id cap_33333333333333333333333333333333
```

Replace the example IDs with IDs shown by the desktop warehouse. Use `--state-dir /path/to/reweave-state` only when the warehouse is outside the default application state directory. The JSON result is the raw `ReweaveAppService` product result, including the product ID, manifest digest, product path, exact capsule versions, quality result, and runtime acceptance.

The CLI does not scan, promote, select a model, or choose capsules implicitly. No capsule ID means no generation.

**Boundary:** Source Boxes remain read-only. Generated products live in Reweave application state and never overwrite the source project.

## Current Mainline

```text
Source Box -> read-only snapshot -> atomic extraction -> review
-> one formal SQLite warehouse -> one module_native composer
-> index.html / styles.css / app.js -> quality and runtime gates
-> immutable manifest and product usage
```

Supervision model selection belongs to the desktop warehouse workflow and has no hardcoded CLI default. Product generation consumes only eligible active/current formal versions.

### Static Web V1 support

| Supported | Not supported in V1 |
| --- | --- |
| One confirmed HTML entry | Classic `<script src>`, inline scripts, or automatic multi-page inference |
| A self-contained local ES module closure using `.js` / `.mjs` and static relative imports | CommonJS, TypeScript, JSX, React/Vue/Svelte component source, dynamic imports, or bare package imports |
| Sources that need no dependency install or build step | `node_modules`, build-required projects, and unapproved `dist` / `build` output |
| Independently provable presentation, interaction, and computation roles | SVG, fonts, or code whose atomic role and local asset closure cannot be proven |

Vite is judged by the executable source, not its name: an already self-contained native module entry may qualify, but a project that must run Vite or install dependencies does not.

## Why

Small local models can write code, but they often lose the project memory that makes code useful: naming, layout, patterns, copy, and tiny business rules.

Reweave treats an old project folder as a **Source Box**, cleans it into reusable **Capsules**, then lets a task use those capsules to build a previewable **Small Project Pack** with provenance.

The inspiration is a spider spinning silk: old project threads are cleaned, joined, and woven into something new.

## What It Does Today

- Binds an old project folder as a local Source Box.
- For supported Static Web V1 sources, takes a read-only snapshot and extracts independently verifiable presentation, interaction, and computation capsules.
- Uses the desktop workflow for review, model supervision, validation, publishing, backup, and restore.
- Stores formal immutable versions in one local SQLite Capsule Warehouse.
- Uses one `module_native` composer with in-memory formal capsule objects.
- Lets the CLI generate only from explicitly selected formal capsule IDs through `ReweaveAppService`.
- Produces runnable `index.html`, `styles.css`, `app.js`, a manifest, provenance, quality evidence, and exact product usage records.
- Keeps real source project writes off by default.

## Screenshots

The repository images below are interface illustrations. Release acceptance uses the separately recorded real-QWeb interaction and model-assisted screenshot evidence in the design document; these images are not pixel-level sign-off.

### Source Box

Bind an old project folder. Reweave reads it as context, not as a write target.

![Reweave Source Box onboarding](assets/reweave-source-box.png)

### Capsule Workbench

Use local capsules to plan a new web task while keeping trace and source-write status visible.

![Reweave desktop workbench](assets/reweave-workbench.png)

## Quick Start

After publishing capsules in the desktop warehouse, run the public CLI:

```bash
python3 scripts/run_public_reweave_demo.py \
  --task "Build a quote summary card" \
  --capsule-id cap_11111111111111111111111111111111 \
  --capsule-id cap_22222222222222222222222222222222
```

Windows PowerShell:

```powershell
py -3 scripts\run_public_reweave_demo.py `
  --task "Build a quote summary card" `
  --capsule-id cap_11111111111111111111111111111111 `
  --capsule-id cap_22222222222222222222222222222222
```

The returned `previewPath` points to the generated product. `productId`, `manifestDigest`, and `capsulesUsed` provide exact local traceability.

Use the versioned ESM developer fixture for the current positive flow:

```text
tests/fixtures/reweave_phase6_quote
```

The public `customer-quote-widget` and `ops-status-card` examples use classic scripts. They are retained as V1 boundary examples and are expected to stop at `classic_script_unsupported_v1`, not complete the positive intake flow.

Desktop loop:

```text
Bind Source Box -> Discover and confirm -> Refresh -> Review and publish -> Generate -> View provenance
```

Desktop management keeps Source Box intake, review, publishing, backup, and restore on the same SQLite mainline. The CLI uses the same application service for generation.

See [Desktop User Flow](docs/DESKTOP_USER_FLOW.md).

Run the public checks:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci
python -m pytest tests -q
node --check reweave_frontend/app.js
```

Optional desktop shell on macOS/Linux:

```bash
npm ci
python3 -m venv .venv-reweave
. .venv-reweave/bin/activate
python -m pip install -r pimos_lite/requirements-desktop.txt
./start_reweave_static.sh
```

PySide6 remains isolated in `.venv-reweave`; it is not a core dependency. The launcher never installs dependencies or contacts a package index automatically. Ollama supervision is loopback-only and requires an explicitly selected installed model; Reweave has no hardcoded default model.

### Historical demos

The following scripts remain as inactive migration history and are not the current product-generation path or direct CI entrypoints:

```bash
python scripts/run_public_stage4_demo.py
python scripts/run_public_stage4_demo.py --case data
```

They do not read from the formal SQLite generation path. Windows desktop shell support remains experimental; CLI help and the test suite are checked on Windows.

Optional runtime bridge:

```bash
REWEAVE_RUNTIME_STATE_PATH=/path/to/frontend_runtime_state.json \
./start_reweave_static.sh
```

## Public Reproducibility

- GitHub Actions runs the Reweave test suite.
- GitHub Actions checks the service-backed public CLI help on Ubuntu and Windows.
- GitHub Actions checks frontend JavaScript syntax.
- Historical demo scripts are not direct CI entrypoints.
- Local default launch does not depend on private workspace paths.
- Source project writes stay off by default.

Runtime evidence labels are intentionally distinct:

| Label | What it proves |
| --- | --- |
| `synthetic_declared_interaction` | Declared-interaction simulation only; it is not browser acceptance. |
| `real_qwebengine_render` / `real_qwebengine_interaction` | Candidate render or interaction in an isolated real QWebEngine. |
| `real_qwebengine_product_bootstrap` | The generated product starts in real QWebEngine; it is not a complete business interaction. |
| `real_qwebengine_product_interaction` | External input and click reached the expected product result in real QWebEngine; it is not pixel-level or human visual sign-off. |

Hosted CI uses Python 3.11 and Node 24 on Ubuntu and Windows. It does not install PySide6 or replace the local macOS real-QWeb desktop gate. Windows desktop packaging remains experimental.

Historical internal workbench notes are not required for this public repo.

## Boundaries

Reweave is not a full autopilot IDE.

It does **not** currently promise arbitrary production-grade project generation, automatic multi-file writes, overwrites, deletes, or frontend write buttons.

This repo publishes a safe Reweave-lite path for building inspectable Small Project Packs from old project context, not an automatic IDE that edits your project for you.

Generated product writes are confined to a new application-state product directory; Source Boxes remain read-only.

## Project Shape

```text
Desktop UI                         reweave_frontend/
Application service                pimos_lite/reweave_app_service.py
Formal SQLite warehouse            pimos_lite/reweave_capsule_store.py
Read-only intake                   pimos_lite/reweave_capsule_intake.py
Safety and validation              pimos_lite/reweave_capsule_stage3.py
Single composer                    pimos_lite/composer/module_native.py
Public samples                     examples/source_boxes/
Public CLI                         scripts/run_public_reweave_demo.py
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
