from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bro_runtime import (
    ActionRequest,
    AssignmentState,
    AuthorityEnvelope,
    CompletionVerdict,
    EffectState,
    Evidence,
    EvidenceFreshness,
    EvidenceValidity,
    NextAction,
    ProviderAdapterRegistry,
    SQLiteTaskStore,
    SpecialistAssignment,
    TaskSupervisor,
    evidence_scope,
)
from bro_runtime.github_provider import GitHubAcceptanceTarget, GitHubIssueCommentProvider
from bro_runtime.live_readback import LiveReadbackRuntime
from bro_runtime.restart_recovery import RestartRecoveryRejected, RestartRecoveryRuntime
from bro_runtime.secret_runtime import SecretMediator

T0 = "2026-09-01T00:00:00Z"
T1 = "2026-09-01T00:00:01Z"
T2 = "2026-09-01T00:10:00Z"
TASK = "task:restart"
ASSIGNMENT = "assignment:restart"
ACTION = "action:restart"
PROJECT = "BRO"
CRITERION = "external GitHub comment matches the governed request"


class FakeGitHub:
    def __init__(self) -> None:
        self.comments: list[dict] = []
        self.posts = 0

    def __call__(self, method: str, url: str, token: str, payload: dict | None):
        if token != "TOKEN":
            raise AssertionError("unexpected credential")
        if method == "GET":
            return [dict(item) for item in self.comments]
        self.posts += 1
        item = {
            "id": 9000 + self.posts,
            "html_url": "https://github.test/issues/45#comment",
            **(payload or {}),
        }
        self.comments.append(item)
        return dict(item)


def authority(target: GitHubAcceptanceTarget, provider: GitHubIssueCommentProvider) -> AuthorityEnvelope:
    return AuthorityEnvelope(
        envelope_id="auth:restart",
        version=1,
        principal="BRO",
        proof_ref="proof:restart",
        authority_source="system",
        operation="github.issue_comment.ensure",
        target=target.resource_ref,
        allowed_scope=(
            "operation:github.issue_comment.ensure",
            f"target:{target.resource_ref}",
            TASK,
            "project:BRO",
        ),
        prohibited_scope=(),
        task_ref=TASK,
        risk_class="R1",
        valid_from="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
        revocation_ref=None,
        environment="production",
        tool_boundary=(provider.adapter_id,),
        decision="ALLOWED",
        reason="bounded recovery acceptance",
        audit_ref="audit:restart",
    )


def assignment(provider: GitHubIssueCommentProvider) -> SpecialistAssignment:
    return SpecialistAssignment(
        assignment_id=ASSIGNMENT,
        task_ref=TASK,
        step_ref="step:restart",
        project_boundary=PROJECT,
        required_capability="cap:github-write",
        context_manifest_ref="context:restart",
        expected_output_contract="evidence:github-comment",
        authority_envelope_ref="auth:restart",
        allowed_tools=(provider.adapter_id,),
        deadline=None,
        budget={"seconds": 60},
        evidence_requirements=(CRITERION,),
    )


def request(target: GitHubAcceptanceTarget, provider: GitHubIssueCommentProvider) -> ActionRequest:
    return ActionRequest(
        action_request_id=ACTION,
        task_ref=TASK,
        intended_effect="ensure one bounded GitHub issue comment",
        operation="github.issue_comment.ensure",
        target=target.resource_ref,
        environment="production",
        adapter_id=provider.adapter_id,
        input_parameters={
            "owner": target.owner,
            "repository": target.repository,
            "issue_number": target.issue_number,
            "idempotency_key": "restart-proof-1",
            "body": "BRO restart recovery proof",
            "operation": "github.issue_comment.ensure",
        },
        authority_envelope_ref="auth:restart",
        risk_class="R1",
        reversibility="REVERSIBLE",
        idempotency_key="restart-proof-1",
        idempotency_guaranteed=True,
        expected_result={"exists": True, "matches_expected": True},
        verification_requirements=("registered external readback",),
        assignment_ref=ASSIGNMENT,
        project_boundary=PROJECT,
    )


def evidence(evidence_id: str, criterion: str, observation_ref: str, result: object) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        criterion=criterion,
        evidence_type="external-readback",
        source="github",
        provenance={"observation_ref": observation_ref},
        collection_method="registered provider read after process restart",
        collected_at=T2,
        result=result,
        scope=evidence_scope(PROJECT, TASK),
        limitations=(),
        validity=EvidenceValidity.VALID,
        freshness=EvidenceFreshness.CURRENT,
        verifier="IMMUNE_SYSTEM",
    )


def write_adapter(provider: GitHubIssueCommentProvider):
    def invoke(public_inputs: dict):
        runtime_inputs = dict(public_inputs)
        runtime_inputs["token"] = "TOKEN"
        return provider.invoke(runtime_inputs)

    return invoke


