"""The single governed entry through which a BRO action outcome becomes experience.

Both production ACT paths — the conversational surface and the canonical acceptance
script — submit their governed receipts here. This is deliberately not a second
execution path and not a second learning authority: it executes nothing, authorises
nothing, and owns no storage. It decides one thing, using the same truth rules the
execution runtime already enforces: whether an outcome carries enough independently
verified evidence to become a reusable lesson, and it files the outcome either way.

Model output is inference. It supplies proposed guidance, a skill name, a trigger and
a procedure. It never supplies the pattern an outcome is filed under, the observations
that support a lesson, the evidence references, or the confidence — those are derived
here from the governed receipt, so a model cannot merge, split or inflate BRO's
learned state. Model identity is recorded as provenance and owns nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Mapping, Sequence

from .learning_memory import BINDING_PREFIX, DurableLearningMemory, Provenance, SkillCandidate, utc_now

EXTERNAL_ASSURANCE = frozenset({"external_system", "production"})

# What the model is allowed to see about a receipt. Credentials, tokens and raw
# provider payloads are not in this set and never reach the extractor.
RECEIPT_FIELDS_FOR_EXTRACTION = (
    "specialist_ref", "provider_ref", "effect_ref", "readback_ref",
    "readback_provider_ref", "evidence_ref", "assurance",
)


class LearningEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    FAILED_OUTCOME = "FAILED_OUTCOME"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    INSUFFICIENT_ASSURANCE = "INSUFFICIENT_ASSURANCE"
    SELF_ATTESTED = "SELF_ATTESTED"


@dataclass(frozen=True)
class ExperienceContext:
    """Everything about the run that BRO owns, independent of who reasoned."""

    request: str
    mode: str = "ACT"
    interpreted_scope: tuple[str, ...] = ()
    source_revision: str = ""
    environment: str = ""
    instance_id: str = ""
    model_ref: str = ""
    target_ref: str = ""

    def provenance(self) -> Provenance:
        now = utc_now()
        return Provenance(
            model_ref=self.model_ref, source_revision=self.source_revision,
            environment=self.environment, instance_id=self.instance_id,
            first_seen_at=now, last_seen_at=now,
        )


@dataclass(frozen=True)
class LearningSubmission:
    eligibility: LearningEligibility
    recorded: bool
    pattern_key: str = ""
    lesson_created: bool = False
    candidate: SkillCandidate | None = None
    observations: tuple[str, ...] = ()
    error: str = ""

    @property
    def became_lesson(self) -> bool:
        return self.lesson_created


class GovernedLearningBoundary:
    """Submit governed outcomes to BRO's one outcome-learning mechanism."""

    def __init__(
        self,
        memory: DurableLearningMemory,
        *,
        extractor: Callable[[str, Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        self.memory = memory
        self.extractor = extractor

    # ------------------------------------------------------------- truth rules
    @staticmethod
    def capability_class(provider_ref: str) -> str:
        """The runtime-owned identity of what actually acted.

        ``github:github-issue-comment@v1:write`` and its ``:readback`` twin are the same
        capability. Deriving the pattern from this rather than from the model's chosen
        specialist keeps a lesson findable after the reasoning model is replaced.
        """
        parts = [part for part in str(provider_ref or "").split(":") if part]
        if len(parts) >= 3:
            return ":".join(parts[:-1])
        return ":".join(parts)

    @classmethod
    def eligibility(cls, receipt: Mapping[str, Any]) -> LearningEligibility:
        """Apply the same evidence rules the execution runtime already enforces."""
        assurance = str(receipt.get("assurance", "")).strip()
        effect_ref = str(receipt.get("effect_ref", "")).strip()
        readback_ref = str(receipt.get("readback_ref", "")).strip()
        evidence_ref = str(receipt.get("evidence_ref", "")).strip()
        provider_ref = str(receipt.get("provider_ref", "")).strip()
        readback_provider_ref = str(receipt.get("readback_provider_ref", "")).strip()
        if not (effect_ref and readback_ref and evidence_ref):
            return LearningEligibility.MISSING_EVIDENCE
        if assurance not in EXTERNAL_ASSURANCE:
            return LearningEligibility.INSUFFICIENT_ASSURANCE
        if provider_ref and provider_ref == readback_provider_ref:
            return LearningEligibility.SELF_ATTESTED
        if readback_ref == effect_ref:
            return LearningEligibility.SELF_ATTESTED
        return LearningEligibility.ELIGIBLE

    def pattern_key(self, context: ExperienceContext, receipt: Mapping[str, Any]) -> str:
        return self.memory.pattern_digest(context.request, self.capability_class(str(receipt.get("provider_ref", ""))))

    @staticmethod
    def observations(context: ExperienceContext, receipt: Mapping[str, Any]) -> tuple[str, ...]:
        """Facts, not prose. Derived from the receipt, never from the model."""
        capability = GovernedLearningBoundary.capability_class(str(receipt.get("provider_ref", "")))
        facts = [
            f"{BINDING_PREFIX}capability={capability}",
            f"observed:assurance={str(receipt.get('assurance', '')).strip()}",
            f"observed:effect_ref={str(receipt.get('effect_ref', '')).strip()}",
            f"observed:readback_ref={str(receipt.get('readback_ref', '')).strip()}",
            f"observed:evidence_ref={str(receipt.get('evidence_ref', '')).strip()}",
            f"observed:specialist_ref={str(receipt.get('specialist_ref', '')).strip()}",
        ]
        if context.environment:
            facts.insert(0, f"{BINDING_PREFIX}environment={context.environment}")
        if context.target_ref:
            facts.insert(0, f"{BINDING_PREFIX}target_ref={context.target_ref}")
        if context.source_revision:
            facts.append(f"observed:source_revision={context.source_revision}")
        if context.model_ref:
            facts.append(f"provenance:model_ref={context.model_ref}")
        return tuple(fact for fact in facts if not fact.endswith("="))

    @staticmethod
    def sanitized_receipt(receipt: Mapping[str, Any]) -> dict[str, str]:
        return {key: str(receipt.get(key, "")).strip() for key in RECEIPT_FIELDS_FOR_EXTRACTION if str(receipt.get(key, "")).strip()}

    # --------------------------------------------------------------- submission
    def submit_success(self, context: ExperienceContext, receipt: Mapping[str, Any]) -> LearningSubmission:
        """Record an outcome that the execution runtime already returned as a receipt.

        This never raises into the caller. A governed action that has already happened
        and been independently read back stays true whatever the learning subsystem does.
        """
        eligibility = self.eligibility(receipt)
        pattern_key = ""
        observations: tuple[str, ...] = ()
        try:
            pattern_key = self.pattern_key(context, receipt)
            observations = self.observations(context, receipt)
            if eligibility is not LearningEligibility.ELIGIBLE:
                self._file_experience(context, receipt, success=True, learning=None, pattern_key=pattern_key)
                return LearningSubmission(eligibility, recorded=True, pattern_key=pattern_key, observations=observations)
            learning = self._extract(context, receipt)
            if learning is None:
                self._file_experience(context, receipt, success=True, learning=None, pattern_key=pattern_key)
                return LearningSubmission(eligibility, recorded=True, pattern_key=pattern_key, observations=observations,
                                          error="no lesson extractor configured")
            candidate = self._file_experience(
                context, receipt, success=True, learning=learning, pattern_key=pattern_key, observations=observations
            )
            return LearningSubmission(eligibility, recorded=True, pattern_key=pattern_key, lesson_created=True,
                                      candidate=candidate, observations=observations)
        except Exception as exc:  # learning must never rewrite an executed truth
            return LearningSubmission(eligibility, recorded=False, pattern_key=pattern_key,
                                      observations=observations, error=f"{type(exc).__name__}:{exc}")

    def submit_failure(self, context: ExperienceContext, *, error_ref: str, receipt: Mapping[str, Any] | None = None) -> LearningSubmission:
        """Keep the failure as experience. It can lower confidence; it can never raise it."""
        receipt = dict(receipt or {})
        pattern_key = ""
        try:
            pattern_key = self.pattern_key(context, receipt) if receipt.get("provider_ref") else ""
            self.memory.record_outcome(
                request=context.request, success=False, error_ref=error_ref,
                specialist_ref=str(receipt.get("specialist_ref", "")), provider_ref=str(receipt.get("provider_ref", "")),
                interpreted_scope=context.interpreted_scope, mode=context.mode,
                provenance=context.provenance(), pattern_key=pattern_key,
            )
            return LearningSubmission(LearningEligibility.FAILED_OUTCOME, recorded=True, pattern_key=pattern_key)
        except Exception as exc:
            return LearningSubmission(LearningEligibility.FAILED_OUTCOME, recorded=False, pattern_key=pattern_key,
                                      error=f"{type(exc).__name__}:{exc}")

    def _file_experience(
        self, context: ExperienceContext, receipt: Mapping[str, Any], *, success: bool,
        learning: Mapping[str, Any] | None, pattern_key: str, observations: Sequence[str] = (),
    ) -> SkillCandidate | None:
        return self.memory.record_outcome(
            request=context.request,
            success=success,
            specialist_ref=str(receipt.get("specialist_ref", "")),
            evidence_ref=str(receipt.get("evidence_ref", "")),
            learning=learning,
            observations=observations,
            provenance=context.provenance(),
            interpreted_scope=context.interpreted_scope,
            provider_ref=str(receipt.get("provider_ref", "")),
            effect_ref=str(receipt.get("effect_ref", "")),
            readback_ref=str(receipt.get("readback_ref", "")),
            readback_provider_ref=str(receipt.get("readback_provider_ref", "")),
            assurance=str(receipt.get("assurance", "")),
            mode=context.mode,
            pattern_key=pattern_key,
        )

    def _extract(self, context: ExperienceContext, receipt: Mapping[str, Any]) -> dict[str, Any] | None:
        if self.extractor is None:
            return None
        proposed = dict(self.extractor(context.request, self.sanitized_receipt(receipt)))
        # The model proposes guidance; BRO decides identity. Overriding the pattern key
        # here is what stops a model from merging or splitting BRO's learned state.
        proposed["pattern_key"] = self.pattern_key(context, receipt)
        return proposed

    # ---------------------------------------------------------------- retrieval
    def advisory_context(
        self, request: str, *, current_truth: Mapping[str, str], limit: int = 5,
        record_contradictions: bool = True,
    ) -> dict[str, Any]:
        """Prior verified experience, offered as context and never as permission.

        Retrieval itself is a pure read. Filing a contradiction is a separate write and
        is allowed to fail: a contradiction is always surfaced in the returned payload,
        so a store that cannot be written loses the record but never hides the finding
        and never breaks the turn.
        """
        retrieval = self.memory.retrieve(request, current_truth=current_truth, limit=limit)
        recorded, record_error = False, ""
        if record_contradictions and retrieval.contradictions:
            try:
                self.memory.record_contradictions(retrieval.contradictions)
                recorded = True
            except Exception as exc:
                record_error = f"{type(exc).__name__}:{exc}"
        return {
            "advisory": True,
            "grants_authority": False,
            "contradictions_recorded": recorded,
            "contradiction_record_error": record_error,
            "lessons": [
                {
                    "pattern_key": lesson.pattern_key,
                    "guidance": lesson.lesson,
                    "skill_name": lesson.skill_name,
                    "trigger": lesson.trigger,
                    "procedure": list(lesson.procedure),
                    "observations": list(lesson.observations),
                    "status": lesson.status.value,
                    "confidence": lesson.confidence,
                    "evidenced_successes": lesson.successes,
                    "failures": lesson.failures,
                    "provenance": lesson.provenance.as_dict(),
                }
                for lesson in retrieval.lessons
            ],
            "withheld_for_contradiction": [
                {
                    "pattern_key": item.pattern_key,
                    "field": item.field_name,
                    "learned_value": item.learned_value,
                    "current_value": item.current_value,
                }
                for item in retrieval.contradictions
            ],
        }
