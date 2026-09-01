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

## Current state

Architecture checkpoints 1–4 are defined. Repository foundation implementation has begun with provider-independent canonical contracts, a single-owner registry, fail-closed validation, tests, and CI enforcement.

The first runtime slice now provides a durable SQLite/WAL Task state machine, optimistic revision control, append-only Runtime Events, an evidence-controlled completion gate, resumable pause checkpoints, and recovery routing that reconciles actual effects without replaying commands.

## Contract gate

Run:

```bash
make check
```

No runtime implementation or donor port may redefine a canonical primitive, assign a second owner, or bypass these contract gates. Selective ports from the OS donor follow only after the target contract they serve exists and their provenance, behavior, tests, parity evidence, and rollback are recorded.
