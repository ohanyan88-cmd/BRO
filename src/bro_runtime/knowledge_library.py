"""BRO's governed library of external sources.

Acquisition and study are different trust boundaries and this module sits between
them. Fetching something is not the same as believing it: material arrives STAGED,
a human reviews it, and only an explicit approval lets it become part of the corpus
STUDY can read. Nothing here fetches anything, and nothing here studies anything.

Authority is recorded per source and is scope-sensitive: the RFC Editor is
authoritative for the RFC it publishes and about nothing else. External material never
outranks BRO's own contracts, governance or runtime truth, and no text inside an
acquired document grants anyone permission to do anything -- it is data BRO may learn
about, never an instruction BRO obeys.

The registry lives in DurableLearningMemory, which stays the single learning-memory
authority; this adds records to it rather than standing up a second store.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Sequence

from .learning_memory import (
    SUPPORTED_LANGUAGES, DurableLearningMemory, LearningMemoryRejected, detect_language, utc_now,
)


class KnowledgeLibraryRejected(RuntimeError):
    pass


class SourceStatus(StrEnum):
    STAGED = "STAGED"
    REVIEWED = "REVIEWED"
    APPROVED_FOR_STUDY = "APPROVED_FOR_STUDY"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class AuthorityClass(StrEnum):
    """Whose word this is. Never a global ranking -- always read with source_scope."""

    NORMATIVE_STANDARD = "NORMATIVE_STANDARD"
    OFFICIAL_SPECIFICATION = "OFFICIAL_SPECIFICATION"
    OFFICIAL_GOVERNMENT_OR_ACADEMIC = "OFFICIAL_GOVERNMENT_OR_ACADEMIC"
    OFFICIAL_VENDOR_DOCUMENTATION = "OFFICIAL_VENDOR_DOCUMENTATION"
    OFFICIAL_SECURITY_GUIDANCE = "OFFICIAL_SECURITY_GUIDANCE"
    USER_APPROVED_INTERNAL = "USER_APPROVED_INTERNAL"
    TRUSTED_REFERENCE = "TRUSTED_REFERENCE"


class LanguageVariant(StrEnum):
    """Kept apart on purpose: a Western or Classical text must never quietly become
    part of the normative Eastern Armenian baseline."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    EASTERN_ARMENIAN_NORMATIVE = "EASTERN_ARMENIAN_NORMATIVE"
    EASTERN_ARMENIAN_CONVERSATIONAL = "EASTERN_ARMENIAN_CONVERSATIONAL"
    WESTERN_ARMENIAN = "WESTERN_ARMENIAN"
    DIALECTAL_ARMENIAN = "DIALECTAL_ARMENIAN"
    CLASSICAL_ARMENIAN_GRABAR = "CLASSICAL_ARMENIAN_GRABAR"

    @property
    def is_eastern_normative(self) -> bool:
        return self is LanguageVariant.EASTERN_ARMENIAN_NORMATIVE


@dataclass(frozen=True)
class KnowledgeSource:
    source_id: str
    shelf: str
    publisher: str
    canonical_url: str
    authority_class: AuthorityClass
    source_scope: str
    upstream_version: str
    acquired_at: str
    content_digest: str
    local_path: str
    status: SourceStatus
    source_language: str = ""
    license: str = ""
    language_variant: LanguageVariant = LanguageVariant.NOT_APPLICABLE
    notes: str = ""
    reviewed_by: str = ""
    approved_by: str = ""
    superseded_by: str = ""

    @property
    def study_visible(self) -> bool:
        return self.status is SourceStatus.APPROVED_FOR_STUDY


_COLUMNS = (
    "source_id", "shelf", "publisher", "canonical_url", "authority_class", "source_scope",
    "upstream_version", "acquired_at", "content_digest", "local_path", "status",
    "source_language", "license",
    "language_variant", "notes", "reviewed_by", "reviewed_at", "approved_by", "approved_at",
    "superseded_by",
)

