from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bro_runtime.action_runtime import ActionRequest, AdapterResult, EffectState
from bro_runtime.evidence_verification import EvidenceObservation, EvidenceVerifier, VerificationResult
from bro_runtime.immune import AuthorityEnvelope, EvidenceFreshness, EvidenceValidity, evidence_scope
from bro_runtime.kernel import BROKernel, KernelRejected
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.provider_adapters import ProviderAdapter
from bro_runtime.provider_execution import ProviderRoute
from bro_runtime.skills import Capability, CapabilityKind, CapabilityStatus
from bro_runtime.supervision import NextAction
from bro_runtime.task_runtime import SQLiteTaskStore

T0 = "2026-09-01T00:00:00Z"
T1 = "2026-09-01T00:00:01Z"
T2 = "2026-09-01T00:10:00Z"


def register_capability(kernel: BROKernel) -> None:
    kernel.skills.register(
        Capability(
            capability_id="cap:restart-write",
            version=1,
            kind=CapabilityKind.TOOL_ADAPTER,
            name="restart write",
            description="kernel restart recovery test capability",
            operations=("write",),
            domains=("crm",),
            input_contract_ref=None,
            output_contract_ref="artifact:restart",
            dependency_refs=(),
            authority_requirements=("write",),
            evidence_capabilities=("readback",),
            provider_ref="crm",
            health_ref=None,
            status=CapabilityStatus.ACTIVE,
            recorded_at=T0,
        )
    )


def prepare(kernel: BROKernel):
    return kernel.prepare(
        request="Create restart-safe CRM customer",
        source="test",
        project_boundary="BRO",
        desired_outcome="customer exists after restart",
        interpreted_scope=("crm",),
        success_conditions=("customer exists",),
        operation="write",
        domain="crm",
        authority_basis="bounded test authority",
        materiality="MATERIAL",
        risk_class="R2",
        expected_output="artifact:customer",
        verification_requirement="external readback",
    )


def authority(prepared) -> AuthorityEnvelope:
    task_id = prepared.assignment.task_ref
    return AuthorityEnvelope(
        envelope_id="auth:kernel-restart",
        version=1,
        principal="BRO",
        proof_ref="proof:kernel-restart",
        authority_source="system",
        operation="write",
        target="crm:customers",
        allowed_scope=("operation:write", "target:crm:customers", task_id, "project:BRO"),
        prohibited_scope=(),
        task_ref=task_id,
        risk_class="R2",
        valid_from=T0,
        expires_at="2026-09-02T00:00:00Z",
        revocation_ref=None,
        environment="prod",
        tool_boundary=("crm",),
        decision="ALLOWED",
        reason="bounded restart test",
        audit_ref="audit:kernel-restart",
    )


def action(prepared) -> ActionRequest:
    return ActionRequest(
        action_request_id="action:kernel-restart",
        task_ref=prepared.assignment.task_ref,
        intended_effect="create customer",
        operation="write",
        target="crm:customers",
        environment="prod",
        adapter_id="crm",
        input_parameters={"name": "Restart"},
        authority_envelope_ref="auth:kernel-restart",
        risk_class="R2",
        reversibility="REVERSIBLE",
        idempotency_key="restart:customer:1",
        idempotency_guaranteed=True,
        expected_result={"id": "C-R"},
        verification_requirements=("external readback",),
        assignment_ref=prepared.assignment.assignment_id,
        project_boundary="BRO",
    )


