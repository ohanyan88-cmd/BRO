import json
import unittest

from bro_runtime.external_model import ExternalModel, ExternalModelConfig, ExternalModelRejected


class ExternalModelTests(unittest.TestCase):
    def test_declares_provider_model_and_keeps_bounded_payload(self):
        calls = []
        def transport(method, url, headers, data, timeout):
            calls.append((method, url, headers, json.loads(data), timeout))
            return {"choices": [{"message": {"content": json.dumps({"scope": ["comment on isolated issue"], "constraints": ["no other resource"], "success_conditions": ["readback matches"], "material": True})}}]}
        model = ExternalModel(ExternalModelConfig(provider="groq", api_key="secret", model="openai/gpt-oss-120b", api_url="https://api.groq.com/openai/v1/chat/completions"), transport=transport)
        result = model.interpret("bounded acceptance request")
        self.assertEqual(result["scope"], ["comment on isolated issue"])
        self.assertEqual(model.config.model_ref, "groq:openai-compatible:openai/gpt-oss-120b")
        payload = calls[0][3]
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")
        self.assertIn("bounded acceptance request", payload["messages"][0]["content"])
        self.assertNotIn("secret", payload["messages"][0]["content"])

    def test_selects_specialist_through_external_model(self):
        def transport(*args):
            return {"choices": [{"message": {"content": '{"specialist_ref":"specialist:github-operations"}'}}]}
        model = ExternalModel(ExternalModelConfig(provider="groq", api_key="x", model="openai/gpt-oss-120b", api_url="https://api.groq.com/openai/v1/chat/completions"), transport=transport)
        self.assertEqual(model.select_specialist("do task", ("github comment",)), "specialist:github-operations")

    def test_fails_closed_on_invalid_output(self):
        model = ExternalModel(ExternalModelConfig(provider="groq", api_key="x", model="openai/gpt-oss-120b", api_url="https://api.groq.com/openai/v1/chat/completions"), transport=lambda *args: {"choices": [{"message": {"content": "not-json"}}]})
        with self.assertRaises(ExternalModelRejected):
            model.interpret("request")

    def test_rejects_test_model_and_non_https_boundary(self):
        with self.assertRaises(ExternalModelRejected):
            ExternalModelConfig(provider="groq", api_key="x", model="test:fixture", api_url="https://api.groq.com/openai/v1/chat/completions")
        with self.assertRaises(ExternalModelRejected):
            ExternalModelConfig(provider="groq", api_key="x", model="real", api_url="http://localhost/model")



class ExternalModelOutputBudgetTests(unittest.TestCase):
    """A truncated answer must say it was truncated, not look like broken JSON."""

    def model(self, response, *, max_output_tokens=2048):
        self.sent = []

        def transport(method, url, headers, data, timeout):
            self.sent.append(json.loads(data))
            return response

        return ExternalModel(
            ExternalModelConfig(provider="stub", api_key="k", model="m",
                                api_url="https://example.invalid/v1",
                                max_output_tokens=max_output_tokens),
            transport=transport,
        )

    def test_an_output_budget_is_always_sent(self):
        model = self.model({"choices": [{"message": {"content": "{\"scope\": [\"x\"]}"}}]})
        model.json_object(instruction="do", request="thing")
        self.assertEqual(self.sent[0]["max_tokens"], 2048)

    def test_a_truncated_response_is_reported_as_truncated(self):
        truncated = {"choices": [{"finish_reason": "length", "message": {"content": "{\"claims\": [{"}}]}
        model = self.model(truncated)
        with self.assertRaisesRegex(ExternalModelRejected, "truncated"):
            model.json_object(instruction="do", request="thing")

    def test_a_completed_response_is_not_treated_as_truncated(self):
        complete = {"choices": [{"finish_reason": "stop", "message": {"content": "{\"claims\": []}"}}]}
        self.assertEqual(self.model(complete).json_object(instruction="do", request="thing"), {"claims": []})

    def test_a_fenced_json_object_is_unwrapped_not_rejected(self):
        # The production planner failure: a complete, correct object inside a ```json fence.
        fenced = {"choices": [{"finish_reason": "stop",
                               "message": {"content": "```json\n{\"topics\": [{\"topic\": \"t\"}]}\n```"}}]}
        self.assertEqual(self.model(fenced).json_object(instruction="plan", request="mission"),
                         {"topics": [{"topic": "t"}]})

    def test_a_fence_without_a_language_tag_is_unwrapped(self):
        fenced = {"choices": [{"finish_reason": "stop", "message": {"content": "```\n{\"a\": 1}\n```"}}]}
        self.assertEqual(self.model(fenced).json_object(instruction="plan", request="mission"), {"a": 1})

    def test_prose_around_json_is_still_a_genuine_failure(self):
        # Unwrapping a fence must not become "find braces anywhere": a model that answered
        # in prose has not answered, and hiding that would hide a real planner failure.
        prose = {"choices": [{"finish_reason": "stop",
                              "message": {"content": "Sure! Here is the plan: {\"topics\": []} hope that helps"}}]}
        with self.assertRaisesRegex(ExternalModelRejected, "did not return valid JSON"):
            self.model(prose).json_object(instruction="plan", request="mission")

    def test_a_truncated_fenced_response_is_still_reported_as_truncated(self):
        cut = {"choices": [{"finish_reason": "length", "message": {"content": "```json\n{\"topics\": [{"}}]}
        with self.assertRaisesRegex(ExternalModelRejected, "truncated"):
            self.model(cut).json_object(instruction="plan", request="mission")

    def test_a_non_object_answer_is_still_refused(self):
        listed = {"choices": [{"finish_reason": "stop", "message": {"content": "```json\n[1, 2]\n```"}}]}
        with self.assertRaisesRegex(ExternalModelRejected, "must be a JSON object"):
            self.model(listed).json_object(instruction="plan", request="mission")

    def test_a_non_positive_output_budget_is_refused(self):
        with self.assertRaisesRegex(ExternalModelRejected, "max_output_tokens"):
            ExternalModelConfig(provider="stub", api_key="k", model="m",
                                api_url="https://example.invalid/v1", max_output_tokens=0)


if __name__ == "__main__":
    unittest.main()
