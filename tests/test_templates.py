import re
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fk_templates as t  # noqa: E402

TEMPLATES = ["AGENTS.md", "CLAUDE.md", "factory.md", "pr-description.md", "triage-labels-note.md"]


def settings_block(text):
    return tomllib.loads(re.search(r"```toml\n(.*?)```", text, re.S).group(1))


class TemplatesTest(unittest.TestCase):
    def test_every_template_renders_with_sample_values(self):
        for name in TEMPLATES:
            with self.subTest(name):
                values = t.factory_values(t.SAMPLE_VALUES) if name == "factory.md" else t.SAMPLE_VALUES
                out = t.render_file(name, values)
                self.assertNotIn("{{", out)
                self.assertNotIn("}}", out)

    def test_missing_value_is_an_error(self):
        with self.assertRaisesRegex(KeyError, "project_name"):
            t.render_file("AGENTS.md", {})

    def test_claude_md_only_imports_agents_md(self):
        self.assertEqual(t.render_file("CLAUDE.md", {}).strip(), "@AGENTS.md")

    def test_factory_settings_block_parses_with_defaults(self):
        settings = settings_block(t.render_file("factory.md", t.factory_values(t.SAMPLE_VALUES)))
        self.assertEqual(settings["risky_paths"], t.DEFAULT_RISKY_PATHS)
        self.assertEqual(settings["max_parallel"], 2)
        self.assertEqual(settings["reviewer_model"], "sonnet")
        self.assertEqual(settings["verify"]["test"], "python -m unittest discover -s tests")
        self.assertEqual(settings["verify"]["typecheck"], "")

    def test_factory_settings_escape_quotes_and_backslashes(self):
        values = dict(t.SAMPLE_VALUES, test_cmd='pytest -k "not slow" C:\\tmp', risky_paths_list=['db/"x"/**'])
        settings = settings_block(t.render_file("factory.md", t.factory_values(values)))
        self.assertEqual(settings["verify"]["test"], 'pytest -k "not slow" C:\\tmp')
        self.assertEqual(settings["risky_paths"], ['db/"x"/**'])

    def test_factory_rules_block_has_all_four_rules(self):
        out = t.render_file("factory.md", t.factory_values(t.SAMPLE_VALUES))
        for heading in ["docs PR", "Trace block", "Post decisions before acting", "Builder rules"]:
            self.assertIn(heading, out)

    def test_pr_description_starts_with_closes_and_trace(self):
        lines = t.render_file("pr-description.md", t.SAMPLE_VALUES).splitlines()
        self.assertEqual(lines[0], "Closes #42")
        self.assertTrue(lines[1].startswith('Trace: ticket #42 "Add retry to SMS sender" -> spec #30'))

    def test_marked_blocks_can_be_found_for_in_place_updates(self):
        agents = t.render_file("AGENTS.md", t.SAMPLE_VALUES)
        self.assertRegex(agents, r"(?s)<!-- factorykit:rules:begin -->.*<!-- factorykit:rules:end -->")
        note = t.render_file("triage-labels-note.md", {})
        self.assertIn("ready-for-human`: not used", note)
        self.assertRegex(note, r"(?s)<!-- factorykit:triage:begin -->.*<!-- factorykit:triage:end -->")


if __name__ == "__main__":
    unittest.main()
