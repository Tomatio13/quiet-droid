import base64
import fnmatch
import json
import os
import re
import tempfile
from pathlib import Path

from .base import Tool


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".tif"}
IMAGE_MAX_SIZE = 10 * 1024 * 1024
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def _is_protected_path(file_path):
    protected = {"permissions.json", ".quiet-droid.json", "config.json"}
    return os.path.basename(file_path) in protected


class ReadTool(Tool):
    name = "Read"
    description = "Read a file from the filesystem."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file to read"},
            "offset": {"type": "number", "description": "Line number to start reading from (1-based)"},
            "limit": {"type": "number", "description": "Number of lines to read"},
        },
        "required": ["file_path"],
    }

    def execute(self, params):
        file_path = params.get("file_path", "")
        if not file_path:
            return "Error: no file_path provided"
        if not os.path.isabs(file_path):
            file_path = os.path.join(os.getcwd(), file_path)
        try:
            real_path = os.path.realpath(file_path)
        except (OSError, ValueError):
            return f"Error: cannot resolve path: {file_path}"
        cwd_real = os.path.realpath(os.getcwd())
        if not (real_path == cwd_real or real_path.startswith(cwd_real + os.sep)):
            return f"Error: path is outside the current working directory: {file_path}"
        if not os.path.exists(real_path):
            return f"Error: file not found: {file_path}"
        if os.path.isdir(real_path):
            return f"Error: path is a directory: {file_path}"

        suffix = Path(real_path).suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            try:
                size = os.path.getsize(real_path)
                if size > IMAGE_MAX_SIZE:
                    return f"Error: image too large ({size} bytes). Max size is {IMAGE_MAX_SIZE} bytes."
                with open(real_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("ascii")
                return json.dumps({
                    "type": "image",
                    "media_type": MEDIA_TYPES.get(suffix, "application/octet-stream"),
                    "data": encoded,
                })
            except OSError as exc:
                return f"Error: could not read image: {exc}"

        try:
            offset = max(1, int(params.get("offset", 1)))
        except (ValueError, TypeError):
            offset = 1
        try:
            limit = max(1, int(params.get("limit", 2000)))
        except (ValueError, TypeError):
            limit = 2000
        try:
            with open(real_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as exc:
            return f"Error: could not read file: {exc}"
        start = offset - 1
        end = min(len(lines), start + limit)
        numbered = [f"{i + 1:>6}\t{lines[i].rstrip()}" for i in range(start, end)]
        return "\n".join(numbered) if numbered else "(no content)"


class WriteTool(Tool):
    name = "Write"
    description = "Write a file to the filesystem."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "content": {"type": "string", "description": "Full file contents"},
        },
        "required": ["file_path", "content"],
    }

    def execute(self, params):
        file_path = params.get("file_path", "")
        content = params.get("content", "")
        if not file_path:
            return "Error: no file_path provided"
        if not os.path.isabs(file_path):
            return "Error: Write requires an absolute path"
        try:
            real_path = os.path.realpath(file_path)
        except (OSError, ValueError):
            return f"Error: cannot resolve path: {file_path}"
        cwd_real = os.path.realpath(os.getcwd())
        if not (real_path == cwd_real or real_path.startswith(cwd_real + os.sep)):
            return f"Error: path is outside the current working directory: {file_path}"
        if _is_protected_path(real_path):
            return "Error: writing to protected configuration files is blocked."
        try:
            os.makedirs(os.path.dirname(real_path), exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(real_path), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, real_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            return f"Error: could not write file: {exc}"
        return f"Wrote {len(content)} bytes to {real_path}"


class EditTool(Tool):
    name = "Edit"
    description = "Replace exact text inside a file."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "old_string": {"type": "string", "description": "Exact text to replace"},
            "new_string": {"type": "string", "description": "Replacement text"},
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    def execute(self, params):
        file_path = params.get("file_path", "")
        old_string = params.get("old_string", "")
        new_string = params.get("new_string", "")
        if not file_path:
            return "Error: no file_path provided"
        if not os.path.isabs(file_path):
            return "Error: Edit requires an absolute path"
        try:
            real_path = os.path.realpath(file_path)
        except (OSError, ValueError):
            return f"Error: cannot resolve path: {file_path}"
        cwd_real = os.path.realpath(os.getcwd())
        if not (real_path == cwd_real or real_path.startswith(cwd_real + os.sep)):
            return f"Error: path is outside the current working directory: {file_path}"
        if _is_protected_path(real_path):
            return "Error: editing protected configuration files is blocked."
        try:
            with open(real_path, encoding="utf-8", errors="replace") as f:
                original = f.read()
        except OSError as exc:
            return f"Error: could not read file: {exc}"
        if old_string not in original:
            return "Error: old_string not found in file"
        updated = original.replace(old_string, new_string, 1)
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(real_path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(updated)
            os.replace(tmp_path, real_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return f"Edited {real_path}"


class GlobTool(Tool):
    name = "Glob"
    description = "Find files by glob pattern."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern relative to cwd"},
            "path": {"type": "string", "description": "Optional starting directory"},
        },
        "required": ["pattern"],
    }

    def execute(self, params):
        pattern = params.get("pattern", "")
        base_path = params.get("path") or os.getcwd()
        if not pattern:
            return "Error: no pattern provided"
        if not os.path.isabs(base_path):
            base_path = os.path.join(os.getcwd(), base_path)
        try:
            base_real = os.path.realpath(base_path)
        except (OSError, ValueError):
            return f"Error: cannot resolve path: {base_path}"
        cwd_real = os.path.realpath(os.getcwd())
        if not (base_real == cwd_real or base_real.startswith(cwd_real + os.sep)):
            return f"Error: path is outside the current working directory: {base_path}"
        matches = []
        for root, dirs, files in os.walk(base_real):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), base_real)
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
                    matches.append(os.path.join(root, name))
        matches.sort()
        return "\n".join(matches[:1000]) if matches else "(no matches)"


class GrepTool(Tool):
    name = "Grep"
    description = "Search text in files using a regex pattern."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression to search for"},
            "path": {"type": "string", "description": "Optional file or directory to search"},
            "glob": {"type": "string", "description": "Optional filename glob filter"},
        },
        "required": ["pattern"],
    }

    def execute(self, params):
        pattern = params.get("pattern", "")
        path = params.get("path") or os.getcwd()
        filename_glob = params.get("glob")
        if not pattern:
            return "Error: no pattern provided"
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        try:
            real_path = os.path.realpath(path)
        except (OSError, ValueError):
            return f"Error: cannot resolve path: {path}"
        cwd_real = os.path.realpath(os.getcwd())
        if not (real_path == cwd_real or real_path.startswith(cwd_real + os.sep)):
            return f"Error: path is outside the current working directory: {path}"
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Error: invalid regex: {exc}"

        files = []
        if os.path.isfile(real_path):
            files = [real_path]
        else:
            for root, dirs, names in os.walk(real_path):
                dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
                for name in names:
                    if filename_glob and not fnmatch.fnmatch(name, filename_glob):
                        continue
                    files.append(os.path.join(root, name))

        matches = []
        for file_path in files:
            try:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    for idx, line in enumerate(f, start=1):
                        if regex.search(line):
                            matches.append(f"{file_path}:{idx}: {line.rstrip()}")
            except OSError:
                continue
        return "\n".join(matches[:2000]) if matches else "(no matches)"
