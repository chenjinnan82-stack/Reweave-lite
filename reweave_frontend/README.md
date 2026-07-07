# Reweave Frontend

Plain HTML/CSS/JS desktop UI for Reweave-lite. No build step.

## Quick Preview

See the UI before installing the desktop shell:

```bash
cd reweave_frontend
python3 -m http.server 8765
# http://localhost:8765/index.html
# http://localhost:8765/index.html?main=1
```

Browser mode uses `mock-data.json` or the embedded read-only fallback. It is for layout preview only.

## Desktop Shell

The real desktop shell uses PySide6 + QtWebEngine:

```bash
./start_reweave_static.sh
```

First run may create `.venv-reweave` and install PySide6 wheels. This is large; use browser preview first if you only want to inspect the UI.

Optional mirror:

```bash
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
./start_reweave_static.sh
```

## Current Public Flow

```text
Bind Source Box -> Scan -> Prepare -> Store capsules -> Build Task Pack preview
```

The public default is read-only against source projects. No frontend apply/export/open-folder write path is exposed.

The Lumo Lite bridge can show known runtime artifacts as bounded metadata/text preview, with copy-path support. Direct open-folder/open-artifact actions stay out of the public release surface for now.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Source Box onboarding and workbench |
| `styles.css` | Desktop layout and Reweave logo treatment |
| `app.js` | UI state and desktop bridge calls |
| `mock-data.json` | Read-only fallback data |

## Stable Integration IDs

```text
#screen-welcome       #screen-main        #capsule-dock
#task-bay             #used-capsule-dock  #capsule-reader
#generated-package    #history-popover    #sources-popover
```

Optional browser hook:

```js
window.ReweavePrototype.getState()
```

## Boundary

This folder is the UI surface, not the full backend. The public release target is Reweave-lite: safe Source Box intake, capsule review, read-only runtime/artifact viewing, and Task Pack preview.
