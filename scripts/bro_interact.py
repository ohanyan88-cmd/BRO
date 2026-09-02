#!/usr/bin/env python3
"""Interactive CLI for BRO conversation plus governed production execution."""
from __future__ import annotations

import argparse
import json
import os
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


def build_surface() -> ConversationalInteractionSurface:
    model = build_model()
    target = GitHubAcceptanceTarget(
        required("BRO_GITHUB_OWNER"),
        required("BRO_GITHUB_REPOSITORY"),
        int(required("BRO_GITHUB_ISSUE")),
    )
    provider = GitHubIssueCommentProvider(target)
    token = required("BRO_GITHUB_TOKEN")
    body = required("BRO_INTELLIGENT_COMMENT_BODY")
    key = required("BRO_INTELLIGENT_IDEMPOTENCY_KEY")

    def interpreter(request: str):
        return model.interpret(request)

    def planner(intent):
        return model.select_specialist(intent.raw_request, intent.interpreted_scope)

    def executor(_intent, _specialist):
        result = provider.invoke({
            "token": token,
            "owner": target.owner,
            "repository": target.repository,
            "issue_number": target.issue_number,
            "idempotency_key": key,
            "body": body,
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
        result = provider.invoke({
            "token": token,
            "owner": target.owner,
            "repository": target.repository,
            "issue_number": target.issue_number,
            "idempotency_key": key,
            "body": body,
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
        return model.conversational_response(mode.value, request, history_payload(history))

    return ConversationalInteractionSurface(
        action_surface=action_surface,
        router=router,
        responder=responder,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Talk, think, or act with BRO through the production path")
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
