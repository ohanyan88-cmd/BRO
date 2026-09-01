# BRO — Current Repository Compatibility Map v0.1

**Status:** DONOR COMPATIBILITY BASELINE — decision record, not code-port authorization  
**Product:** BRO  
**Current repository:** `menqstudio/OS`  
**Audited baseline:** `main@87bfe7359cf2142eda5ec57a0a070d3d24edbde9`  
**Target implementation repository:** `ohanyan88-cmd/BRO`  
**Target references:** `BRO_ARCHITECTURE_FOUNDATION_V0_2.md`, `BRO_LOGICAL_ARCHITECTURE_V0_1.md`  
**Purpose:** Select proven work for a new BRO repository while preventing legacy abstractions from becoming the new architecture by accident

---

## 1. Decision

The current `menqstudio/OS` repository is a **read-only donor repository** for BRO. The target BRO is implemented only in `ohanyan88-cmd/BRO`. OS is not rewritten in place, mechanically renamed, or accepted wholesale as the target architecture.

The selective-port strategy is:

> **Preserve proven mechanisms. Replace incorrect ownership. Unify competing models. Add the missing BRO organs. Retire legacy paths only after verified parity.**

The donor repository already contains a substantial governance, execution, evidence, recovery, specialist, desktop, and testing system. Selected proven parts may be ported into the new BRO repository as implementation mechanisms beneath BRO's organ boundaries.

The donor repository does not implement the complete target BRO because persistent SELF, HEART, MIND, layered MEMORY, unified PERCEPTION, and one canonical runtime model are incomplete or absent.

---

## 2. Baseline Evidence

The audited Git tree contains:

| Surface | Observed baseline |
|---|---:|
| Total tracked files | 1,351 |
| Python files | 282 |
| Rust files | 110 |
| TypeScript + TSX files | 200 |
| JSON files | 83 |
| SQL files | 28 |
| Test-like files | 264 |
| Engine runtime modules | 53 |
| Engine test files | 95 |
| Desktop frontend files | 204 |
| Desktop Rust core files | 67 |
| Generated specialist definitions | 262 |
| Repository workflow files | 8 |

The audited head was protected and its observed GitHub workflow runs were green for CI, supply chain, AI surface, design gates, accessibility, performance budget, and computed style.

This evidence establishes that the repository is a serious reusable system. It does not establish that every declared design is shipped, reachable, independently audited, or compatible with the target architecture.

---

## 3. Classification Vocabulary

### ADOPT

Preserve the mechanism and its tests substantially as-is. Namespace, interfaces, documentation, or packaging may still change.

### ADAPT

Preserve the proven behavior and significant implementation, but change contracts, ownership boundaries, state model, or integration points.

### REBUILD

The required target responsibility is absent or the current abstraction is structurally incompatible. Existing lessons and tests may inform a new implementation, but the current component is not the target core.

### RETIRE

Remove after a named replacement reaches verified parity. Retirement is never immediate merely because the design changed.

### QUARANTINE

Keep outside the active target architecture until authority, security, provenance, correctness, or product value is resolved. Quarantined code is not deleted and is not treated as production capability.

---

## 4. Ownership Rule

Every canonical BRO concern has exactly one canonical BRO organ owner. Project-governance artifacts outside BRO's runtime also have exactly one explicitly named project owner.

Other organs may contribute, execute, verify, control, consume, or hold custody. None becomes a co-owner.

Physical location does not determine ownership:

- a Python file is not automatically MIND;
- a database table is not automatically MEMORY;
- a security check used by HANDS remains owned by IMMUNE SYSTEM if it defines an authorization or integrity decision;
- a UI screen displaying Task state remains a VOICE consumer, not owner of Task state;
- a coordinator calling a specialist remains NERVOUS SYSTEM, not SKILLS & KNOWLEDGE;
- a tool producing evidence remains HANDS or PERCEPTION, while the Evidence record and sufficiency decision remain IMMUNE SYSTEM.

When one legacy module mixes multiple target concerns, the module is classified `ADAPT` and must be decomposed by responsibility before becoming canonical.

---

## 5. Executive Compatibility Summary

