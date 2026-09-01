# BRO — Logical Architecture v0.1

**Status:** LOGICAL ARCHITECTURE DRAFT — Phase B baseline, not an implementation or deployment specification  
**Product:** BRO  
**Depends on:** `BRO_ARCHITECTURE_FOUNDATION_V0_2.md`  
**Scope:** Logical responsibilities, runtime primitives, state ownership, contracts, lifecycle, recovery, and acceptance gates

---

## 1. Purpose

This document translates BRO's human-shaped foundation into a buildable logical system without prematurely choosing a programming language, framework, repository layout, database, model provider, process topology, or deployment platform.

It defines:

- the smallest canonical runtime primitives;
- ownership and boundary rules;
- task and action lifecycles;
- contracts between BRO's organs;
- the runtime control loop;
- durable state, events, evidence, and recovery requirements;
- cross-cutting control requirements;
- Phase B acceptance gates.

This document does **not** define:

- final schemas or storage engines;
- final APIs or wire formats;
- prompts;
- model selection;
- source-code packages;
- services or deployment units;
- user-interface design;
- detailed organ specifications belonging to later phases.

---

## 2. Foundation Constraints

The logical architecture inherits these non-negotiable constraints:

1. **One BRO** — internal specialists, skills, models, and tools never become competing user-facing identities.
2. **BRO owns judgment** — delegation may expand reasoning or execution capacity but may not transfer final interpretation, decision, synthesis, or reporting ownership.
3. **Current reality outranks stale memory** — memory supplies continuity and contradiction detection, not automatic truth.
4. **Real capability only** — no access, action, verification, or result may be claimed unless it actually occurred.
5. **Evidence before DONE** — completion is a governed state supported by evidence appropriate to materiality and risk.
6. **Context isolation** — self, relationship, user, project, work, and private contexts remain separated unless an authorized promotion or sharing rule applies.
7. **Autonomy inside authority** — BRO continues through clear, reversible, authorized work without unnecessary handback.
8. **Recoverable execution** — material multi-step work has explicit state and can be inspected, interrupted, resumed, failed, recovered, or cancelled honestly.
9. **Single canonical ownership** — every durable fact, rule, state class, contract, decision class, and runtime primitive has exactly one authoritative owner. Ownership is never shared between organs.
10. **Logical organs are not deployment units** — an organ is not automatically an agent, service, process, package, database, model, or repository folder.
11. **Provider independence** — BRO's identity and logical behavior must not depend on one model, tool vendor, or hosting platform.
12. **Observable truth** — material decisions, actions, transitions, and checks must be traceable.

### 2.1 Ownership doctrine

Ownership is indivisible.

For every canonical concern, the architecture must name exactly one owner. Other organs may participate through explicit roles without becoming co-owners:

- **Contributor** — supplies input or proposes a change;
- **Executor** — performs work authorized by the owner or control layer;
- **Verifier** — evaluates evidence or a completion condition;
- **Controller** — permits, denies, gates, or vetoes an operation within its own authority;
- **Consumer** — reads or depends on the owned output;
- **Custodian** — stores or protects the representation without owning its meaning.

Contribution, execution, verification, control, consumption, custody, or physical storage never divides canonical ownership.

If two organs appear to own the same thing, the design is invalid until either:

1. the concern is decomposed into separate primitives with one owner each; or
2. one canonical owner is selected and every other relationship is expressed as a contract, collaboration, or control.

---

## 3. Logical Architecture Layers

BRO is described through six logical layers. These layers organize responsibility; they do not prescribe processes or services.

### 3.1 Continuity Layer

Contains SELF and HEART responsibilities.

Owns:

- identity continuity;
- behavioral stance;
- relationship policy and private foundation boundaries;
- stable voice baseline;
- versioned evolution of BRO-specific identity.

Must not own project facts, task execution state, evidence, or tool credentials.

### 3.2 Cognition Layer

Contains MIND responsibilities.

Owns:

- intent interpretation;
- problem framing;
- reasoning and judgment;
- decision formation;
- planning and replanning;
- synthesis and reflection.

MIND consumes observations, relevant context, capability information, policy decisions, and execution results. It does not directly manufacture observations or action results.

### 3.3 Reality and Knowledge Layer

Contains PERCEPTION, MEMORY, and SKILLS & KNOWLEDGE responsibilities.

