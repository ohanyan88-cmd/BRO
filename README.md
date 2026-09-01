# BRO

BRO is one persistent AI operating partner: one identity, expandable intelligence, governed memory, specialist orchestration, real execution, continuation across work, and evidence-based completion.

> **ONE BRO — MANY CAPABILITIES.**

## Repository authority

This repository is the sole source-of-truth and target implementation repository for the new BRO architecture.

`menqstudio/OS` is a read-only donor/reference. Selected proven mechanisms may be ported with provenance, single ownership, tests, and parity evidence. The donor repository is never modified as part of this build.

## Canonical architecture

Read in this order:

1. `docs/architecture/BRO_ARCHITECTURE_FOUNDATION_V0_2.md`
2. `docs/architecture/BRO_LOGICAL_ARCHITECTURE_V0_1.md`
3. `docs/architecture/BRO_CONSTITUTION_AND_AUTHORITY_MODEL_V0_1.md`
4. `docs/architecture/BRO_SELF_AND_HEART_V0_1.md`
5. `docs/architecture/BRO_INTELLIGENCE_AND_CONTEXT_V0_1.md`
6. `docs/architecture/BRO_RUNTIME_BODY_V0_1.md`
7. `docs/architecture/BRO_PROJECT_AND_CONTEXT_MODEL_V0_1.md`
8. `docs/migration/BRO_CURRENT_REPOSITORY_COMPATIBILITY_MAP_V0_1.md`

## Non-negotiable rules

- BRO remains one identity; specialists remain internal.
- Every canonical concern has exactly one owner.
- Capability does not grant authority.
- Current reality outranks stale memory.
- No simulated access, action, evidence, or completion.
- Material work is durable and recoverable.
- `DONE` requires sufficient evidence.
- Project/private boundaries are enforced.
- Models, tools, and providers remain replaceable mechanisms.

## Development delivery rule

All repository changes must follow **branch → pull request → green CI → merge**. Direct delivery to `main` is forbidden. The canonical CI workflow checks every `main` push against GitHub's associated pull requests and fails closed when the pushed commit is not associated with a merged PR targeting `main`.

Product readiness is evidence-derived from `contracts/product_readiness.json`. Tests calculate expected readiness from the current declared criteria and evidence instead of duplicating manually maintained percentages.

## Current state

Architecture checkpoints 1–4 are defined. Repository foundation implementation has begun with provider-independent canonical contracts, a single-owner registry, fail-closed validation, tests, and CI enforcement.

The first runtime slice now provides a durable SQLite/WAL Task state machine, optimistic revision control, append-only Runtime Events, an evidence-controlled completion gate, resumable pause checkpoints, and recovery routing that reconciles actual effects without replaying commands.

The HANDS execution slice adds canonical Action Requests, immutable Authority Envelope binding, exact scope/tool/risk enforcement, one immutable Action Attempt per try, idempotency-aware retry control, and explicit effect reconciliation. Timeouts become `UNKNOWN`, never assumed `NONE`.

The orchestration slice adds durable Specialist Assignments, serialized claims, scoped worker leases, heartbeats, expiry-driven recovery, monotonic fencing tokens, stale-result rejection, evidence-backed settlement, and explicit partial-result preservation. Workers execute bounded assignments; they never become canonical owners or alternate BRO identities.

The supervision slice connects those owners into one governed flow:

`Task → Specialist Assignment → Authority → Action Request/Attempt → Effect Reconciliation → Evidence → Verified Completion Manifest`

It adds the IMMUNE SYSTEM runtime (`src/bro_runtime/immune.py`) — the single authority evaluator, the append-only Evidence ledger with scope isolation and freshness/validity sufficiency, and the Completion Manifest gate — and the NERVOUS SYSTEM controller (`src/bro_runtime/supervision.py`), which sequences the existing owners without taking their state. HANDS no longer evaluates authority: it submits an Action Request and consumes an explicit `ALLOW` / `DENY` / `APPROVAL_REQUIRED` verdict, and every verdict is recorded.

`COMPLETED` is reachable only through a `VERIFIED` Completion Manifest. A failed gate durably records its verdict and reason and leaves the Task blocked, recoverable, and auditable. Unknown or possible effects, insufficient or stale Evidence, partial results, boundary mismatches, superseded fencing tokens, and stale Task revisions all fail closed. `resume()` reconstructs the valid next step from durable state alone and replays no command.

The Task record now conforms to `contracts/v0.1/task.schema.json`: canonical plan, context, authority, artifact, approval, and excluded-scope references are stored, bound by the transition that establishes them, and projected by `SQLiteTaskStore.canonical_task()`. Databases written by an earlier build migrate in place.

### Boundary and tool semantics

- A project boundary has one canonical scope token, normalised exactly once: `project:BRO` stays `project:BRO`, and a bare `BRO` becomes `project:BRO`.
- `SpecialistAssignment.allowed_tools` holds **adapter identifiers** — the same namespace as `ActionRequest.adapter_id` and `AuthorityEnvelope.tool_boundary`. Targets belong to `target` and the envelope's `allowed_scope`. A delegated tool grant may never exceed the envelope's tool boundary.

## Contract gate

Run:

```bash
make check
```

No runtime implementation or donor port may redefine a canonical primitive, assign a second owner, or bypass these contract gates. Selective ports from the OS donor follow only after the target contract they serve exists and their provenance, behavior, tests, parity evidence, and rollback are recorded.
