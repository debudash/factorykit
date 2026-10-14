"""Tests for the factory router. Run: python -m unittest discover -s tests -v"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "factory" / "router"))
import router as r  # noqa: E402


class FakeGitHub:
    def __init__(self):
        self.prs, self.runs, self.logs = [], {}, {}
        self.reviews_, self.inline, self.conv = {}, {}, {}
        self.labels_added, self.comments = [], []

    def open_prs(self, label):
        return [p for p in self.prs if not label or label in {l["name"] for l in p["labels"]}]

    def runs_for(self, branch):
        return self.runs.get(branch, [])

    def failed_log(self, run_id):
        return self.logs.get(run_id, "boom")

    def reviews(self, n):
        return self.reviews_.get(n, [])

    def review_comments(self, n):
        return self.inline.get(n, [])

    def issue_comments(self, n):
        return self.conv.get(n, [])

    def add_label(self, n, label):
        self.labels_added.append((n, label))
        for p in self.prs:
            if p["number"] == n:
                p["labels"].append({"name": label})

    def comment(self, n, body):
        self.comments.append((n, body))


class FakeHandle:
    def __init__(self):
        self.rc = None
        self.terminated = False

    def poll(self):
        return self.rc

    def terminate(self):
        self.terminated = True


class FakeSpawner:
    def __init__(self):
        self.calls = []

    def spawn(self, cmd, cwd, out_path, err_path):
        h = FakeHandle()
        self.calls.append({"cmd": cmd, "cwd": cwd, "out": out_path, "handle": h})
        return h

    def finish(self, i, result="done", rc=0, is_error=False):
        call = self.calls[i]
        call["out"].write_text(json.dumps({"result": result, "is_error": is_error, "total_cost_usd": 0.12}))
        call["handle"].rc = rc


def pr(n=1, branch="idea/notify", sha="abc", labels=("factory",)):
    return {"number": n, "title": "t", "headRefName": branch, "headRefOid": sha,
            "isDraft": False, "labels": [{"name": l} for l in labels], "url": ""}


def human(login="alice"):
    return {"login": login, "type": "User"}


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gh, self.sp = FakeGitHub(), FakeSpawner()
        self.owners = {"idea/notify": self.root / "wt-notify", "fix/bug": self.root / "wt-bug"}
        self.cfg = r.Config(baseline_existing=False)

    def tearDown(self):
        self.tmp.cleanup()

    def router(self, cfg=None):
        return r.Router(cfg or self.cfg, self.root, self.gh, self.sp,
                        owners_fn=lambda _: self.owners, echo=False)

    def failing_run(self, run_id=101, sha="abc"):
        return {"databaseId": run_id, "status": "completed", "conclusion": "failure",
                "headSha": sha, "workflowName": "ci", "url": "u"}

    # ---- CI routing

    def test_ci_failure_dispatches_once_to_owner(self):
        self.gh.prs = [pr()]
        self.gh.runs["idea/notify"] = [self.failing_run()]
        rt = self.router()
        rt.cycle()
        self.assertEqual(len(self.sp.calls), 1)
        self.assertEqual(self.sp.calls[0]["cwd"], self.owners["idea/notify"])
        self.assertIn("ci:101", self.sp.calls[0]["cmd"][2])
        self.sp.finish(0)
        rt.cycle()
        self.assertEqual(len(self.sp.calls), 1, "same failed run must not be routed twice")
        self.assertTrue(any("Factory router" in body for _, body in self.gh.comments))

    def test_ci_failure_on_old_commit_is_ignored(self):
        self.gh.prs = [pr(sha="new")]
        self.gh.runs["idea/notify"] = [self.failing_run(sha="old")]
        self.router().cycle()
        self.assertEqual(self.sp.calls, [])

    def test_ci_budget_exhaustion_escalates(self):
        self.cfg.max_ci_attempts = 1
        self.gh.prs = [pr()]
        self.gh.runs["idea/notify"] = [self.failing_run(101)]
        rt = self.router()
        rt.cycle()
        self.sp.finish(0)
        self.gh.prs[0]["headRefOid"] = "def"
        self.gh.runs["idea/notify"] = [self.failing_run(102, sha="def")]
        rt.cycle()
        self.assertEqual(len(self.sp.calls), 1)
        self.assertIn((1, "needs-decision"), self.gh.labels_added)

    def test_ci_green_resets_budget(self):
        self.cfg.max_ci_attempts = 1
        self.gh.prs = [pr()]
        self.gh.runs["idea/notify"] = [self.failing_run(101)]
        rt = self.router()
        rt.cycle()
        self.sp.finish(0)
        self.gh.prs[0]["headRefOid"] = "green"
        self.gh.runs["idea/notify"] = [{"databaseId": 103, "status": "completed", "conclusion": "success",
                                        "headSha": "green", "workflowName": "ci", "url": "u"}]
        rt.cycle()
        self.assertEqual(rt.state["attempts"]["1"]["ci"], 0)

    # ---- review routing and filters

    def test_review_filters(self):
        self.gh.prs = [pr()]
        self.gh.conv[1] = [
            {"id": 1, "user": human(), "body": "/agent rename this function"},
            {"id": 2, "user": human(), "body": "looks nice"},
            {"id": 3, "user": {"login": "lint[bot]", "type": "Bot"}, "body": "/fix everything"},
            {"id": 4, "user": human(), "body": r.MARKER + "\n/agent loop"},
            {"id": 5, "user": human(), "body": "Null check missing [blocking]"},
        ]
        self.router().cycle()
        prompt = self.sp.calls[0]["cmd"][2]
        self.assertIn("review:conversation:1", prompt)
        self.assertIn("review:conversation:5", prompt)
        for skipped in ("conversation:2", "conversation:3", "conversation:4"):
            self.assertNotIn(skipped, prompt)

    def test_changes_requested_routes_its_inline_comments(self):
        self.gh.prs = [pr()]
        self.gh.reviews_[1] = [{"id": 9, "state": "CHANGES_REQUESTED", "body": "", "user": human()}]
        self.gh.inline[1] = [
            {"id": 21, "pull_request_review_id": 9, "user": human(), "body": "off by one", "path": "a.py", "line": 4},
            {"id": 22, "pull_request_review_id": 8, "user": human(), "body": "nit", "path": "b.py", "line": 1},
        ]
        self.router().cycle()
        prompt = self.sp.calls[0]["cmd"][2]
        self.assertIn("review:inline:21", prompt)
        self.assertIn("a.py", prompt)
        self.assertNotIn("review:inline:22", prompt)
        self.assertNotIn("review:review:9", prompt, "empty review with inline comments is not a separate item")

    def test_allowlist_and_allowed_bot(self):
        self.cfg.reviewer_allowlist = ["lead"]
        self.cfg.allow_bot_authors = ["reviewer[bot]"]
        self.gh.prs = [pr()]
        self.gh.conv[1] = [
            {"id": 1, "user": human("alice"), "body": "/agent do x"},
            {"id": 2, "user": human("lead"), "body": "/agent do y"},
            {"id": 3, "user": {"login": "reviewer[bot]", "type": "Bot"}, "body": "[blocking] leak"},
        ]
        self.router().cycle()
        prompt = self.sp.calls[0]["cmd"][2]
        self.assertNotIn("conversation:1", prompt)
        self.assertIn("conversation:2", prompt)
        self.assertIn("conversation:3", prompt)

    def test_baseline_skips_existing_comments(self):
        cfg = r.Config(baseline_existing=True)
        self.gh.prs = [pr()]
        self.gh.conv[1] = [{"id": 1, "user": human(), "body": "/agent old request"}]
        rt = self.router(cfg)
        rt.cycle()
        self.assertEqual(self.sp.calls, [])
        self.gh.conv[1].append({"id": 2, "user": human(), "body": "/agent new request"})
        rt.cycle()
        self.assertIn("conversation:2", self.sp.calls[0]["cmd"][2])
        self.assertNotIn("conversation:1", self.sp.calls[0]["cmd"][2])

    # ---- ownership, concurrency, escalation

    def test_busy_owner_is_not_double_dispatched(self):
        self.gh.prs = [pr()]
        self.gh.conv[1] = [{"id": 1, "user": human(), "body": "/agent a"}]
        rt = self.router()
        rt.cycle()
        self.gh.conv[1].append({"id": 2, "user": human(), "body": "/agent b"})
        rt.cycle()
        self.assertEqual(len(self.sp.calls), 1)
        self.sp.finish(0)
        rt.cycle()
        self.assertEqual(len(self.sp.calls), 2)
        self.assertIn("conversation:2", self.sp.calls[1]["cmd"][2])

    def test_no_local_worktree_means_no_dispatch(self):
        self.gh.prs = [pr(branch="someone/else")]
        self.gh.conv[1] = [{"id": 1, "user": human(), "body": "/agent a"}]
        self.router().cycle()
        self.assertEqual(self.sp.calls, [])

    def test_concurrency_cap(self):
        self.cfg.max_concurrent = 1
        self.gh.prs = [pr(1, "idea/notify"), pr(2, "fix/bug")]
        self.gh.conv[1] = [{"id": 1, "user": human(), "body": "/agent a"}]
        self.gh.conv[2] = [{"id": 2, "user": human(), "body": "/agent b"}]
        self.router().cycle()
        self.assertEqual(len(self.sp.calls), 1)

    def test_needs_decision_escalates_and_pauses(self):
        self.gh.prs = [pr()]
        self.gh.conv[1] = [{"id": 1, "user": human(), "body": "/agent pick a queue"}]
        rt = self.router()
        rt.cycle()
        self.sp.finish(0, result="NEEDS_DECISION: at-least-once or exactly-once delivery?")
        self.gh.conv[1].append({"id": 2, "user": human(), "body": "/agent another"})
        rt.cycle()
        self.assertIn((1, "needs-decision"), self.gh.labels_added)
        self.assertEqual(len(self.sp.calls), 1, "paused while label present")
        self.assertTrue(any("exactly-once" in body for _, body in self.gh.comments))

    def test_clearing_label_resumes_and_resets_budget(self):
        self.gh.prs = [pr()]
        self.gh.conv[1] = [{"id": 1, "user": human(), "body": "/agent a"}]
        rt = self.router()
        rt.cycle()
        self.sp.finish(0, rc=1)
        rt.cycle()
        self.assertIn("1", rt.state["escalated"])
        self.gh.prs[0]["labels"] = [{"name": "factory"}]
        self.gh.conv[1].append({"id": 2, "user": human(), "body": "/agent b"})
        rt.cycle()
        self.assertNotIn("1", rt.state["escalated"])
        self.assertEqual(len(self.sp.calls), 2)

    def test_timeout_terminates_and_escalates(self):
        self.cfg.max_run_minutes = 0
        self.gh.prs = [pr()]
        self.gh.conv[1] = [{"id": 1, "user": human(), "body": "/agent a"}]
        rt = self.router()
        rt.cycle()
        rt.cycle()
        self.assertTrue(self.sp.calls[0]["handle"].terminated)
        self.assertIn((1, "needs-decision"), self.gh.labels_added)

    def test_state_survives_restart(self):
        self.gh.prs = [pr()]
        self.gh.conv[1] = [{"id": 1, "user": human(), "body": "/agent a"}]
        self.router().cycle()
        self.sp.finish(0)
        rt2 = self.router()  # new process picks up the detached run from state
        self.assertEqual(len(rt2.running), 1)
        rt2.cycle()
        self.assertEqual(len(rt2.running), 0)
        self.assertEqual(len(self.sp.calls), 1)

    def test_draft_and_unlabeled_ignored(self):
        p = pr()
        p["isDraft"] = True
        self.gh.prs = [p, pr(2, "fix/bug", labels=())]
        self.gh.conv[1] = [{"id": 1, "user": human(), "body": "/agent a"}]
        self.gh.conv[2] = [{"id": 2, "user": human(), "body": "/agent b"}]
        self.router().cycle()
        self.assertEqual(self.sp.calls, [])


class HelperTests(unittest.TestCase):
    def test_parse_multi_json(self):
        self.assertEqual(r.parse_multi_json('[1,2]\n[3]'), [1, 2, 3])
        self.assertEqual(r.parse_multi_json(""), [])

    def test_parse_worktrees(self):
        text = ("worktree /repo\nHEAD a\nbranch refs/heads/main\n\n"
                "worktree /wt/notify\nHEAD b\nbranch refs/heads/idea/notify\n\n"
                "worktree /wt/detached\nHEAD c\ndetached\n")
        self.assertEqual(r.parse_worktrees(text),
                         {"main": Path("/repo"), "idea/notify": Path("/wt/notify")})

    def test_command_shape(self):
        cmd = r.build_command(r.Config(), "PROMPT", "idea/notify")
        self.assertEqual(cmd[:3], ["claude", "-p", "PROMPT"])
        self.assertIn("--fork-session", cmd)
        self.assertIn("--continue", cmd)
        rules = cmd[cmd.index("--append-system-prompt") + 1]
        self.assertIn("idea/notify", rules)
        self.assertNotIn("--continue", r.build_command(r.Config(session="new"), "P", "b"))

    def test_config_rejects_unknown_keys(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write("[routing]\ntrigger_prefixs = ['/x']\n")
        with self.assertRaises(ValueError):
            r.Config.load(Path(f.name))

    def test_shipped_config_loads(self):
        cfg = r.Config.load(r.ROUTER_DIR / "config.toml")
        self.assertEqual(cfg.max_concurrent, 3)


if __name__ == "__main__":
    unittest.main()
