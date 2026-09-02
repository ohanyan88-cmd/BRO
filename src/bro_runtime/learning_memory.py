"""Durable conversation memory and governed outcome-learning for BRO."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LearningMemoryRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class LearnedLesson:
    pattern_key: str
    lesson: str
    skill_name: str
    trigger: str
    procedure: tuple[str, ...]
    successes: int
    failures: int


@dataclass(frozen=True)
class SkillCandidate:
    candidate_id: str
    pattern_key: str
    skill_name: str
    trigger: str
    procedure: tuple[str, ...]
    status: str


class DurableLearningMemory:
    """SQLite-backed memory that learns from evidenced outcomes without self-authorizing.

    Conversation history and execution experiences are durable. Model-derived lessons
    are accumulated only after a successful governed action receipt. Repeated evidence
    may create a reusable skill candidate, but activation is impossible without an
    explicit approval transition and an explicit promotion transition.
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
            """
        )

    @staticmethod
    def _text(value: Any, label: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise LearningMemoryRejected(f"{label} must not be empty")
        return cleaned

    @classmethod
    def _learning_payload(cls, learning: Mapping[str, Any]) -> tuple[str, str, str, str, tuple[str, ...]]:
        pattern_key = cls._text(learning.get("pattern_key"), "pattern_key")
        lesson = cls._text(learning.get("lesson"), "lesson")
        skill_name = cls._text(learning.get("skill_name"), "skill_name")
        trigger = cls._text(learning.get("trigger"), "trigger")
        procedure = tuple(dict.fromkeys(str(step).strip() for step in learning.get("procedure", ()) if str(step).strip()))
        if not procedure:
            raise LearningMemoryRejected("procedure must contain at least one step")
        return pattern_key, lesson, skill_name, trigger, procedure

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

    def record_outcome(
        self,
        *,
        request: str,
        success: bool,
        specialist_ref: str = "",
        evidence_ref: str = "",
        error_ref: str = "",
        learning: Mapping[str, Any] | None = None,
    ) -> SkillCandidate | None:
        request = self._text(request, "request")
        with self.connection:
            self.connection.execute(
                "INSERT INTO bro_learning_experience(request,mode,success,specialist_ref,evidence_ref,error_ref,created_at) VALUES (?,?,?,?,?,?,?)",
                (request, "ACT", int(success), specialist_ref.strip(), evidence_ref.strip(), error_ref.strip(), utc_now()),
            )
        if not success or learning is None:
            return None
        if not evidence_ref.strip():
            raise LearningMemoryRejected("successful learning requires external evidence_ref")
        pattern_key, lesson, skill_name, trigger, procedure = self._learning_payload(learning)
        procedure_json = json.dumps(procedure, ensure_ascii=False)
        row = self.connection.execute(
            "SELECT successes,failures FROM bro_learned_lessons WHERE pattern_key=?", (pattern_key,)
        ).fetchone()
        successes = 1 if row is None else int(row["successes"]) + 1
        failures = 0 if row is None else int(row["failures"])
        with self.connection:
            self.connection.execute(
                """INSERT INTO bro_learned_lessons(pattern_key,lesson,skill_name,trigger_text,procedure_json,successes,failures,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(pattern_key) DO UPDATE SET
                  lesson=excluded.lesson, skill_name=excluded.skill_name,
                  trigger_text=excluded.trigger_text, procedure_json=excluded.procedure_json,
                  successes=excluded.successes, failures=excluded.failures, updated_at=excluded.updated_at""",
                (pattern_key, lesson, skill_name, trigger, procedure_json, successes, failures, utc_now()),
            )
        if successes < self.candidate_threshold:
            return None
        existing = self.connection.execute(
            "SELECT * FROM bro_skill_candidates WHERE pattern_key=?", (pattern_key,)
        ).fetchone()
        if existing is not None:
            return self._candidate(existing)
        candidate_id = f"skill-candidate:{uuid.uuid4()}"
        with self.connection:
            self.connection.execute(
                "INSERT INTO bro_skill_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (candidate_id, pattern_key, skill_name, trigger, procedure_json, "CANDIDATE", "", "", "", "", utc_now()),
            )
        return SkillCandidate(candidate_id, pattern_key, skill_name, trigger, procedure, "CANDIDATE")

    def relevant_lessons(self, request: str, *, limit: int = 5) -> tuple[LearnedLesson, ...]:
        request_terms = {term for term in self._text(request, "request").lower().split() if len(term) >= 3}
        rows = self.connection.execute(
            "SELECT * FROM bro_learned_lessons ORDER BY successes DESC, updated_at DESC LIMIT 50"
        ).fetchall()
        scored: list[tuple[int, sqlite3.Row]] = []
        for row in rows:
            haystack = f"{row['pattern_key']} {row['lesson']} {row['skill_name']} {row['trigger_text']}".lower()
            score = sum(1 for term in request_terms if term in haystack)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], int(item[1]["successes"])), reverse=True)
        return tuple(self._lesson(row) for _, row in scored[:limit])

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

    @staticmethod
    def _candidate(row: sqlite3.Row) -> SkillCandidate:
        return SkillCandidate(
            row["candidate_id"], row["pattern_key"], row["skill_name"], row["trigger_text"],
            tuple(json.loads(row["procedure_json"])), row["status"],
        )

    @staticmethod
    def _lesson(row: sqlite3.Row) -> LearnedLesson:
        return LearnedLesson(
            row["pattern_key"], row["lesson"], row["skill_name"], row["trigger_text"],
            tuple(json.loads(row["procedure_json"])), int(row["successes"]), int(row["failures"]),
        )

    @staticmethod
    def pattern_digest(request: str, specialist_ref: str) -> str:
        normalized = " ".join(request.lower().split())
        return hashlib.sha256(f"{specialist_ref.strip()}|{normalized}".encode()).hexdigest()