Owns:

- current observations and source provenance;
- governed continuity and retrieval;
- capability definitions and quality state;
- knowledge and method access;
- contradiction and freshness signals.

### 3.4 Coordination Layer

Contains NERVOUS SYSTEM responsibilities.

Owns:

- context assembly;
- routing and scheduling;
- dependency coordination;
- specialist and capability activation;
- interruption and continuation coordination;
- runtime event progression.

It coordinates judgment but does not replace MIND's judgment.

### 3.5 Agency Layer

Contains HANDS, FEET, and VOICE responsibilities.

Owns:

- authorized state-changing actions;
- navigation across environments and work stages;
- continuation toward the outcome;
- coherent user-facing communication.

### 3.6 Trust and Control Layer

Contains IMMUNE SYSTEM and CONSTITUTION responsibilities and applies across every other layer.

Owns:

- authority resolution;
- permissions and approval gates;
- truth and evidence controls;
- privacy, security, and isolation enforcement;
- irreversible-action controls;
- release, promotion, and completion gates;
- integrity and audit requirements.

No other layer may bypass this layer.

---

## 4. Canonical Runtime Primitives

The primitives below are logical records. A later design may store some together, derive some dynamically, or implement them across multiple components, but their meanings and ownership must remain distinct.

### 4.1 Intent

The user's expressed request or authorized external trigger as received, before BRO's interpretation.

Minimum properties:

- immutable original input or trigger reference;
- origin and actor;
- received time;
- channel and environment;
- attachments or referenced resources;
- initial authority context.

**Owner:** PERCEPTION.  
**Consumer:** MIND interprets the Intent and produces a separately owned Goal.  
**Rule:** interpreted scope must never overwrite the original intent.

### 4.2 Goal

BRO's explicit representation of the required outcome.

Minimum properties:

- desired outcome;
- interpreted scope;
- constraints;
- assumptions and uncertainty;
- success conditions;
- non-goals;
- authority basis;
- materiality and risk classification.

**Owner:** MIND.  
**Rule:** material ambiguity must be resolved or exposed before irreversible execution.

### 4.3 Task

The durable unit of outcome ownership.

A Task connects the Goal to execution and remains the canonical record of work state.

Minimum properties:

- stable identifier;
- goal reference;
- accountable product identity: BRO;
- current lifecycle state;
- plan reference and revision;
- active step or blocker;
- context manifest reference;
- authority and approval state;
- evidence and artifact references;
- timestamps and revision;
- completion or termination reason.

**Owner:** NERVOUS SYSTEM.  
**Collaborators and controls:** MIND owns the referenced Goal and Plan; IMMUNE SYSTEM controls guarded transitions through explicit allow, deny, or approval decisions.

### 4.4 Plan

A versioned execution strategy for a Task.

Minimum properties:

- ordered or dependency-based steps;
- required capabilities;
- direct-work versus delegation decisions;
- expected observations and outputs;
- checkpoints and verification requirements;
- authority gates;
- recovery options;
- completion path.

**Owner:** MIND.  
**Rule:** replanning creates a new revision and preserves the reason for change.

### 4.5 Step

A bounded unit within a Plan with an observable completion condition.

Minimum properties:

- purpose;
- dependencies;
- required context and capability;
- expected effect or output;
- authority class;
- verification requirement;
- retry and failure policy;
- current state.

**Owner:** NERVOUS SYSTEM.  
**Executor:** the assigned organ or specialist performs the Step's bounded work and returns results without owning the Step record or lifecycle.

### 4.6 Context Manifest

A scoped, traceable declaration of the context assembled for a Task or decision.

It references rather than blindly copies:

- active SELF and HEART versions;
- user context;
- project source-of-truth;
- work and decision memory;
- current observations;
- applicable instructions and policies;
- capability and tool state;
- quarantined conflicts or exclusions.

Minimum metadata:

- source;
- scope;
- authority;
- freshness or effective time;
- trust state;
- sensitivity;
- reason for inclusion;
- isolation boundary.

**Owner:** NERVOUS SYSTEM.  
**Contributors and controls:** MEMORY and PERCEPTION own the referenced source records; IMMUNE SYSTEM controls inclusion and boundary compliance.

### 4.7 Observation

A time-bound representation of something BRO actually perceived.

Minimum properties:

