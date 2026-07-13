# P10 Bounded Copy and Behavior Migration

Date: 2026-07-12

Model: `qwen2.5-coder:7b` via local Ollama with `--require-llm`.

## Question

Can one closed behavior capsule support several natural-language tasks without
becoming a fixed template?

## Method

Three read-only Source Boxes were used. Each source received three different
tasks. Every run had to:

- apply the local model rather than silently fall back;
- preserve the old module's scripts, DOM ids, events, and behavior;
- pass the quality gate and runtime interaction check;
- write no files to the Source Box;
- produce task-specific bounded copy.

## Result

| Source behavior | Variant | Bounded copy change | Runtime | Human verdict |
| --- | --- | --- | --- | --- |
| Two-number addition | Invoice total | CTA: `计算发票总额` | passed | usable |
| Two-number addition | Travel budget | CTA: `计算旅行预算` | passed | usable, shallow |
| Two-number addition | Event cost | CTA: `计算活动费用` | passed | usable, shallow |
| Status refresh | Service health | subtitle, log heading, CTA | passed | usable |
| Status refresh | Greenhouse sensors | subtitle, log heading, CTA | passed | usable |
| Status refresh | Production equipment | subtitle, log heading, CTA | passed | usable |
| Target interaction | Reaction practice | instructions and CTA | passed | usable |
| Target interaction | Accuracy drill | instructions and CTA | passed | usable |
| Target interaction | Visual inspection | instructions and CTA | passed | needs review |

Machine result: 9/9 model-applied, quality-passed, runtime-passed, and
`source_project_write=false`.

Human result: 8/9 usable under the bounded-copy criterion. All nine product
entries had different SHA-256 digests. The visual-inspection variant retained
too much target-shooting meaning to count as a clean domain migration.

## Correct Claim

Reweave can reuse a closed old-project behavior module while a local model
adapts a small set of safe, static words for several tasks.

This is **bounded copy migration plus behavior reuse**.

## Not Proven

- Field labels are not migrated. An earlier experiment produced incompatible
  units such as cost plus days while the old addition logic stayed unchanged;
  that capability was removed before this report.
- Dynamic state text, scripts, ids, events, and file structure are not model
  writable.
- The result does not prove arbitrary domain conversion, multi-capsule
  composition, or unit-aware business-logic migration.

## Safety Boundary

- Source Boxes remained unchanged during the runs.
- The model used localhost Ollama only.
- Model participation and applied patches are recorded in provenance.
- Failed or non-applied model output does not pass `--require-llm`.
