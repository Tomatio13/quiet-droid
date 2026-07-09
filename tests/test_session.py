import os
import tempfile
import time
import unittest

from quiet_droid.session import (
    COMPACTABLE_TOOLS,
    MICROCOMPACT_CLEARED,
    MICROCOMPACT_IMAGE_CLEARED,
    Session,
)


class DummyConfig:
    def __init__(self, context_window, root=None):
        self.context_window = context_window
        self.session_id = None
        self.model = "test-model"
        self.cwd = root or os.getcwd()
        self.sessions_dir = root or os.getcwd()
        self.microcompact_gap_minutes = 60
        self.microcompact_keep_recent = 5


class SessionContextWindowTests(unittest.TestCase):
    def test_context_window_status_is_ok_within_limit(self):
        session = Session(DummyConfig(context_window=100), "system")
        session.add_user_message("hello")

        status = session.context_window_status()

        self.assertTrue(status["ok"])
        self.assertLessEqual(status["current"], status["limit"])
        self.assertEqual(status["over_by"], 0)

    def test_context_window_status_reports_overflow(self):
        session = Session(DummyConfig(context_window=10), "system")
        session.add_user_message("x" * 80)

        status = session.context_window_status()

        self.assertFalse(status["ok"])
        self.assertGreater(status["current"], status["limit"])
        self.assertEqual(status["over_by"], status["current"] - status["limit"])
        self.assertGreater(status["pct"], 100)

    def test_save_and_load_restores_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DummyConfig(context_window=1000, root=tmpdir)
            session = Session(config, "system")
            session.add_user_message("hello")
            session.add_droid_message("done")
            session.save()

            restored = Session(config, "system")
            self.assertTrue(restored.load(session.session_id))

        self.assertEqual([m["role"] for m in restored.messages], ["user", "assistant"])
        self.assertEqual(restored.messages[0]["content"], "hello")
        self.assertEqual(restored.messages[1]["content"], "done")

    def test_save_updates_project_session_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DummyConfig(context_window=1000, root=tmpdir)
            session = Session(config, "system")
            session.add_user_message("hello")
            session.save()

            self.assertEqual(Session.get_project_session(config), session.session_id)

    def test_list_sessions_returns_saved_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DummyConfig(context_window=1000, root=tmpdir)
            session = Session(config, "system")
            session.add_user_message("hello")
            session.save()

            sessions = Session.list_sessions(config)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], session.session_id)