| Target owner | Current maturity | Reuse outlook | Primary decision |
|---|---|---:|---|
| SELF | Low | 10–20% | REBUILD canonical SELF; reuse brand and identity lessons |
| HEART | Very low | 5–15% | REBUILD governed relationship stance |
| MIND | Low–medium | 15–30% | REBUILD cognition core; adapt conductor/orchestration inputs |
| PERCEPTION | Medium | 30–50% | ADAPT source and tool observations into one contract |
| MEMORY | Low–medium | 25–40% | REBUILD layered governance; adapt stores and UI |
| SKILLS & KNOWLEDGE | High but fragmented | 75–90% | ADAPT registries and generated specialists |
| NERVOUS SYSTEM | High | 60–75% | ADAPT durable orchestration to canonical Task/Event model |
| HANDS | High | 60–75% | ADOPT controls; adapt execution adapters and reachability |
| FEET | Medium | 40–60% | ADAPT recovery/checkpoint; add navigation and continuation |
| VOICE | Medium–high | 40–60% | ADAPT cockpit/chat under one BRO expression policy |
| IMMUNE SYSTEM | Very high | 80–90% | ADOPT the security/evidence spine with targeted hardening |

**Derived repository-level preservation estimate:** approximately 60–70% of accumulated engineering value survives through direct adoption or controlled adaptation. This is an architecture-fit range, not a line-of-code measurement.

---

## 6. SELF Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| `engine/runtime/bro_identity.py` | ADAPT | Stable specialist identity derivation and validation | Rename responsibility to specialist identity; it must not become BRO SELF | Specialist identity tests remain green under new contract |
| `engine/schemas/agent-profile.schema.json` | ADAPT | Agent profile validation | Keep as specialist schema; remove any implied ownership of BRO identity | Schema explicitly identifies specialist scope |
| `engine/agents/` and `.claude/agents/` identity fields | ADAPT | Deterministic agent IDs and provenance | Keep internal; never expose as competing BRO identities | Generated definitions trace to capability registry |
| Desktop product/brand assets | ADOPT | Existing visual product work | Bind to versioned SELF visual identity later | Brand artifact integrity and UI regression gates pass |
| Canonical BRO SELF schema | REBUILD | Current lessons only | Create immutable identity core, versioned evolution, change authority, and provider independence | Phase D acceptance gates |

**SELF owner decision:** SELF owns BRO identity. Specialist identities remain owned by SKILLS & KNOWLEDGE, not SELF.

---

## 7. HEART Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| Existing persona/conductor prose across docs | QUARANTINE | Historical intent and tone clues | Extract only confirmed behavioral principles; reject prompt folklore and duplicates | Reviewed provenance ledger |
| UI preferences and user-facing settings | ADAPT | Existing preference capture surfaces | Separate stable user preference from private relationship foundation | Isolation tests |
| Canonical HEART state and policy | REBUILD | None is canonical today | Define relationship stance, privacy, non-deception, change authority, and behavior-only use | Phase D acceptance gates |

**HEART owner decision:** HEART owns relationship stance. MEMORY may store governed HEART records as custodian but does not own their meaning.

---

## 8. MIND Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| Conductor behavior described in `README.md` and engine policies | ADAPT | Interpretation→delegation intent | Replace prose-only behavior with canonical Intent, Goal, Decision, and Plan contracts | End-to-end Goal/Decision trace |
| `engine/runtime/bro_orchestration.py` | ADAPT | Routing and orchestration inputs | Remove any embedded final-judgment ownership; MIND emits decisions, NERVOUS SYSTEM routes | Contract tests separate Decision from Assignment |
| Planning fields in task contracts and desktop Runs | ADAPT | Existing plan representation and UI | Map to one versioned Plan primitive | Replan preserves causal history |
| Provider/model selection logic in desktop `ai.rs` | ADAPT | Working provider invocation experience | Move routing policy beneath MIND/Nervous contracts; provider must remain replaceable | Provider substitution tests |
| Canonical Intent→Goal→Decision→Plan cognition runtime | REBUILD | Existing failure lessons | Implement explicit framing, uncertainty, alternatives, re-entry, reflection, and judgment ownership | Phase E acceptance gates |

