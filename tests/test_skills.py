import os
import tempfile
import unittest

from quiet_droid.skills import load_skills


class DummyConfig:
    def __init__(self, root):
        self.cwd = root
        self.config_dir = os.path.join(root, "config")
        os.makedirs(self.config_dir, exist_ok=True)


class SkillsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        self.config = DummyConfig(self.root)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_loads_markdown_skill_file(self):
        skills_dir = os.path.join(self.config.config_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        with open(os.path.join(skills_dir, "plan.md"), "w", encoding="utf-8") as f:
            f.write("plan body")
        skills = load_skills(self.config)
        self.assertEqual(skills["plan"], "plan body")

    def test_loads_symlinked_skill_directory(self):
        source_dir = os.path.join(self.root, "source-skill")
        os.makedirs(source_dir, exist_ok=True)
        with open(os.path.join(source_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("linked body")

        skills_dir = os.path.join(self.config.config_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        os.symlink(source_dir, os.path.join(skills_dir, "plan"))

        skills = load_skills(self.config)
        self.assertEqual(skills["plan"], "linked body")


if __name__ == "__main__":
    unittest.main()
