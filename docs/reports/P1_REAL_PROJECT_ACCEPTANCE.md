# P1 Real Project Acceptance

Date: 2026-07-09

This is a local acceptance note for Reweave-lite against three non-demo Source Boxes. Paths are intentionally redacted.

## Scope

Reweave was run against:

| Case | Source type | Task template | Result |
| --- | --- | --- | --- |
| A | personal / portfolio site | portfolio-viewer | accepted |
| B | business operations demo | operations-panel | accepted |
| C | legacy artist app | artist-landing | accepted |

## Checks

- Source Box scan completed.
- Capsule draft / store completed.
- Small Project Pack was generated.
- `index.html`, `styles.css`, and `app.js` were present.
- `task_pack.json`, `capsules_used.json`, `provenance.json`, and `snippets_used.json` were present.
- Chrome loaded each generated `index.html`.
- CSS and JS assets loaded.
- The local review button updated page state.
- Source project writes stayed `false`.
- No `.reweave` state folder was written into the source project.
- Local source paths stayed redacted in public provenance.

## Verdict

Reweave-lite can use non-demo old project folders to generate runnable Small Project Packs with provenance.

This proves the current alpha is useful for small project-pack reuse. It does not prove production-grade generation for arbitrary large projects.

## Next Product Gap

The generated packs are structurally usable, but still generic. The next quality pass should make each task template produce a more task-specific layout:

- portfolio-viewer should look more like a project gallery.
- operations-panel should look more like a working status / workflow panel.
- artist-landing should look more like a focused creator landing page.