- observed claim or raw result reference;
- source and provenance;
- observation time;
- freshness;
- confidence or trust state;
- scope and limitations;
- integrity metadata where available.

**Owner:** PERCEPTION.  
**Rule:** an Observation is not automatically a Fact or Decision.

### 4.8 Decision

A judgment selected by MIND from evidence, constraints, policy, and alternatives.

Minimum properties:

- question decided;
- selected conclusion or route;
- rationale;
- evidence and assumptions;
- alternatives materially considered;
- authority basis;
- uncertainty;
- reversibility;
- time and version.

**Owner:** MIND.  
**Rule:** specialists may recommend; BRO records the final decision.

### 4.9 Capability

A versioned, testable ability to achieve a class of outcomes under declared conditions.

Minimum properties:

- capability definition;
- inputs and outputs;
- prerequisites;
- permitted scopes;
- quality and evidence state;
- limitations;
- cost and latency characteristics where known;
- compatible skills, specialists, models, and tools;
- version and lifecycle state.

**Owner:** SKILLS & KNOWLEDGE.

### 4.10 Specialist Assignment

A bounded internal delegation from BRO to a specialist worker.

Minimum properties:

- task and step scope;
- required capability;
- provided context boundary;
- expected output contract;
- authority and tool limits;
- deadline or budget;
- evidence requirements;
- status and result.

**Owner:** NERVOUS SYSTEM.  
**Rule:** delegation transfers work, never BRO's identity or final judgment ownership.

### 4.11 Action Request

A proposed use of an execution interface.

Minimum properties:

- intended effect;
- target and environment;
- requested capability or tool;
- input parameters;
- authority basis;
- risk and reversibility class;
- idempotency strategy;
- expected result;
- required verification.

**Owner:** HANDS.  
**Controller:** IMMUNE SYSTEM authorizes, denies, or requires approval without owning the Action Request.

### 4.12 Action Attempt

The immutable record of one actual execution attempt.

Minimum properties:

- action request reference;
- exact executor and interface version;
- start and end time;
- sanitized inputs;
- actual result or error;
- side-effect state: none, possible, confirmed, or unknown;
- retry relationship;
- produced artifacts and observations.

**Owner:** HANDS.  
**Rule:** an attempted action is not a successful action.

### 4.13 Artifact

A produced or modified work product.

Minimum properties:

- identity and version;
- type and location;
- producing task, step, and action;
- content integrity reference where applicable;
- ownership and sensitivity;
- validation state;
- persistence and retention state.

**Owner:** HANDS.  
**Authority boundary:** the relevant Project or Work source-of-truth may own domain facts represented by the Artifact, but not the Artifact runtime record itself.

### 4.14 Evidence

A record that supports or refutes a claim, transition, or completion condition.

Minimum properties:

- claim or criterion addressed;
- evidence type;
- source and provenance;
- collection method and time;
- result;
- scope and limitations;
- validity and freshness;
- verifier identity or process.

**Owner:** IMMUNE SYSTEM.  
**Contributors:** PERCEPTION and HANDS collect and submit evidence material without owning the canonical Evidence record or its sufficiency state.

### 4.15 Approval

A recorded authorization decision required before a guarded transition or action.

Minimum properties:

- requested decision;
- exact scope;
- risk and consequence;
- approver identity and authority;
- decision: approved, denied, expired, or revoked;
- conditions;
- time and validity window.

**Owner:** IMMUNE SYSTEM.  
**Rule:** approval is scope-bound and must not be generalized silently.

### 4.16 Runtime Event

An immutable statement that a material runtime occurrence happened.

Examples:

- intent received;
- goal interpreted;
- plan revised;
- state transitioned;
- approval requested or resolved;
- action attempted;
- evidence recorded;
- blocker detected;
- task interrupted, resumed, completed, failed, or cancelled.

Minimum properties:

- event identifier and type;
- subject reference;
- actor;
- occurred time and recorded time;
- causal and correlation references;
- sanitized payload;
- schema version.

**Owner:** NERVOUS SYSTEM.  
**Contributor:** the originating organ supplies the occurrence payload and remains accountable for its accuracy without owning the canonical Runtime Event.

### 4.17 Blocker

A condition that prevents a valid next transition.

Classes include:

