#!/usr/bin/env python3
"""Run FINAL-1 production intelligent execution against an isolated GitHub issue.

The configured OpenAI Responses model interprets the natural-language request.
The exact interpreted scope and digest are shown to the human operator, who must
re-enter that digest before specialist selection or any external effect occurs.
The effect is then independently read back from GitHub. Credentials are consumed
from process environment only and are never written into the acceptance record.
"""
from __future__ import annotations

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


def main() -> int:
    request = _required("BRO_INTELLIGENT_REQUEST")
    token = _required("BRO_GITHUB_TOKEN")
    key = _required("BRO_INTELLIGENT_IDEMPOTENCY_KEY")
    body = _required("BRO_INTELLIGENT_COMMENT_BODY")
    confirmed_by = _required("BRO_INTELLIGENT_CONFIRMED_BY")

    model = OpenAIResponsesModel(OpenAIResponsesConfig(
        api_key=_required("BRO_OPENAI_API_KEY"),
        model=os.environ.get("BRO_OPENAI_MODEL", "gpt-5.6-terra").strip(),
        api_url=os.environ.get("BRO_OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses").strip(),
    ))
    target = GitHubAcceptanceTarget(
        _required("BRO_GITHUB_OWNER"),
        _required("BRO_GITHUB_REPOSITORY"),
        int(_required("BRO_GITHUB_ISSUE")),
    )
    provider = GitHubIssueCommentProvider(target)

    parsed = model.interpret(request)

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
        return {
            "provider_ref": f"github:{provider.adapter_id}@{provider.version}:write",
            "effect_ref": f"github-effect:issue-comment:{state.get('comment_id')}",
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

    runtime = IntelligentInteractionRuntime(
        interpreter=lambda _request: dict(parsed),
        planner=planner,
        executor=executor,
        readback=readback,
        model_ref=model.config.model_ref,
    )
    intent = runtime.interpret(request)
    digest = runtime.scope_digest(intent.request_id)
    preview = {
        "request_id": intent.request_id,
        "model_ref": intent.model_ref,
        "interpreted_scope": list(intent.interpreted_scope),
        "constraints": list(intent.constraints),
        "success_conditions": list(intent.success_conditions),
        "material": intent.material,
        "scope_digest": digest,
    }
    print("=== INTERPRETED SCOPE ===")
    print(json.dumps(preview, sort_keys=True, indent=2))
    entered = input("Confirm by pasting the exact scope_digest: ").strip()
    if entered != digest:
        raise SystemExit("scope confirmation mismatch; no external effect was attempted")

    runtime.confirm_scope(intent.request_id, confirmed_by=confirmed_by, scope_digest=entered)
    receipt = runtime.execute(intent.request_id)
    result = {
        **preview,
        "confirmed_by": confirmed_by,
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
    print("=== INTELLIGENT ACCEPTANCE RECORD ===")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
