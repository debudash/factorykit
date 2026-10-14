import importlib.machinery
import importlib.util
import tempfile
import tomllib
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("setup_project", str(ROOT / "scripts" / "setup-project"))
_spec = importlib.util.spec_from_loader("setup_project", _loader)
sp = importlib.util.module_from_spec(_spec)
_loader.exec_module(sp)

NOW = datetime(2026, 10, 14, 21, 30)


class FakeGitHub:
    def __init__(self, rulesets_allowed=True):
        self.rulesets_allowed = rulesets_allowed
        self.labels = {"bug", "enhancement"}
        self.ruleset = None
        self.settings = {"allow_auto_merge": False, "delete_branch_on_merge": False}
        self.prs = []
        self.calls = []

    def repo_info(self):
        return {"name": "debudash/scratch", "visibility": "public", "default_branch": "main"}

    def label_names(self):
        return set(self.labels)

    def create_label(self, name, color, description):
        self.calls.append(("label", name))
        self.labels.add(name)

    def find_ruleset(self):
        if not self.rulesets_allowed:
            return 403, None
        return 200, self.ruleset

    def create_ruleset(self, body):
        self.calls.append(("create_ruleset",))
        self.ruleset = dict(body, id=7)

    def update_ruleset(self, ruleset_id, body):
        self.calls.append(("update_ruleset", ruleset_id))
        self.ruleset = dict(body, id=ruleset_id)

    def merge_settings(self):
        return dict(self.settings)

    def set_merge_settings(self, settings):
        self.calls.append(("settings",))
        self.settings = dict(settings)

    def create_pr(self, branch, base, title, body, label):
        self.prs.append((branch, base, label))
        return f"https://github.com/debudash/scratch/pull/{len(self.prs)}"


class FakeGit:
    """Reports every existing setup file as changed until committed."""

    def __init__(self, repo):
        self.repo = repo
        self.committed = {}

    def changed(self, paths):
        found = []
        for p in paths:
            target = self.repo / p
            files = [target] if target.is_file() else sorted(f for f in target.rglob("*") if f.is_file()) if target.is_dir() else []
            for f in files:
                rel = f.relative_to(self.repo).as_posix()
                if self.committed.get(rel) != f.read_text(encoding="utf-8"):
                    found.append(rel)
        return found

    def commit_on_new_branch(self, branch, paths, message):
        for rel in paths:
            self.committed[rel] = (self.repo / rel).read_text(encoding="utf-8")


def answers(**overrides):
    base = dict(project_name="scratch", owner="debudash", project_summary="A scratch repo.",
                test_cmd="python -m unittest", typecheck_cmd="", lint_cmd="", build_cmd="",
                ci_check="test", reviewer_model="sonnet")
    base.update(overrides)
    return sp.Answers(**base)


def matt_setup(repo):
    """Simulate /setup-matt-pocock-skills: edits AGENTS.md and writes docs/agents/*."""
    agents = repo / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8") + "\n## Agent skills\n\nSee docs/agents/.\n", encoding="utf-8")
    (repo / "docs" / "agents").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "agents" / "issue-tracker.md").write_text("GitHub issues.\n", encoding="utf-8")
    (repo / "docs" / "agents" / "triage-labels.md").write_text("# Triage Labels\n\n| table |\n", encoding="utf-8")


class SetupProjectTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "scratch"
        self.repo.mkdir()
        self.registry = Path(tmp.name) / "factory" / "projects.toml"
        self.gh = FakeGitHub()
        self.git = FakeGit(self.repo)
        self.out = []

    def run_setup(self, dry_run=False, **kw):
        self.out = []
        return sp.setup(self.repo, answers(**kw), self.gh, self.git, self.registry, dry_run, self.out.append, now=NOW)

    def text(self, rel):
        return (self.repo / rel).read_text(encoding="utf-8")

    def test_dry_run_prints_plan_and_changes_nothing(self):
        count = self.run_setup(dry_run=True)
        self.assertGreater(count, 0)
        self.assertIn("would write AGENTS.md", self.out)
        self.assertTrue(any(l.startswith("would create ruleset factorykit-main") for l in self.out))
        self.assertTrue(any(l.startswith("would create label needs-decision") for l in self.out))
        self.assertEqual(list(self.repo.iterdir()), [])
        self.assertFalse(self.registry.exists())
        self.assertEqual(self.gh.calls, [])

    def test_first_run_writes_agents_and_factory_then_waits_for_matt_setup(self):
        self.run_setup()
        self.assertIn("<!-- factorykit:rules:begin -->", self.text("AGENTS.md"))
        self.assertIn("reviewer_model = \"sonnet\"", self.text("docs/agents/factory.md"))
        self.assertFalse((self.repo / "CLAUDE.md").exists())
        self.assertTrue(any(l.startswith("NEXT: in Claude Code") for l in self.out))
        self.assertEqual(self.gh.prs, [])

    def test_second_run_after_matt_setup_finishes_and_opens_pr(self):
        self.run_setup()
        matt_setup(self.repo)
        self.run_setup()
        self.assertEqual(self.text("CLAUDE.md").strip(), "@AGENTS.md")
        self.assertIn("ready-for-human`: not used", self.text("docs/agents/triage-labels.md"))
        self.assertIn("## Agent skills", self.text("AGENTS.md"))
        self.assertEqual(self.gh.prs, [("factorykit/setup-20261014-2130", "main", "no-dispatch")])
        self.assertIn("docs/agents/issue-tracker.md", self.git.committed)

    def test_rerun_after_complete_setup_changes_nothing(self):
        self.run_setup()
        matt_setup(self.repo)
        self.run_setup()
        self.assertEqual(self.run_setup(), 0)
        self.assertIn("nothing to change", self.out)
        self.assertEqual(len(self.gh.prs), 1)

    def test_existing_agents_md_keeps_owner_text_and_gets_block_once(self):
        (self.repo / "AGENTS.md").write_text("# My rules\n\nKeep this.\n", encoding="utf-8")
        self.run_setup()
        self.run_setup()
        text = self.text("AGENTS.md")
        self.assertTrue(text.startswith("# My rules\n\nKeep this.\n"))
        self.assertEqual(text.count("factorykit:rules:begin"), 1)

    def test_changed_owner_name_updates_the_block_in_place(self):
        self.run_setup()
        self.run_setup(owner="someone-else")
        text = self.text("AGENTS.md")
        self.assertIn("Decision by @someone-else", text)
        self.assertNotIn("Decision by @debudash", text)

    def test_existing_factory_md_is_never_overwritten(self):
        path = self.repo / "docs" / "agents" / "factory.md"
        path.parent.mkdir(parents=True)
        path.write_text("owner edited\n", encoding="utf-8")
        self.run_setup()
        self.assertEqual(self.text("docs/agents/factory.md"), "owner edited\n")

    def test_claude_md_with_content_stops_before_matt_setup_edits_the_wrong_file(self):
        (self.repo / "CLAUDE.md").write_text("old instructions\n", encoding="utf-8")
        with self.assertRaisesRegex(sp.SetupError, "Move its content into AGENTS.md"):
            self.run_setup()
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_one_line_claude_md_is_removed_until_matt_setup_then_written_back(self):
        (self.repo / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        self.run_setup()
        self.assertFalse((self.repo / "CLAUDE.md").exists())
        matt_setup(self.repo)
        self.run_setup()
        self.assertEqual(self.text("CLAUDE.md").strip(), "@AGENTS.md")

    def test_dry_run_with_one_line_claude_md_removes_nothing(self):
        (self.repo / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        self.run_setup(dry_run=True)
        self.assertTrue((self.repo / "CLAUDE.md").exists())

    def test_claude_md_with_own_content_is_kept(self):
        self.run_setup()
        matt_setup(self.repo)
        (self.repo / "CLAUDE.md").write_text("extra content\n", encoding="utf-8")
        self.run_setup()
        self.assertEqual(self.text("CLAUDE.md"), "extra content\n")
        self.assertTrue(any("CLAUDE.md has its own content" in l for l in self.out))

    def test_worktrees_ignored_once_and_existing_gitignore_kept(self):
        (self.repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        self.run_setup()
        self.run_setup()
        self.assertEqual(self.text(".gitignore"), "node_modules/\n.claude/worktrees/\n")

    def test_only_missing_labels_are_created(self):
        self.run_setup()
        created = sorted(name for kind, *rest in self.gh.calls if kind == "label" for name in rest)
        self.assertEqual(created, sorted(n for n, _, _ in sp.LABELS if n not in ("bug", "enhancement")))
        self.assertEqual(len(self.gh.labels), 8)

    def test_ruleset_requires_ci_check_and_dispatcher_review(self):
        self.run_setup(ci_check="build-and-test")
        checks = [r for r in self.gh.ruleset["rules"] if r["type"] == "required_status_checks"][0]
        contexts = [c["context"] for c in checks["parameters"]["required_status_checks"]]
        self.assertEqual(contexts, ["build-and-test", "dispatcher/review"])
        self.assertEqual(self.gh.settings, {"allow_auto_merge": True, "delete_branch_on_merge": True})

    def test_changed_ci_check_updates_existing_ruleset(self):
        self.run_setup(ci_check="test")
        self.run_setup(ci_check="ci")
        self.assertIn(("update_ruleset", 7), self.gh.calls)

    def test_manual_merge_mode_keeps_ruleset_but_not_auto_merge(self):
        self.run_setup(merge_mode="manual")
        self.assertIsNotNone(self.gh.ruleset)
        self.assertNotIn(("settings",), self.gh.calls)

    def test_plan_without_rulesets_falls_back_to_manual(self):
        self.gh = FakeGitHub(rulesets_allowed=False)
        self.run_setup()
        self.assertTrue(any("adr/0017" in l for l in self.out))
        entry = tomllib.loads(self.registry.read_text(encoding="utf-8"))["scratch"]
        self.assertEqual(entry["merge_mode"], "manual")
        self.assertNotIn(("settings",), self.gh.calls)

    def test_registry_entry_written_and_other_projects_kept(self):
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text('# my projects\n[other]\npath = "C:/x"\nauto_fix = "off"\nmerge_mode = "manual"\n',
                                 encoding="utf-8")
        self.run_setup()
        self.run_setup(auto_fix="ci")
        text = self.registry.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        self.assertTrue(text.startswith("# my projects\n"))
        self.assertEqual(data["other"]["auto_fix"], "off")
        self.assertEqual(data["scratch"]["auto_fix"], "ci")
        self.assertEqual(data["scratch"]["path"], self.repo.as_posix())
        self.assertEqual(text.count("[scratch]"), 1)


class HelpersTest(unittest.TestCase):
    def test_upsert_block_replaces_only_same_named_block(self):
        text = "a\n<!-- factorykit:x:begin -->old<!-- factorykit:x:end -->\nb\n"
        out = sp.upsert_block(text, "<!-- factorykit:x:begin -->new<!-- factorykit:x:end -->\n")
        self.assertEqual(out, "a\n<!-- factorykit:x:begin -->new<!-- factorykit:x:end -->\nb\n")

    def test_ruleset_matches_ignores_server_fields(self):
        wanted = sp.ruleset_body("ci")
        existing = dict(wanted, id=1, source="x", rules=[dict(r) for r in wanted["rules"]])
        self.assertTrue(sp.ruleset_matches(existing, wanted))
        self.assertFalse(sp.ruleset_matches(existing, sp.ruleset_body("test")))

    def test_ruleset_without_admin_bypass_needs_update(self):
        wanted = sp.ruleset_body("ci")
        self.assertEqual(wanted["bypass_actors"], [sp.ADMIN_BYPASS])
        self.assertEqual(wanted["bypass_actors"][0]["bypass_mode"], "pull_request")
        self.assertFalse(sp.ruleset_matches(dict(wanted, bypass_actors=[]), wanted))


if __name__ == "__main__":
    unittest.main()
