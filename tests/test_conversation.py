import unittest

from bro_runtime.conversation import ConversationRejected, ConversationalInteractionSurface, InteractionMode
from bro_runtime.final_delivery import IntelligentInteractionRuntime
from bro_runtime.interaction_surface import InteractionSurface


class ConversationalInteractionSurfaceTests(unittest.TestCase):
    def make_surface(self, mode="TALK"):
        calls = []
        runtime = IntelligentInteractionRuntime(
            interpreter=lambda request: {
                "scope": [request],
                "constraints": ["existing governed path"],
                "success_conditions": ["external readback"],
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
        action_surface = InteractionSurface(runtime)
        routed_history = []

        def router(request, history):
            routed_history.append((request, tuple(history)))
            return {"mode": mode}

        def responder(actual_mode, request, history):
            calls.append(("respond", actual_mode.value, request, len(history)))
            return f"reply:{actual_mode.value}:{request}"

        return ConversationalInteractionSurface(
            action_surface=action_surface,
            router=router,
            responder=responder,
        ), calls, routed_history

    def test_talk_returns_reply_without_external_effect(self):
        surface, calls, _ = self.make_surface("TALK")
        result = surface.submit("Let's discuss the architecture")
        self.assertEqual(result["mode"], "TALK")
        self.assertEqual(result["response"], "reply:TALK:Let's discuss the architecture")
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(calls, [("respond", "TALK", "Let's discuss the architecture", 0)])

    def test_think_keeps_bounded_conversation_state_for_followup(self):
        surface, calls, routed_history = self.make_surface("THINK")
        surface.submit("Compare two designs")
        surface.submit("What was the stronger one?")
        self.assertEqual(calls[0], ("respond", "THINK", "Compare two designs", 0))
        self.assertEqual(calls[1], ("respond", "THINK", "What was the stronger one?", 2))
        self.assertEqual(len(routed_history[1][1]), 2)
        self.assertEqual(routed_history[1][1][0].role, "user")
        self.assertEqual(routed_history[1][1][1].role, "assistant")

    def test_act_delegates_to_existing_governed_action_surface(self):
        surface, calls, _ = self.make_surface("ACT")
        routed = surface.submit("Create the governed GitHub comment")
        self.assertEqual(routed["mode"], "ACT")
        self.assertTrue(routed["requires_confirmation"])
        self.assertEqual(calls, [])
        preview = routed["action"]
        receipt = surface.confirm_and_execute(
            preview["request_id"],
            confirmed_by="gev",
            scope_digest=preview["scope_digest"],
        )
        self.assertEqual(receipt["assurance"], "external_system")
        self.assertEqual(calls, [("execute", "specialist:github"), ("readback",)])

    def test_invalid_router_mode_fails_closed(self):
        surface, calls, _ = self.make_surface("MAYBE")
        with self.assertRaises(ConversationRejected):
            surface.submit("Do something")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
