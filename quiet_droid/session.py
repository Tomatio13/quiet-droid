import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime

COMPACTABLE_TOOLS = frozenset(
    {
        "Read",
        "Bash",
        "Grep",
        "Glob",
        "Write",
        "Edit",
        "SubAgent",
        "ParallelAgents",
    }
)
MICROCOMPACT_CLEARED = "[Old tool result content cleared]"
MICROCOMPACT_IMAGE_CLEARED = "[Old image cleared]"


class Session:
    MAX_MESSAGES = 500
    MAX_SESSION_FILE_SIZE = 50 * 1024 * 1024

    def __init__(self, config, system_prompt):
        self.config = config
        self.system_prompt = system_prompt
        self.messages = []
        self._client = None
        self._hooks = None
        raw_id = config.session_id or (
            datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        )
        self.session_id = re.sub(r"[^A-Za-z0-9_\-]", "", raw_id)[:64] or (
            datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        )
        self._token_estimate = 0
        self._last_compact_msg_count = 0
        self._just_compacted = False
        self._last_microcompact_stats = None
        self._goal_overlay = ""

    def set_client(self, client):
        self._client = client

    def set_hooks(self, hooks):
        self._hooks = hooks

    def set_goal_overlay(self, text):
        """Set the active-goal overlay appended to the system prompt.

        Pass an empty string (or None) to clear it. Token estimates are
        recomputed so compact/microcompact thresholds reflect the change.
        """
        self._goal_overlay = text or ""
        self._recalculate_tokens()

    def get_goal_overlay(self):
        return self._goal_overlay

    @staticmethod
    def _project_index_path(config):
        return os.path.join(config.sessions_dir, "project-index.json")

    @staticmethod
    def _load_project_index(config):
        path = Session._project_index_path(config)
        if not os.path.isfile(path) or os.path.islink(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _save_project_index(config, index):
        path = Session._project_index_path(config)
        fd, tmp_path = tempfile.mkstemp(dir=config.sessions_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @staticmethod
    def _cwd_hash(config):
        return hashlib.sha256(os.path.abspath(config.cwd).encode("utf-8")).hexdigest()[
            :16
        ]

    @staticmethod
    def get_project_session(config):
        return Session._load_project_index(config).get(Session._cwd_hash(config))

    @staticmethod
    def _estimate_tokens(text):
        if not text:
            return 0
        cjk_count = sum(
            1
            for ch in text
            if "\u4e00" <= ch <= "\u9fff"
            or "\u3400" <= ch <= "\u4dbf"
            or "\u3040" <= ch <= "\u30ff"
            or "\u3000" <= ch <= "\u303f"
            or "\u31f0" <= ch <= "\u31ff"
            or "\uff01" <= ch <= "\uff60"
            or "\uac00" <= ch <= "\ud7af"
        )
        return cjk_count + (len(text) - cjk_count) // 4

    def _recalculate_tokens(self):
        total = 0
        for msg in self.messages:
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            total += self._estimate_tokens(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            total += 800
            else:
                total += self._estimate_tokens(content or "")
            if msg.get("tool_calls"):
                total += len(json.dumps(msg["tool_calls"], ensure_ascii=False)) // 4
        self._token_estimate = total

    def _enforce_max_messages(self):
        if len(self.messages) <= self.MAX_MESSAGES:
            return
        cut = len(self.messages) - self.MAX_MESSAGES
        while cut < len(self.messages) and self.messages[cut].get("role") == "tool":
            cut += 1
        self.messages = self.messages[cut:]
        skip = 0
        while (
            skip < len(self.messages) - 1 and self.messages[skip].get("role") == "tool"
        ):
            skip += 1
        if skip:
            self.messages = self.messages[skip:]
        if not self.messages:
            self.messages = [{"role": "user", "content": "(history trimmed)"}]
        self._recalculate_tokens()

    def add_user_message(self, text):
        self.messages.append({"role": "user", "content": text})
        self._token_estimate += self._estimate_tokens(text)
        self._enforce_max_messages()

    def add_droid_message(self, text, tool_calls=None):
        msg = {"role": "assistant", "content": text if text else None}
        msg["_timestamp"] = time.time()
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)
        self._token_estimate += self._estimate_tokens(text or "")
        if tool_calls:
            self._token_estimate += len(json.dumps(tool_calls, ensure_ascii=False)) // 4

    @staticmethod
    def _parse_image_marker(output):
        if not output or not output.startswith('{"type":'):
            return None
        try:
            obj = json.loads(output)
            if (
                isinstance(obj, dict)
                and obj.get("type") == "image"
                and obj.get("media_type")
                and obj.get("data")
            ):
                return obj["media_type"], obj["data"]
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        return None

    def add_tool_results(self, results):
        max_result_tokens = int(self.config.context_window * 0.25)
        for result in results:
            output = str(result.output) if result.output is not None else ""
            image_info = self._parse_image_marker(output)
            if image_info is not None:
                media_type, b64_data = image_info
                data_uri = f"data:{media_type};base64,{b64_data}"
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.id,
                        "content": f"[Image loaded: {media_type}]",
                    }
                )
                self.messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Image from ReadTool:"},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    }
                )
                self._token_estimate += 800
                continue
            if self._estimate_tokens(output) > max_result_tokens:
                cutoff = max_result_tokens * 3
                output = output[:cutoff] + "\n...(truncated: result too large)..."
            self.messages.append(
                {"role": "tool", "tool_call_id": result.id, "content": output}
            )
            self._token_estimate += self._estimate_tokens(output)
        self._enforce_max_messages()

    def get_messages(self):
        msgs = [
            {k: v for k, v in m.items() if k != "_timestamp"} for m in self.messages
        ]
        system = self.system_prompt
        if self._goal_overlay:
            system += "\n\n" + self._goal_overlay
        return [{"role": "system", "content": system}] + msgs

    def get_token_estimate(self):
        return (
            self._token_estimate
            + self._estimate_tokens(self.system_prompt)
            + self._estimate_tokens(self._goal_overlay)
        )

    def context_window_status(self):
        current = self.get_token_estimate()
        limit = int(getattr(self.config, "context_window", 0) or 0)
        over_by = max(0, current - limit) if limit > 0 else 0
        pct = int((current / limit) * 100) if limit > 0 else 0
        return {
            "ok": limit <= 0 or current <= limit,
            "current": current,
            "limit": limit,
            "over_by": over_by,
            "pct": pct,
        }

    def _summarize_old_messages(self, old_messages):
        if not self._client or not self.config.model:
            return None
        parts = []
        for msg in old_messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            if not content:
                continue
            if len(content) > 300:
                content = content[:300] + "..."
            parts.append(f"{role}: {content}")
        if not parts:
            return None
        transcript = "\n".join(parts)
        if len(transcript) > 4000:
            transcript = transcript[:4000] + "\n...(truncated)"
        prompt = [
            {
                "role": "system",
                "content": "You are a concise summarizer. Respond ONLY with bullet points.",
            },
            {
                "role": "user",
                "content": (
                    "Summarize this conversation so far in 3-5 bullet points, focusing on: "
                    "what was discussed, what files were modified, what decisions were made.\n\n"
                    f"{transcript}"
                ),
            },
        ]
        try:
            resp = self._client.chat(
                model=self.config.model, messages=prompt, tools=None, stream=False
            )
            choices = resp.get("choices", [])
            if choices:
                summary = choices[0].get("message", {}).get("content", "")
                if summary and len(summary.strip()) > 10:
                    return summary.strip()
        except Exception:
            return None
        return None

    def compact_if_needed(self, force=False):
        if not force and len(self.messages) > 300:
            force = True
        max_tokens = self.config.context_window * 0.70
        if not force and self.get_token_estimate() < max_tokens:
            return
        if not force and len(self.messages) == self._last_compact_msg_count:
            return
        before_tokens = self.get_token_estimate()
        before_messages = len(self.messages)
        if self._hooks:
            self._hooks.emit(
                "PreCompact",
                {
                    "before_tokens": before_tokens,
                    "message_count": before_messages,
                    "forced": bool(force),
                },
            )
        self._last_compact_msg_count = len(self.messages)
        preserve_count = min(30, len(self.messages))
        cutoff = len(self.messages) - preserve_count
        if cutoff > 0:
            summary = self._summarize_old_messages(self.messages[:cutoff])
            if summary:
                remaining = self.messages[cutoff:]
                while remaining and remaining[0].get("role") == "tool":
                    remaining.pop(0)
                if (
                    remaining
                    and remaining[0].get("role") == "assistant"
                    and remaining[0].get("tool_calls")
                ):
                    if len(remaining) < 2 or remaining[1].get("role") != "tool":
                        remaining.pop(0)
                self.messages = [
                    {
                        "role": "user",
                        "content": "[Earlier conversation summary]\n" + summary,
                    }
                ] + remaining
                self._last_compact_msg_count = len(self.messages)
                self._recalculate_tokens()
                self._just_compacted = True
                return
        actual_cutoff = cutoff
        while (
            actual_cutoff < len(self.messages)
            and self.messages[actual_cutoff].get("role") == "tool"
        ):
            actual_cutoff += 1
        self.messages = self.messages[actual_cutoff:]
        if len(self.messages) > self.MAX_MESSAGES:
            cut_idx = len(self.messages) - self.MAX_MESSAGES
            while (
                cut_idx < len(self.messages)
                and self.messages[cut_idx].get("role") == "tool"
            ):
                cut_idx += 1
            self.messages = self.messages[cut_idx:]
        skip = 0
        while skip < len(self.messages) and self.messages[skip].get("role") == "tool":
            skip += 1
        if skip:
            self.messages = self.messages[skip:]
        self._recalculate_tokens()
        if self._token_estimate > max_tokens:
            for idx, msg in enumerate(self.messages):
                if msg.get("role") == "tool":
                    content = msg.get("content", "")
                    if len(content) > 500:
                        self.messages[idx] = {
                            **msg,
                            "content": content[:200]
                            + "\n...(truncated)...\n"
                            + content[-200:],
                        }
            self._recalculate_tokens()
        self._just_compacted = True
        if self._hooks:
            self._hooks.emit(
                "PostCompact",
                {
                    "before_tokens": before_tokens,
                    "after_tokens": self.get_token_estimate(),
                    "before_message_count": before_messages,
                    "after_message_count": len(self.messages),
                    "forced": bool(force),
                },
            )

    def microcompact_if_needed(self):
        try:
            self._last_microcompact_stats = None
            gap = getattr(self.config, "microcompact_gap_minutes", 60)
            keep = max(1, getattr(self.config, "microcompact_keep_recent", 5))
            if gap <= 0:
                return False
            before_tokens = self.get_token_estimate()

            # Find last assistant message timestamp
            last_ts = None
            for msg in reversed(self.messages):
                if msg.get("role") == "assistant" and "_timestamp" in msg:
                    last_ts = msg["_timestamp"]
                    break
            if last_ts is None:
                return False

            gap_minutes = (time.time() - last_ts) / 60.0
            if gap_minutes < gap:
                return False

            # Collect compactable tool call IDs in chronological order
            compactable_ids = []
            for msg in self.messages:
                if msg.get("role") != "assistant":
                    continue
                for tc in msg.get("tool_calls") or []:
                    name = tc.get("function", {}).get("name", "")
                    if name in COMPACTABLE_TOOLS:
                        compactable_ids.append(tc.get("id", ""))

            if not compactable_ids:
                return False

            # Keep last N, clear the rest
            keep_set = set(compactable_ids[-keep:])
            clear_set = set(compactable_ids) - keep_set
            if not clear_set:
                return False

            cleared = False
            for i, msg in enumerate(self.messages):
                if msg.get("role") != "tool":
                    continue
                tc_id = msg.get("tool_call_id", "")
                if tc_id not in clear_set:
                    continue
                content = msg.get("content", "")
                if content == MICROCOMPACT_CLEARED:
                    continue
                self.messages[i] = {**msg, "content": MICROCOMPACT_CLEARED}
                cleared = True

                if i + 1 >= len(self.messages):
                    continue
                next_msg = self.messages[i + 1]
                if next_msg.get("role") != "user":
                    continue
                next_content = next_msg.get("content")
                if not isinstance(next_content, list):
                    continue
                has_image = any(
                    isinstance(part, dict) and part.get("type") == "image_url"
                    for part in next_content
                )
                if not has_image:
                    continue
                self.messages[i + 1] = {
                    **next_msg,
                    "content": MICROCOMPACT_IMAGE_CLEARED,
                }

            if not cleared:
                return False

            self._recalculate_tokens()
            tokens_saved = max(0, before_tokens - self.get_token_estimate())
            self._last_microcompact_stats = {
                "tokens_saved": tokens_saved,
                "results_cleared": len(clear_set),
                "gap_minutes": round(gap_minutes, 1),
            }

            if self._hooks:
                self._hooks.emit(
                    "PostMicrocompact",
                    self._last_microcompact_stats,
                )

            return True
        except Exception:
            self._last_microcompact_stats = None
            return False

    def get_last_microcompact_stats(self):
        return dict(self._last_microcompact_stats) if self._last_microcompact_stats else None

    def save(self):
        if not self.messages:
            return
        path = os.path.join(self.config.sessions_dir, f"{self.session_id}.jsonl")
        real_path = os.path.realpath(path)
        real_dir = os.path.realpath(self.config.sessions_dir)
        if not real_path.startswith(real_dir + os.sep):
            return
        fd, tmp_path = tempfile.mkstemp(dir=self.config.sessions_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for msg in self.messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            os.replace(tmp_path, real_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return
        index = self._load_project_index(self.config)
        index[self._cwd_hash(self.config)] = self.session_id
        self._save_project_index(self.config, index)

    def load(self, session_id=None):
        sid = session_id or self.session_id
        path = os.path.join(self.config.sessions_dir, f"{sid}.jsonl")
        real_path = os.path.realpath(path)
        real_dir = os.path.realpath(self.config.sessions_dir)
        if not real_path.startswith(real_dir + os.sep):
            return False
        if not os.path.isfile(path) or os.path.islink(path):
            return False
        try:
            if os.path.getsize(path) > self.MAX_SESSION_FILE_SIZE:
                return False
        except OSError:
            return False
        messages = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(msg, dict) and isinstance(msg.get("role"), str):
                        messages.append(msg)
        except OSError:
            return False
        self.messages = messages
        self.session_id = sid
        self._recalculate_tokens()
        return True

    @staticmethod
    def list_sessions(config):
        if not os.path.isdir(config.sessions_dir):
            return []
        sessions = []
        for filename in sorted(os.listdir(config.sessions_dir), reverse=True):
            if not filename.endswith(".jsonl"):
                continue
            path = os.path.join(config.sessions_dir, filename)
            if os.path.islink(path):
                continue
            try:
                size = os.path.getsize(path)
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            sessions.append(
                {
                    "id": filename[:-6],
                    "modified": datetime.fromtimestamp(mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                    "size": size,
                    "messages": max(1, size // 200),
                }
            )
        return sessions[:50]
