# BRO canonical contracts

This directory is the machine-enforceable boundary between the canonical architecture and later implementations.

- `registry.json` is the canonical primitive-to-owner and schema registry.
- `v0.1/` contains provider- and framework-independent JSON Schema contracts.
- Contract versions are immutable after release. Breaking changes require a new version and an explicit migration decision.
- Implementations may store or transport records differently, but they must preserve the meanings, ownership, required fields, and invariants represented here.

Run `make check` before accepting a contract change. A registry entry without a valid schema, duplicate primitive ownership, an owner outside the constitutional owner set, or a schema whose identity disagrees with the registry fails closed.

