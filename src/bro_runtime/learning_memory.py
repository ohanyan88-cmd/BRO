"""Durable conversation memory and governed outcome-learning for BRO.

The knowledge here belongs to BRO, not to whichever model produced it. Model and
provider identity are recorded as provenance only: the schema is ordinary SQLite,
carries no provider-specific semantics, and a lesson learned while one model was
configured is retrievable and reusable when another is. Every fact that governs
reuse — the pattern a lesson is filed under, the observations that support it, its
evidence references, its confidence — is derived by this runtime from governed
receipts. Model output supplies inferred guidance and nothing that decides truth.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LearningMemoryRejected(RuntimeError):
    pass


class LessonStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    STALE = "STALE"
    RETIRED = "RETIRED"


# A lesson whose evidenced successes fall to or below this share of its total
# outcomes is disputed: it may still be surfaced, but never as settled guidance.
DISPUTED_BELOW = 0.6

# Observations recorded under this prefix are claims about the world that must still
# hold for the lesson to be reusable, and are therefore checkable against current truth.
BINDING_PREFIX = "binding:"


@dataclass(frozen=True)
class Provenance:
    """Where a piece of learned knowledge came from. Never an authority."""

    model_ref: str = ""
    source_revision: str = ""
    environment: str = ""
    instance_id: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "model_ref": self.model_ref,
            "source_revision": self.source_revision,
            "environment": self.environment,
            "instance_id": self.instance_id,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
        }

    @classmethod
    def from_json(cls, raw: str) -> "Provenance":
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return cls(**{key: str(data.get(key, "")) for key in cls().as_dict()})


@dataclass(frozen=True)
class LearnedLesson:
    pattern_key: str
    lesson: str
    skill_name: str
    trigger: str
    procedure: tuple[str, ...]
    successes: int
    failures: int
    observations: tuple[str, ...] = ()
    status: LessonStatus = LessonStatus.ACTIVE
    confidence: float = 0.0
    last_evidence_ref: str = ""
    provenance: Provenance = field(default_factory=Provenance)

    @property
    def is_settled(self) -> bool:
        return self.status is LessonStatus.ACTIVE


@dataclass(frozen=True)
class Contradiction:
    pattern_key: str
    field_name: str
    learned_value: str
    current_value: str
    detail: str


@dataclass(frozen=True)
class Retrieval:
    """What retrieval offers, what it refuses to offer, and why."""

    lessons: tuple[LearnedLesson, ...] = ()
    withheld: tuple[LearnedLesson, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()


@dataclass(frozen=True)
class SkillCandidate:
    candidate_id: str
    pattern_key: str
    skill_name: str
    trigger: str
    procedure: tuple[str, ...]
    status: str
    intended_outcome: str = ""
    preconditions: tuple[str, ...] = ()
    required_authority: str = ""
    verification: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    supporting_executions: int = 0
    confidence: float = 0.0
    provenance: Provenance = field(default_factory=Provenance)


_LESSON_COLUMNS = (
    ("observations_json", "observations_json TEXT NOT NULL DEFAULT '[]'"),
    ("status", "status TEXT NOT NULL DEFAULT 'ACTIVE'"),
    ("confidence", "confidence REAL NOT NULL DEFAULT 0.0"),
    ("last_evidence_ref", "last_evidence_ref TEXT NOT NULL DEFAULT ''"),
    ("provenance_json", "provenance_json TEXT NOT NULL DEFAULT '{}'"),
)
_EXPERIENCE_COLUMNS = (
    ("interpreted_scope_json", "interpreted_scope_json TEXT NOT NULL DEFAULT '[]'"),
    ("provider_ref", "provider_ref TEXT NOT NULL DEFAULT ''"),
    ("effect_ref", "effect_ref TEXT NOT NULL DEFAULT ''"),
    ("readback_ref", "readback_ref TEXT NOT NULL DEFAULT ''"),
    ("readback_provider_ref", "readback_provider_ref TEXT NOT NULL DEFAULT ''"),
    ("assurance", "assurance TEXT NOT NULL DEFAULT ''"),
    ("source_revision", "source_revision TEXT NOT NULL DEFAULT ''"),
    ("environment", "environment TEXT NOT NULL DEFAULT ''"),
    ("instance_id", "instance_id TEXT NOT NULL DEFAULT ''"),
    ("model_ref", "model_ref TEXT NOT NULL DEFAULT ''"),
    ("pattern_key", "pattern_key TEXT NOT NULL DEFAULT ''"),
    ("lesson_ref", "lesson_ref TEXT NOT NULL DEFAULT ''"),
    ("candidate_ref", "candidate_ref TEXT NOT NULL DEFAULT ''"),
)
_CANDIDATE_COLUMNS = (
    ("intended_outcome", "intended_outcome TEXT NOT NULL DEFAULT ''"),
    ("preconditions_json", "preconditions_json TEXT NOT NULL DEFAULT '[]'"),
    ("required_authority", "required_authority TEXT NOT NULL DEFAULT ''"),
    ("verification_json", "verification_json TEXT NOT NULL DEFAULT '[]'"),
    ("failure_modes_json", "failure_modes_json TEXT NOT NULL DEFAULT '[]'"),
    ("supporting_executions", "supporting_executions INTEGER NOT NULL DEFAULT 0"),
    ("confidence", "confidence REAL NOT NULL DEFAULT 0.0"),
    ("provenance_json", "provenance_json TEXT NOT NULL DEFAULT '{}'"),
)


class DurableLearningMemory:
    """SQLite-backed memory that learns from evidenced outcomes without self-authorizing.

    Conversation history and execution experiences are durable. Model-derived lessons
    are accumulated only after a successful governed action receipt. Repeated evidence
    may create a reusable skill candidate, but activation is impossible without an
    explicit approval transition and an explicit promotion transition.

    Confidence follows evidence in both directions. A failure recorded against a
    learned pattern lowers that pattern's confidence and can dispute it; contradiction
    against current runtime truth withholds a lesson from reuse rather than letting it
    quietly win. Current truth always outranks remembered truth.
    """

    VALID_CANDIDATE_STATES = {"CANDIDATE", "APPROVED", "PROMOTED", "REJECTED"}

    def __init__(self, connection: sqlite3.Connection, *, candidate_threshold: int = 2) -> None:
        if candidate_threshold < 2:
            raise LearningMemoryRejected("candidate_threshold must be at least 2")
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.candidate_threshold = candidate_threshold
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS bro_conversation_memory(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              mode TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bro_learning_experience(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              request TEXT NOT NULL,
              mode TEXT NOT NULL,
              success INTEGER NOT NULL,
              specialist_ref TEXT NOT NULL,
              evidence_ref TEXT NOT NULL,
              error_ref TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bro_learned_lessons(
              pattern_key TEXT PRIMARY KEY,
              lesson TEXT NOT NULL,
              skill_name TEXT NOT NULL,
              trigger_text TEXT NOT NULL,
              procedure_json TEXT NOT NULL,
              successes INTEGER NOT NULL,
              failures INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bro_skill_candidates(
              candidate_id TEXT PRIMARY KEY,
              pattern_key TEXT UNIQUE NOT NULL,
              skill_name TEXT NOT NULL,
              trigger_text TEXT NOT NULL,
              procedure_json TEXT NOT NULL,
              status TEXT NOT NULL,
              approved_by TEXT NOT NULL,
              approved_at TEXT NOT NULL,
              promoted_by TEXT NOT NULL,
              promoted_at TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bro_failure_observations(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              pattern_key TEXT NOT NULL,
              request TEXT NOT NULL,
              error_ref TEXT NOT NULL,
              provider_ref TEXT NOT NULL,
              source_revision TEXT NOT NULL,
              model_ref TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bro_learning_contradictions(
              contradiction_id TEXT PRIMARY KEY,
              pattern_key TEXT NOT NULL,
              field_name TEXT NOT NULL,
              learned_value TEXT NOT NULL,
              current_value TEXT NOT NULL,
              detail TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bro_skill_candidate_transitions(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              candidate_id TEXT NOT NULL,
              from_status TEXT NOT NULL,
              to_status TEXT NOT NULL,
              actor TEXT NOT NULL,
              reason TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        self._migrate()

    def _migrate(self) -> None:
        """Add columns to databases created by an earlier revision; never drop data."""
        for table, columns in (
            ("bro_learned_lessons", _LESSON_COLUMNS),
            ("bro_learning_experience", _EXPERIENCE_COLUMNS),
            ("bro_skill_candidates", _CANDIDATE_COLUMNS),
        ):
            present = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            for name, ddl in columns:
                if name not in present:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        self.connection.commit()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _text(value: Any, label: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise LearningMemoryRejected(f"{label} must not be empty")
        return cleaned

    @staticmethod
    def _sequence(values: Any) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(item).strip() for item in values or () if str(item).strip()))

    @staticmethod
    def confidence_for(successes: int, failures: int) -> float:
        total = successes + failures
        if total <= 0:
            return 0.0
        return round(successes / total, 4)

    @classmethod
    def status_for(cls, successes: int, failures: int, *, current: str = LessonStatus.ACTIVE) -> LessonStatus:
        if current in {LessonStatus.RETIRED, LessonStatus.STALE}:
            return LessonStatus(current)
        if successes <= 0:
            return LessonStatus.DISPUTED
        if cls.confidence_for(successes, failures) < DISPUTED_BELOW:
            return LessonStatus.DISPUTED
        return LessonStatus.ACTIVE

    @classmethod
    def _learning_payload(cls, learning: Mapping[str, Any]) -> tuple[str, str, str, str, tuple[str, ...]]:
        pattern_key = cls._text(learning.get("pattern_key"), "pattern_key")
        lesson = cls._text(learning.get("lesson"), "lesson")
        skill_name = cls._text(learning.get("skill_name"), "skill_name")
        trigger = cls._text(learning.get("trigger"), "trigger")
        procedure = cls._sequence(learning.get("procedure", ()))
        if not procedure:
            raise LearningMemoryRejected("procedure must contain at least one step")
        return pattern_key, lesson, skill_name, trigger, procedure

    # ------------------------------------------------------------- conversation
    def append_message(self, role: str, content: str, *, mode: str) -> None:
        role = self._text(role, "role")
        content = self._text(content, "content")
        mode = self._text(mode, "mode")
        with self.connection:
            self.connection.execute(
                "INSERT INTO bro_conversation_memory(role,content,mode,created_at) VALUES (?,?,?,?)",
                (role, content, mode, utc_now()),
            )

    def recent_messages(self, *, limit: int = 12) -> tuple[dict[str, str], ...]:
        if limit <= 0:
            return ()
        rows = self.connection.execute(
            "SELECT role,content FROM bro_conversation_memory ORDER BY sequence DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return tuple({"role": row["role"], "content": row["content"]} for row in reversed(rows))

    # ---------------------------------------------------------------- outcomes
    def record_outcome(
        self,
        *,
        request: str,
        success: bool,
        specialist_ref: str = "",
        evidence_ref: str = "",
        error_ref: str = "",
        learning: Mapping[str, Any] | None = None,
        observations: Sequence[str] = (),
        provenance: Provenance | None = None,
        interpreted_scope: Sequence[str] = (),
        provider_ref: str = "",
        effect_ref: str = "",
        readback_ref: str = "",
        readback_provider_ref: str = "",
        assurance: str = "",
        mode: str = "ACT",
        pattern_key: str = "",
    ) -> SkillCandidate | None:
        """Record one governed outcome. Only evidenced success may touch a lesson."""
        request = self._text(request, "request")
        provenance = provenance or Provenance()
        recorded_pattern = pattern_key.strip() or (str(learning.get("pattern_key", "")).strip() if learning else "")
        with self.connection:
            self.connection.execute(
                """INSERT INTO bro_learning_experience(
                     request,mode,success,specialist_ref,evidence_ref,error_ref,created_at,
                     interpreted_scope_json,provider_ref,effect_ref,readback_ref,readback_provider_ref,
                     assurance,source_revision,environment,instance_id,model_ref,pattern_key,lesson_ref,candidate_ref)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    request, mode.strip() or "ACT", int(success), specialist_ref.strip(), evidence_ref.strip(),
                    error_ref.strip(), utc_now(), json.dumps(list(self._sequence(interpreted_scope)), ensure_ascii=False),
                    provider_ref.strip(), effect_ref.strip(), readback_ref.strip(), readback_provider_ref.strip(),
                    assurance.strip(), provenance.source_revision, provenance.environment, provenance.instance_id,
                    provenance.model_ref, recorded_pattern, "", "",
                ),
            )
        if not success:
            self._record_failure(
                pattern_key=recorded_pattern, request=request, error_ref=error_ref,
                provider_ref=provider_ref, provenance=provenance,
            )
            return None
        if learning is None:
            return None
        if not evidence_ref.strip():
            raise LearningMemoryRejected("successful learning requires external evidence_ref")
        return self._accumulate(
            learning=learning, evidence_ref=evidence_ref.strip(), observations=observations,
            provenance=provenance, pattern_key=pattern_key,
        )

    def _record_failure(self, *, pattern_key: str, request: str, error_ref: str, provider_ref: str, provenance: Provenance) -> None:
        """A failure is experience. It never raises a success count and never creates a lesson."""
        if not pattern_key:
            return
        with self.connection:
            self.connection.execute(
                """INSERT INTO bro_failure_observations(pattern_key,request,error_ref,provider_ref,source_revision,model_ref,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (pattern_key, request, error_ref.strip(), provider_ref.strip(), provenance.source_revision, provenance.model_ref, utc_now()),
            )
            row = self.connection.execute(
                "SELECT successes,failures,status FROM bro_learned_lessons WHERE pattern_key=?", (pattern_key,)
            ).fetchone()
            if row is None:
                return
            failures = int(row["failures"]) + 1
            successes = int(row["successes"])
            self.connection.execute(
                "UPDATE bro_learned_lessons SET failures=?,confidence=?,status=?,updated_at=? WHERE pattern_key=?",
                (
                    failures,
                    self.confidence_for(successes, failures),
                    self.status_for(successes, failures, current=row["status"]).value,
                    utc_now(),
                    pattern_key,
                ),
            )

    def _accumulate(
        self, *, learning: Mapping[str, Any], evidence_ref: str, observations: Sequence[str],
        provenance: Provenance, pattern_key: str,
    ) -> SkillCandidate | None:
        payload = dict(learning)
        if pattern_key.strip():
            payload["pattern_key"] = pattern_key.strip()
        key, lesson, skill_name, trigger, procedure = self._learning_payload(payload)
        row = self.connection.execute("SELECT * FROM bro_learned_lessons WHERE pattern_key=?", (key,)).fetchone()
        successes = 1 if row is None else int(row["successes"]) + 1
        failures = 0 if row is None else int(row["failures"])
        previous_status = LessonStatus.ACTIVE.value if row is None else row["status"]
        kept = () if row is None else self._json_tuple(row["observations_json"])
        merged_observations = tuple(dict.fromkeys(kept + self._sequence(observations)))
        first_seen = provenance.first_seen_at or utc_now()
        if row is not None:
            first_seen = Provenance.from_json(row["provenance_json"]).first_seen_at or first_seen
        stored_provenance = Provenance(
            model_ref=provenance.model_ref, source_revision=provenance.source_revision,
            environment=provenance.environment, instance_id=provenance.instance_id,
            first_seen_at=first_seen, last_seen_at=utc_now(),
        )
        with self.connection:
            self.connection.execute(
                """INSERT INTO bro_learned_lessons(
                     pattern_key,lesson,skill_name,trigger_text,procedure_json,successes,failures,updated_at,
                     observations_json,status,confidence,last_evidence_ref,provenance_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(pattern_key) DO UPDATE SET
                     lesson=excluded.lesson, skill_name=excluded.skill_name,
                     trigger_text=excluded.trigger_text, procedure_json=excluded.procedure_json,
                     successes=excluded.successes, failures=excluded.failures, updated_at=excluded.updated_at,
                     observations_json=excluded.observations_json, status=excluded.status,
                     confidence=excluded.confidence, last_evidence_ref=excluded.last_evidence_ref,
                     provenance_json=excluded.provenance_json""",
                (
                    key, lesson, skill_name, trigger, json.dumps(procedure, ensure_ascii=False), successes, failures,
                    utc_now(), json.dumps(merged_observations, ensure_ascii=False),
                    self.status_for(successes, failures, current=previous_status).value,
                    self.confidence_for(successes, failures), evidence_ref, json.dumps(stored_provenance.as_dict(), ensure_ascii=False),
                ),
            )
        if successes < self.candidate_threshold:
            return None
        existing = self.connection.execute("SELECT * FROM bro_skill_candidates WHERE pattern_key=?", (key,)).fetchone()
        if existing is not None:
            with self.connection:
                self.connection.execute(
                    "UPDATE bro_skill_candidates SET supporting_executions=?,confidence=? WHERE pattern_key=?",
                    (successes, self.confidence_for(successes, failures), key),
                )
            return self._candidate(self.connection.execute("SELECT * FROM bro_skill_candidates WHERE pattern_key=?", (key,)).fetchone())
        candidate_id = f"skill-candidate:{uuid.uuid4()}"
        with self.connection:
            self.connection.execute(
                """INSERT INTO bro_skill_candidates(
                     candidate_id,pattern_key,skill_name,trigger_text,procedure_json,status,
                     approved_by,approved_at,promoted_by,promoted_at,created_at,
                     intended_outcome,preconditions_json,required_authority,verification_json,
                     failure_modes_json,supporting_executions,confidence,provenance_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    candidate_id, key, skill_name, trigger, json.dumps(procedure, ensure_ascii=False), "CANDIDATE",
                    "", "", "", "", utc_now(),
                    str(payload.get("intended_outcome", "")).strip(),
                    json.dumps(self._sequence(payload.get("preconditions", ())), ensure_ascii=False),
                    str(payload.get("required_authority", "")).strip(),
                    json.dumps(merged_observations, ensure_ascii=False),
                    json.dumps(self._sequence(payload.get("failure_modes", ())), ensure_ascii=False),
                    successes, self.confidence_for(successes, failures),
                    json.dumps(stored_provenance.as_dict(), ensure_ascii=False),
                ),
            )
            self.connection.execute(
                "INSERT INTO bro_skill_candidate_transitions(candidate_id,from_status,to_status,actor,reason,created_at) VALUES (?,?,?,?,?,?)",
                (candidate_id, "", "CANDIDATE", "runtime", f"{successes} independently evidenced executions", utc_now()),
            )
        return self._candidate(self.connection.execute("SELECT * FROM bro_skill_candidates WHERE candidate_id=?", (candidate_id,)).fetchone())

    # --------------------------------------------------------------- retrieval
    def retrieve(self, request: str, *, current_truth: Mapping[str, str] | None = None, limit: int = 5) -> Retrieval:
        """Rank durable lessons for reuse and refuse the ones current truth contradicts."""
        terms = {term for term in self._text(request, "request").lower().split() if len(term) >= 3}
        rows = self.connection.execute(
            "SELECT * FROM bro_learned_lessons WHERE status != ? ORDER BY confidence DESC, successes DESC, updated_at DESC LIMIT 200",
            (LessonStatus.RETIRED.value,),
        ).fetchall()
        scored: list[tuple[float, int, sqlite3.Row]] = []
        withheld: list[LearnedLesson] = []
        contradictions: list[Contradiction] = []
        for row in rows:
            lesson = self._lesson(row)
            found = self._contradictions_for(lesson, current_truth or {})
            if found:
                contradictions.extend(found)
                withheld.append(lesson)
                self._record_contradictions(found)
                continue
            identity = f"{row['pattern_key']} {row['skill_name']} {row['trigger_text']}".lower()
            body = f"{row['lesson']} {row['procedure_json']}".lower()
            score = 2.0 * sum(1 for term in terms if term in identity) + sum(1 for term in terms if term in body)
            if score <= 0:
                continue
            if lesson.status is LessonStatus.DISPUTED:
                score -= 1.0
            scored.append((score + float(row["confidence"]), int(row["successes"]), row))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return Retrieval(
            lessons=tuple(self._lesson(row) for _, _, row in scored[:limit]),
            withheld=tuple(withheld),
            contradictions=tuple(contradictions),
        )

    def relevant_lessons(self, request: str, *, limit: int = 5) -> tuple[LearnedLesson, ...]:
        return self.retrieve(request, limit=limit).lessons

    @staticmethod
    def _contradictions_for(lesson: LearnedLesson, current_truth: Mapping[str, str]) -> tuple[Contradiction, ...]:
        """A lesson that names a binding fact current truth denies is withheld, not silently used.

        Only observations recorded under the ``binding:`` prefix participate. Those are
        the facts that must still hold for the lesson to apply — the environment it was
        learned in, the capability it used, the external target it was bound to. Evidence
        references and the revision a lesson was learned on are history, not claims about
        now, so a later deployment does not turn every lesson into a contradiction.
        """
        found: list[Contradiction] = []
        for key, current in current_truth.items():
            current = str(current).strip()
            if not current:
                continue
            prefix = f"{BINDING_PREFIX}{key}="
            for observation in lesson.observations:
                if not observation.startswith(prefix):
                    continue
                learned = observation[len(prefix):].strip()
                if learned and learned != current:
                    found.append(Contradiction(lesson.pattern_key, key, learned, current,
                                               "learned observation contradicts current runtime truth"))
        return tuple(found)

    def _record_contradictions(self, contradictions: Sequence[Contradiction]) -> None:
        with self.connection:
            for item in contradictions:
                existing = self.connection.execute(
                    "SELECT 1 FROM bro_learning_contradictions WHERE pattern_key=? AND field_name=? AND learned_value=? AND current_value=?",
                    (item.pattern_key, item.field_name, item.learned_value, item.current_value),
                ).fetchone()
                if existing is not None:
                    continue
                self.connection.execute(
                    "INSERT INTO bro_learning_contradictions VALUES (?,?,?,?,?,?,?)",
                    (f"contradiction:{uuid.uuid4()}", item.pattern_key, item.field_name,
                     item.learned_value, item.current_value, item.detail, utc_now()),
                )

    def contradictions(self) -> tuple[Contradiction, ...]:
        rows = self.connection.execute("SELECT * FROM bro_learning_contradictions ORDER BY created_at").fetchall()
        return tuple(Contradiction(r["pattern_key"], r["field_name"], r["learned_value"], r["current_value"], r["detail"]) for r in rows)

    def mark_stale(self, pattern_key: str, *, reason: str, observed_by: str) -> LearnedLesson:
        return self._set_status(pattern_key, LessonStatus.STALE, reason=reason, observed_by=observed_by)

    def retire(self, pattern_key: str, *, reason: str, observed_by: str) -> LearnedLesson:
        return self._set_status(pattern_key, LessonStatus.RETIRED, reason=reason, observed_by=observed_by)

    def _set_status(self, pattern_key: str, status: LessonStatus, *, reason: str, observed_by: str) -> LearnedLesson:
        self._text(reason, "reason")
        self._text(observed_by, "observed_by")
        key = self._text(pattern_key, "pattern_key")
        row = self.connection.execute("SELECT 1 FROM bro_learned_lessons WHERE pattern_key=?", (key,)).fetchone()
        if row is None:
            raise LearningMemoryRejected("unknown learned pattern")
        with self.connection:
            self.connection.execute(
                "UPDATE bro_learned_lessons SET status=?,updated_at=? WHERE pattern_key=?",
                (status.value, utc_now(), key),
            )
        return self.lesson(key)

    def lesson(self, pattern_key: str) -> LearnedLesson:
        row = self.connection.execute("SELECT * FROM bro_learned_lessons WHERE pattern_key=?", (pattern_key,)).fetchone()
        if row is None:
            raise LearningMemoryRejected("unknown learned pattern")
        return self._lesson(row)

    # ------------------------------------------------------- candidate lifecycle
    def approve_candidate(self, candidate_id: str, *, approved_by: str) -> SkillCandidate:
        actor = self._text(approved_by, "approved_by")
        row = self._candidate_row(candidate_id)
        if row["status"] != "CANDIDATE":
            raise LearningMemoryRejected("only CANDIDATE skills can be approved")
        with self.connection:
            self.connection.execute(
                "UPDATE bro_skill_candidates SET status='APPROVED', approved_by=?, approved_at=? WHERE candidate_id=?",
                (actor, utc_now(), candidate_id),
            )
            self._transition(candidate_id, "CANDIDATE", "APPROVED", actor, "explicit approval")
        return self._candidate(self._candidate_row(candidate_id))

    def promote_candidate(self, candidate_id: str, *, promoted_by: str) -> SkillCandidate:
        actor = self._text(promoted_by, "promoted_by")
        row = self._candidate_row(candidate_id)
        if row["status"] != "APPROVED" or not row["approved_by"]:
            raise LearningMemoryRejected("skill promotion requires prior explicit approval")
        with self.connection:
            self.connection.execute(
                "UPDATE bro_skill_candidates SET status='PROMOTED', promoted_by=?, promoted_at=? WHERE candidate_id=?",
                (actor, utc_now(), candidate_id),
            )
            self._transition(candidate_id, "APPROVED", "PROMOTED", actor, "explicit promotion")
        return self._candidate(self._candidate_row(candidate_id))

    def _transition(self, candidate_id: str, from_status: str, to_status: str, actor: str, reason: str) -> None:
        self.connection.execute(
            "INSERT INTO bro_skill_candidate_transitions(candidate_id,from_status,to_status,actor,reason,created_at) VALUES (?,?,?,?,?,?)",
            (candidate_id, from_status, to_status, actor, reason, utc_now()),
        )

    def candidate_transitions(self, candidate_id: str) -> tuple[dict[str, str], ...]:
        rows = self.connection.execute(
            "SELECT from_status,to_status,actor,reason,created_at FROM bro_skill_candidate_transitions WHERE candidate_id=? ORDER BY sequence",
            (candidate_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def candidate(self, candidate_id: str) -> SkillCandidate:
        return self._candidate(self._candidate_row(candidate_id))

    def _candidate_row(self, candidate_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM bro_skill_candidates WHERE candidate_id=?", (self._text(candidate_id, "candidate_id"),)
        ).fetchone()
        if row is None:
            raise LearningMemoryRejected("unknown skill candidate")
        if row["status"] not in self.VALID_CANDIDATE_STATES:
            raise LearningMemoryRejected("invalid skill candidate state")
        return row

    # ----------------------------------------------------------------- mapping
    @staticmethod
    def _json_tuple(raw: Any) -> tuple[str, ...]:
        try:
            value = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return ()
        return tuple(str(item) for item in value) if isinstance(value, list) else ()

    @classmethod
    def _candidate(cls, row: sqlite3.Row) -> SkillCandidate:
        keys = row.keys()
        return SkillCandidate(
            row["candidate_id"], row["pattern_key"], row["skill_name"], row["trigger_text"],
            cls._json_tuple(row["procedure_json"]), row["status"],
            intended_outcome=row["intended_outcome"] if "intended_outcome" in keys else "",
            preconditions=cls._json_tuple(row["preconditions_json"]) if "preconditions_json" in keys else (),
            required_authority=row["required_authority"] if "required_authority" in keys else "",
            verification=cls._json_tuple(row["verification_json"]) if "verification_json" in keys else (),
            failure_modes=cls._json_tuple(row["failure_modes_json"]) if "failure_modes_json" in keys else (),
            supporting_executions=int(row["supporting_executions"]) if "supporting_executions" in keys else 0,
            confidence=float(row["confidence"]) if "confidence" in keys else 0.0,
            provenance=Provenance.from_json(row["provenance_json"]) if "provenance_json" in keys else Provenance(),
        )

    @classmethod
    def _lesson(cls, row: sqlite3.Row) -> LearnedLesson:
        return LearnedLesson(
            row["pattern_key"], row["lesson"], row["skill_name"], row["trigger_text"],
            cls._json_tuple(row["procedure_json"]), int(row["successes"]), int(row["failures"]),
            observations=cls._json_tuple(row["observations_json"]),
            status=LessonStatus(row["status"]),
            confidence=float(row["confidence"]),
            last_evidence_ref=row["last_evidence_ref"],
            provenance=Provenance.from_json(row["provenance_json"]),
        )

    @staticmethod
    def pattern_digest(request: str, binding: str) -> str:
        """Stable identity for a learned pattern: the request shape plus a runtime-owned binding."""
        normalized = " ".join(request.lower().split())
        return hashlib.sha256(f"{binding.strip()}|{normalized}".encode()).hexdigest()
