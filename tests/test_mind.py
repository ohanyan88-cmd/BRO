import tempfile, unittest
from bro_runtime.mind import KnowledgeState, MindRejected, MindRuntime, SQLiteMindStore

class MindRuntimeTests(unittest.TestCase):
    def setUp(self): self.store=SQLiteMindStore(); self.mind=MindRuntime(self.store)
    def tearDown(self): self.store.close()
    def test_goal_decision_plan_and_replan_are_durable(self):
        g=self.mind.form_goal(intent_ref="intent:1",desired_outcome="implement MIND",interpreted_scope=("project:BRO",),success_conditions=("tests pass",),authority_basis="authority:user",materiality="MATERIAL",risk_class="LOW",goal_id="goal:1",uncertainty=KnowledgeState.CONFIRMED)
        d=self.mind.decide(goal_ref=g.goal_id,question="route?",conclusion="build",rationale="Task refs need a canonical producer",authority_basis="authority:user",uncertainty=KnowledgeState.DERIVED,reversibility="REVERSIBLE",decision_id="decision:1")
        p=self.mind.plan(goal_ref=g.goal_id,decision_ref=d.decision_id,step_refs=("step:1",),checkpoints=("tests",),recovery_options=("replan",),completion_path=("verify",),reason="initial",plan_id="plan:1")
        p2=self.mind.replan(p.plan_id,step_refs=("step:1","step:2"),reason="new evidence")
        self.assertEqual(self.store.goal("goal:1"),g); self.assertEqual(self.store.decision("decision:1"),d)
        self.assertEqual(self.store.plan("plan:1",1).step_refs,("step:1",)); self.assertEqual(p2.supersedes,"plan:1@1"); self.assertEqual(p2.revision,2)
    def test_goal_requires_success_condition(self):
        with self.assertRaises(MindRejected): self.mind.form_goal(intent_ref="i",desired_outcome="x",interpreted_scope=(),success_conditions=(),authority_basis="a",materiality="LOW",risk_class="LOW")
    def test_plan_requires_step_reference(self):
        with self.assertRaises(MindRejected): self.mind.plan(goal_ref="g",decision_ref="d",step_refs=(),checkpoints=(),recovery_options=(),completion_path=("verify",),reason="initial")
    def test_store_survives_reopen(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            s=SQLiteMindStore(f.name); m=MindRuntime(s); m.form_goal(intent_ref="i",desired_outcome="persist",interpreted_scope=("project:BRO",),success_conditions=("reload",),authority_basis="a",materiality="MATERIAL",risk_class="LOW",goal_id="goal:p"); s.close()
            s=SQLiteMindStore(f.name)
            try:self.assertEqual(s.goal("goal:p").desired_outcome,"persist")
            finally:s.close()

if __name__=="__main__": unittest.main()
