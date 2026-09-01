import unittest

from bro_runtime.final_delivery import FinalDeliveryRejected, IntelligentInteractionRuntime
from bro_runtime.interaction_surface import InteractionSurface


class InteractionSurfaceTests(unittest.TestCase):
    def make_surface(self):
        calls = []
        runtime = IntelligentInteractionRuntime(
            interpreter=lambda request: {
                "scope": ["create governed GitHub issue comment"],
                "constraints": ["same production execution path"],
                "success_conditions": ["external readback confirms the comment"],
                "material": True,
            },
            planner=lambda _intent: "specialist:github",
            executor=lambda _intent, specialist: calls.append(("execute", specialist)) or {
                "provider_ref": "github:adapter@1:write",
                "effect_ref": "github-effect:issue-comment:42",
            },
            readback=lambda _intent, _effect: calls.append(("readback",)) or {
                "provider_ref": "github:adapter@1:readback",
                "readback_ref": "observation:comment:42",
                "evidence_ref": "github-external-readback:comment:42",
                "assurance": "external_system",
            },
            model_ref="model:production",
        )
        return InteractionSurface(runtime), calls

    def test_submit_exposes_interpreted_scope_and_confirmation_digest(self):
        surface, calls = self.make_surface()
        preview = surface.submit("Do the real thing")
        self.assertEqual(preview["raw_request"], "Do the real thing")
        self.assertEqual(preview["interpreted_scope"], ["create governed GitHub issue comment"])
        self.assertTrue(preview["requires_confirmation"])
        self.assertEqual(len(preview["scope_digest"]), 64)
        self.assertEqual(calls, [])

    def test_confirmation_executes_through_runtime_and_returns_readback(self):
        surface, calls = self.make_surface()
        preview = surface.submit("Do the real thing")
        result = surface.confirm_and_execute(
            preview["request_id"], confirmed_by="gev", scope_digest=preview["scope_digest"]
        )
        self.assertEqual(calls, [("execute", "specialist:github"), ("readback",)])
        self.assertEqual(result["assurance"], "external_system")
        self.assertEqual(result["readback_ref"], "observation:comment:42")

    def test_bad_digest_fails_closed_before_execution(self):
        surface, calls = self.make_surface()
        preview = surface.submit("Do the real thing")
        with self.assertRaises(FinalDeliveryRejected):
            surface.confirm_and_execute(preview["request_id"], confirmed_by="gev", scope_digest="bad")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
