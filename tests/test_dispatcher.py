import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dispatcher import core  # noqa: E402
from dispatcher.rules import Change  # noqa: E402

FACTORY_MD = """# settings
```toml
risky_paths = ["**/migrations/**"]
max_parallel = 2
reviewer_model = "opus"
[verify]
test = "python -m unittest"
```
"""
BODY = 'Closes #8\nTrace: ticket #8 "t" -> spec #6 "s" -> docs PR #7\nStarted by @me on 2026-10-14 from ticket #8\n'


class FakeGitHub:
    def __init__(self):
        self.prs, self.checks_, self.files, self.logs, self.branch_prs = [], {}, {}, {}, {}
        self.comments, self.reviews, self.statuses, self.labels_added, self.auto_merged = [], [], [], [], []

    def open_prs(self):
        return self.prs

    def checks(self, n):
        return self.checks_.get(n, ("green", []))

    def changed_files(self, n):
        return self.files.get(n, ["src/a.py"])

    def issue_text(self, n):
        return f"#{n} issue text"

    def failed_log(self, run_id):
        return self.logs.get(run_id, "Traceback: boom")

    def pr_for_branch(self, branch):
        return self.branch_prs.get(branch)

    def comment(self, n, body):
        self.comments.append((n, body))

    def review(self, n, body):
        self.reviews.append((n, body))

    def set_review_status(self, sha, success, description):
        self.statuses.append((sha, success, description))

    def add_label(self, n, label):
        self.labels_added.append((n, label))
        for p in self.prs:
            if p["number"] == n:
                p["labels"].append({"name": label})

    def enable_auto_merge(self, n):
        self.auto_merged.append(n)


class FakeGit:
    def __init__(self):
        self.factory_md = FACTORY_MD
        self.remote = {}
        self.added, self.removed, self.pushed = [], [], []
        self.fix = {"commits": ["abc1234 Fix it"], "changes": [Change("M", "src/a.py")], "added": {"src/a.py": ["x"]}}
        self.push_ok = (True, "")
        self.trees, self.dirty, self.builder_removed = [], set(), []

    def fetch(self):
        pass

    def show(self, ref, path):
        return self.factory_md

    def merge_base(self, a, b):
        return "base000"

    def diff(self, a, b):
        return "diff --git a/src/a.py b/src/a.py\n+x"

    def diff_stat(self, a, b):
        return " src/a.py | 1 +"

    def remote_head(self, branch):
        return self.remote.get(branch)

    def add_worktree(self, path, ref):
        Path(path).mkdir(parents=True, exist_ok=True)
        self.added.append((Path(path), ref))

    def remove_worktree(self, path):
        self.removed.append(Path(path))

    def commits(self, base, cwd):
        return self.fix["commits"]

    def changes(self, base, cwd):
        return self.fix["changes"]

    def added_lines(self, base, cwd):
        return self.fix["added"]

    def push(self, cwd, branch):
        self.pushed.append(branch)
        return self.push_ok

    def worktrees(self):
        return self.trees

    def has_tracked_changes(self, path):
        return Path(path).name in self.dirty

    def remove_builder_worktree(self, path, branch):
        self.builder_removed.append((Path(path).name, branch))


class FakeHandle:
    def __init__(self):
        self.rc, self.terminated = None, False

    def poll(self):
        return self.rc

    def terminate(self):
        self.terminated = True


class FakeSpawner:
    def __init__(self):
        self.calls = []

    def spawn(self, cmd, cwd, prompt_path, out_path, err_path):
        h = FakeHandle()
        self.calls.append({"cmd": cmd, "cwd": cwd, "prompt": Path(prompt_path).read_text(encoding="utf-8"),
                           "out": Path(out_path), "handle": h})
        return h

    def finish(self, i, result, rc=0, cost=0.25, is_error=False):
        c = self.calls[i]
        c["out"].write_text(json.dumps({"result": result, "total_cost_usd": cost, "is_error": is_error}),
                            encoding="utf-8")
        c["handle"].rc = rc

    def kind(self, i):
        return "review" if "--agent" in self.calls[i]["cmd"] else "fix"


