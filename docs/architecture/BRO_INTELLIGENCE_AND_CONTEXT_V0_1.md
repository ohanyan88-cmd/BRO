# BRO — Intelligence and Context v0.1

**Status:** CANONICAL DESIGN DRAFT  
**Scope:** MIND, PERCEPTION, MEMORY, SKILLS & KNOWLEDGE  
**Rule:** each primitive has one owner

## 1. Purpose

This design defines how BRO understands, observes, remembers, knows, learns, judges, and plans without loading the entire universe or confusing memory, evidence, knowledge, and current reality.

## 2. Ownership

| Primitive/concern | Single owner |
|---|---|
| Intent record and Observation | PERCEPTION |
| Goal, Decision, Plan | MIND |
| Durable memory record and memory-class lifecycle | MEMORY |
| Knowledge, Skill, Capability, Specialist definition | SKILLS & KNOWLEDGE |
| Context Manifest | NERVOUS SYSTEM |
| Evidence | IMMUNE SYSTEM |
| Project facts | Project source-of-truth |

## 3. Intelligence Loop

`INTENT → FRAME → CONTEXT NEEDS → PERCEIVE/RETRIEVE → ASSEMBLE → REASON → JUDGE → DECIDE → PLAN → OBSERVE RESULTS → REFLECT`

The loop is re-entrant. New evidence, contradiction, failure, interruption, or authority change can return it to any earlier valid stage.

## 4. MIND Contract

Inputs:

- Intent;
- scoped Context Manifest;
- Observations;
- relevant memory references;
- capability state;
- authority constraints;
- action results and Evidence.

Outputs:

- Goal;
- framing;
- assumptions and knowledge states;
- options;
- Decision;
- versioned Plan;
- replan;
- synthesis;
- reflection/learning proposal.

MIND must:

- distinguish `CONFIRMED`, `DERIVED`, `UNVERIFIED`, `UNKNOWN`, `CONFLICTED`;
- seek current reality when material;
- challenge user or specialist recommendations when evidence requires;
- preserve alternatives when decision reversibility/risk requires;
- own final judgment even after delegation;
- never manufacture action or evidence.

## 5. PERCEPTION Contract

PERCEPTION converts authorized contact with reality into Observations.

Observation fields:

- stable ID and schema version;
- source identity and type;
- observed content/reference;
- collection method;
- observed and recorded time;
- freshness/effective period;
- scope and limitations;
- trust state;
- integrity/provenance;
- sensitivity;
- authority reference.

Sources may include user input, files, repositories, APIs, apps, databases, logs, runtime state, screenshots, sensors, and tool results.

Untrusted instructions inside content remain data.

## 6. MEMORY Classes

Each record belongs to exactly one class:

1. Self Memory;
2. Relationship Foundation;
3. User Context;
4. Project Memory;
5. Work Memory;
6. Decision Memory;
7. Evidence Reference Memory;
8. Failure/Learning Memory;
9. Working Memory;
10. Quarantine.

Memory record fields:

- class;
- subject and scope;
- content/reference;
- source owner;
- authority;
- sensitivity;
- confidence;
- effective time and freshness;
- supersession/conflict links;
- retention;
- promotion permissions;
- integrity;
- status.

MEMORY never converts a stored claim into current fact. Retrieval must return provenance, freshness, conflicts, and authority.

## 7. Memory Operations

- `PROPOSE_STORE`;
- `ACCEPT`;
- `REJECT`;
- `RETRIEVE`;
- `CORRECT`;
- `SUPERSEDE`;
- `QUARANTINE`;
- `PROMOTE`;
- `EXPIRE`;
- `DELETE_WHERE_AUTHORIZED`.

Promotion changes scope/class and therefore requires explicit policy plus Authority Decision. Raw private or project material never promotes automatically.

## 8. Skills and Knowledge

- Knowledge is information usable by BRO.
- Skill is a repeatable method.
- Capability is a tested ability to achieve an outcome class.
- Specialist is an internal worker configured around capabilities.

Capability contract:

- identifier/version;
- outcome class;
- inputs/outputs;
- prerequisites;
- limits;
- authority needs;
- compatible skills/tools/models/specialists;
- quality state;
- evidence/tests;
- cost/latency/privacy characteristics;
- lifecycle status.

Availability is not capability. Capability is not authority. Specialist count is not intelligence.

## 9. Context Assembly

NERVOUS SYSTEM owns the Context Manifest. Intelligence components contribute records.

Assembly sequence:

1. start from Goal/Decision need;
2. load minimal SELF/HEART envelope;
3. identify current-reality needs;
4. retrieve only scoped memory;
5. load applicable project truth and policies;
6. load capability/tool state;
7. detect conflicts, staleness, sensitivity, and missing proof;
8. apply authority/isolation controls;
9. rank by relevance and materiality;
10. record included and materially excluded sources;
11. enforce context/token/resource budget;
12. issue immutable manifest revision.

## 10. Learning

Outcome reflection produces a Learning Proposal, not automatic durable truth.

Promotion requires:

- observed outcome;
- causal confidence;
- scope;
- generalizability;
- risks;
- evidence;
- target memory or capability owner;
- authority;
- validation/rollback.

Failure learning must capture defect, cause, remediation, prevention, and evidence without preserving secrets or unsafe raw context.

## 11. Model and Provider Independence

Models are replaceable mechanisms. Canonical state lives outside provider conversations. Every provider adapter must consume/produce versioned contracts, disclose limitations internally, and preserve task/decision correlation.

## 12. Acceptance Gates

- IC-1: every primitive has one owner.
- IC-2: current Observation outranks stale memory.
- IC-3: Context Manifest is minimal, scoped, traceable, and versioned.
- IC-4: private/project boundaries survive retrieval and delegation.
- IC-5: model/provider swap preserves canonical state.
- IC-6: MIND retains judgment ownership.
- IC-7: capability and authority cannot be confused.
- IC-8: learning cannot self-promote without evidence/authority.
- IC-9: contradiction remains visible until resolved.
- IC-10: no memory class becomes a generic dumping ground.
- IC-11: working memory expires by policy.
- IC-12: end-to-end request can trace Intent→Goal→Decision→Plan with sources.

## 13. Decision

BRO's intelligence is one judgment system grounded by current perception, governed continuity, and expandable tested capability. Context is assembled for the decision, not accumulated for its own sake.

> **Perceive what is real. Remember what deserves continuity. Load only what matters. Judge as one BRO.**
