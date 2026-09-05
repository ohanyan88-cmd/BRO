"""The vocabulary a study programme is described in, and nothing that decides anything.

This module used to hold the answer to "how far through the programme is BRO", and it
answered by searching the words of a claim for a domain's keywords. That answer was wrong
twice in opposite directions. Once it accepted a single ordinary word and reported 27 of 32
domains covered on BRO's own architecture notes -- including Rust, which had never been
opened. Once, corrected, it demanded phrase forms no publisher writes and scored thirty
verified rows from the Rust Book as one, stranding a domain in PARTIAL while every source
that could have advanced it was already withheld as sufficiently studied.

The second correction is what showed the mechanism was the problem. A keyword set is a guess
about how a document will phrase itself, and a guess cannot be the authoritative record of
what a system has learned. Coverage now lives in :mod:`bro_runtime.curriculum_manifest`,
where a requirement is satisfied by verified knowledge retained from the canonical documents
the curriculum declares for it -- decided by which document the evidence came from, never by
which words it contains.

What remains here is shared vocabulary: the three states a domain can be in, the grounds on
which studied material may be read again, and the rejection every curriculum raises.
"""
from __future__ import annotations

from enum import StrEnum


class CurriculumRejected(RuntimeError):
    pass


class DomainState(StrEnum):
    COVERED = "COVERED"
    PARTIAL = "PARTIAL"
    UNSTUDIED = "UNSTUDIED"


class RevisitReason(StrEnum):
    """The only grounds on which already-studied material may be planned again."""

    CONTRADICTION = "CONTRADICTION"
    STALE_SOURCE = "STALE_SOURCE"
    MISSING_VERIFICATION = "MISSING_VERIFICATION"
    DEPENDENCY_DEPTH = "DEPENDENCY_DEPTH"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    EXPLICIT_REFRESH = "EXPLICIT_REFRESH"