**MIND owner decision:** MIND owns Goal, Decision, and Plan. It does not own Task lifecycle, execution attempts, observations, evidence, or approvals.

---

## 9. PERCEPTION Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| Desktop file/research/integration access surfaces | ADAPT | Existing source access and UI | Emit canonical Observation with source, time, freshness, scope, and limitations | Observation provenance tests |
| Bridge read operations | ADAPT | Controlled cross-runtime reads | Make read result a typed Observation, not untyped context | Contract and failure tests |
| Repository/status inspection tools | ADOPT | Strong current-state verification practice | Wrap results in Observation contract | Tool result provenance retained |
| Web/API/integration adapters | ADAPT | Existing connector models | Add trust classification, freshness, untrusted-content handling, and authority scope | Phase F source-adapter gates |
| Canonical Observation registry/model | REBUILD | Current result shapes as inputs | Unify perception outputs without centralizing every source implementation | Phase F acceptance gates |

**PERCEPTION owner decision:** PERCEPTION owns Intent intake records and Observations. MIND consumes and interprets them.

---

## 10. MEMORY Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| Desktop `memory` repository/table/UI | ADAPT | CRUD, pinning, scope UI, audit integration | Replace generic scope with governed memory classes, authority, freshness, sensitivity, retention, and quarantine | Memory-class migration tests |
| Knowledge notes and library items | ADAPT | Existing knowledge surfaces | Separate knowledge artifacts from durable personal/project memory | Cross-class isolation tests |
| Runtime JSON/state stores | ADAPT | Durable execution history | Classify as Task/Work state, not general MEMORY | No runtime state retrieved as user memory |
| Evidence store and audit ledger | RETIRE from MEMORY classification | Durable records remain valuable | Keep them under IMMUNE SYSTEM; MEMORY stores references only | Ownership validation gate |
| Project/source-of-truth documents | ADAPT | Strong current-source discipline | MEMORY stores pointers and context; project domain remains fact owner | Contradiction tests |
| Layered Memory model | REBUILD | Existing stores and lessons | Implement Self, Relationship, User, Project, Work, Decision, Evidence-reference, Failure/Learning, Working, and Quarantine classes | Phase G acceptance gates |

**MEMORY owner decision:** MEMORY owns governed continuity records and memory-class lifecycle. It does not own external/project facts, Evidence, Task state, or BRO identity.

---

## 11. SKILLS & KNOWLEDGE Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| `engine/skills/` | ADOPT→ADAPT | Large domain skill corpus | Normalize metadata, inputs, outputs, prerequisites, limitations, quality, and version | Capability contract validation |
| `engine/skills/index.json` | ADAPT | Central skill discovery | Replace roster-centric fields with canonical Skill/Capability separation | Registry has no duplicate canonical IDs |
| `engine/orchestration/registry.json` | ADAPT | Specialist routing registry | Move specialist definitions beneath Capability contracts | Assignment resolves through capability |
| `.claude/agents/` generated definitions | ADAPT | 262 reusable specialist configurations | Treat as provider-specific compiled artifacts, not source-of-truth | Regeneration is deterministic |
| `tools/generate_agent_definitions.py` | ADOPT | Generated-artifact discipline | Change input to canonical capability/specialist registry | Check mode remains green |
| `bro_skill_evolution.py` and proposal schema | ADAPT | Controlled skill evolution groundwork | Add evidence-backed promotion, rollback, owner and version gates | No self-promotion without policy gate |
| Capability quality/evidence state | REBUILD around current registries | Existing test evidence | Make capability truth explicit and provider-independent | Phase H acceptance gates |

**SKILLS & KNOWLEDGE owner decision:** SKILLS & KNOWLEDGE owns Knowledge, Skill, Capability, and Specialist definitions. NERVOUS SYSTEM owns assignments and runtime coordination.

---

