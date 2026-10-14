import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dispatcher import rules  # noqa: E402
from dispatcher.rules import Change  # noqa: E402

RISKY = ["**/auth/**", "**/migrations/**", ".github/workflows/**", "infra/**", "**/*.tf"]


def guard(name, results):
    return next(r for r in results if r.name == name)


class GlobTest(unittest.TestCase):
    def test_double_star_spans_folders(self):
        self.assertTrue(rules.matches("src/app/auth/login.py", "**/auth/**"))
        self.assertTrue(rules.matches("auth/login.py", "**/auth/**"))
        self.assertTrue(rules.matches("db/migrations/0001.sql", "**/migrations/**"))
        self.assertFalse(rules.matches("src/author.py", "**/auth/**"))

    def test_single_star_stays_in_one_folder(self):
        self.assertTrue(rules.matches("infra/main.tf", "infra/*"))
        self.assertFalse(rules.matches("infra/modules/x.tf", "infra/*"))
        self.assertTrue(rules.matches("infra/modules/x.tf", "**/*.tf"))

    def test_pattern_without_slash_matches_file_name_anywhere(self):
        self.assertTrue(rules.matches("deep/dir/Dockerfile", "Dockerfile"))


class FixGuardsTest(unittest.TestCase):
    def check(self, changes, added=None):
        return rules.check_fix(changes, added or {}, RISKY)

    def test_clean_fix_passes_every_guard(self):
        results = self.check([Change("M", "src/calc.py"), Change("A", "tests/test_calc.py")],
                             {"src/calc.py": ["    return a - b"], "tests/test_calc.py": ["def test_sub(): ..."]})
        self.assertTrue(rules.guards_passed(results))

    def test_deleted_test_file_is_rejected(self):
        for path in ["tests/test_calc.py", "src/calc_test.go", "web/app.spec.ts", "src/__tests__/a.js", "CalcTests.cs"]:
            with self.subTest(path):
                results = self.check([Change("D", path)])
                self.assertFalse(guard("no deleted tests", results).ok)
                self.assertFalse(rules.guards_passed(results))

    def test_deleted_non_test_file_is_allowed(self):
        self.assertTrue(guard("no deleted tests", self.check([Change("D", "src/old.py")])).ok)

    def test_added_skip_markers_are_rejected(self):
        for line in ["@pytest.mark.skip(reason='flaky')", "    it.skip('works', () => {})", "xit('works')",
                     "describe.skip('suite')", "@unittest.skip('later')", "        self.skipTest('x')",
                     "    pytest.skip('x')", "\tt.Skip(\"later\")", "@Disabled", "[Ignore]", "[Fact(Skip = \"x\")]",
                     "@pytest.mark.xfail"]:
            with self.subTest(line):
                results = self.check([Change("M", "tests/test_a.py")], {"tests/test_a.py": [line]})
                self.assertFalse(guard("no skip markers", results).ok)

    def test_words_like_skip_in_normal_code_are_fine(self):
        results = self.check([Change("M", "src/a.py")], {"src/a.py": ["skip_count = 0", "def skipper(): pass"]})
        self.assertTrue(guard("no skip markers", results).ok)

    def test_ci_config_change_is_rejected(self):
        for path in [".github/workflows/ci.yml", ".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml"]:
            with self.subTest(path):
                self.assertFalse(guard("no CI config changes", self.check([Change("M", path)])).ok)

    def test_risky_path_is_rejected(self):
        results = self.check([Change("M", "app/auth/session.py")])
        self.assertFalse(guard("no risky paths", results).ok)
        self.assertIn("app/auth/session.py", guard("no risky paths", results).detail)

    def test_dependency_manifest_change_is_rejected(self):
        for path in ["package.json", "web/package-lock.json", "requirements-dev.txt", "pyproject.toml",
                     "go.mod", "Cargo.lock", "src/App/App.csproj"]:
            with self.subTest(path):
                self.assertFalse(guard("no dependency manifest changes", self.check([Change("M", path)])).ok)

    def test_guard_table_shows_failures(self):
        table = rules.guard_table(self.check([Change("D", "tests/test_x.py")]))
        self.assertIn("| no deleted tests | FAIL: tests/test_x.py |", table)
        self.assertIn("| no CI config changes | pass |", table)


class VerdictTest(unittest.TestCase):
    def test_small_safe_pr_auto_merges(self):
        v = rules.merge_verdict(212, ["src/a.py", "tests/test_a.py"], RISKY, "auto-low-risk")
        self.assertTrue(v.auto_merge)
        self.assertEqual(v.message, "Auto-merge: low risk (212 lines, no risky paths)")

    def test_manual_mode_holds(self):
        v = rules.merge_verdict(10, ["src/a.py"], RISKY, "manual")
        self.assertFalse(v.auto_merge)
        self.assertEqual(v.message, "Held for you: merge_mode is manual")

    def test_400_lines_or_more_holds(self):
        self.assertTrue(rules.merge_verdict(399, ["a.py"], RISKY, "auto-low-risk").auto_merge)
        v = rules.merge_verdict(400, ["a.py"], RISKY, "auto-low-risk")
        self.assertFalse(v.auto_merge)
        self.assertIn("400 changed lines", v.message)

    def test_manifest_or_risky_path_holds_with_reason(self):
        v = rules.merge_verdict(20, ["package.json", "db/migrations/0002.sql"], RISKY, "auto-low-risk")
        self.assertFalse(v.auto_merge)
        self.assertIn("changes dependency manifest package.json", v.message)
        self.assertIn("touches db/migrations/0002.sql", v.message)


class RecordTest(unittest.TestCase):
    BODY = ('Closes #8\nTrace: ticket #8 "x" -> spec #6 "y" -> docs PR #7\nStarted by @me on 2026-10-14\n')

    def test_trace_present(self):
        self.assertEqual(rules.trace_problems(self.BODY), [])
        self.assertEqual(rules.linked_numbers(self.BODY), {"ticket": 8, "spec": 6, "docs_pr": 7})

    def test_trace_missing_parts(self):
        self.assertEqual(rules.trace_problems("Fixes a bug"), ["`Closes #N`", "the `Trace:` line"])
        self.assertEqual(rules.trace_problems("Fixes #3\nno trace"), ["the `Trace:` line"])

    def test_review_result_uses_last_line(self):
        self.assertEqual(rules.parse_review_result("x\nREVIEW_RESULT: blocking=0\n...\nREVIEW_RESULT: blocking=2"), 2)
        self.assertIsNone(rules.parse_review_result("no result line"))

    def test_needs_decision_questions(self):
        self.assertEqual(rules.needs_decision_questions("a\nNEEDS_DECISION: drop the test?\nb"), ["drop the test?"])


if __name__ == "__main__":
    unittest.main()
