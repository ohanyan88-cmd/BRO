#!/usr/bin/env python3
"""Interactive CLI for BRO conversation plus governed production execution."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bro_runtime.conversation import ConversationalInteractionSurface, InteractionMode
from bro_runtime.curriculum import CurriculumRejected
from bro_runtime.curriculum_manifest import CurriculumManifest
from bro_runtime.inference import InferenceRejected
from bro_runtime.model_provider import build_model as build_configured_model
from bro_runtime.final_delivery import IntelligentInteractionRuntime
from bro_runtime.github_provider import (
    GitHubAcceptanceTarget,
    GitHubIssueCommentProvider,
    GitHubProviderRejected,
)
from bro_runtime.interaction_surface import InteractionSurface
from bro_runtime.learning_boundary import ExperienceContext, GovernedLearningBoundary
from bro_runtime.learning_memory import DurableLearningMemory
from bro_runtime.knowledge_library import GovernedKnowledgeLibrary, KnowledgeLibraryRejected
from bro_runtime.source_policy import SourcePolicy, SourcePolicyRejected
from bro_runtime.study_acquisition import (
    AcquisitionRejected,
    AcquisitionResult,
    GovernedStudyAcquisition,
    LinkFrontier,
)
from bro_runtime.study_runtime import GovernedStudyRuntime, StudyContext, StudyRejected, StudySourceReader


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def build_model():
    """Provider selection lives in one place; this surface does not care which answered."""
    try:
        return build_configured_model(os.environ)
    except InferenceRejected as exc:
        raise SystemExit(str(exc)) from None


def memory_database_path() -> str:
    return os.environ.get("BRO_MEMORY_DB_PATH", "/var/lib/bro/runtime.sqlite3").strip()


def study_root() -> str:
    """Self-study reads the deployed release by default, and only ever reads."""
    return os.environ.get("BRO_STUDY_ROOT", str(ROOT)).strip()


DEFAULT_STUDY_ITEM_BUDGET = 30
DEFAULT_STUDY_DIMINISHING_AFTER = 6
DEFAULT_ACQUISITION_BUDGET = 8


def _positive(name: str, default: int) -> int:
    """A study limit is a positive count. A malformed one falls back rather than disabling the limit."""
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def study_item_budget() -> int:
    """How many curriculum items one mission may study before it stops."""
    return _positive("BRO_STUDY_ITEM_BUDGET", DEFAULT_STUDY_ITEM_BUDGET)


def acquisition_enabled() -> bool:
    """Whether STUDY may reach the Internet at all. Off unless an operator says otherwise."""
    return os.environ.get("BRO_STUDY_ACQUISITION", "").strip().lower() in {"1", "true", "yes", "on"}


def proposed_sources(model, subject: str, entry_points=()) -> tuple[list[str], set[str]]:
    """The declared entry points first, then whatever the model suggests -- and the declared
    ones survive the model failing.

    They did not, once. The model call raised, the handler reset the whole proposal list to
    empty, and a mission that had been handed the exact canonical document to fetch acquired
    nothing and reported its corpus exhausted. A curriculum's declared source does not depend
    on a model being reachable; that is most of the point of declaring it.
    """
    declared = [str(url) for url in (entry_points or ())]
    proposed = list(declared)
    try:
        answer = model.propose_sources(subject)
        for entry in answer.get("sources", []) or []:
            if isinstance(entry, Mapping) and entry.get("url"):
                proposed.append(str(entry["url"]))
    except (InferenceRejected, AttributeError, TypeError):
        pass
    return proposed, set(declared)


def master_curriculum_path() -> str:
    return os.environ.get("BRO_CURRICULUM_MANIFEST",
                          str(ROOT / "contracts" / "curriculum_manifest.json")).strip()


def load_master_curriculum():
    """The long programme, or None. Without it a mission is bounded and has no memory of
    territory, which is exactly how it behaved before.

    This is the curriculum manifest: where each domain is studied and what evidence settles
    a requirement. It replaced a keyword model whose authoritative answer to "has BRO
    learned this" was decided by which strings someone guessed into a contract.
    """
    try:
        return CurriculumManifest.load(master_curriculum_path())
    except CurriculumRejected as exc:
        print(f"BRO curriculum manifest unavailable: {exc}", file=sys.stderr)
        return None


def source_policy_path() -> str:
    return os.environ.get("BRO_SOURCE_POLICY", str(ROOT / "contracts" / "source_policy.json")).strip()


def study_refresh_requested() -> bool:
    """Whether covered ground may be re-read. An operator setting, never mission prose.

    It was prose once. A continuation mission saying "do not re-study material that is
    already sufficiently verified" contained the phrase "re-study", turned the switch on,
    and disabled the very withholding it was asking for -- the prohibition activated its own
    opposite. A capability that reverses a boundary has to be stated by an operator, the same
    way acquisition is.
    """
    return os.environ.get("BRO_STUDY_REFRESH", "").strip().lower() in {"1", "true", "yes", "on"}


def acquisition_budget() -> int:
    return _positive("BRO_STUDY_ACQUISITION_BUDGET", DEFAULT_ACQUISITION_BUDGET)


def study_diminishing_after() -> int:
    """How many consecutive barren sources end a mission for diminishing returns.

    A wide corpus is uneven: a run over many shelves passes through stretches that teach
    nothing without being finished. Ending on the second such source is right for a small
    repository read and wrong for a library."""
    return _positive("BRO_STUDY_DIMINISHING_AFTER", DEFAULT_STUDY_DIMINISHING_AFTER)


def current_truth() -> dict[str, str]:
    """What is true now. It outranks anything BRO remembers."""
    return {
        "environment": os.environ.get("BRO_ENVIRONMENT", "").strip(),
        "source_revision": os.environ.get("BRO_SOURCE_REVISION", "").strip(),
    }


def build_surface() -> ConversationalInteractionSurface:
    model = build_model()
    memory_connection = sqlite3.connect(memory_database_path(), timeout=10)
    memory = DurableLearningMemory(memory_connection)

    def extract_lesson(request: str, receipt_facts: dict) -> dict:
        return model.json_object(
            instruction=(
                "Extract one reusable operational lesson from a successfully verified BRO action. "
                "Required keys: lesson, skill_name, trigger, procedure. Optional keys: intended_outcome, "
                "preconditions, required_authority, failure_modes. procedure, preconditions and failure_modes "
                "must be arrays of concrete strings. Generalize only what the supplied evidence supports. "
                "Do not invent permissions, credentials, systems, or success beyond the supplied receipt."
            ),
            request=json.dumps({"request": request, "receipt": receipt_facts}, ensure_ascii=False, sort_keys=True),
        )

    boundary = GovernedLearningBoundary(memory, extractor=extract_lesson)

    def study_context() -> StudyContext:
        truth = current_truth()
        return StudyContext(
            environment=truth["environment"], source_revision=truth["source_revision"],
            instance_id=os.environ.get("BRO_INSTANCE_ID", "").strip(),
            model_ref=model.config.model_ref, root_ref=study_root(),
        )

    def run_study(request: str) -> dict:
        # Read-and-learn only: this runtime has no executor and no provider, so a study
        # mission cannot become permission to change anything.
        try:
            reader = StudySourceReader(study_root())
        except StudyRejected as exc:
            return {
                "mission": request, "status": "BLOCKED", "stop_reason": "SOURCE_UNAVAILABLE",
                "curriculum": {"planned": 0, "studied": 0, "blocked": 0, "remaining": []},
                "knowledge": {"verified": 0, "inference": 0, "unverified_observation": 0},
                "uncertain_topics": [], "contradictions": [], "notes": [str(exc)],
                "external_effects": 0, "grants_authority": False,
            }
        runtime = GovernedStudyRuntime(
            memory, reader,
            planner=lambda mission, sources, coverage=None: model.study_plan(
                mission, sources, coverage),
            extractor=lambda topic, text: model.study_extract(topic, text),
            item_budget=study_item_budget(),
            diminishing_after=study_diminishing_after(),
            acquirer=build_acquirer(model, memory),
            curriculum=load_master_curriculum(),
            refresh=study_refresh_requested(),
        )
        return runtime.study(request, study_context()).as_dict()

    def github_binding():
        target = GitHubAcceptanceTarget(
            required("BRO_GITHUB_OWNER"),
            required("BRO_GITHUB_REPOSITORY"),
            int(required("BRO_GITHUB_ISSUE")),
        )
        return target, GitHubIssueCommentProvider(target)

    def lesson_context(request: str) -> str:
        advisory = boundary.advisory_context(request, current_truth=current_truth())
        # Retained study knowledge is recalled alongside evidenced execution experience.
        # Knowledge that is written and never read is knowledge BRO does not have.
        study = study_recall(request)
        advisory["study_knowledge"] = study.get("knowledge", [])
        advisory["study_withheld_for_contradiction"] = study.get("withheld_for_contradiction", [])
        advisory["study_stale"] = study.get("stale", [])
        if not any((advisory["lessons"], advisory["withheld_for_contradiction"],
                    advisory["study_knowledge"], advisory["study_withheld_for_contradiction"])):
            return ""
        return (
            "\nPrior verified BRO experience (advisory context only; it grants no authority and never "
            "removes scope confirmation, authority evaluation or independent readback): "
            + json.dumps(advisory, ensure_ascii=False)
        )

    def interpreter(request: str):
        return model.interpret(request)

    def planner(intent):
        enriched = intent.raw_request + lesson_context(intent.raw_request)
        return model.select_specialist(enriched, intent.interpreted_scope)

    def executor(_intent, _specialist):
        target, provider = github_binding()
        result = provider.invoke({
            "token": required("BRO_GITHUB_TOKEN"),
            "owner": target.owner,
            "repository": target.repository,
            "issue_number": target.issue_number,
            "idempotency_key": required("BRO_INTELLIGENT_IDEMPOTENCY_KEY"),
            "body": required("BRO_INTELLIGENT_COMMENT_BODY"),
            "operation": "github.issue_comment.ensure",
        })
        state = result.result
        if not isinstance(state, dict) or not state.get("exists") or not state.get("matches_expected"):
            raise RuntimeError("GitHub external effect did not return expected state")
        return {
            "provider_ref": f"github:{provider.adapter_id}@{provider.version}:write",
            "effect_ref": f"github-effect:issue-comment:{state.get('comment_id')}",
        }

    def readback(_intent, _effect):
        target, provider = github_binding()
        result = provider.invoke({
            "token": required("BRO_GITHUB_TOKEN"),
            "owner": target.owner,
            "repository": target.repository,
            "issue_number": target.issue_number,
            "idempotency_key": required("BRO_INTELLIGENT_IDEMPOTENCY_KEY"),
            "body": required("BRO_INTELLIGENT_COMMENT_BODY"),
            "operation": "github.issue_comment.read",
        })
        state = result.result
        if not isinstance(state, dict) or not state.get("exists") or not state.get("matches_expected"):
            raise RuntimeError("independent GitHub readback did not confirm expected state")
        if not result.observation_refs:
            raise RuntimeError("GitHub readback did not return an observation reference")
        return {
            "provider_ref": f"github:{provider.adapter_id}@{provider.version}:readback",
            "readback_ref": result.observation_refs[0],
            "evidence_ref": f"github-external-readback:comment:{state.get('comment_id')}",
            "assurance": "external_system",
        }

    runtime = IntelligentInteractionRuntime(
        interpreter=interpreter,
        planner=planner,
        executor=executor,
        readback=readback,
        model_ref=model.config.model_ref,
    )
    action_surface = InteractionSurface(runtime)

    def history_payload(history):
        return [{"role": item.role, "content": item.content} for item in history]

    def router(request, history):
        return model.route_interaction(request, history_payload(history))

    def responder(mode: InteractionMode, request: str, history):
        # The durable record goes in the system position, not into the chat, so a prior
        # conversational reply cannot outrank what BRO has actually written down.
        return model.conversational_response(
            mode.value, request, history_payload(history), record=lesson_context(request)
        )

    def record_message(role: str, content: str, mode: str) -> None:
        memory.append_message(role, content, mode=mode)

    def build_acquirer(model, memory):
        """Wire STUDY to the governed acquisition boundary, or to nothing at all.

        Returning None is a real answer: with acquisition off, the study runtime has no
        acquirer to call and behaves exactly as it did before, which is what makes this
        capability something an operator grants rather than something the code assumes.
        """
        if not acquisition_enabled():
            return None
        try:
            policy = SourcePolicy.load(source_policy_path())
        except SourcePolicyRejected as exc:
            print(f"BRO study acquisition is disabled: {exc}", file=sys.stderr)
            return None
        library = GovernedKnowledgeLibrary(memory)
        acquisition = GovernedStudyAcquisition(policy, library, study_root())
        frontier_budget = acquisition_budget()

        def acquire(subject: str, hints, record=None, entry_points=()) -> tuple[str, ...]:
            """Fetch what the curriculum declares first, and only then ask the model.

            Every acquired document in the corpus carries ``discovered_from: model-proposed``,
            because until now the question "where is this studied" was answered by whichever
            urls a model produced and the policy happened to admit. The policy checks the
            host; it has never checked that the url is the right document. A declared entry
            point is that missing half, and it goes first.
            """
            def note(url: str, host: str, outcome, detail: str = "") -> None:
                if record is not None:
                    record(url, host, getattr(outcome, "value", str(outcome)), detail)

            frontier = LinkFrontier(policy, mission_budget=frontier_budget)
            proposed, declared = proposed_sources(model, subject, entry_points)
            candidates = list(acquisition.propose(proposed, topic=subject))
            if not candidates:
                note("", "", AcquisitionResult.NOT_PROPOSED,
                     "neither the curriculum manifest nor the model named a source the "
                     "policy could classify")
            # A declared document is what the curriculum says this domain is studied from,
            # so it is fetched before anything a model suggested for the same mission.
            candidates.sort(key=lambda candidate: candidate.url not in declared)
            admitted: list[str] = []
            depth_one: list[tuple[str, tuple[str, ...], Mapping[str, str]]] = []
            for candidate in candidates:
                if len(admitted) >= frontier_budget or not frontier.admit(candidate.url):
                    note(candidate.url, candidate.host, AcquisitionResult.BUDGET_EXHAUSTED,
                         "the mission's acquisition budget was already spent")
                    continue
                try:
                    outcome = acquisition.acquire(candidate)
                except (AcquisitionRejected, KnowledgeLibraryRejected) as exc:
                    note(candidate.url, candidate.host, AcquisitionResult.ACQUISITION_FAILED,
                         str(exc)[:200])
                    continue
                note(candidate.url, candidate.host, outcome.result, outcome.reason[:200])
                if outcome.admitted:
                    admitted.append(outcome.local_path)
                    depth_one.append((candidate.url, outcome.links, outcome.link_texts))
            for source_url, links, anchors in depth_one:
                if len(admitted) >= frontier_budget:
                    break
                for link in frontier.next_links(source_url, links, depth=1,
                                                topic=subject, anchors=anchors):
                    if len(admitted) >= frontier_budget or not frontier.admit(link):
                        continue
                    for follow in acquisition.propose([link], topic=subject,
                                                      discovered_from=source_url):
                        try:
                            outcome = acquisition.acquire(follow)
                        except (AcquisitionRejected, KnowledgeLibraryRejected) as exc:
                            note(follow.url, follow.host, AcquisitionResult.ACQUISITION_FAILED,
                                 str(exc)[:200])
                            continue
                        note(follow.url, follow.host, outcome.result, outcome.reason[:200])
                        if outcome.admitted:
                            admitted.append(outcome.local_path)
            return tuple(admitted)

        return acquire

    def study_recall(topic: str) -> dict:
        reader_root = study_root()
        try:
            runtime = GovernedStudyRuntime(
                memory, StudySourceReader(reader_root),
                planner=lambda mission, sources: {}, extractor=lambda topic_, text: {},
            )
        except StudyRejected:
            return {}
        return runtime.recall(topic, study_context())

    def experience_context(request: str, receipt) -> ExperienceContext:
        target_ref = ""
        if isinstance(receipt, dict) and receipt.get("effect_ref"):
            try:
                target_ref = github_binding()[0].resource_ref
            except SystemExit:
                target_ref = ""
        truth = current_truth()
        return ExperienceContext(
            request=request,
            mode="ACT",
            interpreted_scope=tuple(receipt.get("interpreted_scope", ())) if isinstance(receipt, dict) else (),
            source_revision=truth["source_revision"],
            environment=truth["environment"],
            instance_id=os.environ.get("BRO_INSTANCE_ID", "").strip(),
            model_ref=model.config.model_ref,
            target_ref=target_ref,
        )

    def record_outcome(request: str, success: bool, receipt, error_ref: str) -> None:
        if not success:
            boundary.submit_failure(experience_context(request, receipt), error_ref=error_ref,
                                    receipt=receipt if isinstance(receipt, dict) else None)
            return
        if not isinstance(receipt, dict):
            return
        submission = boundary.submit_success(experience_context(request, receipt), receipt)
        if submission.error:
            print(f"BRO learning warning > {submission.error}", file=sys.stderr)
        if submission.eligibility.value != "ELIGIBLE":
            print(f"BRO learning > outcome recorded as experience only ({submission.eligibility.value})")
        if submission.candidate is not None:
            print(
                "BRO learning > reusable skill candidate ready for explicit approval: "
                f"{submission.candidate.skill_name} ({submission.candidate.candidate_id}), "
                f"supporting executions={submission.candidate.supporting_executions}"
            )

    return ConversationalInteractionSurface(
        action_surface=action_surface,
        router=router,
        responder=responder,
        initial_history=memory.recent_messages(limit=12),
        message_recorder=record_message,
        outcome_recorder=record_outcome,
        study_runner=run_study,
    )


BLOCK_DELIMITER = '"""'


