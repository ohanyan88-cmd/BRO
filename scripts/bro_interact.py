#!/usr/bin/env python3
"""Interactive CLI for BRO conversation plus governed production execution."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bro_runtime.anthropic_messages import AnthropicMessagesConfig, AnthropicMessagesModel
from bro_runtime.conversation import ConversationalInteractionSurface, InteractionMode
from bro_runtime.anthropic_messages import AnthropicMessagesRejected
from bro_runtime.external_model import ExternalModel, ExternalModelConfig, ExternalModelRejected
from bro_runtime.final_delivery import IntelligentInteractionRuntime
from bro_runtime.github_provider import (
    GitHubAcceptanceTarget,
    GitHubIssueCommentProvider,
    GitHubProviderRejected,
)
from bro_runtime.interaction_surface import InteractionSurface
from bro_runtime.learning_boundary import ExperienceContext, GovernedLearningBoundary
from bro_runtime.learning_memory import DurableLearningMemory
from bro_runtime.study_runtime import GovernedStudyRuntime, StudyContext, StudyRejected, StudySourceReader


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def build_model():
    provider = required("BRO_MODEL_PROVIDER").lower()
    if provider == "anthropic":
        return AnthropicMessagesModel(
            AnthropicMessagesConfig(
                api_key=required("BRO_MODEL_API_KEY"),
                model=required("BRO_MODEL_NAME"),
                api_url=os.environ.get("BRO_MODEL_API_URL", "https://api.anthropic.com/v1/messages").strip(),
            )
        )
    return ExternalModel(
        ExternalModelConfig(
            provider=provider,
            api_key=required("BRO_MODEL_API_KEY"),
            model=required("BRO_MODEL_NAME"),
            api_url=required("BRO_MODEL_API_URL"),
        )
    )


def memory_database_path() -> str:
    return os.environ.get("BRO_MEMORY_DB_PATH", "/var/lib/bro/runtime.sqlite3").strip()


def study_root() -> str:
    """Self-study reads the deployed release by default, and only ever reads."""
    return os.environ.get("BRO_STUDY_ROOT", str(ROOT)).strip()


def study_item_budget() -> int:
    try:
        return max(1, int(os.environ.get("BRO_STUDY_ITEM_BUDGET", "6")))
    except ValueError:
        return 6


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
            planner=lambda mission, sources: model.study_plan(mission, sources),
            extractor=lambda topic, text: model.study_extract(topic, text),
            item_budget=study_item_budget(),
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
BOUNDARY_FAILURES = (ExternalModelRejected, AnthropicMessagesRejected, GitHubProviderRejected)


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