class MicrocompactTests(unittest.TestCase):
    def _make_session(self, gap=60, keep=5, context_window=100000):
        config = DummyConfig(context_window=context_window)
        config.microcompact_gap_minutes = gap
        config.microcompact_keep_recent = keep
        return Session(config, "system")

    def _add_tool_exchange(self, session, tool_name, call_id, result_text, ts=None):
        """Add an assistant message with a tool call + a tool result."""
        tc = {
            "id": call_id,
            "type": "function",
            "function": {"name": tool_name, "arguments": "{}"},
        }
        if ts is not None:
            msg = {"role": "assistant", "content": None, "tool_calls": [tc]}
            msg["_timestamp"] = ts
            session.messages.append(msg)
        else:
            session.add_droid_message(None, tool_calls=[tc])
        session.messages.append(
            {"role": "tool", "tool_call_id": call_id, "content": result_text}
        )

    def test_no_action_when_recent(self):
        session = self._make_session()
        self._add_tool_exchange(session, "Read", "c1", "file contents", ts=time.time())
        self.assertFalse(session.microcompact_if_needed())
        self.assertEqual(session.messages[1]["content"], "file contents")

    def test_clears_old_tool_results(self):
        session = self._make_session(gap=60, keep=1)
        old_ts = time.time() - 120 * 60  # 2 hours ago
        self._add_tool_exchange(session, "Read", "c1", "old file", ts=old_ts)
        self._add_tool_exchange(session, "Read", "c2", "kept file", ts=old_ts)
        self.assertTrue(session.microcompact_if_needed())
        self.assertEqual(session.messages[1]["content"], MICROCOMPACT_CLEARED)
        self.assertEqual(session.messages[3]["content"], "kept file")

    def test_preserves_recent_n(self):
        session = self._make_session(keep=2)
        old_ts = time.time() - 120 * 60
        for i in range(5):
            self._add_tool_exchange(session, "Read", f"c{i}", f"content {i}", ts=old_ts)
        self.assertTrue(session.microcompact_if_needed())
        tool_msgs = [m for m in session.messages if m.get("role") == "tool"]
        self.assertEqual(tool_msgs[0]["content"], MICROCOMPACT_CLEARED)
        self.assertEqual(tool_msgs[1]["content"], MICROCOMPACT_CLEARED)
        self.assertEqual(tool_msgs[2]["content"], MICROCOMPACT_CLEARED)
        self.assertEqual(tool_msgs[3]["content"], "content 3")
        self.assertEqual(tool_msgs[4]["content"], "content 4")

    def test_preserves_non_compactable_tools(self):
        session = self._make_session(keep=1)
        old_ts = time.time() - 120 * 60
        self._add_tool_exchange(session, "Read", "c1", "file", ts=old_ts)
        self._add_tool_exchange(session, "Read", "c2", "file2", ts=old_ts)
        self._add_tool_exchange(
            session, "AskUserQuestion", "c3", "user answer", ts=old_ts
        )
        self.assertTrue(session.microcompact_if_needed())
        tool_msgs = [m for m in session.messages if m.get("role") == "tool"]
        self.assertEqual(tool_msgs[0]["content"], MICROCOMPACT_CLEARED)
        self.assertEqual(tool_msgs[1]["content"], "file2")
        self.assertEqual(tool_msgs[2]["content"], "user answer")

    def test_no_timestamp_is_noop(self):
        session = self._make_session()
        # Legacy session: assistant message without _timestamp
        session.messages.append(
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
            }
        )
        session.messages.append(
            {"role": "tool", "tool_call_id": "c1", "content": "file"}
        )
        self.assertFalse(session.microcompact_if_needed())
        self.assertEqual(session.messages[1]["content"], "file")

    def test_idempotent(self):
        session = self._make_session(keep=1)
        old_ts = time.time() - 120 * 60
        self._add_tool_exchange(session, "Read", "c1", "data", ts=old_ts)
        self._add_tool_exchange(session, "Read", "c2", "data2", ts=old_ts)
        self.assertTrue(session.microcompact_if_needed())
        first_result = [
            m["content"] for m in session.messages if m.get("role") == "tool"
        ]
        self.assertFalse(session.microcompact_if_needed())
        second_result = [
            m["content"] for m in session.messages if m.get("role") == "tool"
        ]
        self.assertEqual(first_result, second_result)

    def test_disabled_with_zero_gap(self):
        session = self._make_session(gap=0)
        old_ts = time.time() - 999 * 60
        self._add_tool_exchange(session, "Read", "c1", "file", ts=old_ts)
        self.assertFalse(session.microcompact_if_needed())
        self.assertEqual(session.messages[1]["content"], "file")

    def test_token_estimate_updated(self):
        session = self._make_session(keep=1)
        old_ts = time.time() - 120 * 60
        self._add_tool_exchange(session, "Read", "c1", "x" * 1000, ts=old_ts)
        self._add_tool_exchange(session, "Read", "c2", "short", ts=old_ts)
        session._recalculate_tokens()
        before = session.get_token_estimate()
        session.microcompact_if_needed()
        after = session.get_token_estimate()
        self.assertLess(after, before)
        stats = session.get_last_microcompact_stats()
        self.assertIsNotNone(stats)
        self.assertGreater(stats["tokens_saved"], 0)
        self.assertEqual(stats["results_cleared"], 1)

    def test_clears_synthetic_image_messages(self):
        session = self._make_session(keep=1)
        old_ts = time.time() - 120 * 60
        session.messages.append(
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
            }
        )
        session.messages.append(
            {"role": "tool", "tool_call_id": "c1", "content": "[Image loaded: image/png]"}
        )
        session.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Image from ReadTool:"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            }
        )
        session.messages.append(
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
            }
        )
        session.messages.append(
            {"role": "tool", "tool_call_id": "c2", "content": "keep me"}
        )

        self.assertTrue(session.microcompact_if_needed())
        self.assertEqual(session.messages[1]["content"], MICROCOMPACT_CLEARED)
        self.assertEqual(session.messages[2]["content"], MICROCOMPACT_IMAGE_CLEARED)
        self.assertEqual(session.messages[4]["content"], "keep me")

    def test_timestamp_survives_save_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DummyConfig(context_window=1000, root=tmpdir)
            session = Session(config, "system")
            session.add_droid_message("hello")
            ts = session.messages[0]["_timestamp"]
            session.save()

            restored = Session(config, "system")
            restored.load(session.session_id)

        self.assertAlmostEqual(restored.messages[0]["_timestamp"], ts, places=2)

    def test_timestamp_stripped_from_api_messages(self):
        session = self._make_session()
        session.add_droid_message("hello")
        api_msgs = session.get_messages()
        for msg in api_msgs:
            self.assertNotIn("_timestamp", msg)

    def test_compactable_tools_set(self):
        self.assertIn("Read", COMPACTABLE_TOOLS)
        self.assertIn("Bash", COMPACTABLE_TOOLS)
        self.assertIn("Grep", COMPACTABLE_TOOLS)
        self.assertNotIn("AskUserQuestion", COMPACTABLE_TOOLS)


class GoalOverlayTests(unittest.TestCase):
    def _make_session(self):
        return Session(DummyConfig(context_window=10000), "base-system-prompt")

    def test_overlay_default_empty(self):
        session = self._make_session()
        self.assertEqual(session.get_goal_overlay(), "")
        msgs = session.get_messages()
        self.assertEqual(msgs[0]["content"], "base-system-prompt")

    def test_set_overlay_appends_to_system_prompt(self):
        session = self._make_session()
        session.set_goal_overlay("# Active Goal\nObjective: x")
        msgs = session.get_messages()
        self.assertIn("# Active Goal", msgs[0]["content"])
        self.assertIn("base-system-prompt", msgs[0]["content"])
        self.assertTrue(
            msgs[0]["content"].startswith("base-system-prompt"),
            "overlay should come after the base system prompt",
        )

    def test_set_overlay_none_clears(self):
        session = self._make_session()
        session.set_goal_overlay("overlay text")
        session.set_goal_overlay(None)
        self.assertEqual(session.get_goal_overlay(), "")
        msgs = session.get_messages()
        self.assertEqual(msgs[0]["content"], "base-system-prompt")

    def test_overlay_included_in_token_estimate(self):
        session = self._make_session()
        base = session.get_token_estimate()
        session.set_goal_overlay("# Active Goal\nObjective: ship it")
        with_overlay = session.get_token_estimate()
        self.assertGreater(with_overlay, base)
        # clearing returns to baseline
        session.set_goal_overlay("")
        self.assertEqual(session.get_token_estimate(), base)


if __name__ == "__main__":
    unittest.main()
