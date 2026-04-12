import os
import re


SKILL_REFERENCE_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Za-z0-9][A-Za-z0-9_-]*)")


def _iter_skill_files(skill_dir):
    try:
        entries = os.listdir(skill_dir)
    except OSError:
        return
    for entry in entries:
        path = os.path.join(skill_dir, entry)
        if entry.endswith(".md") and os.path.isfile(path):
            yield entry[:-3], path
            continue
        if os.path.isdir(path):
            skill_md = os.path.join(path, "SKILL.md")
            if os.path.isfile(skill_md):
                yield entry, skill_md


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
        for skill_name, path in _iter_skill_files(skill_dir):
            try:
                if os.path.getsize(path) > 50000:
                    continue
                with open(path, encoding="utf-8") as f:
                    skills[skill_name] = f.read(50000)
            except (OSError, UnicodeDecodeError):
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
    for skill_name in referenced:
        parts.append("")
        parts.append(f"## Skill: {skill_name}")
        parts.append(skills[skill_name])
    return "\n".join(parts).strip()
