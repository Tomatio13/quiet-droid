import ipaddress
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime


DEFAULT_LIMIT = 8000
MAX_LINE_LENGTH = 240
HEAD_LINES = 18
TAIL_LINES = 18
IMPORTANT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"traceback",
        r"\berror\b",
        r"\bexception\b",
        r"\bfatal\b",
        r"\bpanic\b",
        r"\bfailed\b",
        r"\bassert\b",
        r"\bwarning\b",
        r"\bwarn\b",
        r"\(exit code: [1-9]\d*\)",
        r"npm err!",
        r"make:\s*\*\*\*",
        r"permission denied",
        r"^diff --git",
        r"^--- ",
        r"^\+\+\+ ",
        r"^@@ ",
        r"^[+-][^+-]",
    ]
]
TOOL_LIMITS = {
    "Bash": 12000,
    "SubAgent": 12000,
    "ParallelAgents": 10000,
}


def is_local_backend(base_url):
    if not base_url:
        return False
    try:
        parsed = urllib.parse.urlparse(base_url)
    except ValueError:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback
    except ValueError:
        return host.endswith(".local")


def clamp_line(line, max_length=MAX_LINE_LENGTH):
    if len(line) <= max_length:
        return line
    return line[: max_length - 1] + "…"


def is_important(line):
    return any(pattern.search(line) for pattern in IMPORTANT_PATTERNS)


def build_line_summary(text, max_chars):
    lines = text.splitlines()
    if not lines:
        return text
    selected = set(range(min(HEAD_LINES, len(lines))))
    selected.update(range(max(0, len(lines) - TAIL_LINES), len(lines)))
    for index, line in enumerate(lines):
        if is_important(line):
            selected.add(index)
    ordered = sorted(selected)
    pieces = []
    previous = -1
    for index in ordered:
        if index <= previous:
            continue
        if previous >= 0 and index - previous > 1:
            pieces.append(f"...({index - previous - 1} lines omitted)...")
        pieces.append(clamp_line(lines[index]))
        previous = index
    summary = "\n".join(pieces)
    if len(summary) <= max_chars:
        return summary
    keep = max(200, (max_chars - 64) // 2)
    return summary[:keep] + "\n...(truncated)...\n" + summary[-keep:]


def normalize_project_dir(project_dir):
    path = os.path.realpath(project_dir or os.getcwd())
    base = os.path.basename(path)
    parent = os.path.dirname(path)
    if base == "hooks" and os.path.basename(parent) == ".quiet-droid":
        return os.path.dirname(parent)
    if base == ".quiet-droid":
        return parent
    return path


def store_artifact(project_dir, tool_name, text):
    artifact_dir = os.path.join(project_dir, ".quiet-droid", "artifacts")
    os.makedirs(artifact_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_tool = re.sub(r"[^A-Za-z0-9_.-]", "-", tool_name or "tool")[:32] or "tool"
    filename = f"{stamp}-{safe_tool}.log"
    path = os.path.join(artifact_dir, filename)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return os.path.relpath(path, project_dir)


def transform(payload):
    if payload.get("hook_event_name") not in {"PostToolUse", "PostToolUseFailure"}:
        return None
    if not is_local_backend(payload.get("api_base_url", "")):
        return None
    tool_name = payload.get("tool_name", "")
    text = str(payload.get("tool_response", "") or "")
    max_chars = TOOL_LIMITS.get(tool_name, DEFAULT_LIMIT)
    if len(text) <= max_chars:
        return None
    project_dir = normalize_project_dir(os.environ.get("QUIET_DROID_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    artifact_path = store_artifact(project_dir, tool_name, text)
    note = f"\n[full output saved to {artifact_path}]"
    body_budget = max(200, max_chars - len(note))
    summary = build_line_summary(text, body_budget)
    transformed = summary + note
    if len(transformed) > max_chars:
        keep = max(200, (max_chars - len(note) - 32) // 2)
        transformed = summary[:keep] + "\n...(truncated)...\n" + summary[-keep:] + note
    return {
        "hookSpecificOutput": {
            "hookEventName": payload["hook_event_name"],
            "transformedOutput": transformed,
        }
    }


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    result = transform(payload)
    if result is not None:
        json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