## 12. NERVOUS SYSTEM Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| `engine/runtime/bro_orchestration_runtime.py` | ADAPT | Durable task creation, claim, lease, checkpoint, retry, cancel, recover, verify, complete | Map records and transitions to canonical Task, Step, Runtime Event, Blocker, and Context Manifest | Full transition matrix passes |
| `engine/runtime/bro_orchestration_runtime_v1.py` | RETIRE | Historical compatibility evidence | Preserve fixtures only; remove active canonical status after parity | No production call sites |
| `engine/runtime/bro_orchestration.py` | ADAPT | Assignment and routing behavior | Consume MIND Decision/Plan and Capability records | Routing never creates final Decision |
| Desktop Run/RunStep orchestration in Rust core | ADAPT | Working local scheduling and abandoned-run reconciliation | Become projection/adapter of canonical Task runtime, not second owner | Bidirectional parity test |
| Bridge governed-turn submit/result flow | ADAPT | Cross-runtime dispatch and return | Emit canonical events and Action references | Exactly-once correlation tests |
| Root coordination hooks and state documents | RETIRE from runtime authority | Useful development workflow | Keep as repository process, not BRO runtime state | Runtime has no dependency on chat handoff docs |
| Canonical Context Manifest assembly | REBUILD | Existing context fields as inputs | Add authority, scope, freshness, sensitivity, inclusion reason, and version | Context isolation gates |

**NERVOUS SYSTEM owner decision:** NERVOUS SYSTEM owns Task, Step, Specialist Assignment, Context Manifest, Runtime Event, Blocker, and their lifecycle state.

---

## 13. HANDS Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| Bridge sidecar and engine adapter | ADAPT | Existing execution dispatch boundary | Convert op-specific payloads to versioned Action Request/Attempt contracts | Contract compatibility tests |
| Desktop Tauri commands | ADAPT | Broad working execution surface | Separate UI command from canonical action; all material effects pass authority and attempt recording | Reachability and audit gates |
| Rust broker/executor/launcher/proof crates | ADOPT→ADAPT | Strong contained-execution and proof work | Preserve enforcement; complete production reachability and platform contracts | Independent code audit + platform tests |
| `bro_security.enforce_scope` and command analysis | ADOPT | Proven scope and command controls | Keep under IMMUNE SYSTEM ownership; HANDS consumes decision | Negative tests remain green |
| Execution lease reservation/finalization | ADOPT | Single-use execution discipline | Bind directly to Action Attempt and Task/Step IDs | Replay and uncertain-effect tests |
| Governed staging upload/output stream modules | ADOPT→ADAPT | Strong controlled artifact/output pipeline | Map outputs to Artifact records and canonical custody | Artifact integrity gates |
| Legacy direct/ordinary chat provider path | QUARANTINE | Useful fallback behavior | Must not masquerade as governed execution; later decide controlled fallback policy | Explicit trust-state UI and audit |
| Placeholder or unreachable production execution paths | QUARANTINE | Test and design evidence | Do not advertise as capability until reachable and independently verified | Reachability + independent audit |

**HANDS owner decision:** HANDS owns Action Request, Action Attempt, Artifact runtime record, and execution truth. IMMUNE SYSTEM controls authorization and evidence gates.

---

## 14. FEET Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| `engine/runtime/bro_recovery.py` | ADOPT→ADAPT | Prepare/settle/recovery-proof discipline | Bind recovery to canonical Action Attempt effect state | No-blind-replay tests |
| Orchestration checkpoint/retry/recover functions | ADAPT | Durable continuation | Add resume position, route revision, dependency traversal, and interruption semantics | Crash/resume scenarios |
| Rust abandoned-execution reconciliation | ADOPT→ADAPT | Actual-session reconciliation | Integrate with canonical recovery events | External-state reconciliation tests |
| Desktop navigation and workflow surfaces | ADAPT | User-visible movement | Separate presentation navigation from runtime continuation | UI cannot advance invalid state |
| Cross-system navigation engine | REBUILD | Existing adapters as inputs | Add environment location, route, return point, unresolved-work queue, and re-entry | Phase K acceptance gates |

**FEET owner decision:** FEET owns movement position, route, continuation, and resume checkpoint. NERVOUS SYSTEM owns Task lifecycle and schedules movement.

---