- missing required information;
- unavailable capability or system;
- denied or missing authority;
- unresolved material contradiction;
- failed prerequisite;
- unsafe or integrity-threatening condition;
- external dependency;
- uncertain side-effect state.

**Rule:** a Blocker must state what is blocked, why, what evidence supports it, and the shortest valid resolution path.

**Owner:** NERVOUS SYSTEM.  
**Contributors and controls:** any organ may detect and report a blocking condition; IMMUNE SYSTEM may impose a blocker through a control decision.

---

## 5. Task Lifecycle

### 5.1 Primary states

`RECEIVED → INTERPRETING → READY → PLANNING → AUTHORIZING → EXECUTING → VERIFYING → COMPLETED`

Not every Task requires a visible or separately persisted stay in every state, but every material transition must satisfy the corresponding invariant.

| State | Meaning | Exit requirement |
|---|---|---|
| `RECEIVED` | Intent exists and is preserved | Intake integrity established |
| `INTERPRETING` | BRO is framing the real outcome | Goal, scope, constraints, and uncertainty are sufficient |
| `READY` | The Task is understood enough to plan or act | No unresolved blocker prevents planning |
| `PLANNING` | Execution route and controls are being formed | A viable plan revision exists |
| `AUTHORIZING` | Required policy, permission, or user approval is being resolved | Required authorization is granted or work is blocked/terminated |
| `EXECUTING` | Authorized work is progressing | Planned work reaches verification, replanning, blocking, or termination |
| `VERIFYING` | Claims, artifacts, effects, and completion criteria are checked | Evidence gate passes or work returns to execution/planning |
| `COMPLETED` | Required outcome exists and evidence gate passed | Terminal |

### 5.2 Control and exception states

| State | Meaning | Valid next directions |
|---|---|---|
| `BLOCKED` | Progress requires a real unresolved dependency | previous active path, `CANCELLED`, or `FAILED` |
| `PAUSED` | Progress intentionally stopped with resumable state | previous active path or `CANCELLED` |
| `RECOVERING` | BRO is reconciling interrupted or uncertain execution | `EXECUTING`, `VERIFYING`, `BLOCKED`, or `FAILED` |
| `FAILED` | The outcome was not achieved and no valid automatic recovery remains | terminal, or a new explicitly authorized recovery Task |
| `CANCELLED` | Authorized cancellation ended the Task | terminal |

### 5.3 Transition invariants

- No transition occurs without an actor, reason, time, and prior state.
- Terminal states are never rewritten; corrections append events or create a new Task/recovery relation.
- `COMPLETED` requires satisfied completion criteria and sufficient Evidence.
- `FAILED` must distinguish no effect, partial effect, confirmed effect, and unknown effect.
- `BLOCKED` must not be used to hide avoidable internal indecision.
- `PAUSED` requires a resume checkpoint.
- `RECOVERING` must reconcile durable state with actual external state before retrying.
- Replanning preserves earlier Plan revisions and causal history.

---

## 6. Step and Action Lifecycles

### 6.1 Step states

`PENDING → READY → ACTIVE → CHECKING → SUCCEEDED`

Exception states:

`BLOCKED`, `PAUSED`, `FAILED`, `SKIPPED`, `CANCELLED`

`SKIPPED` is valid only when the Plan revision explicitly makes the Step unnecessary and preserves why.

### 6.2 Action states

`PROPOSED → AUTHORIZED → DISPATCHED → RESULT_RECEIVED → EFFECT_RECONCILED → VERIFIED`

Exception states:

`DENIED`, `FAILED`, `TIMED_OUT`, `EFFECT_UNKNOWN`, `CANCELLED`

Critical rules:

- Timeout does not prove that an external side effect did not occur.
- Retry is forbidden while a material side effect remains `EFFECT_UNKNOWN` unless the interface has a valid idempotency guarantee or reconciliation proves safety.
- Tool success output is not sufficient verification when material external state can be inspected directly.
- Every retry is a new Action Attempt linked to the same Action Request or its revision.

---

## 7. Organ Contracts

### 7.1 SELF

**Receives:** governed identity updates and versioned evolution proposals.  
**Produces:** identity profile reference, behavioral invariants, visual/voice baseline references.  
**Owns:** BRO identity continuity.  
**Must not:** own user/project facts, execute tools, or rewrite evidence.  
**Protected by:** IMMUNE SYSTEM change and integrity gates.

### 7.2 HEART

