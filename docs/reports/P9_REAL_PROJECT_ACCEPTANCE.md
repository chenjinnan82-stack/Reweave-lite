# P9 Real Project Acceptance

Date: 2026-07-09

Scope: 10 local non-demo Source Boxes. Local paths are intentionally redacted.

## Criteria

- Generates `index.html`, `styles.css`, `app.js`.
- Generates `task_pack.json`, `capsules_used.json`, `provenance.json`, `snippets_used.json`.
- `source_project_write` stays `false`.
- Provenance keeps source paths redacted.
- No `.reweave` state folder is written into the source project.

## Result

| Case | Task template | Verdict | Notes |
| --- | --- | --- | --- |
| personal_site | portfolio-viewer | usable | 4 capsules, files complete |
| ai_workorder | operations-panel | usable | 4 capsules, files complete |
| neon_breakout | artist-landing | usable | 4 capsules, files complete |
| simple_adder | operations-panel | usable | 4 capsules, files complete |
| fibo_test | portfolio-viewer | usable | 4 capsules, files complete |
| haypile | operations-panel | usable | 4 capsules, files complete |
| reweave_standalone | operations-panel | rejected | missing `snippets_used.json` |
| meowbus_core | operations-panel | usable | 2 capsules, files complete |
| old_reweave_frontend | portfolio-viewer | usable | 4 capsules, files complete |
| luna | operations-panel | rejected | missing `snippets_used.json` |

Summary: 8 usable / 10 total.

The target for this pass was at least 7 usable / 10. P9 passed.

## Boundary

This proves Reweave-lite can reuse several local old project folders into Small Project Packs with provenance. It does not prove arbitrary large-project production generation.
