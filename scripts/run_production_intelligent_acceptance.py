#!/usr/bin/env python3
"""Run FINAL-1 production intelligent execution against an isolated GitHub issue.

Phase 1 interprets a natural-language request through the configured OpenAI
Responses model and writes an intent record containing the exact scope digest.
Phase 2 requires that digest back as explicit user confirmation before selecting
a specialist, performing the authenticated GitHub effect, and independently
reading the external state back.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from bro_runtime.final_delivery import IntelligentInteractionRuntime
from bro_runtime.github_provider import GitHubAcceptanceTarget, GitHubIssueCommentProvider
from bro_runtime.openai_responses import OpenAIResponsesConfig, OpenAIResponsesModel


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def _runtime(model: OpenAIResponsesModel, provider: GitHubIssueCommentProvider, token: str, parsed: dict):
    target = provider.target
    key = _required("BRO_INTELLIGENT_IDEMPOTENCY_KEY")
    body = _required("BRO_INTELLIGENT_COMMENT_BODY")

    def planner(intent):
        return model.select_specialist(intent.raw_request, intent.interpreted_scope)

    def executor(intent, specialist):
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
        comment_id = state.get("comment_id")
        return {
            "provider_ref": f"github:{provider.adapter_id}@{provider.version}:write",
            "effect_ref": f"github-effect:issue-comment:{comment_id}",
        }

    def readback(intent, effect):
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

    return IntelligentInteractionRuntime(
        interpreter=lambda _request: dict(parsed),
        planner=planner,
        executor=executor,
        readback=readback,
        model_ref=model.config.model_ref,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interpret", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.interpret == args.execute:
        raise SystemExit("choose exactly one of --interpret or --execute")

    request = _required("BRO_INTELLIGENT_REQUEST")
    record_path = Path(os.environ.get("BRO_INTELLIGENT_INTENT_RECORD", "/var/lib/bro/intelligent-intent.json"))
    model = OpenAIResponsesModel(OpenAIResponsesConfig(
        api_key=_required("BRO_OPENAI_API_KEY"),
        model=os.environ.get("BRO_OPENAI_MODEL", "gpt-5.6-terra").strip(),
        api_url=os.environ.get("BRO_OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses").strip(),
    ))

    if args.interpret:
        parsed = model.interpret(request)
        target = GitHubAcceptanceTarget(
            _required("BRO_GITHUB_OWNER"),
            _required("BRO_GITHUB_REPOSITORY"),
            int(_required("BRO_GITHUB_ISSUE")),
        )
        runtime = _runtime(model, GitHubIssueCommentProvider(target), "not-used-during-interpret", parsed)
        intent = runtime.interpret(request)
        record = {
            "request": request,
            "model_ref": intent.model_ref,
            "interpreted_scope": list(intent.interpreted_scope),
            "constraints": list(intent.constraints),
            "success_conditions": list(intent.success_conditions),
            "material": intent.material,
            "scope_digest": runtime.scope_digest(intent.request_id),
        }
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(record, sort_keys=True))
        return 0

    saved = json.loads(record_path.read_text(encoding="utf-8"))
    if saved.get("request") != request:
        raise SystemExit("saved interpreted request does not match BRO_INTELLIGENT_REQUEST")
    confirmed_digest = _required("BRO_INTELLIGENT_CONFIRMED_SCOPE_DIGEST")
    if confirmed_digest != saved.get("scope_digest"):
        raise SystemExit("confirmed scope digest does not match saved interpreted scope")

    parsed = {
        "scope": saved["interpreted_scope"],
        "constraints": saved.get("constraints", []),
        "success_conditions": saved["success_conditions"],
        "material": bool(saved.get("material", True)),
    }
    target = GitHubAcceptanceTarget(
        _required("BRO_GITHUB_OWNER"),
        _required("BRO_GITHUB_REPOSITORY"),
        int(_required("BRO_GITHUB_ISSUE")),
    )
    provider = GitHubIssueCommentProvider(target)
    runtime = _runtime(model, provider, _required("BRO_GITHUB_TOKEN"), parsed)
    intent = runtime.interpret(request)
    runtime.confirm_scope(
        intent.request_id,
        confirmed_by=_required("BRO_INTELLIGENT_CONFIRMED_BY"),
        scope_digest=confirmed_digest,
    )
    receipt = runtime.execute(intent.request_id)
    result = {
        "request_id": receipt.request_id,
        "model_ref": model.config.model_ref,
        "scope_digest": confirmed_digest,
        "specialist_ref": receipt.specialist_ref,
        "provider_ref": receipt.provider_ref,
        "effect_ref": receipt.effect_ref,
        "readback_ref": receipt.readback_ref,
        "readback_provider_ref": receipt.readback_provider_ref,
        "evidence_ref": receipt.evidence_ref,
        "assurance": receipt.assurance.value,
    }
    out = Path(os.environ.get("BRO_INTELLIGENT_ACCEPTANCE_RECORD", "/var/lib/bro/intelligent-acceptance.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
