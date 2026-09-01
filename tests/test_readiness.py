import unittest
from types import SimpleNamespace
from bro_runtime.feet import RouteState
from bro_runtime.nervous_records import StepState
from bro_runtime.readiness import CheckState, ReadinessCheck, ReadinessMeter, RuntimeReadiness

class ReadinessMeterTests(unittest.TestCase):
    def setUp(self): self.meter=ReadinessMeter()
    def check(self, cid, state, weight=1):
        evidence=(f"evidence:{cid}",) if state is CheckState.PASS else ()
        return ReadinessCheck(cid,cid,weight,state,evidence)
    def test_100_requires_verified_done(self):
        checks=(self.check("scope",CheckState.PASS),self.check("tests",CheckState.PASS))
        report=self.meter.measure(build_checks=checks,production_checks=(),completion_verified=False)
        self.assertEqual(report.score,99); self.assertFalse(report.verified_done)
        done=self.meter.measure(build_checks=checks,production_checks=(),completion_verified=True)
        self.assertEqual(done.score,100); self.assertTrue(done.verified_done)
    def test_blocker_caps_readiness_and_is_named(self):
        report=self.meter.measure(build_checks=(self.check("code",CheckState.PASS,3),),production_checks=(self.check("deploy",CheckState.BLOCKED),),completion_verified=True)
        self.assertLess(report.score,100); self.assertEqual(report.blockers,("deploy",)); self.assertFalse(report.verified_done)
    def test_build_and_production_are_separate(self):
        report=self.meter.measure(build_checks=(self.check("code",CheckState.PASS),),production_checks=(self.check("recovery",CheckState.UNKNOWN),),completion_verified=False)
        self.assertEqual(report.build_score,100); self.assertEqual(report.production_score,0); self.assertEqual(report.missing,("recovery",))
    def test_pass_requires_evidence(self):
        with self.assertRaises(ValueError): ReadinessCheck("x","x",1,CheckState.PASS,())

class RuntimeReadinessTests(unittest.TestCase):
    def setUp(self): self.runtime=RuntimeReadiness()
    def test_verified_consistent_runtime_is_100(self):
        task={"task_id":"task:1","state":"COMPLETED","plan_ref":"plan:1","context_manifest_ref":"context:1","authority_state":"ALLOWED","completion_manifest_ref":"manifest:1"}
        step=SimpleNamespace(step_id="step:1",revision=3,state=StepState.SUCCEEDED)
        route=SimpleNamespace(route_id="route:1",version=2,state=RouteState.COMPLETED)
        manifest={"manifest_id":"manifest:1","task_ref":"task:1","verdict":"VERIFIED"}
        report=self.runtime.measure_task(task=task,step=step,route=route,completion_manifest=manifest)
        self.assertEqual(report.score,100); self.assertEqual(report.build_score,100); self.assertEqual(report.production_score,100)
    def test_task_manifest_mismatch_cannot_claim_done(self):
        task={"task_id":"task:1","state":"COMPLETED","plan_ref":"plan:1","context_manifest_ref":"context:1","authority_state":"ALLOWED","completion_manifest_ref":"manifest:other"}
        step=SimpleNamespace(step_id="step:1",revision=3,state=StepState.SUCCEEDED)
        route=SimpleNamespace(route_id="route:1",version=2,state=RouteState.COMPLETED)
        manifest={"manifest_id":"manifest:1","task_ref":"task:1","verdict":"VERIFIED"}
        report=self.runtime.measure_task(task=task,step=step,route=route,completion_manifest=manifest)
        self.assertLess(report.score,100); self.assertIn("evidence",report.missing); self.assertIn("truthful-terminal",report.missing)
    def test_blocked_runtime_names_authority_and_route(self):
        task={"task_id":"task:1","state":"BLOCKED","plan_ref":"plan:1","context_manifest_ref":"context:1","authority_state":"APPROVAL_REQUIRED","completion_manifest_ref":None}
        step=SimpleNamespace(step_id="step:1",revision=2,state=StepState.BLOCKED)
        route=SimpleNamespace(route_id="route:1",version=1,state=RouteState.BLOCKED)
        report=self.runtime.measure_task(task=task,step=step,route=route,completion_manifest=None)
        self.assertIn("route-terminal",report.blockers); self.assertIn("authority",report.blockers); self.assertFalse(report.verified_done)

if __name__ == "__main__": unittest.main()
