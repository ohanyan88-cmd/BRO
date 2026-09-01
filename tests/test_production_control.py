import sqlite3, unittest
from bro_runtime.acceptance_runtime import AcceptanceResult, AcceptanceRun, AcceptanceVerdict
from bro_runtime.deployment_runtime import DeploymentResult, ReleaseState
from bro_runtime.production_control import ProductionControlPlane, ProductionControlRejected, ProductionState

class ProductionControlTests(unittest.TestCase):
    def setUp(self): self.c=sqlite3.connect(':memory:'); self.runtime=ProductionControlPlane(self.c)
    def test_activation_requires_promoted_deployment_and_external_acceptance(self):
        deployment=DeploymentResult('release:1','production',ReleaseState.PROMOTED,'evidence:deploy:1')
        acceptance=AcceptanceRun('acceptance:1',AcceptanceVerdict.PASS,(AcceptanceResult('external',True,'evidence:external','ok','external_system'),),'2026-09-01T00:00:00+00:00')
        active=self.runtime.activate(deployment=deployment,artifact_ref='artifact:1',source_revision='git:1',acceptance=acceptance)
        self.assertEqual(active.state,ProductionState.ACTIVE); self.assertEqual(self.runtime.active('production').release_ref,'release:1')
    def test_repository_only_acceptance_cannot_activate_production(self):
        deployment=DeploymentResult('release:1','production',ReleaseState.PROMOTED,'evidence:deploy:1')
        acceptance=AcceptanceRun('acceptance:1',AcceptanceVerdict.PASS,(AcceptanceResult('repo',True,'evidence:repo','ok','repository'),),'2026-09-01T00:00:00+00:00')
        with self.assertRaisesRegex(ProductionControlRejected,'external evidence'):
            self.runtime.activate(deployment=deployment,artifact_ref='artifact:1',source_revision='git:1',acceptance=acceptance)
    def test_new_activation_supersedes_previous_active_release(self):
        a=AcceptanceRun('acceptance:1',AcceptanceVerdict.PASS,(AcceptanceResult('external',True,'evidence:external','ok','production'),),'2026-09-01T00:00:00+00:00')
        for n in ('1','2'):
            self.runtime.activate(deployment=DeploymentResult(f'release:{n}','production',ReleaseState.PROMOTED,f'evidence:deploy:{n}'),artifact_ref=f'artifact:{n}',source_revision=f'git:{n}',acceptance=a)
        self.assertEqual(self.runtime.active('production').release_ref,'release:2')
    def test_latest_heartbeat_is_observable_per_instance(self):
        self.runtime.heartbeat(service_id='bro',instance_id='worker-1',revision='git:1',state='HEALTHY',evidence_ref='probe:1',observed_at='2026-09-01T00:00:00+00:00')
        self.runtime.heartbeat(service_id='bro',instance_id='worker-1',revision='git:2',state='DEGRADED',evidence_ref='probe:2',observed_at='2026-09-01T00:01:00+00:00')
        latest=self.runtime.latest_heartbeats('bro'); self.assertEqual(len(latest),1); self.assertEqual(latest[0].revision,'git:2'); self.assertEqual(latest[0].state,'DEGRADED')
if __name__=='__main__': unittest.main()