**Receives:** authorized relationship foundation and interaction context.  
**Produces:** relational stance constraints and behavior guidance.  
**Owns:** relationship policy and long-horizon stance.  
**Must not:** manufacture feelings, override evidence, or leak private foundation material.  
**Protected by:** privacy, isolation, and non-deception controls.

### 7.3 MIND

**Receives:** Intent, Context Manifest, Observations, capability state, policy decisions, results, and Evidence.  
**Produces:** Goal, Decision, Plan, replan, interpretation, synthesis, and reflection.  
**Owns:** judgment and meaning.  
**Must not:** claim perception or execution that did not occur, bypass authority, or delegate final judgment.

### 7.4 PERCEPTION

**Receives:** authorized source and inspection requests.  
**Produces:** Observations with provenance, freshness, and limitations.  
**Owns:** contact with current reality.  
**Must not:** silently convert observations into decisions or durable memory.

### 7.5 MEMORY

**Receives:** retrieval queries, governed storage candidates, promotion proposals, corrections, and quarantine decisions.  
**Produces:** scoped memory references, conflicts, freshness signals, and source-of-truth pointers.  
**Owns:** durable continuity classes and their isolation.  
**Must not:** overwrite current reality, cross boundaries silently, or treat every interaction as durable.

### 7.6 SKILLS & KNOWLEDGE

**Receives:** capability discovery, evaluation, versioning, creation, and retirement requests.  
**Produces:** Capability records, skill contracts, quality state, and compatible execution options.  
**Owns:** definitions of what BRO can reliably know or do.  
**Must not:** infer capability from availability alone or expose roster complexity as BRO's identity.

### 7.7 NERVOUS SYSTEM

**Receives:** Goal, Plan, Context Manifest requirements, runtime events, interrupts, capability options, and execution results.  
**Produces:** Task progression, routing, scheduling, assignments, context assembly, and continuation decisions.  
**Owns:** coordination and runtime progression.  
**Must not:** replace judgment, weaken boundaries for convenience, or mark completion without the evidence gate.

### 7.8 HANDS

**Receives:** authorized Action Requests and required scoped context.  
**Produces:** Action Attempts, actual results, artifacts, errors, and side-effect status.  
**Owns:** execution truth.  
**Must not:** act outside authorization, expose secrets, or report proposed work as performed work.

### 7.9 FEET

**Receives:** active route, dependencies, current execution position, interrupts, and blockers.  
**Produces:** navigation events, continuation, resume checkpoints, and route-change requests.  
**Owns:** movement through work and environments.  
**Must not:** continue through invalid authority, unresolved material risk, or a terminal state.

### 7.10 VOICE

**Receives:** BRO's synthesized judgment, actual execution state, evidence state, uncertainty, and communication context.  
**Produces:** coherent user-facing communication.  
**Owns:** expression, not underlying truth.  
**Must not:** invent certainty, conceal material failure, impersonate specialists, or expose internal fragmentation without value.

### 7.11 IMMUNE SYSTEM

**Receives:** proposed transitions, Action Requests, context boundaries, claims, Evidence, promotion requests, and policy conflicts.  
**Produces:** allow, deny, require-approval, quarantine, insufficient-evidence, and verified decisions.  
**Owns:** trust, authority, integrity, isolation, and completion gates.  
**Must not:** become arbitrary hidden bureaucracy; controls must correspond to real authority, risk, or integrity requirements.

---

## 8. Runtime Control Loop

The canonical runtime is a re-entrant control loop:

1. **Receive** — preserve the Intent and environment.
2. **Activate continuity** — load only required SELF and HEART references.
3. **Interpret** — form or revise the Goal.
4. **Detect context needs** — identify what must be known, inspected, or retrieved.
5. **Perceive and retrieve** — collect current Observations and governed Memory.
6. **Assemble context** — produce a scoped Context Manifest.
7. **Frame and decide** — MIND determines the real problem and route.
8. **Discover capabilities** — identify direct, skill, specialist, model, and tool options.
9. **Plan** — create a versioned Plan with dependencies and checks.
10. **Authorize** — resolve policies, permissions, approvals, and risk gates.
11. **Execute and navigate** — HANDS act; FEET continue; NERVOUS SYSTEM coordinates.
12. **Observe results** — record actual effects, errors, artifacts, and new facts.
13. **Reconcile** — compare expected state, recorded state, and actual external state.
14. **Verify** — evaluate Evidence against claims and completion criteria.
15. **Re-enter if needed** — perceive more, reframe, replan, recover, or continue.
16. **Synthesize and communicate** — VOICE reports as one BRO.
17. **Persist selectively** — store only governed durable state and learning.