def pr(n=9, sha="sha1", labels=(), draft=False, body=BODY, branch="agent/8-x", additions=10, deletions=2):
    return {"number": n, "title": f"PR {n}", "headRefName": branch, "headRefOid": sha, "baseRefName": "main",
            "isDraft": draft, "labels": [{"name": l} for l in labels], "body": body, "url": f"https://x/pull/{n}",
            "additions": additions, "deletions": deletions}


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "factory"
        self.paths = {"alpha": self.tmp / "alpha", "beta": self.tmp / "beta"}
        self.gh = {p: FakeGitHub() for p in self.paths.values()}
        self.git = {p: FakeGit() for p in self.paths.values()}
        self.sp = FakeSpawner()
        self.now = [1000.0]
        self.registry = self.tmp / "projects.toml"
        self.set_registry(alpha="ci_and_review")
        self.out = []

    def set_registry(self, merge_mode="auto-low-risk", **auto_fix):
        text = ""
        for name, mode in auto_fix.items():
            text += (f'[{name}]\npath = "{self.paths[name].as_posix()}"\nauto_fix = "{mode}"\n'
                     f'merge_mode = "{merge_mode}"\n\n')
        self.registry.write_text(text, encoding="utf-8")

    def dispatcher(self, dry_run=False):
        return core.Dispatcher(self.registry, self.home, lambda p: self.gh[Path(p)], lambda p: self.git[Path(p)],
                               self.sp, dry_run=dry_run, out=self.out.append, clock=lambda: self.now[0])

    @property
    def a(self):
        return self.gh[self.paths["alpha"]]

    @property
    def ag(self):
        return self.git[self.paths["alpha"]]

    def review_round(self, d, i, blocking, sha="sha1"):
        """Run cycle until review i is started, then finish it with the given blocking count."""
        self.sp.finish(i, f"### Standards\n- [blocking] x\nREVIEW_RESULT: blocking={blocking}")
        d.cycle()

    # ---- skipping and record checks
    def test_draft_and_no_dispatch_prs_are_ignored(self):
        self.a.prs = [pr(1, draft=True), pr(2, labels=["no-dispatch"])]
        self.dispatcher().cycle()
        self.assertEqual(self.sp.calls, [])
        self.assertEqual(self.a.comments, [])

    def test_missing_trace_is_flagged_once(self):
        self.a.prs = [pr(body="did stuff")]
        d = self.dispatcher()
        d.cycle()
        d.cycle()
        flags = [b for _, b in self.a.comments if "missing" in b]
        self.assertEqual(len(flags), 1)
        self.assertIn("`Closes #N` and the `Trace:` line", flags[0])

    # ---- review
    def test_ready_pr_gets_reviewer_with_repo_model_in_temp_worktree(self):
        self.a.prs = [pr()]
        self.dispatcher().cycle()
        call = self.sp.calls[0]
        self.assertIn("--agent", call["cmd"])
        self.assertEqual(call["cmd"][call["cmd"].index("--model") + 1], "opus")
        self.assertIn("Edit", call["cmd"][call["cmd"].index("--disallowedTools") + 1])
        self.assertIn("Merge-base with main: base000", call["prompt"])
        self.assertIn("#8 issue text", call["prompt"])
        self.assertEqual(self.ag.added[0][1], "sha1")
        self.assertEqual(call["cwd"], self.ag.added[0][0])

    def test_review_is_posted_as_round_1_of_2_with_status_and_cost(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=0)
        n, body = self.a.reviews[0]
        self.assertIn("FactoryKit review: Round 1 of 2", body)
        self.assertIn("AI-generated", body)
        self.assertIn("$0.25", body)
        self.assertEqual(self.a.statuses, [("sha1", True, "Round 1: no blocking findings")])
        self.assertIn(self.ag.added[0][0], self.ag.removed)

    def test_blocking_review_sets_failing_status(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=2)
        self.assertEqual(self.a.statuses[0][1], False)

    def test_one_run_per_pr_at_a_time(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.a.prs[0]["headRefOid"] = "sha2"
        d.cycle()
        self.assertEqual(len(self.sp.calls), 1)

    def test_unreadable_review_escalates(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.sp.finish(0, "I reviewed it, looks fine")
        d.cycle()
        self.assertIn((9, "needs-decision"), self.a.labels_added)
        self.assertEqual(self.a.reviews, [])

    def test_round_2_reviews_only_new_commits_and_earlier_items(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=1)       # round 1 blocks -> fix starts
        self.ag.remote["agent/8-x"] = "sha1"
        self.sp.finish(1, "ADDRESSED 1: fixed")
        self.a.prs[0]["headRefOid"] = "sha2"       # the pushed fix
        d.cycle()
        d.cycle()
        prompt = self.sp.calls[2]["prompt"]
        self.assertIn("Round 2: review only the commits since the previous review", prompt)
        self.assertIn("Previous review (round 1, commit sha1)", prompt)

    def test_two_rounds_with_blockers_escalate(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=1)
        self.ag.remote["agent/8-x"] = "sha1"
        self.sp.finish(1, "done")
        self.a.prs[0]["headRefOid"] = "sha2"
        d.cycle()                                  # fix pushed, round 2 starts
        self.review_round(d, 2, blocking=1, sha="sha2")
        d.cycle()
        self.assertIn((9, "needs-decision"), self.a.labels_added)
        self.assertTrue(any("2 review rounds still have blocking findings" in b for _, b in self.a.comments))
        self.assertEqual(len(self.sp.calls), 3, "no third fix")

    # ---- auto_fix modes
    def test_blocking_review_with_ci_and_review_starts_guarded_fix(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=1)
        self.assertEqual(self.sp.kind(1), "fix")
        cmd = self.sp.calls[1]["cmd"]
        self.assertIn("Bash(git push *)", cmd[cmd.index("--disallowedTools") + 1])
        self.assertIn("Bash(python *)", cmd[cmd.index("--allowedTools") + 1])
        self.assertIn("Blocking review findings (round 1)", self.sp.calls[1]["prompt"])

    def test_auto_fix_off_posts_address_feedback_once(self):
        self.set_registry(alpha="off")
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=1)
        d.cycle()
        notes = [b for _, b in self.a.comments if "/address-feedback 9" in b]
        self.assertEqual(len(notes), 1)
        self.assertEqual(len(self.sp.calls), 1)

    def test_auto_fix_ci_fixes_ci_but_not_review_findings(self):
        self.set_registry(alpha="ci")
        self.a.prs = [pr()]
        self.a.checks_[9] = ("failed", [{"name": "ci", "run_id": 55, "url": "u"}])
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=1)
        self.assertEqual(self.sp.kind(1), "fix")
        prompt = self.sp.calls[1]["prompt"]
        self.assertIn("CI failure: ci", prompt)
        self.assertIn("Traceback: boom", prompt)
        self.assertNotIn("Blocking review findings", prompt)
        self.assertTrue(any("blocking review findings" in b and "/address-feedback" in b for _, b in self.a.comments))

    def test_three_ci_fix_attempts_then_escalate(self):
        self.a.prs = [pr()]
        self.a.checks_[9] = ("failed", [{"name": "ci", "run_id": 55, "url": "u"}])
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=0)
        for attempt in range(3):
            sha = f"fix{attempt}"
            self.ag.remote["agent/8-x"] = self.a.prs[0]["headRefOid"]
            self.sp.finish(len(self.sp.calls) - 1, "done")      # the fix
            self.a.prs[0]["headRefOid"] = sha
            d.cycle()                                           # pushes, starts review of new head
            self.review_round(d, len(self.sp.calls) - 1, blocking=0)
        self.assertEqual(sum(self.sp.kind(i) == "fix" for i in range(len(self.sp.calls))), 3)
        d.cycle()
        self.assertIn((9, "needs-decision"), self.a.labels_added)
        self.assertTrue(any("after 3 automatic fix attempts" in b for _, b in self.a.comments))

    def test_global_cap_of_two_concurrent_fixes_across_projects(self):
        self.set_registry(alpha="ci", beta="ci")
        b = self.gh[self.paths["beta"]]
        self.a.prs = [pr(1, branch="b1"), pr(2, branch="b2")]
        b.prs = [pr(3, branch="b3")]
        for g in (self.a, b):
            for p in g.prs:
                g.checks_[p["number"]] = ("failed", [{"name": "ci", "run_id": 1, "url": "u"}])
        d = self.dispatcher()
        d.cycle()
        for i in range(3):
            self.sp.finish(i, "REVIEW_RESULT: blocking=0")
        d.cycle()
        fixes = [i for i in range(len(self.sp.calls)) if self.sp.kind(i) == "fix"]
        self.assertEqual(len(fixes), 2)

    # ---- fix completion and guards
    def start_fix(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=1)
        self.ag.remote["agent/8-x"] = "sha1"
        return d

    def test_fix_passing_guards_is_pushed_and_recorded(self):
        d = self.start_fix()
        self.sp.finish(1, "ADDRESSED finding: fixed", cost=0.4)
        d.cycle()
        self.assertEqual(self.ag.pushed, ["agent/8-x"])
        body = [b for _, b in self.a.comments if "auto_fix" in b][-1]
        self.assertIn("mode `ci_and_review`", body)
        self.assertIn("abc1234 Fix it", body)
        self.assertIn("| no risky paths | pass |", body)
        self.assertIn("$0.40", body)

    def test_each_guard_failure_blocks_the_push_and_escalates(self):
        bad_fixes = {
            "no deleted tests": ([Change("D", "tests/test_a.py")], {}),
            "no skip markers": ([Change("M", "tests/test_a.py")], {"tests/test_a.py": ["@pytest.mark.skip"]}),
            "no CI config changes": ([Change("M", ".github/workflows/ci.yml")], {}),
            "no risky paths": ([Change("M", "db/migrations/1.sql")], {}),
            "no dependency manifest changes": ([Change("M", "requirements.txt")], {}),
        }
        for name, (changes, added) in bad_fixes.items():
            with self.subTest(name):
                self.setUp()
                d = self.start_fix()
                self.ag.fix.update(changes=changes, added=added)
                self.sp.finish(1, "done")
                d.cycle()
                self.assertEqual(self.ag.pushed, [])
                self.assertIn((9, "needs-decision"), self.a.labels_added)
                body = [b for _, b in self.a.comments if "not pushed" in b][-1]
                self.assertIn(f"| {name} | FAIL", body)

    def test_fix_agent_needs_decision_is_escalated_without_push(self):
        d = self.start_fix()
        self.sp.finish(1, "NEEDS_DECISION: the test is wrong, delete it?")
        d.cycle()
        self.assertEqual(self.ag.pushed, [])
        self.assertTrue(any("delete it?" in b for _, b in self.a.comments))

    def test_fix_without_commits_is_escalated(self):
        d = self.start_fix()
        self.ag.fix["commits"] = []
        self.sp.finish(1, "could not fix")
        d.cycle()
        self.assertEqual(self.ag.pushed, [])
        self.assertTrue(any("made no commits" in b for _, b in self.a.comments))

    def test_branch_moved_during_fix_is_not_pushed(self):
        d = self.start_fix()
        self.ag.remote["agent/8-x"] = "someone-else"
        self.sp.finish(1, "done")
        d.cycle()
        self.assertEqual(self.ag.pushed, [])
        self.assertTrue(any("branch moved while the fix ran" in b for _, b in self.a.comments))

    def test_rejected_push_is_escalated(self):
        d = self.start_fix()
        self.ag.push_ok = (False, "rejected: non-fast-forward")
        self.sp.finish(1, "done")
        d.cycle()
        self.assertTrue(any("push was rejected" in b for _, b in self.a.comments))

    # ---- settings reload
    def test_running_fix_finishes_guarded_after_auto_fix_is_switched_off(self):
        d = self.start_fix()                      # fix running under ci_and_review
        self.set_registry(alpha="off")            # owner switches auto_fix off mid-build
        self.sp.finish(1, "done")
        d.cycle()
        self.assertEqual(self.ag.pushed, ["agent/8-x"])
        self.assertTrue(any("| no deleted tests | pass |" in b for _, b in self.a.comments))

    def test_nothing_new_starts_under_the_old_auto_fix_value(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()                                 # review running under ci_and_review
        self.set_registry(alpha="off")
        self.review_round(d, 0, blocking=1)       # findings arrive after the switch
        self.assertEqual(len(self.sp.calls), 1, "no fix starts after switching to off")
        self.assertTrue(any("/address-feedback 9" in b for _, b in self.a.comments))

    def test_new_project_in_registry_is_picked_up_next_poll(self):
        b = self.gh[self.paths["beta"]]
        b.prs = [pr(3)]
        d = self.dispatcher()
        d.cycle()
        self.assertEqual(len(self.sp.calls), 0)
        self.set_registry(alpha="ci_and_review", beta="ci")
        d.cycle()
        self.assertEqual(len(self.sp.calls), 1)

    # ---- merge verdict
    def pass_review(self, **pr_kw):
        self.a.prs = [pr(**pr_kw)]
        d = self.dispatcher()
        d.cycle()
        self.review_round(d, 0, blocking=0)
        return d

    def test_low_risk_pr_gets_auto_merge(self):
        d = self.pass_review()
        self.assertEqual(self.a.auto_merged, [9])
        self.assertIn("Auto-merge: low risk (12 lines, no risky paths)", self.a.comments[-1][1])
        d.cycle()
        self.assertEqual(len([b for _, b in self.a.comments if "Auto-merge" in b]), 1, "verdict once per head")
        self.assertEqual(d.state["auto_merges"][0]["pr"], "alpha#9")
        self.assertEqual(d.state["prs"]["alpha#9"]["verdict"]["auto"], True)

    def test_risky_pr_is_held_with_reason(self):
        self.a.files[9] = ["db/migrations/2.sql"]
        self.pass_review()
        self.assertEqual(self.a.auto_merged, [])
        self.assertIn("Held for you: touches db/migrations/2.sql", self.a.comments[-1][1])

    def test_large_pr_is_held(self):
        self.pass_review(additions=390, deletions=20)
        self.assertEqual(self.a.auto_merged, [])
        self.assertIn("410 changed lines", self.a.comments[-1][1])

    def test_manual_merge_mode_holds(self):
        self.set_registry(merge_mode="manual", alpha="ci_and_review")
        self.pass_review()
        self.assertEqual(self.a.auto_merged, [])
        self.assertIn("Held for you: merge_mode is manual", self.a.comments[-1][1])

    def test_no_verdict_while_ci_pending(self):
        self.a.checks_[9] = ("pending", [])
        self.pass_review()
        self.assertFalse(any("Auto-merge" in b or "Held" in b for _, b in self.a.comments))

    # ---- escalation and resume
    def test_needs_decision_label_pauses_and_removal_resumes(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.sp.finish(0, "garbage")               # unreadable review -> escalated
        d.cycle()
        self.a.prs[0]["headRefOid"] = "sha2"
        d.cycle()
        self.assertEqual(len(self.sp.calls), 1, "paused while labelled")
        self.a.prs[0]["labels"] = []                # owner removes the label
        d.cycle()
        self.assertEqual(len(self.sp.calls), 2)
        self.assertIn("First review", self.sp.calls[1]["prompt"], "limits reset: round 1 again")

    def test_run_over_time_limit_is_stopped_and_escalated(self):
        self.a.prs = [pr()]
        d = self.dispatcher()
        d.cycle()
        self.now[0] += core.MAX_RUN_MINUTES * 60 + 1
        d.cycle()
        self.assertTrue(self.sp.calls[0]["handle"].terminated)
        self.assertIn((9, "needs-decision"), self.a.labels_added)

    def test_running_review_survives_restart(self):
        self.a.prs = [pr()]
        self.dispatcher().cycle()
        self.sp.finish(0, "REVIEW_RESULT: blocking=0")
        d2 = self.dispatcher()                      # new process
        d2.cycle()
        self.assertEqual(len(self.a.reviews), 1)
        self.assertEqual(len(self.sp.calls), 1)

    def test_dry_run_changes_nothing(self):
        self.a.prs = [pr(body="no trace")]
        d = self.dispatcher(dry_run=True)
        d.cycle()
        self.assertEqual(self.sp.calls, [])
        self.assertEqual(self.a.comments, [])
        self.assertEqual(self.ag.added, [])
        self.assertFalse((self.home / "state" / "dispatcher.json").exists())
        self.assertTrue(any("would start review" in l for l in self.out))

    # ---- builder worktree cleanup (ADR 0016)
    def test_merged_builder_worktree_is_removed(self):
        wt = self.paths["alpha"] / ".claude" / "worktrees"
        self.ag.trees = [
            {"path": wt / "agent-merged", "head": "h1", "branch": "agent/1-a", "locked": False},
            {"path": wt / "agent-open", "head": "h2", "branch": "agent/2-b", "locked": False},
            {"path": wt / "agent-unpushed", "head": "local", "branch": "agent/3-c", "locked": False},
            {"path": wt / "agent-dirty", "head": "h4", "branch": "agent/4-d", "locked": False},
            {"path": wt / "agent-locked", "head": "h5", "branch": "agent/5-e", "locked": True},
            {"path": self.paths["alpha"], "head": "m", "branch": "main", "locked": False},
        ]
        self.ag.dirty = {"agent-dirty"}
        self.a.branch_prs = {
            "agent/1-a": {"number": 1, "state": "MERGED", "headRefOid": "h1"},
            "agent/2-b": {"number": 2, "state": "OPEN", "headRefOid": "h2"},
            "agent/3-c": {"number": 3, "state": "MERGED", "headRefOid": "pushed"},
            "agent/4-d": {"number": 4, "state": "CLOSED", "headRefOid": "h4"},
            "agent/5-e": {"number": 5, "state": "MERGED", "headRefOid": "h5"},
            "main": {"number": 6, "state": "MERGED", "headRefOid": "m"},
        }
        self.dispatcher().cycle()
        self.assertEqual(self.ag.builder_removed, [("agent-merged", "agent/1-a")])


if __name__ == "__main__":
    unittest.main()
