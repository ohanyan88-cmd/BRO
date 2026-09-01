import unittest

from bro_runtime.automation import AutomationDispatcher, AutomationRuntime
from bro_runtime.governed_automation import AutomationExecutionSpec, GovernedAutomationExecutor
from bro_runtime.immune import AuthorityEnvelope
from bro_runtime.kernel import BROKernel
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.skills import Capability, CapabilityKind, CapabilityStatus
from bro_runtime.task_runtime import SQLiteTaskStore, TaskRuntime

T0 = "2026-09-01T10:00:00Z"
T1 = "2026-09-01T10:00:01Z"


class GovernedAutomationTests(unittest.TestCase):
    def setUp(self):
        self.tasks = SQLiteTaskStore()
        self.mind = SQLiteMindStore()
        self.kernel = BROKernel(self.tasks, self.mind)
        self.automation = AutomationRuntime(self.tasks.connection)
        self.addCleanup(self.tasks.close)
        self.addCleanup(self.mind.close)
        self.kernel.skills.register(Capability(
            capability_id="cap:automation-write", version=1, kind=CapabilityKind.TOOL_ADAPTER,
            name="Automation writer", description="Executes governed automation work",
            operations=("write",), domains=("ops",), input_contract_ref=None,
            output_contract_ref="artifact:automation", dependency_refs=(), authority_requirements=("write",),
            evidence_capabilities=("inspect",), provider_ref="adapter:ops", health_ref=None,
            status=CapabilityStatus.ACTIVE, recorded_at=T0,
        ))

    def definition(self, automation_id="automation:wave-a"):
        return self.automation.create_interval(
            automation_id=automation_id,
            project_boundary="project:BRO",
            desired_outcome="Execute governed scheduled work",
            interval_seconds=60,
            first_due_at=T0,
        )

    @staticmethod
    def spec(_definition, _occurrence):
        return AutomationExecutionSpec(
            interpreted_scope=("ops", "scheduled-work"), success_conditions=("work completed",),
            operation="write", domain="ops", authority_basis="stored automation policy requires fresh authority",
            materiality="MATERIAL", risk_class="R2", expected_output="artifact:automation",
            verification_requirement="inspect result",
        )

    @staticmethod
    def allowed(definition, occurrence, prepared):
        return AuthorityEnvelope(
            envelope_id=f"auth:{occurrence.occurrence_id}", version=1, principal="BRO", proof_ref="proof:policy",
            authority_source="policy", operation="write", target="ops:scheduled-work",
            allowed_scope=("operation:write", "target:ops:scheduled-work", prepared.assignment.task_ref, "project:BRO"),
            prohibited_scope=(), task_ref=prepared.assignment.task_ref, risk_class="R2", valid_from=T0,
            expires_at="2026-09-02T00:00:00Z", revocation_ref=None, environment="prod",
            tool_boundary=("adapter:ops",), decision="ALLOWED", reason="fresh bounded authority",
            audit_ref=f"audit:{occurrence.occurrence_id}",
        )

    @staticmethod
    def approval_required(definition, occurrence, prepared):
        envelope = GovernedAutomationTests.allowed(definition, occurrence, prepared)
        return AuthorityEnvelope(**{**envelope.__dict__, "decision": "APPROVAL_REQUIRED", "reason": "human approval required"})

    def test_due_occurrence_adopts_reserved_task_and_enters_governed_execution(self):
        self.definition()
        executor = GovernedAutomationExecutor(
            self.automation, self.kernel, spec_for=self.spec, authority_for=self.allowed
        )
        results = executor.tick(now=T0, worker_id="specialist:automation")
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.state, "EXECUTING")
        task = self.tasks.fetch_task(result.task_ref)
        self.assertEqual(task["goal_ref"], "automation-goal:automation:wave-a")
        self.assertEqual(task["authority_state"], "ALLOWED")
        events = [row["event_type"] for row in self.tasks.events(result.task_ref)]
        self.assertEqual(events.count("task.received"), 1)
        self.assertEqual(events.count("task.adopted"), 1)
        self.assertIn("assignment.leased", events)

    def test_restart_reconciles_task_created_but_not_opened_without_duplicate(self):
        self.definition("automation:restart-open")
        dispatcher = AutomationDispatcher(self.automation, TaskRuntime(self.tasks))
        occurrence = dispatcher.tick(now=T0)[0]
        self.assertEqual(self.tasks.fetch_task(occurrence.task_ref)["state"], "RECEIVED")

        executor = GovernedAutomationExecutor(
            self.automation, self.kernel, spec_for=self.spec, authority_for=self.allowed
        )
        results = executor.reconcile_created(worker_id="specialist:automation", now=T1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_ref, occurrence.task_ref)
        self.assertEqual(self.tasks.fetch_task(occurrence.task_ref)["state"], "EXECUTING")
        count = self.tasks.connection.execute(
            "SELECT COUNT(*) AS count FROM tasks WHERE task_id=?", (occurrence.task_ref,)
        ).fetchone()["count"]
        self.assertEqual(count, 1)

    def test_authority_required_is_blocked_not_silently_granted_by_schedule(self):
        self.definition("automation:approval")
        executor = GovernedAutomationExecutor(
            self.automation, self.kernel, spec_for=self.spec, authority_for=self.approval_required
        )
        result = executor.tick(now=T0, worker_id="specialist:automation")[0]
        task = self.tasks.fetch_task(result.task_ref)
        self.assertEqual(result.state, "BLOCKED")
        self.assertEqual(task["authority_state"], "APPROVAL_REQUIRED")
        self.assertEqual(task["blocker_ref"], result.blocker_ref)

    def test_reconcile_does_not_reopen_advanced_task(self):
        self.definition("automation:no-replay")
        executor = GovernedAutomationExecutor(
            self.automation, self.kernel, spec_for=self.spec, authority_for=self.allowed
        )
        first = executor.tick(now=T0, worker_id="specialist:automation")
        self.assertEqual(first[0].state, "EXECUTING")
        self.assertEqual(executor.reconcile_created(worker_id="specialist:other", now=T1), ())
        events = [row["event_type"] for row in self.tasks.events(first[0].task_ref)]
        self.assertEqual(events.count("assignment.leased"), 1)


if __name__ == "__main__":
    unittest.main()
