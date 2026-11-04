from unittest import TestCase
from io import BytesIO
import json
from unittest.mock import Mock, patch

from model import configured_model, validate_model


class AiSettingsTests(TestCase):
    def test_claude_translates_structured_response(self):
        client = configured_model({"provider": "claude", "model": "example", "key": "test-key"})
        body = {"content": [{"type": "tool_use", "name": "return_json", "input": {"ok": True}}]}
        with patch("model.urlopen", return_value=BytesIO(json.dumps(body).encode())) as send:
            result = client.complete({"model": client.model, "response_format": {"type": "json_object"},
                                      "messages": [{"role": "system", "content": "Instructions"},
                                                   {"role": "user", "content": "Return JSON"}]})
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "test-key")
        self.assertEqual(json.loads(request.data)["tool_choice"]["name"], "return_json")
        self.assertEqual(json.loads(result["content"]), {"ok": True})

    def test_compatible_providers_route_to_their_own_endpoints(self):
        endpoints = {
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "groq": "https://api.groq.com/openai/v1/chat/completions",
            "deepseek": "https://api.deepseek.com/chat/completions",
        }
        for provider, endpoint in endpoints.items():
            with self.subTest(provider=provider):
                client = configured_model({"provider": provider, "model": "example", "key": "test-key"})
                with patch("model.urlopen", return_value=BytesIO(b'{"choices":[{"message":{"content":"OK"}}]}')) as send:
                    self.assertEqual(client.complete({"model": client.model})["content"], "OK")
                self.assertEqual(send.call_args.args[0].full_url, endpoint)

    def test_ollama_uses_no_cloud_key(self):
        client = configured_model({"provider": "ollama", "model": "local:latest", "key": "unused"})
        self.assertEqual((client.provider, client.model, client.key), ("ollama", "local:latest", ""))

    def test_reports_partial_capabilities(self):
        client = Mock(model="example")
        client.complete.side_effect = [{"content": "OK"}, ValueError("Unsupported tools"),
                                       {"content": '{"ok": true}'}]
        result = validate_model(client)
        self.assertTrue(result["connected"])
        self.assertFalse(result["tools"])
        self.assertTrue(result["json"])
