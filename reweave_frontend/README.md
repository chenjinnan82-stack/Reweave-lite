# Reweave — Static Frontend Prototype

Local capsule reuse machine UI prototype. **No backend.** **No build step.**

Desktop-ready HTML/CSS/JS intended for future embedding in a local desktop app shell.

## Desktop shell (PySide6)

**独立桌面窗口**（PySide6 + QtWebEngine，不是浏览器标签页）：

```bash
./start_reweave_static.sh
```

首次运行会自动创建 `.venv-reweave` 并安装 PySide6（约 440MB）。不要用系统 `pip install`（Homebrew Python 会报 `externally-managed-environment`）。

若 PyPI 下载中断，先设镜像再运行：

```bash
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
./start_reweave_static.sh
```

**Desktop bridge:** bind → **Scan** → **Prepare** → Generate (real local preview pack) → **Open in folder**. Capsule dock uses warehouse when available. Browser mode unchanged (mock data).

See [docs/REWEAVE_DESKTOP_STATIC_SHELL.md](../docs/REWEAVE_DESKTOP_STATIC_SHELL.md).

## Open in browser

Double-click `index.html`, or:

```bash
open index.html
```

Skip welcome screen:

```bash
cd reweave_frontend
python3 -m http.server 8765
# http://localhost:8765/index.html?main=1
```

If `mock-data.json` fails under strict `file://` rules, use a local server (embed fallback is included).

## Files

| File | Purpose |
|------|---------|
| `index.html` | Welcome → cleaning → main (States A–D) |
| `styles.css` | Desktop-first layout, warm ivory / amber |
| `app.js` | Mock interactions, app state machine |
| `mock-data.json` | Capsules, sources, history, package, states |

## Interaction flow

```text
capsule dock → click capsule → reader
→ enter task → generate
→ capsules glow in place → serial tokens dock into task bay
→ generated package updates
```

### App states (main screen)

| State | `data-app-state` | When |
|-------|------------------|------|
| A Idle | `idle` | Ready, empty used dock |
| B Selected | `selected` | Capsule highlighted / reader |
| C Invoking | `invoking` | Generate in progress |
| D Ready | `ready` | Local preview package prepared |

## Stable integration IDs

```text
#capsule-dock          #task-bay           #used-capsule-dock
#capsule-reader        #generated-package  #history-popover
#sources-popover
```

Capsules expose `data-capsule-id`, `data-capsule-type`, `data-source`, `data-capsule-serial`.

Optional hook for desktop shell:

```js
window.ReweavePrototype.getState()
// { appState, selectedCapsuleId, usedCapsuleIds, taskText, isGenerating }
```

## Desktop Integration Notes

- This is a **static prototype** — no backend, no network calls, no auth.
- Data comes from `mock-data.json` (or the embedded fallback in `index.html`).
- Plain HTML/CSS/JS only — easy to port into Electron, Tauri, WebView2, or similar.
- Future desktop app should replace mock data with **local engine state**.
- The current `REWEAVE_ENGINE=lumo` path uses a legacy Luna HTTP adapter. It is not yet aligned with the P15 Lumo Lite local `frontend_runtime_state` / `capsule_warehouse` contract.
- The P15-aligned local path is `REWEAVE_ENGINE=lumo_lite` with `REWEAVE_LUMO_LITE_STATE_PATH=/path/to/frontend_runtime_state.json`; it surfaces `capsule_warehouse` as read-only capsules.
- The `lumo_lite` path also exposes referenced local artifacts through a read-only Artifacts popover. It can view/open/copy known artifact paths only.

Example Lumo Lite read-only launch:

```bash
REWEAVE_ENGINE=lumo_lite \
REWEAVE_LUMO_LITE_STATE_PATH=/path/to/frontend_runtime_state.json \
./start_reweave_static.sh
```

**Integration points for a real local engine:**

| UI area | Future source |
|---------|----------------|
| Source folders | Local vault / bound directories |
| Capsule list | Engine capsule registry |
| Selected capsule | Selection + reader content |
| Used capsules | Current task invocation set |
| Generation status | Engine job / invoke pipeline |
| Generated package | Output folder + file tree |
| `capsules_used.json` / `provenance.json` | Engine provenance records |

The UI should eventually run inside a desktop wrapper or local app shell. Keep DOM IDs stable; wire `ReweavePrototype.getState()` or replace `loadMockData()` with engine callbacks.

## Constraints

- No CDN, external fonts, images, or API calls
- Desktop-first (1280×800 and up), not mobile-first
- Does not modify code outside `reweave_frontend/`

## Product

**Reweave** · Local · Lumo engine — Recover old work. Weave new tools.
