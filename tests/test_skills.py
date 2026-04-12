import os
import tempfile
import unittest

from quiet_droid.skills import extract_referenced_skills, inject_skill_context, load_skills


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

    def test_extracts_only_loaded_referenced_skills_in_order(self):
        skills = {"sar-analyze": "analyze body", "plan": "plan body"}

        referenced = extract_referenced_skills(
            "$sar-analyze my_capture.bin を見て。そのあと $plan して $sar-analyze も再利用",
            skills,
        )

        self.assertEqual(referenced, ["sar-analyze", "plan"])

    def test_injects_referenced_skill_content_into_turn_context(self):
        skills = {"sar-analyze": "Use ./scripts/analyze-sar.sh first."}

        injected = inject_skill_context("$sar-analyze my_capture.binを分析して", skills)

        self.assertIn("$sar-analyze my_capture.binを分析して", injected)
        self.assertIn("[Invoked Skills]", injected)
        self.assertIn("## Skill: sar-analyze", injected)
        self.assertIn("Use ./scripts/analyze-sar.sh first.", injected)

    def test_does_not_inject_when_no_loaded_skill_is_referenced(self):
        user_input = "$missing test"

        injected = inject_skill_context(user_input, {"plan": "body"})

        self.assertEqual(injected, user_input)


if __name__ == "__main__":
    unittest.main()
