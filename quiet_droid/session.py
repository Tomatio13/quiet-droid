import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime


class Session:
    MAX_MESSAGES = 500

    def __init__(self, config, system_prompt):
        self.config = config
        self.system_prompt = system_prompt
        self.messages = []
        self._client = None
        self._hooks = None
        raw_id = config.session_id or (datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
        self.session_id = re.sub(r"[^A-Za-z0-9_\-]", "", raw_id)[:64] or (
            datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        )
        self._token_estimate = 0
        self._last_compact_msg_count = 0
        self._just_compacted = False

    def set_client(self, client):
        self._client = client

    def set_hooks(self, hooks):
        self._hooks = hooks

    @staticmethod
    def _estimate_tokens(text):
        if not text:
            return 0
        cjk_count = sum(
            1 for ch in text
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
        while skip < len(self.messages) - 1 and self.messages[skip].get("role") == "tool":
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

    def add_assistant_message(self, text, tool_calls=None):
        msg = {"role": "assistant", "content": text if text else None}
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
            if isinstance(obj, dict) and obj.get("type") == "image" and obj.get("media_type") and obj.get("data"):
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
                self.messages.append({"role": "tool", "tool_call_id": result.id, "content": f"[Image loaded: {media_type}]"})
                self.messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Image from ReadTool:"},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                })
                self._token_estimate += 800
                continue
            if self._estimate_tokens(output) > max_result_tokens:
                cutoff = max_result_tokens * 3
                output = output[:cutoff] + "\n...(truncated: result too large)..."
            self.messages.append({"role": "tool", "tool_call_id": result.id, "content": output})
            self._token_estimate += self._estimate_tokens(output)
        self._enforce_max_messages()

    def get_messages(self):
        return [{"role": "system", "content": self.system_prompt}] + self.messages

    def get_token_estimate(self):
        return self._token_estimate + self._estimate_tokens(self.system_prompt)

    def _summarize_old_messages(self, old_messages):
        if not self._client or not self.config.model:
            return None
        parts = []
        for msg in old_messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
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
            {"role": "system", "content": "You are a concise summarizer. Respond ONLY with bullet points."},
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
            resp = self._client.chat(model=self.config.model, messages=prompt, tools=None, stream=False)
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
            self._hooks.emit("PreCompact", {"before_tokens": before_tokens, "message_count": before_messages, "forced": bool(force)})
        self._last_compact_msg_count = len(self.messages)
        preserve_count = min(30, len(self.messages))
        cutoff = len(self.messages) - preserve_count
        if cutoff > 0:
            summary = self._summarize_old_messages(self.messages[:cutoff])
            if summary:
                remaining = self.messages[cutoff:]
                while remaining and remaining[0].get("role") == "tool":
                    remaining.pop(0)
                if remaining and remaining[0].get("role") == "assistant" and remaining[0].get("tool_calls"):
                    if len(remaining) < 2 or remaining[1].get("role") != "tool":
                        remaining.pop(0)
                self.messages = [{"role": "user", "content": "[Earlier conversation summary]\n" + summary}] + remaining
                self._last_compact_msg_count = len(self.messages)
                self._recalculate_tokens()
                self._just_compacted = True
                return
        actual_cutoff = cutoff
        while actual_cutoff < len(self.messages) and self.messages[actual_cutoff].get("role") == "tool":
            actual_cutoff += 1
        self.messages = self.messages[actual_cutoff:]
        if len(self.messages) > self.MAX_MESSAGES:
            cut_idx = len(self.messages) - self.MAX_MESSAGES
            while cut_idx < len(self.messages) and self.messages[cut_idx].get("role") == "tool":
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
                        self.messages[idx] = {**msg, "content": content[:200] + "\n...(truncated)...\n" + content[-200:]}
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
