# Durable Restart Recovery / Դիմացկուն restart recovery

## English
BRO must not replay an external command merely because the process restarted before the effect was verified. Persisted Action truth remains authoritative across restart.

For a persisted `POSSIBLE` or `UNKNOWN` effect, recovery requires an independent external observation first. Only after that observation exists may NERVOUS SYSTEM expire a stale lease, reclaim a fresh fenced lease, and reconcile the effect. A still-live lease is never stolen. The recovery event records `command_replayed: false`.

This mechanism does not create new authority, Evidence, Action, Assignment, or Task records outside their canonical owners. It coordinates the existing durable owners so reconciliation can continue after process loss.

This proof is a restart/reconciliation guarantee for the bounded external-write path; it is not a general production-readiness verdict.

## Հայերեն
BRO-ն արտաքին command-ը չի կրկնում միայն այն պատճառով, որ process-ը restart է եղել մինչև effect-ի verification-ը։ Persisted Action truth-ը restart-ից հետո նույնպես մնում է authoritative։

Persisted `POSSIBLE` կամ `UNKNOWN` effect-ի դեպքում recovery-ն նախ պահանջում է արտաքին համակարգից անկախ observation։ Միայն դրանից հետո NERVOUS SYSTEM-ը կարող է expire անել հին lease-ը, վերցնել նոր fenced lease և reconcile անել effect-ը։ Դեռ կենդանի lease-ը երբեք չի խլվում։ Recovery event-ում պահվում է `command_replayed: false`։

Այս մեխանիզմը նոր authority, Evidence, Action, Assignment կամ Task truth path չի ստեղծում։ Այն շարունակում է արդեն գոյություն ունեցող canonical durable owner-ների state-ը process loss-ից հետո։

Այս proof-ը bounded external-write path-ի restart/reconciliation guarantee է և ընդհանուր production-readiness verdict չէ։
