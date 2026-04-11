import unittest

from quiet_droid.client import OpenAICompatClient


class DummyConfig:
    def __init__(self, base_url):
        self.base_url = base_url
        self.api_key = "test-key"
        self.temperature = 0.7
        self.max_tokens = 1024


class ClientTests(unittest.TestCase):
    def test_glm_chat_uses_non_v1_endpoint(self):
        client = OpenAICompatClient(DummyConfig("https://api.z.ai/api/paas/v4"))
        self.assertEqual(
            client._build_url("/chat/completions", model="glm-4.5"),
            "https://api.z.ai/api/paas/v4/chat/completions",
        )

    def test_non_glm_chat_keeps_v1_endpoint(self):
        client = OpenAICompatClient(DummyConfig("https://example.com/api"))
        self.assertEqual(
            client._build_url("/chat/completions", model="gpt-4.1-mini"),
            "https://example.com/api/v1/chat/completions",
        )

    def test_existing_v1_base_url_is_preserved(self):
        client = OpenAICompatClient(DummyConfig("https://example.com/v1"))
        self.assertEqual(
            client._build_url("/chat/completions", model="gpt-4.1-mini"),
            "https://example.com/v1/chat/completions",
        )

    def test_glm_allows_chat_without_models_check(self):
        client = OpenAICompatClient(DummyConfig("https://api.z.ai/api/paas/v4"))
        self.assertTrue(client.allows_chat_without_models_check("glm-5.1"))
        self.assertFalse(client.allows_chat_without_models_check("gpt-4.1-mini"))


if __name__ == "__main__":
    unittest.main()
