import os


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
