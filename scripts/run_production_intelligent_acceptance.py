#!/usr/bin/env python3
"""Run FINAL-1 production intelligent execution against an isolated GitHub issue."""
from __future__ import annotations
import json, os, re, sqlite3, sys
from pathlib import Path
from bro_runtime.external_model import ExternalModelRejected
from bro_runtime.model_provider import build_model as build_configured_model
from bro_runtime.final_delivery import IntelligentInteractionRuntime
from bro_runtime.github_provider import GitHubAcceptanceTarget, GitHubIssueCommentProvider
from bro_runtime.learning_boundary import ExperienceContext, GovernedLearningBoundary
from bro_runtime.learning_memory import DurableLearningMemory

def _required(name: str) -> str:
    value=os.environ.get(name,"").strip()
    if not value: raise SystemExit(f"missing required environment variable: {name}")
    return value

def _revision() -> str:
    """Acceptance evidence is worthless unless it names the revision it was produced on."""
    value=_required("BRO_SOURCE_REVISION").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value): raise SystemExit("BRO_SOURCE_REVISION must be an exact 40-character git SHA")
    return value

def _model():
    try:
        return build_configured_model(os.environ)
    except ExternalModelRejected as exc:
        raise SystemExit(str(exc)) from None

def _submit_learning(model, target, intent, result: dict) -> str:
    """Send this governed outcome to BRO's one learning mechanism.

    The acceptance path is not a second learning authority: it hands the same receipt
    to the same GovernedLearningBoundary the conversational surface uses. Learning can
    never change what the acceptance already proved, so every failure here is reported
    and swallowed.
    """
    database = os.environ.get("BRO_MEMORY_DB_PATH", os.environ.get("BRO_DB_PATH", "/var/lib/bro/runtime.sqlite3")).strip()
    connection = None
    try:
        connection = sqlite3.connect(database, timeout=10)
        boundary = GovernedLearningBoundary(
            DurableLearningMemory(connection),
            extractor=lambda request, facts: model.json_object(
                instruction=(
                    "Extract one reusable operational lesson from a successfully verified BRO action. "
                    "Required keys: lesson, skill_name, trigger, procedure. Optional keys: intended_outcome, "
                    "preconditions, required_authority, failure_modes. Generalize only what the supplied "
                    "evidence supports. Do not invent permissions, credentials, systems, or success."
                ),
                request=json.dumps({"request": request, "receipt": facts}, ensure_ascii=False, sort_keys=True),
            ),
        )
        context = ExperienceContext(
            request=intent.raw_request, mode="ACT", interpreted_scope=tuple(intent.interpreted_scope),
            source_revision=result["source_revision"], environment=os.environ.get("BRO_ENVIRONMENT", "").strip(),
            instance_id=os.environ.get("BRO_INSTANCE_ID", "").strip(), model_ref=model.config.model_ref,
            target_ref=target.resource_ref,
        )
        submission = boundary.submit_success(context, result)
        return json.dumps({
            "eligibility": submission.eligibility.value, "recorded": submission.recorded,
            "pattern_key": submission.pattern_key, "lesson_created": submission.lesson_created,
            "candidate_id": submission.candidate.candidate_id if submission.candidate else "",
            "error": submission.error,
        }, sort_keys=True)
    except Exception as exc:
        return json.dumps({"recorded": False, "error": f"{type(exc).__name__}:{exc}"}, sort_keys=True)
    finally:
        if connection is not None:
            connection.close()

def main() -> int:
    request=_required("BRO_INTELLIGENT_REQUEST"); token=_required("BRO_GITHUB_TOKEN"); key=_required("BRO_INTELLIGENT_IDEMPOTENCY_KEY"); body=_required("BRO_INTELLIGENT_COMMENT_BODY"); confirmed_by=_required("BRO_INTELLIGENT_CONFIRMED_BY"); source_revision=_revision()
    model=_model(); target=GitHubAcceptanceTarget(_required("BRO_GITHUB_OWNER"),_required("BRO_GITHUB_REPOSITORY"),int(_required("BRO_GITHUB_ISSUE"))); provider=GitHubIssueCommentProvider(target); parsed=model.interpret(request)
    def planner(intent): return model.select_specialist(intent.raw_request,intent.interpreted_scope)
    def executor(intent,specialist):
        result=provider.invoke({"token":token,"owner":target.owner,"repository":target.repository,"issue_number":target.issue_number,"idempotency_key":key,"body":body,"operation":"github.issue_comment.ensure"}); state=result.result
        if not isinstance(state,dict) or not state.get("exists") or not state.get("matches_expected"): raise RuntimeError("GitHub external effect did not return expected state")
        return {"provider_ref":f"github:{provider.adapter_id}@{provider.version}:write","effect_ref":f"github-effect:issue-comment:{state.get('comment_id')}"}
    def readback(intent,effect):
        result=provider.invoke({"token":token,"owner":target.owner,"repository":target.repository,"issue_number":target.issue_number,"idempotency_key":key,"body":body,"operation":"github.issue_comment.read"}); state=result.result
        if not isinstance(state,dict) or not state.get("exists") or not state.get("matches_expected"): raise RuntimeError("independent GitHub readback did not confirm expected state")
        if not result.observation_refs: raise RuntimeError("GitHub readback did not return an observation reference")
        return {"provider_ref":f"github:{provider.adapter_id}@{provider.version}:readback","readback_ref":result.observation_refs[0],"evidence_ref":f"github-external-readback:comment:{state.get('comment_id')}","assurance":"external_system"}
    runtime=IntelligentInteractionRuntime(interpreter=lambda _request:dict(parsed),planner=planner,executor=executor,readback=readback,model_ref=model.config.model_ref); intent=runtime.interpret(request); digest=runtime.scope_digest(intent.request_id)
    preview={"request_id":intent.request_id,"model_ref":intent.model_ref,"interpreted_scope":list(intent.interpreted_scope),"constraints":list(intent.constraints),"success_conditions":list(intent.success_conditions),"material":intent.material,"scope_digest":digest}
    print("=== INTERPRETED SCOPE ==="); print(json.dumps(preview,sort_keys=True,indent=2)); entered=input("Confirm by pasting the exact scope_digest: ").strip()
    if entered != digest: raise SystemExit("scope confirmation mismatch; no external effect was attempted")
    runtime.confirm_scope(intent.request_id,confirmed_by=confirmed_by,scope_digest=entered); receipt=runtime.execute(intent.request_id)
    result={**preview,"source_revision":source_revision,"confirmed_by":confirmed_by,"specialist_ref":receipt.specialist_ref,"provider_ref":receipt.provider_ref,"effect_ref":receipt.effect_ref,"readback_ref":receipt.readback_ref,"readback_provider_ref":receipt.readback_provider_ref,"evidence_ref":receipt.evidence_ref,"assurance":receipt.assurance.value}; out=Path(os.environ.get("BRO_INTELLIGENT_ACCEPTANCE_RECORD","/var/lib/bro/intelligent-acceptance.json")); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8"); print("=== INTELLIGENT ACCEPTANCE RECORD ==="); print(json.dumps(result,sort_keys=True))
    print("=== GOVERNED LEARNING SUBMISSION ==="); print(_submit_learning(model,target,intent,result)); return 0
if __name__ == "__main__": raise SystemExit(main())
