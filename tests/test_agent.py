import io
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from quiet_droid.agent import Agent
from quiet_droid.session import MICROCOMPACT_CLEARED, Session


class DummyConfig:
    def __init__(self, root):
        self.cwd = root
        self.context_window = 10
        self.model = "test-model"
        self.session_id = None
        self.microcompact_gap_minutes = 60
        self.microcompact_keep_recent = 1


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

    def test_microcompact_runs_before_overflow_check(self):
        config = DummyConfig(self.tmpdir.name)
        config.context_window = 1000
        client = DummyClient()
        session = Session(config, "system")
        old_ts = time.time() - 120 * 60
        session.messages.extend(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "Read", "arguments": "{}"},
                        }
                    ],
                    "_timestamp": old_ts,
                },
                {"role": "tool", "tool_call_id": "c1", "content": "old result"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c2",
                            "type": "function",
                            "function": {"name": "Read", "arguments": "{}"},
                        }
                    ],
                    "_timestamp": old_ts,
                },
                {"role": "tool", "tool_call_id": "c2", "content": "recent result"},
            ]
        )
        session._recalculate_tokens()
        session.compact_if_needed = Mock(wraps=session.compact_if_needed)
        agent = Agent(
            config,
            client,
            DummyRegistry(),
            permissions=None,
            session=session,
            tui=DummyTUI(),
        )

        self.assertTrue(agent._ensure_context_window_before_send())
        self.assertEqual(session.messages[1]["content"], MICROCOMPACT_CLEARED)
        session.compact_if_needed.assert_not_called()

    def test_microcompact_prints_summary(self):
        config = DummyConfig(self.tmpdir.name)
        config.context_window = 1000
        client = DummyClient()
        session = Session(config, "system")
        old_ts = time.time() - 120 * 60
        session.messages.extend(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "Read", "arguments": "{}"},
                        }
                    ],
                    "_timestamp": old_ts,
                },
                {"role": "tool", "tool_call_id": "c1", "content": "old result"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c2",
                            "type": "function",
                            "function": {"name": "Read", "arguments": "{}"},
                        }
                    ],
                    "_timestamp": old_ts,
                },
                {"role": "tool", "tool_call_id": "c2", "content": "recent result"},
            ]
        )
        session._recalculate_tokens()
        agent = Agent(
            config,
            client,
            DummyRegistry(),
            permissions=None,
            session=session,
            tui=DummyTUI(),
        )

        output = io.StringIO()
        with redirect_stdout(output):
            agent._maybe_show_microcompact_result()

        rendered = output.getvalue()
        self.assertIn("Micro-compacted:", rendered)
        self.assertIn("results cleared", rendered)


if __name__ == "__main__":
    unittest.main()