def read_request(read_line) -> str | None:
    """Read one request, even when the user pastes several lines.

    A pasted paragraph used to become one mission per line, which is how a fragment
    like a trailing clause became a study mission of its own. A line containing only the
    block delimiter opens a block and the next such line closes it; everything between is
    one request. Ordinary one-line interaction is untouched. Returns None at end of input.
    """
    try:
        first = read_line("You > ")
    except (EOFError, KeyboardInterrupt):
        return None
    if first is None:
        return None
    if first.strip() != BLOCK_DELIMITER:
        return first.strip()
    lines: list[str] = []
    while True:
        try:
            line = read_line("... > ")
        except (EOFError, KeyboardInterrupt):
            break
        if line is None or line.strip() == BLOCK_DELIMITER:
            break
        lines.append(line.rstrip("\n"))
    return "\n".join(lines).strip()


# A model or provider that is unavailable is an operational fact, not a bug in the
# conversation. It is reported in full and the session stays alive; it is never softened
# into a pretend answer, and a governance refusal is deliberately not caught here.
BOUNDARY_FAILURES = (InferenceRejected, GitHubProviderRejected)


def handle(surface: ConversationalInteractionSurface, request: str) -> int:
    """Run one turn. Returns 0, or 1 when a boundary was unavailable."""
    try:
        _dispatch(surface, request)
    except BOUNDARY_FAILURES as exc:
        print(f"BRO could not complete that request: {exc}", file=sys.stderr)
        print("Nothing was executed, and nothing was recorded as an outcome.", file=sys.stderr)
        return 1
    return 0