## 15. VOICE Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| React conversation UI | ADOPT→ADAPT | Mature user-facing chat surface | Bind to one BRO response envelope and explicit execution/evidence state | Conversation regression tests |
| Trust badges and refusal messages | ADOPT | Honest trust-state communication | Normalize states against canonical claim/evidence model | No false-green UI tests |
| Provider-specific response handling | ADAPT | Working stream and message plumbing | Hide internal provider/specialist fragmentation unless materially useful | Provider substitution tests |
| User guides/operator messages | ADAPT | Large documentation investment | Regenerate from target truth; quarantine stale claims | Documentation-claim gates |
| Canonical BRO Voice policy | REBUILD | Existing UX/tone lessons | Define language, style, uncertainty, disagreement, execution reporting, and specialist synthesis | Phase L acceptance gates |

**VOICE owner decision:** VOICE owns user-facing expression. It never owns the Task, Decision, Evidence, or execution result it communicates.

---

## 16. IMMUNE SYSTEM Compatibility Map

| Current surface | Class | Preserved value | Required target change | Gate |
|---|---|---|---|---|
| `bro_authority.py` | ADOPT→ADAPT | Role authority and risk ceilings | Expand from specialist roles to complete authority hierarchy in Phase C | Authority matrix tests |
| `bro_authorization.py` | ADOPT | Action classification | Map result to canonical control decision | Unknown action fails closed |
| `bro_execution_lease.py` | ADOPT | Signed/scoped/single-use execution authorization | Bind to canonical action and authority basis | Replay, expiry, scope tests |
| `bro_security.py` | ADOPT | Scope, command, nonce, and target enforcement | Preserve behavior; split only where ownership remains clear | Negative test suite |
| `bro_completion.py` | ADOPT→ADAPT | High-integrity completion gate | Replace legacy task shape with canonical Task/Goal criteria and Evidence references | No DONE without Evidence |
| `bro_evidence.py` and evidence schemas | ADOPT→ADAPT | Hash-chained evidence validation | Make canonical Evidence primitive explicit | Chain, rollback, freshness tests |
| `bro_audit_log.py` | ADOPT→ADAPT | Append/verify and custody work | Resolve shipped custody gaps before production claims | Independent tamper test |
| Challenge authority and key registry | ADOPT | Strong signing/authority foundation | Integrate into complete Phase C authority model | Key rotation/revocation tests |
| Governance policy and approval flows | ADOPT→ADAPT | Existing approval mechanics | Enforce scope-bound Approval primitive and revocation/expiry | Approval cannot generalize |
| Egress authorization | ADOPT→ADAPT | Destination-axis enforcement | Finish production transport without bypassing decision point | Egress negative tests |
| Negative matrix, conformance, reachability, claim gates | ADOPT | Excellent honesty/control infrastructure | Point gates at target architecture and remove stale legacy claims | Every target claim has a gate |
| Known unreviewed or shipped security gaps | QUARANTINE | Honest debt inventory | Keep fail-closed; close or owner-authorized defer before production | Named closure evidence |

**IMMUNE SYSTEM owner decision:** IMMUNE SYSTEM owns authority decisions, Approval, Evidence, claim state, integrity, isolation, security controls, and completion gates. It does not own Task progression or execution.

---

## 17. Cross-Cutting Repository Surfaces

| Surface | Canonical owner | Class | Decision |
|---|---|---|---|
| `contracts/task-contract.schema.json` | NERVOUS SYSTEM | ADAPT | Migrate to canonical Task/Step contracts |
| `contracts/evidence-event.schema.json` | IMMUNE SYSTEM | ADAPT | Migrate to canonical Evidence contract |
| `contracts/execution-lease.schema.json` | IMMUNE SYSTEM | ADOPT→ADAPT | Preserve enforcement and bind to canonical Action Request/Attempt |
| `contracts/mode-grant.schema.json` | IMMUNE SYSTEM | ADAPT | Integrate into the Phase C authority model |
| `contracts/verifier-receipt.schema.json` | IMMUNE SYSTEM | ADOPT→ADAPT | Preserve verification receipt behavior under canonical Evidence gates |
| `contracts/index.json` | IMMUNE SYSTEM | ADAPT | Own contract integrity and references, not the meaning of primitives owned elsewhere |
| `config/spec-conformance.json` | IMMUNE SYSTEM | ADOPT→ADAPT | Continue as verified conformance ledger against new architecture |
| `config/negative-matrix.json` | IMMUNE SYSTEM | ADOPT | Preserve honest implemented/blocked/unreviewed states |
| `tools/check_*.py` gates | IMMUNE SYSTEM | ADOPT→ADAPT | Preserve gates; update claims and paths as architecture migrates |
| `.github/workflows/` | IMMUNE SYSTEM | ADOPT | Preserve protected validation pipeline; add architecture gates |
| `apps/desktop/src-tauri/core` persistence mechanism | HANDS | ADAPT | HANDS owns persistence execution; stored records retain the single semantic owner defined by their canonical primitive |
| React UI projections | VOICE | ADAPT | UI consumes canonical records; it is never system-of-record for runtime truth |
| Repository handoff/state documents | Project governance | ADAPT | Keep development continuity separate from BRO runtime MEMORY |
| Archived docs/audits | Project governance | QUARANTINE | Preserve as evidence/history; exclude from current runtime truth |

