# Desktop User Flow

The desktop is the human review surface for one formal SQLite Capsule
Warehouse and one `module_native` composer. It keeps two delivery modes as
separate entries while sharing the same formal capsules, service boundary, and
evidence chain.

The published baseline remains `v0.3.0`. Current `main` additionally contains
the completed Static Web review-only target backend and desktop flow from Plans
3 and 4. The current worktree also contains the formal local-model planning
implementation candidate; none of these post-tag changes are part of the
existing Tag.

## Shared Warehouse Flow

```text
Bind Source Box
-> discover and confirm a supported project
-> refresh a stable read-only snapshot
-> review candidates and validation evidence
-> publish immutable capsule versions to the formal SQLite warehouse
-> manage status, backup, restore, and selective revalidation
```

Source Boxes remain read-only. Local model selection is explicit; the model
cannot bypass deterministic safety or publication gates.

## Entry 1: Product Goal and Formal Plan

```text
Describe one product goal in the main input
-> if needed, explicitly select and Schema-probe an installed local <=15B planning model, proven by Ollama actual parameter metadata
-> answer 1–3 blocking planning questions without a preselected recommendation
-> review frontend, backend, data, and infrastructure sections
-> inspect model suggestions bound by the backend to eligible exact capsule versions
-> inspect explicit capability gaps
-> ask for an explanation or review a structured plan Diff
-> confirm the canonical plan
-> restore planning or confirmed state from History after restart
```

The plan workspace lives in Reweave application state under
`product_workspaces`; its internal workspace identity and paths never appear in
the UI or developer evidence. Confirmation stores only an immutable plan
version and receipt. It does not call `module_native`, generate files or a
product, write the products directory, or record `product_capsule_usage`.

The pre-existing formal standalone-generation backend, public CLI, generated
products, and product history remain available. A separate backend action can
compile a confirmed plan into `plan_execution.v1` and invoke the same composer
once to create an isolated `product_candidate.v1`. This action is not yet wired
into the formal desktop and cannot promote, apply, commit, or write usage.

## Entry 2: Static Web Target Review

```text
Open target integration
-> choose one target directory and explicit HTML entry
-> analyze a read-only target snapshot
-> inspect eligibility or structured rejection evidence
-> describe the task and select eligible formal capsule cards
-> request a review_patch_only Patch bound to the exact target snapshot
-> inspect file Diffs, binary metadata, Weave Plan, and validation evidence
-> confirm the reviewed Patch in memory
```

Simple mode is the default review surface. Developer mode reveals hashes,
mapping, connections, Plan details, and validation evidence without creating a
second workflow or weakening any backend rule.

The final confirmation stores only an in-memory receipt bound to `plan_id` and
the target snapshot. It does not call the desktop bridge and does not authorize
write, apply, commit, or rollback.

## Desktop Safety Boundary

- Source folders and selected target folders remain read-only.
- The target frontend consumes the backend profile and Patch contracts; it does
  not duplicate path, resource, authorization, or Patch-generation rules.
- Absolute target paths and Patch `after_content` are not rendered, logged, or
  persisted by the target review UI.
- Text changes render as text Diffs. Binary changes expose metadata only and are
  never decoded or executed by the frontend.
- Changing the target or entry invalidates the target profile, Patch, and
  confirmation. Changing the task or capsule selection invalidates the Patch
  and confirmation. Changing display mode invalidates confirmation.
- The public CLI has no target-integration entry.
- Product-planning model traffic is loopback-only, proxy-free, redirect-free,
  bounded, and bound to an exact selected name/digest with proven parameter
  count. The model receives no capsule source, formal capsule/version identity,
  canonical hash, SQLite row, product file, workspace path, raw prior prompt,
  or raw prior response.
- The product-plan frontend renders model/backend strings as text. Its state and
  developer evidence exclude internal workspace identity, paths, prompts, and
  raw responses.

## Current Acceptance

The standalone product path is accepted through the existing formal service,
composer, manifest/usage, and real QWebEngine product evidence.

Formal product planning has a separate `PARTIAL` acceptance record. The
deterministic backend, bounded human-editable Diff workflow, confirmation, and
restart recovery pass; local 7B free-text revision remains unproven. A separate
candidate record proves deterministic confirmed-plan compilation and real
isolated candidate generation from a strict confirmed-plan protocol fixture.
A real strong-model goal-to-confirmed-plan baseline remains outstanding. The
planning evidence is recorded in
[REWEAVE_PRODUCT_PLANNING_V1_ACCEPTANCE.json](reports/REWEAVE_PRODUCT_PLANNING_V1_ACCEPTANCE.json).
Candidate evidence is recorded in
[REWEAVE_PLAN_TO_EXECUTION_V1_ACCEPTANCE.json](reports/REWEAVE_PLAN_TO_EXECUTION_V1_ACCEPTANCE.json).

The Static Web target path is accepted in two explicit layers:

1. The Plan 3 record proves the real third-party target profile and complete
   review-only Patch backend with zero target, product-store, usage, and
   warehouse writes.
2. The Plan 4 record proves the complete desktop interaction in real
   QWebEngine against a strict stub of that frozen backend contract, including
   zero bridge calls during final confirmation.

A later independent record proves the combined real
`ReweaveAppService -> bridge -> QWebEngine UI` review-only run against the fixed
third-party target, while preserving the same chooser/analyze/generate bridge
sequence, zero-call final confirmation, and zero-write evidence.

## Historical UI Terminology

Earlier public-alpha documentation and compatibility checks retain these exact
labels:

- `Bind Source Box`
- `Build Small Project Pack`
- `Real source project writes stay off.`

`Build Small Project Pack` is a historical name, not the current formal
generation architecture. The current standalone path creates a registered
application-state product through `ReweaveAppService` and `module_native`.
The current source boundary is stronger than the old “off” wording: the public
product paths expose no Source Box write action.

## Not Available

The desktop currently has no action for:

- opening isolated candidates in the formal desktop or a full IDE;
- promoting a candidate into products, usage, or a user worktree;
- composing a large multi-capability product; current `module_native` still
  accepts only 1–3 capsules in one capability group;

- applying and validating a Patch in an isolated target copy, including build,
  test, and behavior checks;
- applying, committing, or rolling back a user's worktree; or
- targeting React + Vite or Node projects.

Those remain future, separately authorized stages. A successful review or
confirmation must not be presented as proof that any of them occurred.
