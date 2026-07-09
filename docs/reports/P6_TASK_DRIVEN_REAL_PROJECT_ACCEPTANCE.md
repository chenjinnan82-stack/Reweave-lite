# P6 Task-Driven Real Project Acceptance

Date: 2026-07-09

Scope: 5 local non-demo Source Boxes. Local paths are intentionally redacted.

## Criteria

- Uses plain `--task`, not `--task-template`.
- Generates `index.html`, `styles.css`, and `app.js`.
- Generates `task_intent.json`, `task_plan.json`, `quality_gate.json`, `task_pack.json`, `capsules_used.json`, `provenance.json`, and `snippets_used.json`.
- `quality_gate.status` is `passed`.
- HTML shows task intent, plan files, source-backed cues, source excerpts, and the review button.
- `source_project_write` stays `false`.
- No `.reweave` state folder is written into the source project.

## Result

| Case | Plain task | Verdict | Notes |
| --- | --- | --- | --- |
| ai_workorder | Build a work order operations dashboard from this old project | usable | data panel intent, 4 capsules, quality gate passed |
| neon_breakout | Build a browser game status page from this old project | usable | page intent, 4 capsules, quality gate passed |
| simple_adder | Build a simple calculator tool from this old project | usable | tool intent, 4 capsules, quality gate passed |
| personal_site | Build a portfolio project viewer from this old project | usable | data panel intent, 4 capsules, quality gate passed |
| haypile | Build a material review admin panel from this old project | usable | data panel intent, 4 capsules, quality gate passed |

Summary: 5 usable / 5 total.

## Boundary

This proves the new task-driven path can run local old projects without templates and produce a complete, provenance-backed Small Project Pack. It does not prove arbitrary production-ready generation, and it does not enable source project writes.
