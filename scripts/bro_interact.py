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
from bro_runtime.external_model import ExternalModel, ExternalModelConfig
from bro_runtime.final_delivery import IntelligentInteractionRuntime
from bro_runtime.github_provider import GitHubAcceptanceTarget, GitHubIssueCommentProvider
from bro_runtime.interaction_surface import InteractionSurface
from bro_runtime.learning_boundary import ExperienceContext, GovernedLearningBoundary
from bro_runtime.learning_memory import DurableLearningMemory


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

    def github_binding():
        target = GitHubAcceptanceTarget(
            required("BRO_GITHUB_OWNER"),
            required("BRO_GITHUB_REPOSITORY"),
            int(required("BRO_GITHUB_ISSUE")),
        )
        return target, GitHubIssueCommentProvider(target)

    def lesson_context(request: str) -> str:
        advisory = boundary.advisory_context(request, current_truth=current_truth())
        if not advisory["lessons"] and not advisory["withheld_for_contradiction"]:
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
    )


def handle(surface: ConversationalInteractionSurface, request: str) -> None:
    result = surface.submit(request)
    mode = result["mode"]
    if mode in {InteractionMode.TALK.value, InteractionMode.THINK.value}:
        print(f"BRO [{mode}] > {result['response']}")
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
        handle(surface, initial)
        return 0

    print("BRO ready. Talk normally; type exit or quit to leave.")
    while True:
        try:
            request = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if request.lower() in {"exit", "quit"}:
            return 0
        if not request:
            continue
        handle(surface, request)


if __name__ == "__main__":
    raise SystemExit(main())