class DurableExternalWriteRecoveryTests(unittest.TestCase):
    def test_restart_reconciles_external_truth_without_blind_replay_and_completes(self) -> None:
        fake = FakeGitHub()
        target = GitHubAcceptanceTarget("safe-owner", "BRO", 45)
        provider = GitHubIssueCommentProvider(target, transport=fake)

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "runtime.sqlite3"

            store1 = SQLiteTaskStore(db)
            supervisor1 = TaskSupervisor(store1)
            binding1 = supervisor1.open_flow(
                task_id=TASK,
                goal_ref="goal:restart",
                plan_ref="plan:restart",
                assignment=assignment(provider),
                envelope=authority(target, provider),
                worker_id="worker:before-crash",
                now=T0,
                lease_seconds=5,
            )
            attempt = supervisor1.execute(
                binding1,
                request(target, provider),
                executor="worker:before-crash",
                interface_version=provider.version,
                adapter=write_adapter(provider),
                now=T1,
            )
            self.assertEqual(attempt["effect_state"], EffectState.POSSIBLE)
            self.assertEqual(fake.posts, 1)
            store1.close()  # process crash boundary: all in-memory runtime objects are discarded

            store2 = SQLiteTaskStore(db)
            self.addCleanup(store2.close)
            supervisor2 = TaskSupervisor(store2)
            providers2 = ProviderAdapterRegistry()
            providers2.register(provider.adapter())
            secrets2 = SecretMediator()
            secrets2.register("secret:github", provider.adapter_id, "TOKEN")

            before = supervisor2.resume(TASK)
            self.assertIs(before.action, NextAction.RECONCILE_EFFECT)
            self.assertEqual(before.action_request_id, ACTION)

            readback = LiveReadbackRuntime(
                supervisor2.actions,
                providers2,
                secrets=secrets2,
            ).observe_from_provider(
                provider="github",
                adapter_id=provider.adapter_id,
                version=provider.version,
                operation="github.issue_comment.read",
                resource_ref=target.resource_ref,
                inputs={
                    "owner": target.owner,
                    "repository": target.repository,
                    "issue_number": target.issue_number,
                    "idempotency_key": "restart-proof-1",
                    "body": "BRO restart recovery proof",
                    "operation": "github.issue_comment.read",
                },
                secret_bindings={"token": "secret:github"},
            )
            self.assertTrue(readback.observed_state["matches_expected"])
            self.assertEqual(fake.posts, 1)

            reconciled = RestartRecoveryRuntime(supervisor2).reconcile_observed_effect(
                TASK,
                ACTION,
                effect_state=EffectState.CONFIRMED,
                evidence=evidence(
                    "evidence:restart-reconcile",
                    "external effect reconciled after restart",
                    readback.evidence_ref,
                    True,
                ),
                worker_id="worker:after-restart",
                now=T2,
            )
            self.assertEqual(fake.posts, 1)
            self.assertEqual(
                supervisor2.actions.effective_effect(supervisor2.actions.latest_attempt(ACTION)),
                EffectState.CONFIRMED,
            )
            self.assertIs(supervisor2.resume(TASK).action, NextAction.SETTLE_ASSIGNMENT)

            completion_evidence = evidence(
                "evidence:restart-completion",
                CRITERION,
                readback.evidence_ref,
                {"matches_expected": True, "comment_id": readback.observed_state["comment_id"]},
            )
            supervisor2.settle_assignment(
                reconciled.binding,
                result_state=AssignmentState.SUCCEEDED,
                output_ref=readback.observed_state["resource_url"],
                evidence=(completion_evidence,),
                now=T2,
            )
            manifest = supervisor2.complete(
                reconciled.binding,
                outcome_statement="the externally written comment survived restart and was independently verified",
                required_criteria=(CRITERION,),
                now=T2,
            )
            self.assertIs(manifest.verdict, CompletionVerdict.VERIFIED)
            self.assertEqual(store2.canonical_task(TASK)["state"], "COMPLETED")
            self.assertEqual(fake.posts, 1)

            events = store2.events(TASK)
            recovery_events = [event for event in events if event["event_type"] == "recovery.lease_reclaimed"]
            self.assertEqual(len(recovery_events), 1)
            self.assertIn('"command_replayed": false', recovery_events[0]["payload"])

    def test_restart_refuses_to_steal_a_still_live_worker_lease(self) -> None:
        fake = FakeGitHub()
        target = GitHubAcceptanceTarget("safe-owner", "BRO", 45)
        provider = GitHubIssueCommentProvider(target, transport=fake)
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "runtime.sqlite3"
            store = SQLiteTaskStore(db)
            supervisor = TaskSupervisor(store)
            binding = supervisor.open_flow(
                task_id=TASK,
                goal_ref="goal:restart",
                plan_ref="plan:restart",
                assignment=assignment(provider),
                envelope=authority(target, provider),
                worker_id="worker:before-crash",
                now=T0,
                lease_seconds=300,
            )
            supervisor.execute(
                binding,
                request(target, provider),
                executor="worker:before-crash",
                interface_version=provider.version,
                adapter=write_adapter(provider),
                now=T1,
            )
            observed = evidence("evidence:still-live", "external effect reconciled after restart", "readback:x", True)
            with self.assertRaisesRegex(RestartRecoveryRejected, "still active"):
                RestartRecoveryRuntime(supervisor).reconcile_observed_effect(
                    TASK,
                    ACTION,
                    effect_state=EffectState.CONFIRMED,
                    evidence=observed,
                    worker_id="worker:other",
                    now="2026-09-01T00:00:02Z",
                )
            self.assertEqual(fake.posts, 1)
            store.close()


if __name__ == "__main__":
    unittest.main()
