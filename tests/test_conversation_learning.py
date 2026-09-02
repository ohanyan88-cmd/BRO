import unittest

from bro_runtime.conversation import ConversationalInteractionSurface
from bro_runtime.final_delivery import IntelligentInteractionRuntime
from bro_runtime.interaction_surface import InteractionSurface


class ConversationLearningHookTests(unittest.TestCase):
    def make_surface(self, outcome_recorder):
        runtime = IntelligentInteractionRuntime(
            interpreter=lambda _request: {
                "scope": ["create governed GitHub issue comment"],
                "constraints": [],
                "success_conditions": ["external readback confirms effect"],
                "material": True,
            },
            planner=lambda _intent: "specialist:github",
            executor=lambda _intent, _specialist: {
                "provider_ref": "github:write",
                "effect_ref": "github-effect:1",
            },
            readback=lambda _intent, _effect: {
                "provider_ref": "github:readback",
                "readback_ref": "observation:1",
                "evidence_ref": "github-readback:1",
                "assurance": "external_system",
            },
            model_ref="model:production",
        )
        return ConversationalInteractionSurface(
            action_surface=InteractionSurface(runtime),
            router=lambda _request, _history: {"mode": "ACT"},
            responder=lambda _mode, _request, _history: "unused",
            outcome_recorder=outcome_recorder,
        )

    def test_success_is_reported_to_learning_hook(self):
        outcomes = []
        surface = self.make_surface(lambda *args: outcomes.append(args))
        result = surface.submit("do it")
        preview = result["action"]
        receipt = surface.confirm_and_execute(
            preview["request_id"], confirmed_by="gev", scope_digest=preview["scope_digest"]
        )
        self.assertEqual(receipt["evidence_ref"], "github-readback:1")
        self.assertEqual(outcomes[0][0], "do it")
        self.assertTrue(outcomes[0][1])

    def test_learning_failure_does_not_falsify_successful_action(self):
        def broken_learning(*_args):
            raise RuntimeError("learning unavailable")

        surface = self.make_surface(broken_learning)
        result = surface.submit("do it")
        preview = result["action"]
        receipt = surface.confirm_and_execute(
            preview["request_id"], confirmed_by="gev", scope_digest=preview["scope_digest"]
        )
        self.assertEqual(receipt["effect_ref"], "github-effect:1")
        self.assertEqual(surface.learning_errors, ("RuntimeError:learning unavailable",))


if __name__ == "__main__":
    unittest.main()
