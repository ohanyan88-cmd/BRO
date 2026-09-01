"""Fail-closed resolution of canonical references across BRO organ owners."""
from __future__ import annotations

from .immune import EvidenceLedger, normalize_boundary_scope
from .mind import SQLiteMindStore
from .nervous_records import NervousRecordStore
from .approval import ApprovalRegistry


class ReferenceIntegrityError(ValueError):
    pass


class ReferenceIntegrity:
    """Resolve canonical references to records owned by the organ that declares them."""

    def __init__(self, *, mind: SQLiteMindStore, nervous: NervousRecordStore,
                 approvals: ApprovalRegistry, evidence: EvidenceLedger) -> None:
        self.mind = mind
        self.nervous = nervous
        self.approvals = approvals
        self.evidence = evidence

    def require_flow(self, *, task_id: str, goal_ref: str, plan_ref: str, plan_revision: int,
                     step_ref: str, context_manifest_ref: str, project_boundary: str) -> None:
        try:
            goal = self.mind.goal(goal_ref)
        except KeyError as exc:
            raise ReferenceIntegrityError(f"goal_ref does not resolve: {goal_ref}") from exc
        try:
            plan = self.mind.plan(plan_ref, plan_revision)
        except KeyError as exc:
            raise ReferenceIntegrityError(f"plan_ref does not resolve at revision {plan_revision}: {plan_ref}") from exc
        if plan.goal_ref != goal.goal_id:
            raise ReferenceIntegrityError("Plan resolves to a different Goal")
        if step_ref not in plan.step_refs:
            raise ReferenceIntegrityError("active Step is not referenced by the selected Plan revision")
        try:
            step = self.nervous.step(step_ref)
        except KeyError as exc:
            raise ReferenceIntegrityError(f"step_ref does not resolve: {step_ref}") from exc
        if (step.task_ref, step.plan_ref, step.plan_revision) != (task_id, plan_ref, plan_revision):
            raise ReferenceIntegrityError("Step is not bound to this Task and Plan revision")
        try:
            context = self.nervous.context_manifest(context_manifest_ref)
        except KeyError as exc:
            raise ReferenceIntegrityError(f"context_manifest_ref does not resolve: {context_manifest_ref}") from exc
        if context.task_ref != task_id:
            raise ReferenceIntegrityError("Context Manifest belongs to a different Task")
        if normalize_boundary_scope(context.isolation_boundary) != normalize_boundary_scope(project_boundary):
            raise ReferenceIntegrityError("Context Manifest crosses the project isolation boundary")

    def require_task_refs(self, task: dict) -> None:
        self.require_flow(
            task_id=task["task_id"], goal_ref=task["goal_ref"], plan_ref=task["plan_ref"],
            plan_revision=task["plan_revision"], step_ref=task["active_step_ref"],
            context_manifest_ref=task["context_manifest_ref"], project_boundary=self.nervous.context_manifest(task["context_manifest_ref"]).isolation_boundary,
        )
        for approval_ref in task["approval_refs"]:
            try:
                row = self.approvals.get(approval_ref)
            except Exception as exc:
                raise ReferenceIntegrityError(f"approval_ref does not resolve: {approval_ref}") from exc
            if row["task_ref"] != task["task_id"]:
                raise ReferenceIntegrityError(f"approval_ref belongs to another Task: {approval_ref}")
        if task["state"] == "COMPLETED":
            manifest_ref = task.get("completion_manifest_ref")
            if not manifest_ref:
                raise ReferenceIntegrityError("COMPLETED Task lacks completion_manifest_ref")
            try:
                manifest = self.evidence.manifest(manifest_ref)
            except Exception as exc:
                raise ReferenceIntegrityError(f"completion_manifest_ref does not resolve: {manifest_ref}") from exc
            if manifest["task_ref"] != task["task_id"] or manifest["verdict"] != "VERIFIED":
                raise ReferenceIntegrityError("completion_manifest_ref is not this Task's VERIFIED manifest")
