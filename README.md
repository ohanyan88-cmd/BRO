# BRO

BRO is a provider-independent durable runtime core for governed AI execution.

## Development delivery rule

All repository changes must follow **branch → pull request → green CI → merge**. Direct delivery to `main` is forbidden. The canonical CI workflow verifies PR-associated delivery on every `main` push and fails closed when the pushed commit is not associated with a merged pull request.

Product readiness is evidence-derived from `contracts/product_readiness.json`. Tests validate the current criteria dynamically; readiness percentages must not be duplicated as manually maintained expectations.

See the repository contracts, executable invariants, runtime modules, and tests for the canonical architecture and enforcement.
