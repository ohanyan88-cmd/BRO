# BRO — Runtime Body v0.1

**Status:** CANONICAL DESIGN DRAFT  
**Scope:** NERVOUS SYSTEM, HANDS, FEET, VOICE, IMMUNE SYSTEM integration

## 1. Purpose

This design turns BRO's judgment into authorized, recoverable, verifiable outcomes while preserving one identity and one owner per canonical concern.

## 2. Ownership

| Concern | Single owner |
|---|---|
| Task, Step, Assignment, Context Manifest, Runtime Event, Blocker | NERVOUS SYSTEM |
| Action Request, Action Attempt, Artifact runtime record, execution truth | HANDS |
| Route, movement position, continuation, resume checkpoint | FEET |
| User-facing expression | VOICE |
| Authority Decision, Approval, Delegation, Evidence, security/integrity/completion gates | IMMUNE SYSTEM |

## 3. Body Control Loop

1. NERVOUS SYSTEM receives Goal/Plan.
2. It creates or advances Task/Steps.
3. It assembles Context Manifest and assignments.
4. IMMUNE SYSTEM evaluates authority and controls guarded transitions.
5. HANDS executes authorized Action Requests.
6. FEET moves across stages/environments and preserves continuation.
7. Results become Action Attempts, Artifacts, Observations, and Evidence submissions.
8. IMMUNE SYSTEM evaluates evidence and completion.
9. NERVOUS SYSTEM advances, replans through MIND, blocks, pauses, recovers, or completes.
10. VOICE communicates actual state as BRO.

## 4. NERVOUS SYSTEM

Responsibilities:

- durable Task/Step lifecycle;
- context assembly orchestration;
- capability and specialist routing;
- dependency scheduling and safe parallelism;
- budget/time allocation;
- interruption handling;
- runtime event ledger;
- blocker lifecycle;
- coordination of recovery and verification;
- continuation until terminal or real blocker.

It cannot judge final meaning, authorize actions, execute effects, or certify Evidence.

## 5. HANDS

Responsibilities:

- normalize proposed effect into Action Request;
- bind target, inputs, authority, risk, idempotency, and verification;
- dispatch through a versioned adapter;
- create immutable Action Attempt per try;
- record actual result/error/side-effect state;
- create and validate Artifact runtime records;
- expose reconciliation interfaces.

Effect states:

- `NONE`;
- `POSSIBLE`;
- `CONFIRMED`;
- `UNKNOWN`;
- `REVERSED`.

Timeout never means `NONE`. Retry under `UNKNOWN` requires reconciliation or valid idempotency proof.

## 6. FEET

Responsibilities:

- current execution location;
- route and next valid movement;
- cross-environment navigation;
- dependency traversal;
- pause/resume checkpoint;
- unresolved-work return queue;
- handoff between interfaces without user handback;
- safe stop and return after interruption.

Movement does not authorize itself. FEET stops at authority, integrity, or risk boundaries and emits Blocker/route-change requests.

## 7. VOICE

VOICE receives synthesized content plus actual Task, authority, evidence, uncertainty, and execution states.

It must:

- speak as one BRO;
- distinguish proposed, attempted, partial, blocked, failed, verified, and completed;
- preserve uncertainty;
- explain authority blockers clearly;
- hide irrelevant internal fragmentation;
- expose internal roles only when materially useful;
- never convert tool success into outcome success;
- never claim human consciousness, emotion, or embodiment.

VOICE output is a projection, not system-of-record truth.

## 8. IMMUNE SYSTEM

Responsibilities:

- authority evaluation/enforcement;
- permission, approval, delegation, revocation;
- privacy and context-isolation controls;
- secret handling policy;
- evidence sufficiency;
- claim states;
- completion gates;
- release/promotion gates;
- security boundaries;
- integrity/conflict/staleness detection;
- irreversible-action controls.

Controls are mostly invisible in safe routine work and strict where consequence is real.

## 9. Adapter Contract

Every tool/model/app/browser/OS/repository/database adapter declares:

- identifier/version;
- operations;
- input/output schemas;
- technical scopes;
- authority needs;
- side effects;
- idempotency/reconciliation strategy;
- timeout/cancellation behavior;
- error taxonomy;
- evidence capability;
- secrets and privacy behavior;
- cost/latency limits;
- health state.

Adapter availability never grants authority.

## 10. Runtime Events

Material events are immutable, correlated, causally linked, versioned, and sanitized. Minimum families:

- intent/task/step lifecycle;
- plan revision;
- context revision;
- authority/approval/delegation;
- assignment;
- action request/attempt/effect;
- artifact/evidence;
- blocker/interruption/recovery;
- movement/checkpoint;
- completion/failure/cancellation;
- communication.

## 11. Concurrency

- parallel Steps require dependency independence;
- shared mutable targets require conflict control;
- each worker binds to Task/Plan/Context versions;
- stale results cannot overwrite newer canonical state;
- partial success remains explicit;
- cancellation is cooperative until effects reconcile;
- one Action Attempt per actual try;
- one canonical writer per state transition.

## 12. Recovery

Recovery sequence:

1. load last durable state;
2. validate integrity/authority;
3. inspect actual external state;
4. reconcile Action Attempts/effects;
5. invalidate stale context/approval;
6. restore route/checkpoint;
7. resume, replan, block, fail, or cancel;
8. record Decision and Evidence.

No blind replay.

## 13. Completion

`COMPLETED` requires:

- Goal outcome exists;
- mandatory scope satisfied;
- material effects reconciled;
- artifacts usable;
- criteria mapped to Evidence;
- checks passed;
- no invalidating blocker;
- partial/excluded scope explicit;
- VOICE reports actual state.

## 14. OS Donor Mapping

Selective-port candidates:

- durable orchestration and recovery → NERVOUS SYSTEM/FEET adapters;
- execution lease, scope, approvals, evidence, audit, completion → IMMUNE SYSTEM;
- bridge, broker, executor, staging/output → HANDS;
- desktop conversations/status projections → VOICE;
- existing run/task stores → compatibility projections, not target owners.

Every port requires donor commit, target owner, preserved tests, changed semantics, provenance/license review, and parity evidence.

## 15. Acceptance Gates

- RB-1: each concern has one owner.
- RB-2: every effect has Action Request and Attempt.
- RB-3: denial cannot be bypassed by adapter change.
- RB-4: unknown effect prevents blind retry.
- RB-5: crash recovery reconciles real state.
- RB-6: parallel results cannot corrupt canonical state.
- RB-7: VOICE cannot claim unverified completion.
- RB-8: Task survives process/session interruption.
- RB-9: specialist remains internal.
- RB-10: OS donor code enters only through port ledger and parity gate.
- RB-11: provider/tool replacement preserves lifecycle/authority semantics.
- RB-12: complete reference request reaches verified terminal state.

## 16. Decision

BRO's runtime body is a durable control loop. NERVOUS SYSTEM coordinates, HANDS acts, FEET moves, VOICE communicates, and IMMUNE SYSTEM protects. None shares ownership with another.

> **Think once as BRO. Coordinate explicitly. Act for real. Keep moving. Verify before DONE. Speak the truth.**
