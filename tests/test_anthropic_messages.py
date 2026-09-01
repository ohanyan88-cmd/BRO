import json, unittest
from bro_runtime.anthropic_messages import AnthropicMessagesConfig, AnthropicMessagesModel, AnthropicMessagesRejected

class AnthropicMessagesTests(unittest.TestCase):
    def test_native_headers_payload_and_model_ref(self):
        calls=[]
        def transport(method,url,headers,data,timeout):
            calls.append((method,url,headers,json.loads(data),timeout)); return {"content":[{"type":"text","text":json.dumps({"scope":["isolated issue comment"],"constraints":["bounded context only"],"success_conditions":["external readback"],"material":True})}]}
        model=AnthropicMessagesModel(AnthropicMessagesConfig(api_key="secret",model="claude-haiku-4-5"),transport=transport)
        self.assertTrue(model.interpret("bounded request")["material"]); self.assertEqual(model.config.model_ref,"anthropic:messages:claude-haiku-4-5")
        self.assertEqual(calls[0][2]["x-api-key"],"secret"); self.assertEqual(calls[0][2]["anthropic-version"],"2023-06-01"); self.assertNotIn("secret",calls[0][3]["messages"][0]["content"])
    def test_specialist_and_fail_closed(self):
        model=AnthropicMessagesModel(AnthropicMessagesConfig(api_key="x",model="claude-haiku-4-5"),transport=lambda *a:{"content":[{"type":"text","text":"{\"specialist_ref\":\"specialist:github-operations\"}"}]})
        self.assertEqual(model.select_specialist("task",("scope",)),"specialist:github-operations")
        bad=AnthropicMessagesModel(AnthropicMessagesConfig(api_key="x",model="claude-haiku-4-5"),transport=lambda *a:{"content":[]})
        with self.assertRaises(AnthropicMessagesRejected): bad.interpret("task")
    def test_rejects_test_model_and_http(self):
        with self.assertRaises(AnthropicMessagesRejected): AnthropicMessagesConfig(api_key="x",model="test:fixture")
        with self.assertRaises(AnthropicMessagesRejected): AnthropicMessagesConfig(api_key="x",model="claude-haiku-4-5",api_url="http://localhost")
if __name__ == "__main__": unittest.main()