The loop terminates only in `COMPLETED`, `FAILED`, or `CANCELLED`, or remains honestly resumable in `BLOCKED` or `PAUSED`.

---

## 9. Direct Work, Skill Use, Specialist Use, and Capability Creation

BRO chooses the smallest reliable execution structure.

### Direct work is preferred when

- the task is within active reliable capability;
- context fits coherently;
- separate delegation adds no quality, speed, isolation, or control value;
- BRO can execute and verify directly.

### A skill is loaded when

- a repeatable method or protocol materially improves reliability;
- specialized instructions, templates, or evaluation rules apply;
- the skill remains compatible with active authority and context boundaries.

### A specialist is assigned when

- independent focused reasoning or execution adds material value;
- parallel work reduces latency without creating unsafe conflicts;
- context or permission isolation is beneficial;
- a capability contract can bound the assignment and output.

### A new capability is created when

- the required outcome class is not reliably supported;
- creation is authorized and economically justified;
- the capability can be tested and versioned;
- temporary improvisation would create unacceptable quality or control risk.

### Routing invariant

The user requests an outcome from BRO. The user does not need to select the internal mechanism unless that choice materially affects cost, risk, commitment, privacy, or outcome.

---

## 10. State Ownership

| State class | Canonical owner | Notes |
|---|---|---|
| Product identity | SELF | Versioned; highly controlled |
| Relationship foundation | HEART | Private; behavior context, not casual content |
| Interpretation and decisions | MIND | Rationale and uncertainty preserved when material |
| Current observations | PERCEPTION | Time-bound and source-bound |
| Durable continuity | MEMORY | Scoped, governed, correctable, quarantinable |
| Capability truth | SKILLS & KNOWLEDGE | Availability is not proof of quality |
| Task runtime state | NERVOUS SYSTEM | Durable for material multi-step work |
| Execution attempts/results | HANDS | Append-only attempt history |
| Navigation/resume state | FEET | Must identify current position and next valid route |
| User-facing expression | VOICE | Derived output, not canonical task truth |
| Authority/evidence decisions | IMMUNE SYSTEM | Scope-bound and auditable |
| Project facts | Project source-of-truth | MEMORY stores references/context, not competing copies |
| Artifacts | Work/Project domain | Provenance links back to Task and actions |

---

## 11. Persistence and Recovery

### 11.1 Durable minimum

Material multi-step Tasks must persist enough state to reconstruct:

- what outcome was authorized;
- what BRO understood;
- which context and policy versions were used;
- what plan revision was active;
- what was attempted and what actually happened;
- which external effects are confirmed or uncertain;
- what evidence exists;
- why execution stopped;
- what transition is valid next.

### 11.2 Recovery sequence

After interruption, crash, timeout, or lost connection:

1. load the last durable Task state;
2. validate integrity and active authority;
3. inspect external reality for in-flight or uncertain effects;
4. reconcile recorded state with observed state;
5. invalidate stale context or approvals where necessary;
6. resume, replan, block, fail, or request required approval;
7. record the recovery Decision and Evidence.

### 11.3 No blind replay

BRO must not blindly replay the last command. Recovery operates on intended effect and reconciled reality, not command repetition.

---

## 12. Concurrency and Interruption

- Parallel Steps require explicit dependency independence.
- Concurrent actions against shared mutable state require a conflict-control strategy.
- One Step must not silently invalidate another Step's assumptions.
- Context and Plan revisions are versioned; work reports the revision it used.
- User interruption is a first-class Runtime Event.
- A new user message may add scope, replace scope, pause, cancel, correct, or ask for status; MIND determines the meaning from context and records material change.
- Cancellation is cooperative until external effects are reconciled.
- Partial parallel success is preserved and reported; it is never flattened into total success or total failure.

---

## 13. Authority and Approval Boundary

Phase C will define the complete authority model. Phase B establishes these interface requirements:

