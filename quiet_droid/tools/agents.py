import json
import threading
import time
import uuid

from .base import Tool

_print_lock = threading.Lock()


class SubAgentTool(Tool):
    name = "SubAgent"
    description = (
        "Launch a sub-agent to handle a task autonomously. "
        "Use it for bounded research or analysis that may require multiple tool calls."
    )

    READ_ONLY_TOOLS = frozenset({"Read", "Glob", "Grep"})
    WRITE_TOOLS = frozenset({"Bash", "Write", "Edit"})
    HARD_MAX_TURNS = 20

    def __init__(self, config, client, registry, permissions=None, hooks=None):
        self._config = config
        self._client = client
        self._registry = registry
        self._permissions = permissions
        self._hooks = hooks

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The task for the sub-agent to perform"},
                "max_turns": {"type": "integer", "description": "Max agent loop iterations (default 10, hard cap 20)"},
                "allow_writes": {"type": "boolean", "description": "Allow Bash, Write, and Edit inside the sub-agent"},
            },
            "required": ["prompt"],
        }

    def _build_sub_system_prompt(self):
        return (
            "You are a sub-agent droid. Complete the given task using the available tools. "
            "Be thorough but concise. Do not ask follow-up questions. "
            "When you have enough information, provide a clear final answer.\n"
            f"Working directory: {self._config.cwd}\n"
        )

    def _extract_message(self, response):
        message = (response.get("choices") or [{}])[0].get("message", {})
        content = message.get("content", "") or ""
        tool_calls = []
        for idx, tc in enumerate(message.get("tool_calls") or []):
            function = tc.get("function", {})
            raw_args = function.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {"raw": raw_args}
            else:
                arguments = raw_args if isinstance(raw_args, dict) else {"raw": str(raw_args)}
            tool_calls.append(
                {
                    "id": tc.get("id", f"call_{idx}_{uuid.uuid4().hex[:8]}"),
                    "name": function.get("name", ""),
                    "arguments": arguments,
                }
            )
        return content, tool_calls

    def execute(self, params):
        prompt = params.get("prompt", "").strip()
        if not prompt:
            return "Error: prompt is required"
        if self._hooks:
            self._hooks.emit("SubagentStart", {"prompt": prompt[:1000]})

        try:
            max_turns = int(params.get("max_turns", 10))
        except (TypeError, ValueError):
            max_turns = 10
        max_turns = max(1, min(max_turns, self.HARD_MAX_TURNS))
        allow_writes = bool(params.get("allow_writes", False))

        allowed_tools = set(self.READ_ONLY_TOOLS)
        if allow_writes:
            allowed_tools |= self.WRITE_TOOLS

        schemas = [s for s in self._registry.get_schemas() if s.get("function", {}).get("name") in allowed_tools]
        messages = [
            {"role": "system", "content": self._build_sub_system_prompt()},
            {"role": "user", "content": prompt},
        ]

        start = time.time()
        with _print_lock:
            print(f"\n  Sub-agent: {prompt[:80]}", flush=True)

        result_text = ""
        last_text = ""
        for _ in range(max_turns):
            try:
                response = self._client.chat_sync(
                    model=self._config.model,
                    messages=messages,
                    tools=schemas if schemas else None,
                )
            except Exception as exc:
                result_text = f"Sub-agent error: {exc}"
                break

            text, tool_calls = self._extract_message(response)
            last_text = text

            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": text or None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )
            else:
                messages.append({"role": "assistant", "content": text or ""})
                result_text = text
                break

            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                if tool_name not in allowed_tools:
                    output = f"Error: tool '{tool_name}' is not allowed in this sub-agent"
                else:
                    tool = self._registry.get(tool_name)
                    if not tool:
                        output = f"Error: unknown tool '{tool_name}'"
                    elif tool_name in self.WRITE_TOOLS and self._permissions and not self._permissions.check(tool_name, tool_args, None):
                        output = "Error: permission denied by parent permission manager"
                    else:
                        try:
                            output = tool.execute(tool_args)
                        except Exception as exc:
                            output = f"Error: {exc}"
                output = str(output) if output is not None else ""
                if len(output) > 10000:
                    output = output[:10000] + "\n...(truncated)"
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": output})

            total_chars = sum(len(str(m.get("content", ""))) for m in messages)
            if total_chars > 80000:
                for i in range(2, len(messages) - 4):
                    if messages[i].get("role") == "tool":
                        content = str(messages[i].get("content", ""))
                        if len(content) > 500:
                            messages[i]["content"] = content[:500] + "\n...(truncated by sub-agent context limit)"
        else:
            result_text = f"Sub-agent reached max turns ({max_turns}). Last response: {last_text[:2000]}"

        elapsed = time.time() - start
        with _print_lock:
            print(f"  Sub-agent finished ({elapsed:.1f}s)", flush=True)

        if len(result_text) > 20000:
            result_text = result_text[:20000] + "\n...(truncated)"
        if self._hooks:
            self._hooks.emit(
                "SubagentStop",
                {
                    "prompt": prompt[:1000],
                    "duration_seconds": round(elapsed, 3),
                    "result_preview": result_text[:1000],
                },
            )
        return result_text


