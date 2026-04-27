import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from quiet_droid.agent import Agent
from quiet_droid.session import Session


class DummyConfig:
    def __init__(self, root):
        self.cwd = root
        self.context_window = 10
        self.model = "test-model"
        self.session_id = None


class DummyClient:
    def __init__(self):
        self.chat = Mock(return_value={"choices": [{"message": {"content": "done"}}]})


class DummyRegistry:
    def get_schemas(self):
        return []

    def get(self, name):
        return None

    def names(self):
        return []


class DummyTUI:
    def start_spinner(self, message):
        pass

    def stop_spinner(self):
        pass

    def show_sync_response(self, response, known_tools=None):
        return response["choices"][0]["message"]["content"], []

    def stream_response(self, response, known_tools=None):
        return "", []


class AgentContextWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_cwd = os.getcwd()
        os.chdir(self.tmpdir.name)

    def tearDown(self):
        os.chdir(self.original_cwd)
        self.tmpdir.cleanup()

    def test_context_window_overflow_stops_before_chat(self):
        config = DummyConfig(self.tmpdir.name)
        client = DummyClient()
        session = Session(config, "system")
        session.compact_if_needed = Mock(wraps=session.compact_if_needed)
        agent = Agent(config, client, DummyRegistry(), permissions=None, session=session, tui=DummyTUI())

        output = io.StringIO()
        with redirect_stdout(output):
            agent.run("x" * 80)

        session.compact_if_needed.assert_called_once_with(force=True)
        client.chat.assert_not_called()
        self.assertIn("Context window exceeded before API request.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
