import os


def load_skills(config):
    skills = {}
    skill_dirs = [
        os.path.join(config.config_dir, "skills"),
        os.path.join(config.cwd, ".tiny-agent", "skills"),
        os.path.join(config.cwd, "skills"),
    ]
    for skill_dir in skill_dirs:
        if not os.path.isdir(skill_dir):
            continue
        try:
            for entry in os.listdir(skill_dir):
                if not entry.endswith(".md"):
                    continue
                path = os.path.join(skill_dir, entry)
                if os.path.islink(path) or not os.path.isfile(path):
                    continue
                try:
                    if os.path.getsize(path) > 50000:
                        continue
                    with open(path, encoding="utf-8") as f:
                        skills[entry[:-3]] = f.read(50000)
                except (OSError, UnicodeDecodeError):
                    pass
        except OSError:
            pass
    return skills
