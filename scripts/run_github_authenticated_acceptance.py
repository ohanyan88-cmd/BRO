#!/usr/bin/env python3
"""Run BRO's governed authenticated GitHub external-write acceptance.

This is intentionally opt-in and target-bound. It traverses the canonical runtime:
Kernel.prepare/open -> IMMUNE authority -> ProviderExecutionGateway -> SecretMediator
-> GitHub write -> registered live readback -> trusted Evidence -> verified completion.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bro_runtime.action_runtime import ActionRequest, EffectState
from bro_runtime.evidence_verification import EvidenceObservation, EvidenceVerifier, VerificationResult
from bro_runtime.github_provider import GitHubAcceptanceTarget, GitHubIssueCommentProvider
from bro_runtime.immune import AuthorityEnvelope, EvidenceFreshness, EvidenceValidity, evidence_scope
from bro_runtime.kernel import BROKernel
from bro_runtime.live_readback import LiveReadbackRuntime
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.orchestration import AssignmentState
from bro_runtime.provider_execution import ProviderRoute
from bro_runtime.skills import Capability, CapabilityKind, CapabilityStatus
from bro_runtime.supervision import NextAction
from bro_runtime.task_runtime import SQLiteTaskStore


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    if _required("BRO_GITHUB_ACCEPTANCE") != "1":
        raise SystemExit("BRO_GITHUB_ACCEPTANCE must be exactly 1")

    owner = _required("BRO_GITHUB_OWNER")
    repository = _required("BRO_GITHUB_REPOSITORY")
    issue_number = int(_required("BRO_GITHUB_ISSUE"))
    target = GitHubAcceptanceTarget(owner, repository, issue_number)
    provider = GitHubIssueCommentProvider(target)
    key = os.environ.get("BRO_GITHUB_IDEMPOTENCY_KEY", "bro-governed-live-write-v1")
    marker = provider.marker_for(key)
    if key in marker or not marker.startswith(provider.marker_prefix):
        raise AssertionError("external reconciliation marker must be a one-way provider-owned digest")
    body = os.environ.get("BRO_GITHUB_COMMENT_BODY", "BRO governed authenticated external write acceptance v1")
    criterion = "authenticated GitHub issue comment exists and matches the governed request"

    tasks = SQLiteTaskStore()
    mind = SQLiteMindStore()
    kernel = BROKernel(tasks, mind)
    try:
        kernel.register_provider(provider.adapter())
        kernel.secrets.register_environment("secret:github-acceptance", provider.adapter_id, "BRO_GITHUB_TOKEN")
        kernel.skills.register(Capability(
            capability_id="cap:github-issue-comment-ensure",
            version=1,
            kind=CapabilityKind.TOOL_ADAPTER,
            name="GitHub issue comment ensure",
            description="Ensures one marker-bound comment on the isolated acceptance issue",
            operations=("github.issue_comment.ensure",),
            domains=("github",),
            input_contract_ref=None,
            output_contract_ref="evidence:github-issue-comment",
            dependency_refs=(),
            authority_requirements=("github.issue_comment.ensure",),
            evidence_capabilities=("github.issue_comment.read",),
            provider_ref=provider.adapter_id,
            health_ref="health:github",
            status=CapabilityStatus.ACTIVE,
            recorded_at=_iso(datetime.now(timezone.utc)),
        ))
        kernel.register_evidence_verifier(EvidenceVerifier(
            "IMMUNE:github-write-acceptance",
            lambda observation: VerificationResult(
                EvidenceValidity.VALID if bool(observation.result) else EvidenceValidity.INVALID,
                EvidenceFreshness.CURRENT,
                {"verification_source": "registered-github-live-readback"},
            ),
        ))

        prepared = kernel.prepare(
            request="Perform BRO governed authenticated GitHub external-write acceptance",
            source="acceptance:github-write",
            project_boundary="BRO",
            desired_outcome="One target-bound GitHub issue comment exists and is independently verified",
            interpreted_scope=("github", "issue-comment", target.resource_ref),
            success_conditions=(criterion,),
            operation="github.issue_comment.ensure",
            domain="github",
            authority_basis="isolated acceptance target",
            materiality="MATERIAL",
            risk_class="R1",
            expected_output="evidence:github-issue-comment",
            verification_requirement="registered authenticated GitHub readback",
        )
        task_ref = prepared.assignment.task_ref
        now = datetime.now(timezone.utc)
        authority = AuthorityEnvelope(
            envelope_id="auth:github-write-acceptance",
            version=1,
            principal="BRO",
            proof_ref="proof:workflow-dispatch",
            authority_source="system",
            operation="github.issue_comment.ensure",
            target=target.resource_ref,
            allowed_scope=(
                "operation:github.issue_comment.ensure",
                f"target:{target.resource_ref}",
                task_ref,
                "project:BRO",
            ),
            prohibited_scope=(),
            task_ref=task_ref,
            risk_class="R1",
            valid_from=_iso(now - timedelta(minutes=1)),
            expires_at=_iso(now + timedelta(minutes=10)),
            revocation_ref=None,
            environment="production",
            tool_boundary=(provider.adapter_id,),
            decision="ALLOWED",
            reason="isolated non-destructive acceptance issue only",
            audit_ref="audit:github-write-acceptance",
        )
        binding = kernel.open(prepared, authority, worker_id="specialist:github-write-acceptance", now=_iso(now))
        request = ActionRequest(
            action_request_id="action:github-write-acceptance",
            task_ref=task_ref,
            intended_effect="ensure marker-bound acceptance comment",
            operation="github.issue_comment.ensure",
            target=target.resource_ref,
            environment="production",
            adapter_id=provider.adapter_id,
            input_parameters={
                "owner": owner,
                "repository": repository,
                "issue_number": issue_number,
                "idempotency_key": key,
                "body": body,
                "operation": "github.issue_comment.ensure",
            },
            authority_envelope_ref=authority.envelope_id,
            risk_class="R1",
            reversibility="REVERSIBLE",
            idempotency_key=key,
            idempotency_guaranteed=True,
            expected_result={"exists": True, "matches_expected": True},
            verification_requirements=("registered authenticated GitHub readback",),
            assignment_ref=binding.assignment_id,
            project_boundary="BRO",
        )
        attempt = kernel.execute_provider(
            binding,
            request,
            route=ProviderRoute("github", provider.adapter_id, provider.version,
                                (("token", "secret:github-acceptance"),)),
            executor="specialist:github-write-acceptance",
            now=_iso(now),
        )

        recovery_after_write = kernel.recover(task_ref, prepared.route_id)
        if EffectState(attempt["effect_state"]) is EffectState.POSSIBLE:
            if recovery_after_write.next_step.action is not NextAction.RECONCILE_EFFECT:
                raise AssertionError("possible external effect did not recover to RECONCILE_EFFECT")

        readback = LiveReadbackRuntime(
            kernel.supervisor.actions,
            kernel.providers,
            secrets=kernel.secrets,
        ).observe_from_provider(
            provider="github",
            adapter_id=provider.adapter_id,
            version=provider.version,
            operation="github.issue_comment.read",
            resource_ref=target.resource_ref,
            inputs={
                "owner": owner,
                "repository": repository,
                "issue_number": issue_number,
                "idempotency_key": key,
                "body": body,
                "operation": "github.issue_comment.read",
            },
            secret_bindings={"token": "secret:github-acceptance"},
        )
        state = readback.observed_state
        if not isinstance(state, dict) or not state.get("exists") or not state.get("matches_expected"):
            raise AssertionError("independent GitHub readback did not confirm the expected external effect")

        observation = EvidenceObservation(
            criterion=criterion,
            evidence_type="external-readback",
            source="github",
            provenance={
                "resource_ref": target.resource_ref,
                "provider_ref": readback.provider_ref,
                "comment_id": state.get("comment_id"),
                "resource_url": state.get("resource_url"),
                "observation_ref": readback.evidence_ref,
            },
            collection_method="registered authenticated GitHub issue-comment read",
            result=True,
            scope=evidence_scope("BRO", task_ref),
        )
        kernel.reconcile_verified(
            prepared,
            binding,
            request.action_request_id,
            EffectState.CONFIRMED,
            observation,
            verifier_id="IMMUNE:github-write-acceptance",
            now=_iso(datetime.now(timezone.utc)),
        )
        kernel.settle_verified_assignment(
            prepared,
            binding,
            result_state=AssignmentState.SUCCEEDED,
            output_ref=state.get("resource_url") or target.resource_ref,
            observations=(("IMMUNE:github-write-acceptance", observation),),
            now=_iso(datetime.now(timezone.utc)),
        )
        manifest = kernel.complete(
            prepared,
            binding,
            outcome_statement="The isolated authenticated GitHub comment exists and was independently read back and verified",
            required_criteria=(criterion,),
            now=_iso(datetime.now(timezone.utc)),
        )
        if not manifest.is_verified():
            raise AssertionError(f"completion manifest is not VERIFIED: {manifest.verdict}")
        canonical = kernel.supervisor.canonical_task(task_ref)
        if canonical["state"] != "COMPLETED":
            raise AssertionError("canonical Task did not reach COMPLETED")

        record = {
            "task_ref": task_ref,
            "provider": "github",
            "resource_ref": target.resource_ref,
            "comment_id": state.get("comment_id"),
            "resource_url": state.get("resource_url"),
            "observation_ref": readback.evidence_ref,
            "initial_effect_state": attempt["effect_state"],
            "recovery_action_after_write": str(recovery_after_write.next_step.action),
            "completion_verdict": str(manifest.verdict),
            "task_state": canonical["state"],
            "authenticated_live_write": True,
            "independent_live_readback": True,
        }
        path = Path(os.environ.get("BRO_GITHUB_ACCEPTANCE_RECORD", "artifacts/github-write-acceptance.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(record, sort_keys=True))
        return 0
    finally:
        tasks.close()
        mind.close()


if __name__ == "__main__":
    raise SystemExit(main())
