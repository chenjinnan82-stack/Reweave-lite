# Desktop User Flow

The desktop app is the human path for the same safe chain used by the CLI.

## Flow

```text
Bind Source Box
-> Scan
-> Draft Capsules
-> Store Capsules
-> Describe Task
-> Select capsules
-> Build Small Project Pack
-> View provenance
```

## Boundary

- Source folders are read-only.
- Preview output is written outside the source folder.
- Export / apply / open real project folder actions stay hidden or blocked in the public default flow.
- Real source project writes stay off.

## Acceptance

A desktop smoke is considered good enough when:

- the Source Box onboarding appears first;
- a source folder can be bound;
- scan / prepare / store can run;
- capsules can be selected;
- Build Small Project Pack returns `task_intent.json`, `task_plan.json`, `quality_gate.json`, and `task_pack.json`;
- generated package files include `index.html`, `styles.css`, `app.js`, `capsules_used.json`, `provenance.json`, and `snippets_used.json`;
- the original source file content is unchanged.
