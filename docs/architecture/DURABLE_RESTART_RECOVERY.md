# Durable Restart Recovery / Դիմացկուն restart recovery

## English
BRO must not replay an external command merely because the process restarted before the effect was verified. Persisted Action truth remains authoritative across restart.

For a persisted `POSSIBLE` or `UNKNOWN` effect, recovery requires an independent external observation first. The canonical `BROKernel.reconcile_after_restart(...)` boundary checks that the observation belongs to the persisted Task/project scope, uses a registered IMMUNE verifier to mint trusted Evidence, and only then delegates to restart recovery. NERVOUS SYSTEM may expire a stale lease, reclaim a fresh fenced lease, and reconcile the effect. A still-live lease is never stolen. The recovery event records `command_replayed: false`.

The restart runtime also performs its own Evidence-scope check before reclaiming a lease. This defense-in-depth means foreign Evidence cannot mutate recovery fencing state even when the lower-level runtime is used directly.

This mechanism does not create new authority, Evidence, Action, Assignment, or Task records outside their canonical owners. BROKernel composes those owners into the privileged restart path instead of requiring callers to stitch trusted Evidence and reconciliation helpers together.

This proof is a restart/reconciliation guarantee for the bounded external-write path; it is not a general production-readiness verdict and is not a second live network restart acceptance.

## Հայերեն
BRO-ն արտաքին command-ը չի կրկնում միայն այն պատճառով, որ process-ը restart է եղել մինչև effect-ի verification-ը։ Persisted Action truth-ը restart-ից հետո նույնպես մնում է authoritative։

Persisted `POSSIBLE` կամ `UNKNOWN` effect-ի դեպքում recovery-ն նախ պահանջում է արտաքին համակարգից անկախ observation։ Canonical `BROKernel.reconcile_after_restart(...)` boundary-ն նախ ստուգում է, որ observation-ը պատկանում է persisted Task/project scope-ին, հետո registered IMMUNE verifier-ով mint է անում trusted Evidence, և միայն դրանից հետո փոխանցում է restart recovery-ին։ NERVOUS SYSTEM-ը կարող է expire անել հին lease-ը, վերցնել նոր fenced lease և reconcile անել effect-ը։ Դեռ կենդանի lease-ը երբեք չի խլվում։ Recovery event-ում պահվում է `command_replayed: false`։

Restart runtime-ը նաև ինքնուրույն ստուգում է Evidence scope-ը մինչև նոր lease վերցնելը։ Այս defense-in-depth-ի շնորհիվ foreign Evidence-ը չի կարող recovery fencing state փոխել նույնիսկ lower-level runtime-ի direct օգտագործման դեպքում։

Այս մեխանիզմը նոր authority, Evidence, Action, Assignment կամ Task truth path չի ստեղծում։ BROKernel-ը canonical owner-ներին միավորում է privileged restart path-ի մեջ, որպեսզի caller-ը trusted Evidence և reconciliation helper-ները կողքից ձեռքով չկապի։

Այս proof-ը bounded external-write path-ի restart/reconciliation guarantee է, ընդհանուր production-readiness verdict չէ և երկրորդ live network restart acceptance էլ չէ։