---

## 18. Canonical Model Collisions Requiring Resolution

### 18.1 Task collision — highest priority

Current competing representations include:

- engine task contract;
- durable orchestration Task;
- desktop Rust Task;
- desktop Run;
- desktop RunStep;
- coordination documents used for repository work.

**Decision:** NERVOUS SYSTEM owns one canonical Task and Step model. Legacy models become adapters, projections, or retired records.

**No migration may create another Task model.**

### 18.2 Identity collision

Current agent IDs, pack roles, desktop users, operator/conductor identities, and future BRO SELF are different concerns.

**Decision:** SELF owns BRO identity. SKILLS & KNOWLEDGE owns specialist definitions. IMMUNE SYSTEM owns authenticated principals and authority decisions. These are linked but never merged into one overloaded identity table.

### 18.3 Evidence/audit/memory collision

Durability does not make all records MEMORY.

**Decision:** IMMUNE SYSTEM owns Evidence and audit integrity. NERVOUS SYSTEM owns runtime events. MEMORY owns governed continuity. Stores may share technology but not ownership.

### 18.4 Plan/run/action collision

A Plan is a judgment artifact. A Run is execution coordination. An Action Attempt is execution truth.

**Decision:** MIND owns Plan; NERVOUS SYSTEM owns Task/Step runtime; HANDS owns Action Request/Attempt.

### 18.5 Approval/decision collision

A Decision selects what BRO judges should happen. Approval authorizes a guarded scope.

**Decision:** MIND owns Decision. IMMUNE SYSTEM owns Approval. An approval never replaces BRO's judgment, and judgment never bypasses approval.

---

## 19. Selective Port and Implementation Order

### Wave 0 — Protect donor and target baselines

1. Pin the audited source head and preserve green workflow evidence.
2. Add the Foundation, Logical Architecture, and this Compatibility Map to the new target repository through a controlled branch/PR.
3. Add a gate that rejects any canonical primitive with zero or multiple owners.
4. Make no runtime behavior change.

### Wave 1 — Build canonical contracts in the new repository

1. Define versioned contracts for Intent, Goal, Task, Plan, Step, Context Manifest, Observation, Decision, Capability, Specialist Assignment, Action Request, Action Attempt, Artifact, Evidence, Approval, Runtime Event, and Blocker.
2. Assign exactly one schema owner per primitive.
3. Add donor compatibility adapters in the new repository without modifying OS.
4. Add contract parity and round-trip tests.

### Wave 2 — Port and unify runtime truth

1. Make the durable orchestration runtime the first implementation candidate for canonical Task progression.
2. Convert desktop Task/Run/RunStep into projections/adapters.
3. Bind execution leases and recovery records to canonical Action Attempts.
4. Bind completion to canonical Goal criteria and Evidence.

### Wave 3 — Preserve and reposition the security spine

1. Retain authority, leases, scope, evidence, receipts, audit, recovery, and fail-closed controls.
2. Map each control to IMMUNE SYSTEM-owned decisions.
3. Complete reachability and custody gaps without weakening refusal behavior.
4. Require independent verification before production trust claims.

### Wave 4 — Add missing BRO organs