# Never acquired, never placed in the corpus. Acquired material is data, never code.
EXCLUDED_NAMES = (".git", "node_modules", "vendor", "__pycache__", ".github", "dist", "build")
EXCLUDED_SUFFIXES = (
    ".exe", ".dll", ".so", ".dylib", ".bin", ".zip", ".tar", ".gz", ".whl", ".jar",
    ".pyc", ".class", ".o", ".a", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".mp4", ".mp3", ".pem", ".key", ".crt", ".env",
)
# A credential is a marker plus a secret. Security documentation quotes these markers
# constantly -- GitHub's own REST quickstart tells you to store a file "including
# -----BEGIN RSA PRIVATE KEY-----" -- so matching the marker alone rejects exactly the
# material this shelf exists to learn from. Each pattern therefore requires the secret too.
CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{0,80}?[A-Za-z0-9+/]{40}"),
    re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*\S{40}"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{40}"),
    re.compile(r"\bxoxb-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{20,}"),
)


class GovernedKnowledgeLibrary:
    """Register, review, approve and verify external sources. Fetches nothing."""

    def __init__(self, memory: DurableLearningMemory) -> None:
        self.memory = memory
        self.connection = memory.connection
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS bro_knowledge_sources(
              source_id TEXT PRIMARY KEY,
              shelf TEXT NOT NULL,
              publisher TEXT NOT NULL,
              canonical_url TEXT NOT NULL,
              authority_class TEXT NOT NULL,
              source_scope TEXT NOT NULL,
              upstream_version TEXT NOT NULL,
              acquired_at TEXT NOT NULL,
              content_digest TEXT NOT NULL,
              local_path TEXT NOT NULL,
              status TEXT NOT NULL,
              source_language TEXT NOT NULL,
              license TEXT NOT NULL,
              language_variant TEXT NOT NULL,
              notes TEXT NOT NULL,
              reviewed_by TEXT NOT NULL,
              reviewed_at TEXT NOT NULL,
              approved_by TEXT NOT NULL,
              approved_at TEXT NOT NULL,
              superseded_by TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS bro_knowledge_source_path
              ON bro_knowledge_sources(local_path);
            CREATE TABLE IF NOT EXISTS bro_knowledge_transitions(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              source_id TEXT NOT NULL,
              from_status TEXT NOT NULL,
              to_status TEXT NOT NULL,
              actor TEXT NOT NULL,
              reason TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    # -------------------------------------------------------------------- helpers
    @staticmethod
    def digest(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _text(value: object, label: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise KnowledgeLibraryRejected(f"{label} must not be empty")
        return cleaned

    @staticmethod
    def acceptable_path(relative: str) -> bool:
        """Corpus paths are relative, inside the root, and never junk or executables."""
        candidate = str(relative or "").strip()
        if not candidate or candidate.startswith(("/", "~")) or ".." in Path(candidate).parts:
            return False
        parts = Path(candidate).parts
        if any(part in EXCLUDED_NAMES or part.startswith(".") for part in parts):
            return False
        return Path(candidate).suffix.lower() not in EXCLUDED_SUFFIXES

    @staticmethod
    def _language(declared: str, text: str) -> str:
        """The declared source language, checked against the script actually acquired.

        A shelf that says Armenian and delivers English is a provenance error, not a
        detail: later evidence would be attributed to the wrong language."""
        observed = detect_language(text)
        wanted = str(declared or '').strip().lower()
        if wanted and wanted not in SUPPORTED_LANGUAGES:
            raise KnowledgeLibraryRejected(f"unsupported source language: {wanted!r}")
        if wanted and observed and wanted != observed:
            raise KnowledgeLibraryRejected(
                f"shelf declares {wanted} but the acquired text reads as {observed}")
        return wanted or observed

    @staticmethod
    def carries_credentials(text: str) -> bool:
        """True when the text contains a credential, not merely the name of one."""
        return any(pattern.search(text) for pattern in CREDENTIAL_PATTERNS)

    # ------------------------------------------------------------------ lifecycle
    def stage(
        self, *, shelf: str, publisher: str, canonical_url: str, authority_class: AuthorityClass,
        source_scope: str, upstream_version: str, content: bytes, local_path: str,
        source_language: str = "", license: str = "",
        language_variant: LanguageVariant = LanguageVariant.NOT_APPLICABLE,
        notes: str = "",
    ) -> KnowledgeSource:
        """Record acquired material. Staged is not trusted and is not study-visible."""
        if not self.acceptable_path(local_path):
            raise KnowledgeLibraryRejected(f"unacceptable corpus path: {local_path!r}")
        text = content.decode("utf-8", "replace")
        if self.carries_credentials(text):
            raise KnowledgeLibraryRejected("acquired material appears to carry a credential")
        source = KnowledgeSource(
            source_id=f"knowledge-source:{uuid.uuid4()}",
            shelf=self._text(shelf, "shelf"),
            publisher=self._text(publisher, "publisher"),
            canonical_url=self._text(canonical_url, "canonical_url"),
            authority_class=AuthorityClass(authority_class),
            source_scope=self._text(source_scope, "source_scope"),
            upstream_version=self._text(upstream_version, "upstream_version"),
            acquired_at=utc_now(),
            content_digest=self.digest(content),
            local_path=local_path.strip(),
            status=SourceStatus.STAGED,
            source_language=self._language(source_language, text),
            license=str(license or "").strip(),
            language_variant=LanguageVariant(language_variant),
            notes=str(notes or "").strip(),
        )
        with self.connection:
            self.connection.execute(
                f"INSERT INTO bro_knowledge_sources({','.join(_COLUMNS)}) "
                f"VALUES ({','.join('?' * len(_COLUMNS))})",
                (source.source_id, source.shelf, source.publisher, source.canonical_url,
                 source.authority_class.value, source.source_scope, source.upstream_version,
                 source.acquired_at, source.content_digest, source.local_path,
                 source.status.value, source.source_language, source.license,
                 source.language_variant.value,
                 source.notes, "", "", "", "", ""),
            )
            self._transition(source.source_id, "", SourceStatus.STAGED.value, "acquisition",
                             f"acquired from {source.canonical_url}")
        return source

    def review(self, source_id: str, *, reviewed_by: str, reason: str = "") -> KnowledgeSource:
        return self._advance(source_id, SourceStatus.STAGED, SourceStatus.REVIEWED,
                             actor=reviewed_by, actor_column="reviewed", reason=reason)

    def approve(self, source_id: str, *, approved_by: str, content: bytes,
                reason: str = "") -> KnowledgeSource:
        """Approval is the only route into the corpus, and it re-checks the bytes.

        Reviewing one document and approving another is the failure this guards: the
        digest recorded at acquisition must still be the digest of what is approved.
        """
        current = self.source(source_id)
        if self.digest(content) != current.content_digest:
            raise KnowledgeLibraryRejected(
                "content changed since it was staged; re-acquire and review it again")
        return self._advance(source_id, SourceStatus.REVIEWED, SourceStatus.APPROVED_FOR_STUDY,
                             actor=approved_by, actor_column="approved", reason=reason)

    def reject(self, source_id: str, *, actor: str, reason: str) -> KnowledgeSource:
        current = self.source(source_id)
        self._set_status(source_id, SourceStatus.REJECTED)
        with self.connection:
            self._transition(source_id, current.status.value, SourceStatus.REJECTED.value,
                             actor, self._text(reason, "reason"))
        return self.source(source_id)

    def supersede(self, source_id: str, *, superseded_by: str, actor: str,
                  reason: str = "") -> KnowledgeSource:
        """Old material stays visible as history rather than being silently deleted."""
        current = self.source(source_id)
        with self.connection:
            self.connection.execute(
                "UPDATE bro_knowledge_sources SET status=?,superseded_by=? WHERE source_id=?",
                (SourceStatus.SUPERSEDED.value, self._text(superseded_by, "superseded_by"), source_id),
            )
            self._transition(source_id, current.status.value, SourceStatus.SUPERSEDED.value,
                             actor, reason or f"superseded by {superseded_by}")
        return self.source(source_id)

    def _advance(self, source_id: str, expected: SourceStatus, target: SourceStatus, *,
                 actor: str, actor_column: str, reason: str) -> KnowledgeSource:
        who = self._text(actor, actor_column + "_by")
        current = self.source(source_id)
        if current.status is not expected:
            raise KnowledgeLibraryRejected(
                f"{target.value} requires {expected.value}, not {current.status.value}")
        with self.connection:
            self.connection.execute(
                f"UPDATE bro_knowledge_sources SET status=?,{actor_column}_by=?,"
                f"{actor_column}_at=? WHERE source_id=?",
                (target.value, who, utc_now(), source_id),
            )
            self._transition(source_id, current.status.value, target.value, who, reason)
        return self.source(source_id)

    def _set_status(self, source_id: str, status: SourceStatus) -> None:
        with self.connection:
            self.connection.execute("UPDATE bro_knowledge_sources SET status=? WHERE source_id=?",
                                    (status.value, source_id))

    def _transition(self, source_id: str, from_status: str, to_status: str, actor: str,
                    reason: str) -> None:
        self.connection.execute(
            "INSERT INTO bro_knowledge_transitions(source_id,from_status,to_status,actor,reason,created_at)"
            " VALUES (?,?,?,?,?,?)",
            (source_id, from_status, to_status, actor, reason, utc_now()),
        )

    # --------------------------------------------------------------------- reading
    def source(self, source_id: str) -> KnowledgeSource:
        row = self.connection.execute(
            "SELECT * FROM bro_knowledge_sources WHERE source_id=?",
            (self._text(source_id, "source_id"),)).fetchone()
        if row is None:
            raise KnowledgeLibraryRejected("unknown knowledge source")
        return self._source(row)

    def sources(self, *, shelf: str = "", status: SourceStatus | None = None) -> tuple[KnowledgeSource, ...]:
        query = "SELECT * FROM bro_knowledge_sources"
        clauses, values = [], []
        if shelf:
            clauses.append("shelf=?"); values.append(shelf)
        if status is not None:
            clauses.append("status=?"); values.append(SourceStatus(status).value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY shelf, local_path"
        return tuple(self._source(row) for row in self.connection.execute(query, values))

    def approved(self, *, shelf: str = "") -> tuple[KnowledgeSource, ...]:
        return self.sources(shelf=shelf, status=SourceStatus.APPROVED_FOR_STUDY)

    def transitions(self, source_id: str) -> tuple[dict[str, str], ...]:
        rows = self.connection.execute(
            "SELECT from_status,to_status,actor,reason,created_at FROM bro_knowledge_transitions"
            " WHERE source_id=? ORDER BY sequence", (source_id,)).fetchall()
        return tuple(dict(row) for row in rows)

    def manifest(self, *, shelf: str = "") -> dict[str, object]:
        """A deterministic description of what was approved, and its one digest."""
        entries = [
            {
                "shelf": item.shelf,
                "local_path": item.local_path,
                "canonical_url": item.canonical_url,
                "publisher": item.publisher,
                "authority_class": item.authority_class.value,
                "source_scope": item.source_scope,
                "upstream_version": item.upstream_version,
                "content_digest": item.content_digest,
                "language_variant": item.language_variant.value,
                "source_language": item.source_language,
            }
            for item in sorted(self.approved(shelf=shelf), key=lambda s: (s.shelf, s.local_path))
        ]
        payload = json.dumps(entries, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return {
            "documents": len(entries),
            "entries": entries,
            "manifest_digest": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }

    # ------------------------------------------------------------------ corpus rule
    def verify_corpus(self, corpus_root: str | Path) -> list[str]:
        """Only approved material, with matching bytes, may exist where STUDY can read.

        This is the whole containment claim in one function: what STUDY sees is exactly
        what a person approved, unchanged since they approved it.
        """
        root = Path(corpus_root)
        problems: list[str] = []
        if not root.is_dir():
            return [f"corpus root is not a readable directory: {root}"]
        approved = {item.local_path: item for item in self.approved()}
        seen: set[str] = set()
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(root))
            seen.add(relative)
            item = approved.get(relative)
            if item is None:
                problems.append(f"{relative}: present in the corpus but not approved for study")
                continue
            if self.digest(path.read_bytes()) != item.content_digest:
                problems.append(f"{relative}: content differs from what was approved")
        for relative in sorted(set(approved) - seen):
            problems.append(f"{relative}: approved for study but missing from the corpus")
        return problems

    # ----------------------------------------------------------------- provenance
    def provenance_for(self, relative_path: str) -> KnowledgeSource | None:
        row = self.connection.execute(
            "SELECT * FROM bro_knowledge_sources WHERE local_path=?", (relative_path,)).fetchone()
        return None if row is None else self._source(row)

    @staticmethod
    def _source(row) -> KnowledgeSource:
        return KnowledgeSource(
            source_id=row["source_id"], shelf=row["shelf"], publisher=row["publisher"],
            canonical_url=row["canonical_url"],
            authority_class=AuthorityClass(row["authority_class"]),
            source_scope=row["source_scope"], upstream_version=row["upstream_version"],
            acquired_at=row["acquired_at"], content_digest=row["content_digest"],
            local_path=row["local_path"], status=SourceStatus(row["status"]),
            source_language=row["source_language"], license=row["license"], language_variant=LanguageVariant(row["language_variant"]),
            notes=row["notes"], reviewed_by=row["reviewed_by"], approved_by=row["approved_by"],
            superseded_by=row["superseded_by"],
        )