class KernelRestartRecoveryTests(unittest.TestCase):
    def test_kernel_mints_trusted_evidence_then_reclaims_fenced_lease_and_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            task_db = Path(td) / "task.sqlite3"
            mind_db = Path(td) / "mind.sqlite3"

            tasks1 = SQLiteTaskStore(task_db)
            mind1 = SQLiteMindStore(mind_db)
            kernel1 = BROKernel(tasks1, mind1)
            register_capability(kernel1)
            kernel1.register_provider(
                ProviderAdapter(
                    adapter_id="crm",
                    provider="acme",
                    version="v1",
                    operations=("write",),
                    invoke=lambda _: AdapterResult({"accepted": True}, EffectState.POSSIBLE),
                    idempotent_operations=("write",),
                )
            )
            prepared = prepare(kernel1)
            task_id = prepared.assignment.task_ref
            route_id = prepared.route_id
            binding = kernel1.open(prepared, authority(prepared), worker_id="worker:before-crash", now=T1)
            attempt = kernel1.execute_provider(
                binding,
                action(prepared),
                route=ProviderRoute("acme", "crm", "v1"),
                executor="worker:before-crash",
                now=T1,
            )
            self.assertEqual(attempt["effect_state"], EffectState.POSSIBLE)
            tasks1.close()
            mind1.close()

            tasks2 = SQLiteTaskStore(task_db)
            mind2 = SQLiteMindStore(mind_db)
            self.addCleanup(tasks2.close)
            self.addCleanup(mind2.close)
            kernel2 = BROKernel(tasks2, mind2)
            kernel2.register_evidence_verifier(
                EvidenceVerifier(
                    "IMMUNE:restart-readback",
                    lambda observation: VerificationResult(
                        EvidenceValidity.VALID,
                        EvidenceFreshness.CURRENT,
                        {"verification_source": "independent-readback"},
                    ),
                )
            )

            before = kernel2.recover(task_id, route_id)
            self.assertIs(before.next_step.action, NextAction.RECONCILE_EFFECT)
            old_token = kernel2.supervisor.assignments.get_assignment(prepared.assignment.assignment_id)["fencing_token"]

            observation = EvidenceObservation(
                criterion="external effect reconciled after restart",
                evidence_type="external-readback",
                source="crm",
                provenance={"resource_ref": "customer:C-R"},
                collection_method="independent provider readback",
                result={"exists": True, "id": "C-R"},
                scope=evidence_scope("BRO", task_id),
            )
            recovered = kernel2.reconcile_after_restart(
                task_id,
                "action:kernel-restart",
                EffectState.CONFIRMED,
                observation,
                verifier_id="IMMUNE:restart-readback",
                worker_id="worker:after-restart",
                now=T2,
            )

            self.assertGreater(recovered.binding.lease.fencing_token, old_token)
            self.assertEqual(
                kernel2.supervisor.actions.effective_effect(
                    kernel2.supervisor.actions.latest_attempt("action:kernel-restart")
                ),
                EffectState.CONFIRMED,
            )
            after = kernel2.recover(task_id, route_id)
            self.assertIs(after.next_step.action, NextAction.SETTLE_ASSIGNMENT)
            events = tasks2.events(task_id)
            recovery = [event for event in events if event["event_type"] == "recovery.lease_reclaimed"]
            self.assertEqual(len(recovery), 1)
            self.assertIn('"command_replayed": false', recovery[0]["payload"])

    def test_kernel_rejects_foreign_restart_observation_before_reclaiming_lease(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tasks = SQLiteTaskStore(Path(td) / "task.sqlite3")
            mind = SQLiteMindStore(Path(td) / "mind.sqlite3")
            self.addCleanup(tasks.close)
            self.addCleanup(mind.close)
            kernel = BROKernel(tasks, mind)
            register_capability(kernel)
            kernel.register_provider(
                ProviderAdapter(
                    adapter_id="crm",
                    provider="acme",
                    version="v1",
                    operations=("write",),
                    invoke=lambda _: AdapterResult({"accepted": True}, EffectState.POSSIBLE),
                    idempotent_operations=("write",),
                )
            )
            kernel.register_evidence_verifier(
                EvidenceVerifier(
                    "IMMUNE:restart-readback",
                    lambda _: VerificationResult(EvidenceValidity.VALID, EvidenceFreshness.CURRENT, {}),
                )
            )
            prepared = prepare(kernel)
            binding = kernel.open(prepared, authority(prepared), worker_id="worker:1", now=T1)
            kernel.execute_provider(
                binding,
                action(prepared),
                route=ProviderRoute("acme", "crm", "v1"),
                executor="worker:1",
                now=T1,
            )
            before = kernel.supervisor.assignments.get_assignment(prepared.assignment.assignment_id)
            foreign = EvidenceObservation(
                criterion="external effect reconciled after restart",
                evidence_type="external-readback",
                source="crm",
                provenance={},
                collection_method="readback",
                result=True,
                scope=evidence_scope("OTHER", prepared.assignment.task_ref),
            )
            with self.assertRaisesRegex(KernelRejected, "crosses the persisted Task boundary"):
                kernel.reconcile_after_restart(
                    prepared.assignment.task_ref,
                    "action:kernel-restart",
                    EffectState.CONFIRMED,
                    foreign,
                    verifier_id="IMMUNE:restart-readback",
                    worker_id="worker:2",
                    now=T2,
                )
            after = kernel.supervisor.assignments.get_assignment(prepared.assignment.assignment_id)
            self.assertEqual(after["state"], before["state"])
            self.assertEqual(after["fencing_token"], before["fencing_token"])


if __name__ == "__main__":
    unittest.main()