1. Build SELF and HEART schemas and change governance.
2. Build canonical MIND runtime.
3. Build layered MEMORY with isolation and promotion.
4. Normalize PERCEPTION and Context Manifest assembly.
5. Expand FEET navigation/continuation and VOICE synthesis.

### Wave 5 — Retire target-repository compatibility paths

1. Prove behavioral and data parity.
2. Import any intentionally selected durable records through reversible import tooling.
3. Remove legacy call paths and duplicate schemas.
4. Preserve history and evidence.
5. Re-run all repository, architecture, security, and product gates.

---

## 20. Selective-Port Safety Rules

1. No big-bang copy or rewrite.
2. No mechanical organ-to-folder or organ-to-service mapping.
3. No donor deletion or mutation; no target compatibility-path deletion before verified parity and rollback.
4. No shared ownership.
5. No legacy model may remain silently canonical after its replacement is selected.
6. No renamed legacy abstraction is considered migrated without semantic parity.
7. No green test is discarded without mapping its protected behavior.
8. No production trust claim is upgraded by documentation alone.
9. No security refusal is removed before its replacement enforcement is reachable and verified.
10. No generated specialist file becomes source-of-truth.
11. No archived or historical document is loaded as current truth without authority/freshness resolution.
12. Every port records donor component and commit, target primitive, owner, compatibility class, provenance/license review, tests, data effect, rollback, and evidence.

---

## 21. Required Port Ledger Record

Every ported component must produce a ledger record with:

- source path and source commit;
- compatibility class;
- canonical target primitive or organ concern;
- exactly one owner;
- preserved behaviors;
- changed behaviors;
- rejected legacy assumptions;
- data/schema impact;
- authority/security impact;
- adapter or replacement path;
- tests retained, changed, and added;
- rollback method;
- verification evidence;
- current state: proposed, accepted, porting, parity, adopted, adapted, retired, or quarantined.

The ledger is the canonical answer to “what happened to the four months of work?”

---

## 22. Acceptance Gates

### CMR-1 — Complete inventory

Every active top-level runtime, desktop, bridge, contract, registry, gate, and workflow surface has a compatibility class.

### CMR-2 — Single ownership

Every mapped canonical concern has exactly one owner; no shared, joint, or split ownership appears.

### CMR-3 — Preservation trace

Every adopted or adapted component names the behavior and tests being preserved.

### CMR-4 — Replacement trace

Every rebuilt or retired component names its replacement, parity gate, and rollback path.

### CMR-5 — Security non-regression

No existing fail-closed or evidence requirement is weakened by migration.

### CMR-6 — Canonical model convergence

Task, identity, evidence, memory, plan/action, and approval/decision collisions have one resolved target model each.

### CMR-7 — Reachability truth

Designed, tested, wired, shipped, and production-reachable states remain distinct.

### CMR-8 — Data safety

Any selected donor records have a versioned import and rollback strategy before target schema retirement.

### CMR-9 — Provider independence

Provider-specific agent definitions, prompts, or adapters do not own canonical BRO behavior.

### CMR-10 — Repository continuity

The existing protected workflow and evidence system remains green or every intentional change is explicitly reviewed and evidenced.

---

## 23. Current Disposition

The current OS repository is **ACCEPTED AS A READ-ONLY DONOR SOURCE**.

`ohanyan88-cmd/BRO` is the **ONLY TARGET IMPLEMENTATION REPOSITORY AND PROJECT SOURCE-OF-TRUTH**.

It is **NOT ACCEPTED AS THE COMPLETE TARGET BRO ARCHITECTURE**.

The strongest preserved core is:

- authority and authorization;
- execution leases and scope controls;
- evidence, receipts, completion, and audit;
- durable orchestration and recovery;
- specialist/skill assets;
- desktop cockpit and data surfaces;
- tests, negative matrix, reachability checks, and CI gates.

The principal new construction is:

- SELF;
- HEART;
- canonical MIND;
- layered MEMORY;
- unified PERCEPTION;
- canonical Context Manifest;
- full FEET navigation and continuation;
- unified VOICE policy;
- one canonical runtime contract set across Python, Rust, bridge, and UI.

> **The existing system is not thrown away. It is reassigned beneath the correct owners, unified where it competes with itself, and extended where BRO is still missing.**
