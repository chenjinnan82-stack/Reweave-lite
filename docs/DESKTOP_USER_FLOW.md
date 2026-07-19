# Desktop User Flow

The desktop is the human review surface for one formal SQLite Capsule
Warehouse and one `module_native` composer. It keeps two delivery modes as
separate entries while sharing the same formal capsules, service boundary, and
evidence chain.

The published baseline remains `v0.3.0`. Current `main` additionally contains
the completed Static Web review-only target backend and desktop flow from Plans
3 and 4; those capabilities are not part of the existing Tag.

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

## Entry 1: Standalone Product

```text
Open standalone product generation
-> describe the task
-> select eligible active-current formal capsules
-> generate through ReweaveAppService and module_native
-> inspect the runnable three-file product
-> inspect manifest, provenance, quality/runtime evidence, and exact usage
```

Generated files live in a new Reweave application-state product directory.
The source project is unchanged. The service-backed public CLI uses this same
formal generation path and requires explicit capsule IDs.

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

## Current Acceptance

The standalone product path is accepted through the existing formal service,
composer, manifest/usage, and real QWebEngine product evidence.

The Static Web target path is accepted in two explicit layers:

1. The Plan 3 record proves the real third-party target profile and complete
   review-only Patch backend with zero target, product-store, usage, and
   warehouse writes.
2. The Plan 4 record proves the complete desktop interaction in real
   QWebEngine against a strict stub of that frozen backend contract, including
   zero bridge calls during final confirmation.

These two records do not yet constitute one combined real
`ReweaveAppService -> bridge -> QWebEngine UI` end-to-end run.

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

- applying and validating a Patch in an isolated target copy, including build,
  test, and behavior checks;
- applying, committing, or rolling back a user's worktree; or
- targeting React + Vite or Node projects.

Those remain future, separately authorized stages. A successful review or
confirmation must not be presented as proof that any of them occurred.
