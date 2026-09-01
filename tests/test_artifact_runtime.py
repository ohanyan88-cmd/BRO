import unittest

from bro_runtime.artifact_runtime import ArtifactRejected, ArtifactState, ArtifactStore
from bro_runtime.immune import Evidence, EvidenceFreshness, EvidenceLedger, EvidenceValidity, evidence_scope
from bro_runtime.task_runtime import SQLiteTaskStore

T0="2026-09-01T00:00:00Z"

class ArtifactRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.store=SQLiteTaskStore(); self.addCleanup(self.store.close)
        self.evidence=EvidenceLedger(self.store.connection); self.artifacts=ArtifactStore(self.store.connection)
    def evidence_record(self,eid="evidence:artifact",scope=None,validity=EvidenceValidity.VALID,freshness=EvidenceFreshness.CURRENT):
        item=Evidence(eid,"artifact usable","inspection","artifact-store",{"readback":"artifact:1"},"read-back",T0,True,scope or evidence_scope("BRO","task:1"),(),validity,freshness,"IMMUNE_SYSTEM")
        self.evidence.record(item); return item
    def test_artifact_runtime_is_canonical_and_verified(self):
        produced=self.artifacts.produce(artifact_id="artifact:1",task_ref="task:1",assignment_ref="assignment:1",project_boundary="BRO",artifact_type="workflow-config",location_ref="repo:path/config.json",expected_contract_ref="contract:workflow",integrity_ref="sha256:abc")
        self.assertEqual(produced.state,ArtifactState.PRODUCED); self.assertEqual(produced.revision,1)
        evidence=self.evidence_record()
        verified=self.artifacts.verify("artifact:1",evidence.evidence_id)
        self.assertEqual(verified.state,ArtifactState.VERIFIED); self.assertEqual(verified.revision,2)
        self.assertEqual(verified.evidence_ref,evidence.evidence_id)
        self.assertEqual(self.artifacts.get("artifact:1",1).state,ArtifactState.PRODUCED)
        self.assertEqual(self.artifacts.get("artifact:1").state,ArtifactState.VERIFIED)
    def test_artifact_cannot_self_verify_or_cross_boundary(self):
        self.artifacts.produce(artifact_id="artifact:1",task_ref="task:1",assignment_ref="assignment:1",project_boundary="BRO",artifact_type="workflow-config",location_ref="repo:path/config.json")
        with self.assertRaisesRegex(ArtifactRejected,"canonical IMMUNE Evidence"):
            self.artifacts.verify("artifact:1","evidence:missing")
        foreign=self.evidence_record("evidence:foreign",evidence_scope("OTHER","task:1"))
        with self.assertRaisesRegex(ArtifactRejected,"crosses"):
            self.artifacts.verify("artifact:1",foreign.evidence_id)
    def test_stale_or_invalid_evidence_cannot_verify_artifact(self):
        self.artifacts.produce(artifact_id="artifact:1",task_ref="task:1",assignment_ref="assignment:1",project_boundary="BRO",artifact_type="workflow-config",location_ref="repo:path/config.json")
        stale=self.evidence_record("evidence:stale",freshness=EvidenceFreshness.STALE)
        with self.assertRaisesRegex(ArtifactRejected,"not sufficient"):
            self.artifacts.verify("artifact:1",stale.evidence_id)

if __name__=="__main__": unittest.main()
