"""BRO's governed library of external sources.

Acquisition and study are different trust boundaries and this module sits between
them. Fetching something is not the same as admitting it: material arrives STAGED, it is
SCREENED against the authorized source policy, and only then may it be approved into the
corpus STUDY can read. Nothing here fetches anything, and nothing here studies anything.

**What APPROVED_FOR_STUDY means, exactly.** It means the source passed the screening
gates: it is named in the authorized source policy at the address it was fetched from, its
provenance is complete, its corpus path is contained and study-eligible, and its bytes
carry no credential and match the declared language. It does **not** mean a person read the
document and fact-checked its statements. That is a different claim about a different kind
of work, it is recorded in its own field, and it is never inferred from this status --
which is why the state is called SCREENED rather than REVIEWED. A name that overstates what
was done is how a governance record starts lying quietly.

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
    SCREENED = "SCREENED"
    APPROVED_FOR_STUDY = "APPROVED_FOR_STUDY"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"

    @classmethod
    def _missing_(cls, value):
        # Rows written before the state was renamed said REVIEWED, which claimed more than
        # the step performed. The history keeps the word it was written with; the state it
        # maps to is the one that is true.
        if str(value).upper() == "REVIEWED":
            return cls.SCREENED
        return None


class ContentReview(StrEnum):
    """Whether a person read the document itself. Never derived from SourceStatus."""

    NOT_HUMAN_REVIEWED = "NOT_HUMAN_REVIEWED"
    HUMAN_CONTENT_REVIEWED = "HUMAN_CONTENT_REVIEWED"


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
    screened_by: str = ""
    approved_by: str = ""
    superseded_by: str = ""
    screening_basis: str = ""
    approval_basis: str = ""
    content_review_state: ContentReview = ContentReview.NOT_HUMAN_REVIEWED
    content_reviewed_by: str = ""
    content_review_evidence: str = ""

    @property
    def study_visible(self) -> bool:
        return self.status is SourceStatus.APPROVED_FOR_STUDY

    @property
    def human_content_reviewed(self) -> bool:
        """Read only from the content-review field. Approval says nothing about this."""
        return self.content_review_state is ContentReview.HUMAN_CONTENT_REVIEWED


_COLUMNS = (
    "source_id", "shelf", "publisher", "canonical_url", "authority_class", "source_scope",
    "upstream_version", "acquired_at", "content_digest", "local_path", "status",
    "source_language", "license",
    "language_variant", "notes", "screened_by", "screened_at", "approved_by", "approved_at",
    "superseded_by", "screening_basis", "approval_basis", "content_review_state",
    "content_reviewed_by", "content_reviewed_at", "content_review_evidence",
)

# Columns added after the first release; an existing registry gains them in place.
_ADDED_COLUMNS = (
    ("screening_basis", "screening_basis TEXT NOT NULL DEFAULT ''"),
    ("approval_basis", "approval_basis TEXT NOT NULL DEFAULT ''"),
    ("content_review_state", "content_review_state TEXT NOT NULL DEFAULT 'NOT_HUMAN_REVIEWED'"),
    ("content_reviewed_by", "content_reviewed_by TEXT NOT NULL DEFAULT ''"),
    ("content_reviewed_at", "content_reviewed_at TEXT NOT NULL DEFAULT ''"),
    ("content_review_evidence", "content_review_evidence TEXT NOT NULL DEFAULT ''"),
)
_RENAMED_COLUMNS = (("reviewed_by", "screened_by"), ("reviewed_at", "screened_at"))

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
# What the study reader can actually open. A corpus file it would skip is not eligible.
STUDY_ELIGIBLE_SUFFIXES = (".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini")
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
              screened_by TEXT NOT NULL,
              screened_at TEXT NOT NULL,
              approved_by TEXT NOT NULL,
              approved_at TEXT NOT NULL,
              superseded_by TEXT NOT NULL,
              screening_basis TEXT NOT NULL DEFAULT '',
              approval_basis TEXT NOT NULL DEFAULT '',
              content_review_state TEXT NOT NULL DEFAULT 'NOT_HUMAN_REVIEWED',
              content_reviewed_by TEXT NOT NULL DEFAULT '',
              content_reviewed_at TEXT NOT NULL DEFAULT '',
              content_review_evidence TEXT NOT NULL DEFAULT ''
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
        self._migrate()
        self.connection.commit()

    def _migrate(self) -> None:
        """Bring a registry written by an earlier revision up to the current shape.

        Nothing is dropped. The two renamed columns keep their values, and rows that were
        written as REVIEWED become SCREENED -- the same event, under the name that does not
        claim a person read the document.
        """
        present = {row[1] for row in self.connection.execute(
            "PRAGMA table_info(bro_knowledge_sources)")}
        for old, new in _RENAMED_COLUMNS:
            if old in present and new not in present:
                self.connection.execute(
                    f"ALTER TABLE bro_knowledge_sources RENAME COLUMN {old} TO {new}")
                present.add(new)
        for name, ddl in _ADDED_COLUMNS:
            if name not in present:
                self.connection.execute(f"ALTER TABLE bro_knowledge_sources ADD COLUMN {ddl}")
        self.connection.execute(
            "UPDATE bro_knowledge_sources SET status=? WHERE status=?",
            (SourceStatus.SCREENED.value, "REVIEWED"))

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
                 source.notes, "", "", "", "", "", "", "",
                 ContentReview.NOT_HUMAN_REVIEWED.value, "", "", ""),
            )
            self._transition(source.source_id, "", SourceStatus.STAGED.value, "acquisition",
                             f"acquired from {source.canonical_url}")
        return source

    def screen(self, source_id: str, *, screened_by: str, policy: Mapping[str, Mapping[str, str]],
               policy_ref: str, reason: str = "") -> KnowledgeSource:
        """Check the staged source against the authorized source policy, and say what passed.

        This is the step that used to be called `review`, and the rename is the point. A
        person clicking past fifty documents proves nothing that can be re-checked later;
        these gates can be re-run by anyone, on any day, against the same policy file. What
        SCREENED asserts is exactly the list recorded in the screening basis -- no more.
        """
        who = self._text(screened_by, "screened_by")
        current = self.source(source_id)
        if current.status is not SourceStatus.STAGED:
            raise KnowledgeLibraryRejected(
                f"screening requires STAGED, not {current.status.value}")
        basis = self.screening_basis(current, policy=policy, policy_ref=policy_ref)
        return self._advance(source_id, SourceStatus.STAGED, SourceStatus.SCREENED,
                             actor=who, actor_column="screened",
                             reason=reason or basis, basis_column="screening_basis", basis=basis)

    def rescreen(self, source_id: str, *, screened_by: str,
                 policy: Mapping[str, Mapping[str, str]], policy_ref: str,
                 reason: str) -> KnowledgeSource:
        """Send an approved source back through screening, deliberately and on the record."""
        current = self.source(source_id)
        if current.status is not SourceStatus.APPROVED_FOR_STUDY:
            raise KnowledgeLibraryRejected(
                f"re-screening requires APPROVED_FOR_STUDY, not {current.status.value}")
        basis = self.screening_basis(current, policy=policy, policy_ref=policy_ref)
        return self._advance(source_id, SourceStatus.APPROVED_FOR_STUDY, SourceStatus.SCREENED,
                             actor=self._text(screened_by, "screened_by"),
                             actor_column="screened", reason=self._text(reason, "reason"),
                             basis_column="screening_basis", basis=basis)

    def screening_basis(self, source: KnowledgeSource, *,
                        policy: Mapping[str, Mapping[str, str]], policy_ref: str) -> str:
        """Run every screening gate and return what they establish, or refuse by name."""
        policy_ref = self._text(policy_ref, "policy_ref")
        authorized = policy.get(source.canonical_url)
        if authorized is None:
            raise KnowledgeLibraryRejected(
                f"{source.canonical_url} is not named in the authorized source policy")
        for field in ("shelf", "publisher", "authority_class", "source_scope"):
            declared = str(authorized.get(field, "")).strip()
            actual = str(getattr(source, field))
            if isinstance(getattr(source, field), AuthorityClass):
                actual = getattr(source, field).value
            if declared and declared != actual:
                raise KnowledgeLibraryRejected(
                    f"{source.local_path}: policy declares {field}={declared!r}, "
                    f"the source carries {actual!r}")
        missing = [field for field in ("publisher", "canonical_url", "source_scope",
                                       "upstream_version", "content_digest", "source_language")
                   if not str(getattr(source, field)).strip()]
        if missing:
            raise KnowledgeLibraryRejected(f"{source.local_path}: provenance is incomplete: {missing}")
        if not self.acceptable_path(source.local_path):
            raise KnowledgeLibraryRejected(f"{source.local_path}: not a containable corpus path")
        if Path(source.local_path).suffix.lower() not in STUDY_ELIGIBLE_SUFFIXES:
            raise KnowledgeLibraryRejected(f"{source.local_path}: not a study-eligible document")
        return (f"source-policy={policy_ref}; official-provenance-verified; "
                f"authority={source.authority_class.value}; scope-declared; "
                f"path-contained; study-eligible; credential-screened; "
                f"language-verified={source.source_language}; "
                f"digest={source.content_digest[:16]}")

    def approve(self, source_id: str, *, approved_by: str, content: bytes,
                approval_basis: str, reason: str = "") -> KnowledgeSource:
        """Admit a screened source into the corpus, on a basis it must state.

        Approval re-checks the bytes, because screening one document and approving another
        is the failure this guards. What it does NOT do is assert that anyone read the
        document: the content-review field is untouched here, on purpose, so no amount of
        approving can ever add up to a claim that a person fact-checked the text.
        """
        current = self.source(source_id)
        if self.digest(content) != current.content_digest:
            raise KnowledgeLibraryRejected(
                "content changed since it was screened; re-acquire and screen it again")
        # The basis requirement is enforced once, in _advance, so there is one place to
        # delete and one test that reddens when someone does.
        basis = str(approval_basis or "").strip()
        return self._advance(source_id, SourceStatus.SCREENED, SourceStatus.APPROVED_FOR_STUDY,
                             actor=approved_by, actor_column="approved",
                             reason=reason or basis, basis_column="approval_basis", basis=basis)

    def record_content_review(self, source_id: str, *, reviewed_by: str,
                              evidence: str) -> KnowledgeSource:
        """Record that a person read this document and stands behind its content.

        Separate on purpose, and never a side effect of anything. It names who read it and
        what they produced -- a note, a ticket, a signed-off summary -- because a review with
        no artifact is indistinguishable from no review at all.
        """
        who = self._text(reviewed_by, "reviewed_by")
        artifact = self._text(evidence, "evidence")
        current = self.source(source_id)
        with self.connection:
            self.connection.execute(
                "UPDATE bro_knowledge_sources SET content_review_state=?,content_reviewed_by=?,"
                "content_reviewed_at=?,content_review_evidence=? WHERE source_id=?",
                (ContentReview.HUMAN_CONTENT_REVIEWED.value, who, utc_now(), artifact, source_id),
            )
            self._transition(source_id, current.status.value, current.status.value, who,
                             f"human content review recorded: {artifact}")
        return self.source(source_id)

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
                 actor: str, actor_column: str, reason: str,
                 basis_column: str = "", basis: str = "") -> KnowledgeSource:
        who = self._text(actor, actor_column + "_by")
        current = self.source(source_id)
        if current.status is not expected:
            raise KnowledgeLibraryRejected(
                f"{target.value} requires {expected.value}, not {current.status.value}")
        if basis_column and not basis:
            raise KnowledgeLibraryRejected(f"{target.value} requires a recorded {basis_column}")
        assignments = f"status=?,{actor_column}_by=?,{actor_column}_at=?"
        values: list[object] = [target.value, who, utc_now()]
        if basis_column:
            assignments += f",{basis_column}=?"
            values.append(basis)
        values.append(source_id)
        with self.connection:
            self.connection.execute(
                f"UPDATE bro_knowledge_sources SET {assignments} WHERE source_id=?", values)
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
                "approval_basis": item.approval_basis,
                "content_review_state": item.content_review_state.value,
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
            source_language=row["source_language"], license=row["license"],
            language_variant=LanguageVariant(row["language_variant"]),
            notes=row["notes"], screened_by=row["screened_by"], approved_by=row["approved_by"],
            superseded_by=row["superseded_by"],
            screening_basis=row["screening_basis"], approval_basis=row["approval_basis"],
            content_review_state=ContentReview(row["content_review_state"]),
            content_reviewed_by=row["content_reviewed_by"],
            content_review_evidence=row["content_review_evidence"],
        )
