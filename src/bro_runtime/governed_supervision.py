"""Reference-closed NERVOUS SYSTEM entrypoint for governed flows."""
from __future__ import annotations

from .approval import ApprovalRegistry
from .mind import SQLiteMindStore
from .nervous_records import NervousRecordStore
from .reference_integrity import ReferenceIntegrity
from .supervision import TaskSupervisor


class GovernedTaskSupervisor(TaskSupervisor):
    """TaskSupervisor that refuses dangling Goal/Plan/Step/Context references."""

    def __init__(self, store, *, mind_store: SQLiteMindStore, verifier: str = "IMMUNE_SYSTEM") -> None:
        super().__init__(store, verifier=verifier)
        self.mind_store = mind_store
        self.nervous_records = NervousRecordStore(store.connection)
        self.approvals = ApprovalRegistry(store.connection)
        self.reference_integrity = ReferenceIntegrity(
            mind=mind_store, nervous=self.nervous_records,
            approvals=self.approvals, evidence=self.evidence,
        )

    def open_flow(self, *, task_id, goal_ref, plan_ref, assignment, envelope, worker_id,
                  plan_revision=1, actor="BRO", now=None, lease_seconds=30):
        self.reference_integrity.require_flow(
            task_id=task_id, goal_ref=goal_ref, plan_ref=plan_ref, plan_revision=plan_revision,
            step_ref=assignment.step_ref, context_manifest_ref=assignment.context_manifest_ref,
            project_boundary=assignment.project_boundary,
        )
        return super().open_flow(
            task_id=task_id, goal_ref=goal_ref, plan_ref=plan_ref, assignment=assignment,
            envelope=envelope, worker_id=worker_id, plan_revision=plan_revision,
            actor=actor, now=now, lease_seconds=lease_seconds,
        )

    def canonical_task(self, task_id: str) -> dict:
        task = self.store.canonical_task(task_id)
        self.reference_integrity.require_task_refs(task)
        return task
