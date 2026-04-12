import ast
import json
import re
import threading
import time
import urllib.error
import uuid

from .terminal import C, ansi
from .skills import inject_skill_context
from .tools import ToolResult


class Agent:
    MAX_ITERATIONS = 50
    MAX_RETRIES = 2
    MAX_SAME_TOOL_REPEAT = 3

    def __init__(self, config, client, registry, permissions, session, tui, hooks=None, skills=None):
        self.config = config
        self.client = client
        self.registry = registry
        self.permissions = permissions
        self.session = session
        self.tui = tui
        self.hooks = hooks
        self.skills = skills or {}
        self._interrupted = threading.Event()

    @staticmethod
    def _detect_parallel_tasks(user_input):
        text = user_input.strip()
        if len(text) < 10 or text.endswith("?") or text.endswith("？"):
            return []
        numbered = re.findall(r"(?:^|\n\s*|\s{2,})(?:\d+[.)）]\s*|[（(]\d+[)）]\s*)(.+?)(?=(?:\n\s*|\s{2,})(?:\d+[.)）]|[（(]\d+)|$)", text)
        if len(numbered) >= 2:
            return [task.strip() for task in numbered if task.strip()]
        investigate_pattern = re.compile(r"(?:調べ|探し|検索|数え|確認|教え|見つけ|search|find|count|check|list|show)", re.IGNORECASE)
        if investigate_pattern.search(text):
            parts = re.split(r"[、,]\s*(?:そして|また|and\s+)?|(?:と(?:、)?)", text)
            tasks = [part.strip() for part in parts if len(part.strip()) >= 5]
            if 2 <= len(tasks) <= 4:
                return tasks
        return []

    def run(self, user_input):
        if self.hooks:
            self.hooks.emit("UserPromptSubmit", {"prompt": user_input})
        parallel_tasks = self._detect_parallel_tasks(user_input)
        if len(parallel_tasks) >= 2:
            tool = self.registry.get("ParallelAgents")
            if tool:
                self.session.add_user_message(user_input)
                result = tool.execute({"tasks": [{"prompt": task, "max_turns": 10} for task in parallel_tasks]})
                self.session.add_droid_message(result)
                if self.hooks:
                    self.hooks.emit("Stop", {"stop_reason": "parallel_agents", "response": result[:4000]})
                print(f"\n{C.BBLUE}droid{C.RESET}: ", end="")
                self.tui._render_markdown(result)
                print()
                return

        effective_input = inject_skill_context(user_input, self.skills)
        self.session.add_user_message(effective_input)
        self._interrupted.clear()
        recent_tool_calls = []
        empty_retries = 0
        start_time = time.time()

        for iteration in range(self.MAX_ITERATIONS):
            if self._interrupted.is_set():
                break
            text = ""
            try:
                tools = self.registry.get_schemas()
                if iteration == 0:
                    self.tui.start_spinner("Thinking")
                else:
                    elapsed = int(time.time() - start_time)
                    self.tui.start_spinner(f"Thinking (step {iteration + 1}, {elapsed}s)")
                response = None
                for retry in range(self.MAX_RETRIES + 1):
                    try:
                        response = self.client.chat(
                            model=self.config.model,
                            messages=self.session.get_messages(),
                            tools=tools if tools else None,
                            stream=True,
                        )
                        break
                    except (RuntimeError, urllib.error.URLError):
                        if retry < self.MAX_RETRIES:
                            time.sleep(1 + retry)
                            continue
                        raise
                self.tui.stop_spinner()
                if response is None:
                    print(f"\n{C.RED}The AI didn't respond.{C.RESET}")
                    break

                if isinstance(response, dict):
                    text, tool_calls = self.tui.show_sync_response(response, known_tools=self.registry.names())
                else:
                    try:
                        text, tool_calls = self.tui.stream_response(response, known_tools=self.registry.names())
                    finally:
                        if hasattr(response, "close"):
                            response.close()

                if isinstance(response, dict) and not self.session._just_compacted:
                    usage = response.get("usage", {})
                    if usage.get("prompt_tokens", 0) > 0:
                        self.session._token_estimate = usage["prompt_tokens"] + usage.get("completion_tokens", 0)
                self.session._just_compacted = False

                if not text and not tool_calls and iteration < self.MAX_ITERATIONS - 1:
                    empty_retries += 1
                    if empty_retries > 3:
                        print(f"\n{C.YELLOW}The AI returned empty responses.{C.RESET}")
                        break
                    time.sleep(empty_retries * 0.5)
                    continue

                self.session.add_droid_message(text, tool_calls if tool_calls else None)
                if not tool_calls:
                    if self.hooks:
                        self.hooks.emit("Stop", {"stop_reason": "droid_response", "response": (text or "")[:4000]})
                    break

                def normalize_args(raw):
                    try:
                        return json.dumps(json.loads(raw), sort_keys=True) if isinstance(raw, str) else str(raw)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        return str(raw)

                current_calls = [
                    (tc.get("function", {}).get("name", ""), normalize_args(tc.get("function", {}).get("arguments", "")))
                    for tc in tool_calls
                ]
                recent_tool_calls.append(current_calls)
                if len(recent_tool_calls) >= self.MAX_SAME_TOOL_REPEAT:
                    recent = recent_tool_calls[-self.MAX_SAME_TOOL_REPEAT:]
                    if all(call == recent[0] for call in recent):
                        print(f"\n{C.YELLOW}The AI got stuck repeating the same action. Stopped.{C.RESET}")
                        break
                if len(recent_tool_calls) > 10:
                    recent_tool_calls = recent_tool_calls[-10:]

                results = []
                parsed_calls = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tc_id = tc.get("id", f"call_{uuid.uuid4().hex[:8]}")
                    tool_name = func.get("name", "")
                    raw_args = func.get("arguments", "{}")
                    try:
                        tool_params = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        if not isinstance(tool_params, dict):
                            tool_params = {"raw": str(tool_params)}
                    except json.JSONDecodeError:
                        try:
                            parsed = ast.literal_eval(raw_args)
                            tool_params = parsed if isinstance(parsed, dict) else {"raw": str(parsed)}
                        except (ValueError, SyntaxError):
                            try:
                                fixed = re.sub(r",\s*}", "}", raw_args)
                                fixed = re.sub(r",\s*]", "]", fixed)
                                tool_params = json.loads(fixed)
                            except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                                results.append(ToolResult(tc_id, f"Error: tool arguments are not valid JSON: {raw_args[:200]}", True))
                                continue
                    parsed_calls.append((tc_id, tool_name, tool_params))

                validated_calls = []
                for tc_id, tool_name, tool_params in parsed_calls:
                    tool = self.registry.get(tool_name)
                    if not tool:
                        results.append(ToolResult(tc_id, f"Error: unknown tool '{tool_name}'", True))
                        continue
                    tool_name = tool.name
                    hook_decision = self.hooks.evaluate_pre_tool_use(tool_name, tool_params) if self.hooks else None
                    if hook_decision and hook_decision.updated_input:
                        tool_params = hook_decision.updated_input
                    self.tui.show_tool_call(tool_name, tool_params)
                    if hook_decision and hook_decision.decision == "deny":
                        message = hook_decision.reason or "Permission denied by hook. Do not retry this operation."
                        if self.hooks:
                            self.hooks.emit("PermissionDenied", {"tool_name": tool_name, "tool_input": dict(tool_params)}, matcher=tool_name)
                        results.append(ToolResult(tc_id, message, True))
                        self.tui.show_tool_result(tool_name, message, True)
                        continue
                    force_ask = bool(hook_decision and hook_decision.decision == "ask")
                    ask_reason = hook_decision.reason if hook_decision else ""
                    if not self.permissions.check(tool_name, tool_params, self.tui, force_ask=force_ask, ask_reason=ask_reason):
                        results.append(ToolResult(tc_id, "Permission denied by user. Do not retry this operation.", True))
                        self.tui.show_tool_result(tool_name, "Permission denied", True)
                        continue
                    validated_calls.append((tc_id, tool_name, tool_params, tool))

                for tc_id, tool_name, tool_params, tool in validated_calls:
                    if self._interrupted.is_set():
                        break
                    tool_started = time.time()
                    try:
                        is_long_op = tool_name == "Bash"
                        if is_long_op:
                            self.tui.start_tool_status(tool_name)
                        output = tool.execute(tool_params)
                        duration = time.time() - tool_started
                        if is_long_op:
                            self.tui.stop_spinner()
                        is_error = isinstance(output, str) and (output.startswith("Error:") or output.startswith("Error -"))
                        if self.hooks:
                            event_name = "PostToolUseFailure" if is_error else "PostToolUse"
                            self.hooks.emit(
                                event_name,
                                {
                                    "tool_name": tool_name,
                                    "tool_input": dict(tool_params),
                                    "tool_response": str(output),
                                    "duration_seconds": round(duration, 3),
                                },
                                matcher=tool_name,
                            )
                        self.tui.show_tool_result(tool_name, output, is_error=is_error, duration=duration, params=tool_params)
                        results.append(ToolResult(tc_id, output, is_error))
                    except KeyboardInterrupt:
                        self.tui.stop_spinner()
                        duration = time.time() - tool_started
                        if self.hooks:
                            self.hooks.emit(
                                "PostToolUseFailure",
                                {
                                    "tool_name": tool_name,
                                    "tool_input": dict(tool_params),
                                    "tool_response": "Interrupted by user",
                                    "duration_seconds": round(duration, 3),
                                },
                                matcher=tool_name,
                            )
                        results.append(ToolResult(tc_id, "Interrupted by user", True))
                        self.tui.show_tool_result(tool_name, "Interrupted", True, duration=duration, params=tool_params)
                        self._interrupted.set()
                        break
                    except Exception as exc:
                        self.tui.stop_spinner()
                        duration = time.time() - tool_started
                        error_msg = f"Tool error: {exc}"
                        if self.hooks:
                            self.hooks.emit(
                                "PostToolUseFailure",
                                {
                                    "tool_name": tool_name,
                                    "tool_input": dict(tool_params),
                                    "tool_response": error_msg,
                                    "duration_seconds": round(duration, 3),
                                },
                                matcher=tool_name,
                            )
                        self.tui.show_tool_result(tool_name, error_msg, True, duration=duration, params=tool_params)
                        results.append(ToolResult(tc_id, error_msg, True))

                if self._interrupted.is_set():
                    called_ids = {result.id for result in results}
                    for tc in tool_calls:
                        tid = tc.get("id", "")
                        if tid and tid not in called_ids:
                            results.append(ToolResult(tid, "Cancelled by user", True))
                self.session.add_tool_results(results)
                if self._interrupted.is_set():
                    break

                before = self.session.get_token_estimate()
                self.session.compact_if_needed()
                after = self.session.get_token_estimate()
                if after < before * 0.9:
                    pct = min(int((after / self.config.context_window) * 100), 100)
                    print(f"\n  {ansi(chr(27)+'[38;5;226m')}⚡ Auto-compacted: {before}→{after} tokens ({pct}% used){C.RESET}")
            except KeyboardInterrupt:
                self.tui.stop_spinner()
                if text:
                    self.session.add_droid_message(text)
                print(f"\n{C.YELLOW}Interrupted.{C.RESET}")
                self._interrupted.set()
                break
            except urllib.error.HTTPError as exc:
                self.tui.stop_spinner()
                print(f"\n{C.RED}HTTP {exc.code} {exc.reason}{C.RESET}")
                break
            except urllib.error.URLError:
                self.tui.stop_spinner()
                print(f"\n{C.RED}OpenAI-compatible API への接続が失われました。{C.RESET}")
                break
            except Exception as exc:
                self.tui.stop_spinner()
                print(f"\n{C.RED}Something went wrong: {exc}{C.RESET}")
                if self.config.debug:
                    import traceback

                    traceback.print_exc()
                break

    def get_typeahead(self):
        return ""

    def interrupt(self):
        self._interrupted.set()