- every material Action Request carries an authority basis;
- authority is evaluated against actor, target, scope, risk, and time;
- permission to inspect does not imply permission to modify;
- permission for one target does not imply permission for another;
- approval is not required for routine reversible work when existing authority is sufficient;
- material irreversible, externally committing, privacy-sensitive, or scope-expanding work may require explicit approval;
- denial, revocation, or expiry becomes runtime state and cannot be bypassed by routing to another tool or specialist;
- conflicting authorities must be resolved by an explicit hierarchy, not convenience.

---

## 14. Evidence and Completion

### 14.1 Evidence proportionality

Verification depth follows:

- consequence of error;
- reversibility;
- uncertainty;
- security, privacy, financial, legal, or operational impact;
- availability and quality of direct evidence.

### 14.2 Completion gate

A Task may enter `COMPLETED` only when:

1. the Goal's required outcome exists;
2. mandatory scope is satisfied;
3. material side effects are reconciled;
4. required artifacts exist and are usable;
5. completion criteria have Evidence;
6. required checks passed;
7. no unresolved blocker invalidates the outcome;
8. partial or excluded scope is explicitly represented;
9. communication reflects actual state.

### 14.3 Claim states

Material claims should be representable as:

- `CONFIRMED` — supported by sufficient current evidence;
- `DERIVED` — logically concluded from confirmed premises;
- `UNVERIFIED` — plausible but not established;
- `UNKNOWN` — insufficient information exists;
- `CONFLICTED` — credible sources or states materially disagree.

---

## 15. Security, Privacy, and Isolation

- Context is least-privilege: load only what the Task materially needs.
- Specialists and tools receive scoped context, authority, and secrets.
- Secrets are referenced through authorized mechanisms and excluded from ordinary logs, memory, artifacts, and messages.
- Private relationship context influences behavior but is not casually surfaced.
- Project and work boundaries are enforced during retrieval, delegation, execution, and persistence.
- Cross-boundary learning requires governed abstraction or promotion; raw private context is not promoted.
- Untrusted content is data, not authority or executable instruction.
- Tool and source output may be malformed, adversarial, stale, partial, or wrong and must be treated accordingly.

---

## 16. Observability and Audit

The architecture must make it possible to answer:

- What did BRO understand?
- Which context, source, capability, model, policy, and tool versions mattered?
- What decision was made and why?
- What was authorized, denied, or approved?
- What action was attempted?
- What actually happened?
- What changed externally?
- What evidence supports the result?
- Why is the Task completed, blocked, failed, paused, or cancelled?
- What is the next valid step?

Observability must preserve traceability without exposing private reasoning, unnecessary private context, or secrets.

---

## 17. Cost, Latency, and Resource Control

Quality and truth remain primary, but runtime resources are governed.

- Context assembly avoids loading irrelevant history.
- Capability routing considers reliability, cost, latency, privacy, and availability.
- Parallelism is used only when dependency and conflict rules allow it.
- Expensive verification is proportional to risk and decision value.
- Budgets may constrain routes but must not silently lower required correctness.
- If a budget prevents a reliable outcome, BRO reports the real constraint rather than simulating completion.
- Model/provider selection is an internal routing decision unless it materially changes user cost, privacy, commitment, or outcome.

---

## 18. Versioning and Compatibility

The following require explicit versions where applicable:

- SELF and HEART definitions;
- Constitution and policies;
- Context Manifest schema;
- Runtime Events;
- Task/Plan state models;
- capabilities and skills;
- specialist and tool contracts;
- evidence requirements;
- artifacts and schemas;
- model/provider adapters.

Historical Task records preserve the versions that governed them. Upgrades must define compatibility, migration, rollback, or quarantine behavior.

---

## 19. Reference Scenario

User request: **“Inspect the current repository, fix the failing authentication tests, and update the technical documentation.”**

The architecture must represent the following without ambiguity:

1. Intent preserves the original request.
2. MIND forms a Goal containing repository inspection, root-cause fix, test verification, and documentation update.
3. PERCEPTION inspects the authorized current repository, instructions, status, code, and test output.
4. NERVOUS SYSTEM assembles a Context Manifest and creates the Task.
5. MIND forms a Plan with inspection, reproduction, diagnosis, implementation, targeted tests, broader regression checks, and documentation validation.
6. IMMUNE SYSTEM confirms read/write/test authority and protects unrelated user changes.
7. HANDS performs versioned Action Attempts; each actual result is recorded.
8. A failed test returns the runtime to diagnosis or replanning rather than allowing completion.
9. FEET continues through required steps without unnecessary user handback.
10. Evidence links the code change, test results, and documentation checks to completion criteria.
11. VOICE reports the actual completed, partial, failed, or blocked state as one BRO.
12. MEMORY stores only governed decisions, evidence, learning, and source-of-truth pointers that deserve durability.

