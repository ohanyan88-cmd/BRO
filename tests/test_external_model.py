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


if __name__ == "__main__":
    unittest.main()
