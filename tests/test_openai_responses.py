import json
import unittest

from bro_runtime.openai_responses import (
    OpenAIResponsesConfig,
    OpenAIResponsesModel,
    OpenAIResponsesRejected,
)


class OpenAIResponsesTests(unittest.TestCase):
    @staticmethod
    def _response(text):
        return {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}
            ]
        }

    def test_interpret_uses_declared_external_model_boundary(self):
        calls = []

        def transport(method, url, headers, data, timeout):
            calls.append((method, url, headers, json.loads(data), timeout))
            return self._response(json.dumps({
                "scope": ["github", "issue-comment"],
                "constraints": ["no destructive writes"],
                "success_conditions": ["external comment reads back"],
                "material": True,
            }))

        model = OpenAIResponsesModel(
            OpenAIResponsesConfig("secret-value", "gpt-5.6-terra"), transport=transport
        )
        parsed = model.interpret("Perform production acceptance")
        self.assertEqual(parsed["scope"], ["github", "issue-comment"])
        self.assertEqual(model.config.model_ref, "openai:responses:gpt-5.6-terra")
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "https://api.openai.com/v1/responses")
        self.assertEqual(calls[0][2]["Authorization"], "Bearer secret-value")
        self.assertEqual(calls[0][3]["model"], "gpt-5.6-terra")

    def test_specialist_selection_is_model_derived_and_nonempty(self):
        model = OpenAIResponsesModel(
            OpenAIResponsesConfig("secret-value", "gpt-5.6-terra"),
            transport=lambda *args: self._response('{"specialist_ref":"specialist:github-operations"}'),
        )
        self.assertEqual(
            model.select_specialist("write acceptance", ("github",)),
            "specialist:github-operations",
        )

    def test_invalid_or_empty_model_output_fails_closed(self):
        model = OpenAIResponsesModel(
            OpenAIResponsesConfig("secret-value", "gpt-5.6-terra"),
            transport=lambda *args: self._response("not-json"),
        )
        with self.assertRaisesRegex(OpenAIResponsesRejected, "valid JSON"):
            model.interpret("do work")

        empty = OpenAIResponsesModel(
            OpenAIResponsesConfig("secret-value", "gpt-5.6-terra"),
            transport=lambda *args: {"output": []},
        )
        with self.assertRaisesRegex(OpenAIResponsesRejected, "output text"):
            empty.interpret("do work")

    def test_test_model_and_non_https_boundary_are_rejected(self):
        with self.assertRaises(OpenAIResponsesRejected):
            OpenAIResponsesConfig("x", "test:model")
        with self.assertRaises(OpenAIResponsesRejected):
            OpenAIResponsesConfig("x", "gpt-5.6-terra", api_url="http://localhost/model")


if __name__ == "__main__":
    unittest.main()