This scenario is not an implementation test by itself. It is the minimum end-to-end trace that every later design must continue to support.

---

## 20. Phase B Acceptance Gates

Phase B is accepted only if all gates pass.

### Gate B1 — Primitive completeness

Every material runtime fact in the reference scenario maps to one canonical primitive without requiring an undefined generic state bucket.

### Gate B2 — Ownership integrity

Every primitive and durable state class has exactly one canonical owner. No shared, joint, or split ownership exists. Participation by another organ is represented only as contribution, execution, verification, control, consumption, or custody.

### Gate B3 — Lifecycle validity

Task, Step, and Action transitions represent success, blocking, pause, interruption, cancellation, partial effect, uncertain effect, failure, recovery, and verified completion.

### Gate B4 — Judgment integrity

Specialists, tools, models, memory, and policies may inform or constrain BRO, but none silently replaces BRO's final judgment and synthesis responsibility.

### Gate B5 — Authority integrity

No action or guarded transition can occur without a representable authority basis, and approval scope cannot be generalized silently.

### Gate B6 — Evidence integrity

`COMPLETED` cannot be reached without mapping completion criteria to sufficient Evidence.

### Gate B7 — Recovery integrity

A material interrupted Task can resume from durable state without blind replay or pretending uncertain side effects did not occur.

### Gate B8 — Isolation integrity

Context retrieval, specialist assignment, execution, and persistence all preserve private, user, project, and work boundaries.

### Gate B9 — Provider independence

No logical primitive or invariant requires a specific model, tool vendor, database, framework, or deployment topology.

### Gate B10 — Human-shaped coherence

The logical architecture remains recognizably one BRO while avoiding deceptive human claims and avoiding a mechanical one-organ-to-one-service mapping.

### Gate B11 — End-to-end trace

At least one realistic multi-step request can be traced from Intent through execution, recovery paths, Evidence, and final communication with no undefined ownership or transition.

### Gate B12 — No premature implementation lock-in

Repository and deployment choices remain derivable from requirements rather than embedded as assumptions in the logical model.

---

## 21. Decisions Deferred to Later Phases

This baseline intentionally defers:

- complete Constitution and authority hierarchy — Phase C;
- SELF and HEART schemas and change governance — Phase D;
- detailed cognition and planning model — Phase E;
- source adapters and perception trust model — Phase F;
- memory schemas, retention, isolation, and promotion — Phase G;
- capability registry and contracts — Phase H;
- orchestration scheduling and specialist runtime — Phase I;
- execution adapter contracts — Phase J;
- navigation and continuation engine — Phase K;
- communication model — Phase L;
- evidence, security, permissions, and policy engine — Phase M;
- Project BRO inheritance and isolation — Phase N;
- context assembly algorithms and budgets — Phase O;
- migration from the current repository — Phase P;
- implementation roadmap and release gates — Phase Q.

Deferral does not make these optional. It prevents Phase B from inventing detail before its canonical owner is designed.

---

## 22. Phase B Decision

BRO's logical runtime is a **durable, re-entrant, evidence-governed task system** wrapped by one persistent identity.

BRO receives intent, constructs an explicit goal, assembles scoped current context, exercises his own judgment, chooses and coordinates capabilities, acts only within authority, navigates multi-step work, reconciles actual effects, verifies completion, communicates as one BRO, and preserves only governed continuity.

The core unit of execution is the **Task**.  
The core unit of truth from the world is the **Observation**.  
The core unit of judgment is the **Decision**.  
The core unit of change is the **Action Attempt**.  
The core unit of proof is the **Evidence**.  
The core unit of runtime history is the **Runtime Event**.

No framework, model, tool, specialist, or deployment shape is BRO. They are replaceable implementation mechanisms beneath this logical architecture.

> **BRO remains one. Work becomes explicit. Authority becomes enforceable. Execution becomes recoverable. Completion becomes provable.**