def _dispatch(surface: ConversationalInteractionSurface, request: str) -> None:
    result = surface.submit(request)
    mode = result["mode"]
    if mode in {InteractionMode.TALK.value, InteractionMode.THINK.value}:
        print(f"BRO [{mode}] > {result['response']}")
        return

    if mode == InteractionMode.STUDY.value:
        report = result["study"]
        curriculum = report["curriculum"]
        knowledge = report["knowledge"]
        print(f"BRO [STUDY] > mission: {report['mission']}")
        print(f"  curriculum : {curriculum['studied']} studied / {curriculum['planned']} planned"
              f" / {curriculum['blocked']} blocked")
        print(f"  knowledge  : {knowledge['verified']} verified, {knowledge['inference']} inferred,"
              f" {knowledge['unverified_observation']} unverified observation")
        targeting = report.get("targeting", {})
        if targeting:
            print(f"  targeting  : {targeting['targeted_sources']} of {targeting['available_sources']}"
                  f" discovered sources matched the mission hints"
                  f"{': ' + ', '.join(targeting['hints'][:8]) if targeting['hints'] else ''}")
        if curriculum["remaining"]:
            print(f"  remaining  : {', '.join(curriculum['remaining'])}")
        master = report.get("master_curriculum", {})
        selected = master.get("selected") or {}
        if selected:
            print(f"  requirement: {selected['domain']} / {selected['requirement']}"
                  f" -- {selected['competency']}")
            if selected.get("entry_point"):
                print(f"  entry point: {selected['entry_point']}")
        if master.get("source_gaps"):
            for gap in master["source_gaps"][:6]:
                print(f"  SOURCE_GAP : {gap['domain']} / {gap['requirement']}"
                      f" needs {gap['source_gap']['needed_publisher']}")
        if report["uncertain_topics"]:
            print(f"  uncertain  : {', '.join(report['uncertain_topics'])}")
        for note in report["notes"]:
            print(f"  note       : {note}")
        print(f"  stopped    : {report['stop_reason']} (no external effect)")
        return

    preview = result["action"]
    print("BRO [ACT] interpreted scope:")
    print(json.dumps(preview, ensure_ascii=False, sort_keys=True, indent=2))
    if preview["requires_confirmation"]:
        entered = input("Confirm by pasting the exact scope_digest (or type cancel): ").strip()
        if entered.lower() == "cancel":
            print("Cancelled; no external effect was attempted.")
            return
        digest = entered
    else:
        digest = preview["scope_digest"]
    receipt = surface.confirm_and_execute(
        preview["request_id"],
        confirmed_by=required("BRO_INTELLIGENT_CONFIRMED_BY"),
        scope_digest=digest,
    )
    print("BRO execution receipt:")
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2))
    if surface.learning_errors:
        print(f"BRO learning warning > {surface.learning_errors[-1]}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Talk, think, act, remember, and learn with BRO through the production path")
    parser.add_argument("request", nargs="*", help="Natural-language request; omit for an interactive conversation")
    args = parser.parse_args()
    surface = build_surface()
    initial = " ".join(args.request).strip()
    if initial:
        return handle(surface, initial)

    print("BRO ready. Talk normally; type exit or quit to leave.")
    print(f'For a multiline request, put {BLOCK_DELIMITER} on its own line, paste, then {BLOCK_DELIMITER} again.')
    while True:
        request = read_request(input)
        if request is None:
            print()
            return 0
        if request.lower() in {"exit", "quit"}:
            return 0
        if not request:
            continue
        handle(surface, request)


if __name__ == "__main__":
    raise SystemExit(main())
