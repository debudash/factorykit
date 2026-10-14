import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("sync_skills", str(ROOT / "scripts" / "sync-skills"))
_spec = importlib.util.spec_from_loader("sync_skills", _loader)
sync_skills = importlib.util.module_from_spec(_spec)
_loader.exec_module(sync_skills)

COMMIT = "c0ffee"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class SyncSkillsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.upstream = self.root / "upstream"
        self.claude = self.root / "claude"
        self.kit = self.root / "kit"
        self.lock = self.root / "skills.lock"
        self.set_upstream({"engineering/tdd": "tdd v1", "engineering/code-review": "review v1"})
        write(self.kit / "skills" / "design-doc" / "SKILL.md", "design-doc v1")
        write(self.kit / "agents" / "builder.md", "builder v1")
        self.set_lock("v1.0.0", COMMIT)
        self.fetched_commit = COMMIT
        self.output = []

    def set_upstream(self, skills):
        if self.upstream.exists():
            import shutil
            shutil.rmtree(self.upstream)
        for path, body in skills.items():
            write(self.upstream / "skills" / path / "SKILL.md", body)
        manifest = {"skills": [f"./skills/{p}" for p in skills]}
        write(self.upstream / ".claude-plugin" / "plugin.json", json.dumps(manifest))

    def set_lock(self, tag, commit):
        write(self.lock, f'[mattpocock]\nrepo = "https://example.invalid/skills.git"\ntag = "{tag}"\ncommit = "{commit}"\n')

    def fake_fetch(self, repo_url, tag, workdir):
        return self.upstream, self.fetched_commit

    def run_sync(self, *extra):
        self.output = []
        args = ["--claude-dir", str(self.claude), "--lock", str(self.lock), "--factorykit-dir", str(self.kit), *extra]
        return sync_skills.main(args, fetch=self.fake_fetch, out=self.output.append)

    def skill(self, name):
        return self.claude / "skills" / name / "SKILL.md"

    def test_sync_installs_upstream_skills_ours_and_agents(self):
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.skill("tdd").read_text(encoding="utf-8"), "tdd v1")
        self.assertTrue(self.skill("code-review").is_file())
        self.assertTrue(self.skill("design-doc").is_file())
        self.assertEqual((self.claude / "agents" / "builder.md").read_text(encoding="utf-8"), "builder v1")

    def test_only_skills_listed_in_plugin_manifest_are_installed(self):
        write(self.upstream / "skills" / "in-progress" / "draft" / "SKILL.md", "draft")
        self.run_sync()
        self.assertFalse(self.skill("draft").exists())

    def test_check_is_clean_after_sync(self):
        self.run_sync()
        self.assertEqual(self.run_sync("--check"), 0)
        self.assertEqual(self.output, ["clean"])

    def test_check_before_any_sync_reports_never_synced(self):
        self.assertEqual(self.run_sync("--check"), 1)
        self.assertIn("never synced", self.output[0])

    def test_check_reports_modified_and_missing_skills(self):
        self.run_sync()
        self.skill("tdd").write_text("edited by hand", encoding="utf-8")
        import shutil
        shutil.rmtree(self.claude / "skills" / "code-review")
        self.assertEqual(self.run_sync("--check"), 1)
        self.assertIn("modified since sync: skill/tdd", self.output)
        self.assertIn("missing: skill/code-review", self.output)

    def test_check_reports_pin_change(self):
        self.run_sync()
        self.set_lock("v2.0.0", "beef")
        self.assertEqual(self.run_sync("--check"), 1)
        self.assertIn("pin: installed v1.0.0, skills.lock says v2.0.0", self.output)

    def test_check_reports_our_changes_additions_and_removals(self):
        self.run_sync()
        write(self.kit / "skills" / "design-doc" / "SKILL.md", "design-doc v2")
        write(self.kit / "skills" / "address-feedback" / "SKILL.md", "new")
        (self.kit / "agents" / "builder.md").unlink()
        self.run_sync("--check")
        self.assertIn("out of date (changed in FactoryKit): skill/design-doc", self.output)
        self.assertIn("not installed: skill/address-feedback", self.output)
        self.assertIn("removed from FactoryKit but still installed: agent/builder.md", self.output)

    def test_resync_updates_changed_and_restores_edited_skills(self):
        self.run_sync()
        self.skill("tdd").write_text("edited by hand", encoding="utf-8")
        self.set_upstream({"engineering/tdd": "tdd v1", "engineering/code-review": "review v2"})
        self.run_sync()
        self.assertIn("update   skill/tdd", self.output)
        self.assertIn("update   skill/code-review", self.output)
        self.assertEqual(self.skill("tdd").read_text(encoding="utf-8"), "tdd v1")
        self.assertEqual(self.skill("code-review").read_text(encoding="utf-8"), "review v2")

    def test_skill_removed_upstream_is_removed(self):
        self.run_sync()
        self.set_upstream({"engineering/tdd": "tdd v1"})
        self.run_sync()
        self.assertIn("remove   skill/code-review", self.output)
        self.assertFalse((self.claude / "skills" / "code-review").exists())
        self.assertEqual(self.run_sync("--check"), 0)

    def test_skill_not_installed_by_sync_is_never_overwritten_or_removed(self):
        write(self.claude / "skills" / "my-own" / "SKILL.md", "mine")
        self.run_sync()
        self.assertEqual((self.claude / "skills" / "my-own" / "SKILL.md").read_text(encoding="utf-8"), "mine")

    def test_name_clash_with_hand_installed_skill_is_refused_without_adopt(self):
        write(self.skill("tdd"), "hand-installed")
        self.assertEqual(self.run_sync(), 2)
        self.assertIn("--adopt", self.output[-1])
        self.assertEqual(self.skill("tdd").read_text(encoding="utf-8"), "hand-installed")
        self.assertFalse((self.claude / "skills" / sync_skills.MANIFEST_NAME).exists())

    def test_adopt_takes_over_hand_installed_skill(self):
        write(self.skill("tdd"), "hand-installed")
        self.assertEqual(self.run_sync("--adopt"), 0)
        self.assertIn("adopt    skill/tdd", self.output)
        self.assertEqual(self.skill("tdd").read_text(encoding="utf-8"), "tdd v1")

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.run_sync("--dry-run"), 0)
        self.assertIn("install  skill/tdd", self.output)
        self.assertFalse(self.claude.exists())

    def test_tag_resolving_to_other_commit_is_refused(self):
        self.fetched_commit = "evil"
        self.assertEqual(self.run_sync(), 2)
        self.assertIn("skills.lock says c0ffee", self.output[-1])
        self.assertFalse(self.claude.exists())

    def test_our_skill_with_same_name_as_upstream_is_refused(self):
        write(self.kit / "skills" / "tdd" / "SKILL.md", "ours")
        self.assertEqual(self.run_sync(), 2)
        self.assertIn("same name", self.output[-1])

    def test_real_lock_file_is_valid(self):
        pin = sync_skills.read_lock(ROOT / "skills.lock")
        self.assertTrue(pin["tag"].startswith("v"))
        self.assertEqual(len(pin["commit"]), 40)


if __name__ == "__main__":
    unittest.main()
