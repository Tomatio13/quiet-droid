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

    def test_loads_frontmatter_from_markdown_skill_file(self):
        skills_dir = os.path.join(self.config.config_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        with open(os.path.join(skills_dir, "plan.md"), "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "name: plan\n"
                "description: Strategic planning with optional interview workflow\n"
                "---\n\n"
                "full body that should not be preloaded\n"
            )

        skills = load_skills(self.config)
        skill = skills["plan"]

        self.assertEqual(skill.name, "plan")
        self.assertEqual(skill.description, "Strategic planning with optional interview workflow")
        self.assertIsNone(skill.body)
        self.assertEqual(skill.skill_root, skills_dir)
        self.assertEqual(skill.skill_md_path, os.path.join(skills_dir, "plan.md"))

    def test_loads_symlinked_skill_directory_and_paths(self):
        source_dir = os.path.join(self.root, "source-skill")
        os.makedirs(os.path.join(source_dir, "scripts"), exist_ok=True)
        with open(os.path.join(source_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "name: plan\n"
                "description: linked description\n"
                "---\n\n"
                "linked body\n"
            )

        skills_dir = os.path.join(self.config.config_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        os.symlink(source_dir, os.path.join(skills_dir, "plan"))

        skills = load_skills(self.config)
        skill = skills["plan"]

        self.assertEqual(skill.description, "linked description")
        self.assertEqual(skill.skill_root, os.path.join(skills_dir, "plan"))
        self.assertEqual(skill.skill_md_path, os.path.join(skills_dir, "plan", "SKILL.md"))
        self.assertEqual(skill.scripts_dir, os.path.join(skills_dir, "plan", "scripts"))

    def test_falls_back_to_filename_when_frontmatter_is_missing(self):
        skills_dir = os.path.join(self.config.config_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        with open(os.path.join(skills_dir, "plain.md"), "w", encoding="utf-8") as f:
            f.write("plain body")

        skills = load_skills(self.config)
        skill = skills["plain"]

        self.assertEqual(skill.name, "plain")
        self.assertEqual(skill.description, "")
        self.assertIsNone(skill.body)

    def test_extracts_only_loaded_referenced_skills_in_order(self):
        skills = {"sar-analyze": object(), "plan": object()}

        referenced = extract_referenced_skills(
            "$sar-analyze my_capture.bin を見て。そのあと $plan して $sar-analyze も再利用",
            skills,
        )

        self.assertEqual(referenced, ["sar-analyze", "plan"])

    def test_injects_referenced_skill_content_with_resolved_paths(self):
        skill_dir = os.path.join(self.root, "skills", "sar-analyze")
        os.makedirs(os.path.join(skill_dir, "scripts"), exist_ok=True)
        os.makedirs(os.path.join(skill_dir, "references"), exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "name: sar-analyze\n"
                "description: Analyze SAR captures\n"
                "compatibility: Requires bash\n"
                "allowed-tools: Bash Read\n"
                "---\n\n"
                "Use scripts/analyze-sar.sh first.\n"
            )

        skills = load_skills(self.config)
        injected = inject_skill_context("$sar-analyze my_capture.binを分析して", skills)
        skill = skills["sar-analyze"]

        self.assertIn("$sar-analyze my_capture.binを分析して", injected)
        self.assertIn("[Invoked Skills]", injected)
        self.assertIn("## Skill: sar-analyze", injected)
        self.assertIn("Description: Analyze SAR captures", injected)
        self.assertIn("Compatibility: Requires bash", injected)
        self.assertIn("Allowed tools: Bash Read", injected)
        self.assertIn(f"Skill root: {skill.skill_root}", injected)
        self.assertIn(f"SKILL.md: {skill.skill_md_path}", injected)
        self.assertIn(f"scripts/: {skill.scripts_dir} (exists)", injected)
        self.assertIn(f"references/: {skill.references_dir} (exists)", injected)
        self.assertIn(f"assets/: {skill.assets_dir} (missing)", injected)
        self.assertIn("Use scripts/analyze-sar.sh first.", injected)
        self.assertEqual(skill.body.strip().splitlines()[-1], "Use scripts/analyze-sar.sh first.")

    def test_does_not_inject_when_no_loaded_skill_is_referenced(self):
        user_input = "$missing test"

        injected = inject_skill_context(user_input, {"plan": object()})

        self.assertEqual(injected, user_input)


if __name__ == "__main__":
    unittest.main()
