import os
import re
from dataclasses import dataclass, field


SKILL_REFERENCE_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Za-z0-9][A-Za-z0-9_-]*)")
FRONTMATTER_DELIMITER = "---"
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):(?:\s+(.*))?$")


@dataclass
class SkillDefinition:
    name: str
    source_name: str
    skill_md_path: str
    skill_root: str
    description: str = ""
    metadata: dict = field(default_factory=dict)
    compatibility: str = ""
    allowed_tools: str = ""
    body: str | None = None

    @property
    def scripts_dir(self):
        return os.path.join(self.skill_root, "scripts")

    @property
    def references_dir(self):
        return os.path.join(self.skill_root, "references")

    @property
    def assets_dir(self):
        return os.path.join(self.skill_root, "assets")

    def load_body(self):
        if self.body is not None:
            return self.body
        try:
            with open(self.skill_md_path, encoding="utf-8") as f:
                self.body = f.read()
        except (OSError, UnicodeDecodeError):
            self.body = ""
        return self.body

    def summary_lines(self):
        lines = [f"- {self.name}: {self.description or '(no description)'}"]
        if self.compatibility:
            lines.append(f"  compatibility: {self.compatibility}")
        if self.allowed_tools:
            lines.append(f"  allowed-tools: {self.allowed_tools}")
        return lines

    def resolved_path_lines(self):
        return [
            f"Skill root: {self.skill_root}",
            f"SKILL.md: {self.skill_md_path}",
            _format_dir_line("scripts/", self.scripts_dir),
            _format_dir_line("references/", self.references_dir),
            _format_dir_line("assets/", self.assets_dir),
        ]


def _format_dir_line(label, path):
    status = "exists" if os.path.isdir(path) else "missing"
    return f"{label}: {path} ({status})"


def _iter_skill_files(skill_dir):
    try:
        entries = os.listdir(skill_dir)
    except OSError:
        return
    for entry in entries:
        path = os.path.join(skill_dir, entry)
        if entry.endswith(".md") and os.path.isfile(path):
            yield entry[:-3], path, os.path.dirname(path)
            continue
        if os.path.isdir(path):
            skill_md = os.path.join(path, "SKILL.md")
            if os.path.isfile(skill_md):
                yield entry, skill_md, path


def _parse_scalar(value):
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _read_skill_frontmatter(path):
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            first = f.readline()
            if first.strip() != FRONTMATTER_DELIMITER:
                return data
            current_map_key = None
            for raw_line in f:
                stripped = raw_line.strip()
                if stripped == FRONTMATTER_DELIMITER:
                    break
                if not stripped or stripped.startswith("#"):
                    continue
                if raw_line[:1].isspace():
                    if current_map_key and ":" in stripped:
                        nested_key, nested_value = stripped.split(":", 1)
                        target = data.setdefault(current_map_key, {})
                        if isinstance(target, dict):
                            target[nested_key.strip()] = _parse_scalar(nested_value)
                    continue
                match = FRONTMATTER_KEY_RE.match(stripped)
                if not match:
                    current_map_key = None
                    continue
                key, value = match.groups()
                if value is None or value == "":
                    data[key] = {}
                    current_map_key = key
                else:
                    data[key] = _parse_scalar(value)
                    current_map_key = None
    except (OSError, UnicodeDecodeError):
        return {}
    return data


def load_skills(config):
    skills = {}
    skill_dirs = [
        os.path.join(config.config_dir, "skills"),
        os.path.join(config.cwd, ".quiet-droid", "skills"),
        os.path.join(config.cwd, "skills"),
    ]
    for skill_dir in skill_dirs:
        if not os.path.isdir(skill_dir):
            continue
        for source_name, skill_md_path, skill_root in _iter_skill_files(skill_dir):
            try:
                frontmatter = _read_skill_frontmatter(skill_md_path)
                skill_name = frontmatter.get("name") or source_name
                description = frontmatter.get("description") or ""
                compatibility = frontmatter.get("compatibility") or ""
                allowed_tools = frontmatter.get("allowed-tools") or ""
                skills[skill_name] = SkillDefinition(
                    name=skill_name,
                    source_name=source_name,
                    skill_md_path=skill_md_path,
                    skill_root=skill_root,
                    description=description,
                    metadata=frontmatter,
                    compatibility=compatibility,
                    allowed_tools=allowed_tools,
                )
            except OSError:
                pass
    return skills


def extract_referenced_skills(user_input, skills):
    seen = set()
    ordered = []
    for match in SKILL_REFERENCE_RE.finditer(user_input or ""):
        skill_name = match.group(1)
        if skill_name in skills and skill_name not in seen:
            seen.add(skill_name)
            ordered.append(skill_name)
    return ordered


def inject_skill_context(user_input, skills):
    referenced = extract_referenced_skills(user_input, skills)
    if not referenced:
        return user_input

    parts = [user_input.rstrip(), "", "[Invoked Skills]"]
    parts.append("The user explicitly invoked the following loaded skills for this turn.")
    parts.append("Treat these skill instructions as active requirements and prefer them over generic exploration.")
    parts.append("These skills are already resolved from the local loader; do not search the filesystem for alternative copies unless the skill itself requires it.")
    parts.append("If you need additional files from a skill, use the resolved paths below and follow relative paths from the skill root.")
    for skill_name in referenced:
        skill = skills[skill_name]
        parts.append("")
        parts.append(f"## Skill: {skill.name}")
        parts.append(f"Description: {skill.description or '(no description)'}")
        if skill.compatibility:
            parts.append(f"Compatibility: {skill.compatibility}")
        if skill.allowed_tools:
            parts.append(f"Allowed tools: {skill.allowed_tools}")
        parts.append("Resolved paths:")
        parts.extend(skill.resolved_path_lines())
        parts.append("")
        parts.append("Full SKILL.md:")
        parts.append(skill.load_body())
    return "\n".join(parts).strip()