class MultiAgentCoordinator:
    MAX_PARALLEL = 4

    def __init__(self, config, client, registry, permissions, hooks=None):
        self._config = config
        self._client = client
        self._registry = registry
        self._permissions = permissions
        self._hooks = hooks

    def run_parallel(self, tasks):
        tasks = tasks[: self.MAX_PARALLEL]
        results = [None] * len(tasks)

        def run_one(idx, task):
            started = time.time()
            try:
                subagent = SubAgentTool(self._config, self._client, self._registry, self._permissions, self._hooks)
                result = subagent.execute(task)
                results[idx] = {
                    "prompt": task.get("prompt", "")[:100],
                    "result": result,
                    "duration": time.time() - started,
                    "error": result if isinstance(result, str) and result.startswith("Sub-agent error:") else None,
                }
            except Exception as exc:
                results[idx] = {
                    "prompt": task.get("prompt", "")[:100],
                    "result": "",
                    "duration": time.time() - started,
                    "error": str(exc),
                }

        threads = []
        for idx, task in enumerate(tasks):
            thread = threading.Thread(target=run_one, args=(idx, task), daemon=True)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join(timeout=300)

        for idx, result in enumerate(results):
            if result is None:
                results[idx] = {
                    "prompt": tasks[idx].get("prompt", "")[:100],
                    "result": "",
                    "duration": 300.0,
                    "error": "Agent timed out (300s limit)",
                }
        return results


class ParallelAgentTool(Tool):
    name = "ParallelAgents"
    description = (
        "Launch 2-4 sub-agents in parallel for independent tasks. "
        "Use it when multiple research or analysis tasks can run simultaneously."
    )

    def __init__(self, coordinator):
        self._coordinator = coordinator

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "Array of task objects with prompt and optional max_turns and allow_writes",
                    "items": {
                        "type": "object",
                        "properties": {
                            "prompt": {"type": "string"},
                            "max_turns": {"type": "integer"},
                            "allow_writes": {"type": "boolean"},
                        },
                        "required": ["prompt"],
                    },
                    "minItems": 1,
                    "maxItems": 4,
                }
            },
            "required": ["tasks"],
        }

    def execute(self, params):
        tasks = params.get("tasks", [])
        if not tasks:
            return "Error: at least one task is required"

        with _print_lock:
            print(f"\n  Launching {min(len(tasks), 4)} parallel agents...", flush=True)

        results = self._coordinator.run_parallel(tasks)
        output = []
        for idx, result in enumerate(results, start=1):
            status = "FAIL" if result["error"] else "OK"
            output.append(f"Agent {idx} [{status}]")
            output.append(f"Task: {result['prompt']}")
            output.append(f"Time: {result['duration']:.1f}s")
            if result["error"]:
                output.append(f"Error: {result['error']}")
            else:
                text = result["result"]
                if len(text) > 3000:
                    text = text[:3000] + "\n...(result truncated)"
                output.append(text)
            output.append("")
        return "\n".join(output).rstrip()
