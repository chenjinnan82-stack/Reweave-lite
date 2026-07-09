# P7 Local Ollama Reproduction

Model: `qwen2.5-coder:1.5b` via local Ollama.

| Source Box | Default files | LLM applied | Require LLM applied | LLM normalizations | Source term overlap |
|---|---:|---:|---:|---|---|
| `customer-quote-widget` | yes | true | true | normalized_html_assets | accent, addeventlistener, aside, b7791f, background, border |
| `ops-status-card` | yes | true | true | normalized_html_assets | active, article, b54708, background, backlog, backlog |
| `support-ticket-triage` | yes | true | true | normalized_html_assets, filled_missing_app_js | addeventlistener, after, article, b42318, background, billing |
| `content-calendar` | yes | true | true | normalized_html_assets, filled_missing_app_js | a5b13, addeventlistener, article, background, border, border-radius |
| `launch-checklist` | yes | true | true | normalized_html_assets | addeventlistener, array, background, block, border, border-radius |

## Boundary

- Source project writes stayed off.
- LLM calls were localhost Ollama only.
- Invalid local-model output is normalized only for local asset links and missing `app.js`; otherwise it falls back or fails under `--require-llm`.
- Required files checked: `index.html`, `styles.css`, `app.js`, `task_pack.json`, `capsules_used.json`, `provenance.json`.
