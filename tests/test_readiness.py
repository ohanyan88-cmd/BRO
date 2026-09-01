import unittest
from bro_runtime.readiness import CheckState, ReadinessCheck, ReadinessMeter

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

if __name__ == "__main__": unittest.main()
