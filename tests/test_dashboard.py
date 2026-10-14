import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dispatcher.dashboard import board as b  # noqa: E402
from dispatcher.dashboard import server  # noqa: E402
from dispatcher.settings import Project  # noqa: E402

ALPHA = Project("alpha", Path("/code/alpha"), "ci_and_review", "auto-low-risk")
BETA = Project("beta", Path("/code/beta"), "off", "manual")


def issue(n, labels=(), title="Ticket", subs=0):
    return {"number": n, "title": title, "labels": [{"name": l} for l in labels], "url": f"https://x/issues/{n}",
            "subIssuesSummary": {"total": subs}}


def pr(n, sha="h1", draft=False, labels=(), body="", title="PR"):
    return {"number": n, "title": title, "headRefOid": sha, "isDraft": draft, "labels": [{"name": l} for l in labels],
            "body": body, "url": f"https://x/pull/{n}"}


def where(board, kind, n):
    return [col for col, cards in board.columns.items() for c in cards if c.kind == kind and c.number == n]


class BoardTest(unittest.TestCase):
    def build(self, issues=(), prs=(), merged=(), state=None, project=ALPHA):
        return b.build_board(project, {"auto_fix": project.auto_fix}, list(issues), list(prs), list(merged),
                             state or {})

    def test_issue_columns_from_labels_and_structure(self):
        board = self.build(issues=[
            issue(1, ["needs-triage"]), issue(2, ["bug"]), issue(3, ["needs-info"]),
            issue(4, ["ready-for-agent"], title="Spec: webhooks"), issue(5, ["ready-for-agent"], subs=3),
            issue(6, ["ready-for-agent"]), issue(7, ["needs-decision"]), issue(8, ["wontfix"]),
            issue(9, ["ready-for-agent"], title="Notify partners")],
            merged=[{"number": 20, "title": "Design for #9: notify", "url": "u", "mergedAt": "2026-10-14"}])
        self.assertEqual(where(board, "issue", 1), ["Triage"])
        self.assertEqual(where(board, "issue", 2), ["Triage"], "no triage-state label yet")
        self.assertEqual(where(board, "issue", 3), ["Triage"])
        self.assertEqual(where(board, "issue", 4), ["Spec"], "title says spec")
        self.assertEqual(where(board, "issue", 5), ["Spec"], "has sub-issues")
        self.assertEqual(where(board, "issue", 9), ["Spec"], "has a design docs PR")
        self.assertEqual(where(board, "issue", 6), ["Ready"])
        self.assertEqual(where(board, "issue", 7), ["Needs you"])
        self.assertEqual(where(board, "issue", 8), [], "wontfix is not on the board")

    def test_ticket_with_open_pr_is_shown_on_the_pr_card(self):
        board = self.build(issues=[issue(8, ["ready-for-agent"])], prs=[pr(9, draft=True, body="Closes #8\nTrace: x")])
        self.assertEqual(where(board, "issue", 8), [])
        card = board.columns["Building"][0]
        self.assertEqual(card.links, [("#8", "https://x/issues/8")])

    def test_pr_columns(self):
        state = {"prs": {
            "alpha#2": {"reviewed_sha": None, "cost": 0.0},
            "alpha#3": {"reviewed_sha": "h1", "blocking": 2, "rounds": 1, "cost": 0.5},
            "alpha#4": {"reviewed_sha": "h1", "blocking": 0, "verdict": {"sha": "h1", "auto": True, "message": "Auto"}},
            "alpha#5": {"reviewed_sha": "h1", "blocking": 0,
                        "verdict": {"sha": "h1", "auto": False, "message": "Held for you: touches db/migrations/1.sql"}},
            "alpha#6": {"reviewed_sha": "h1", "blocking": 0, "verdict": {"sha": "old", "auto": True, "message": "x"}},
        }, "runs": {"alpha#7": {"kind": "fix"}}}
        board = self.build(state=state, prs=[
            pr(1, draft=True), pr(2), pr(3), pr(4), pr(5), pr(6), pr(7),
            pr(8, labels=["needs-decision"]), pr(10, labels=["no-dispatch"], title="Design for #6: x")])
        self.assertEqual(where(board, "pr", 1), ["Building"])
        self.assertEqual(where(board, "pr", 2), ["In review"])
        self.assertEqual(where(board, "pr", 3), ["In review"])
        self.assertEqual(where(board, "pr", 4), ["Ready to merge"])
        self.assertEqual(where(board, "pr", 5), ["Needs you"])
        self.assertEqual(where(board, "pr", 6), ["In review"], "verdict was for an older commit")
        self.assertEqual(where(board, "pr", 7), ["In review"])
        self.assertEqual(where(board, "pr", 8), ["Needs you"])
        self.assertEqual(where(board, "pr", 10), ["Needs you"])
        notes = {c.number: c.note for col in board.columns.values() for c in col}
        self.assertIn("Held for you: touches db/migrations/1.sql", notes[5])
        self.assertIn("2 blocking finding(s)", notes[3])
        self.assertIn("fix running", notes[7])
        self.assertIn("Gate 1", notes[10])
        self.assertEqual([c.cost for c in board.columns["In review"] if c.number == 3], [0.5])

    def test_done_marks_auto_merges_and_lists_recent_ones(self):
        state = {"auto_merges": [{"pr": "alpha#14", "title": "t", "url": "u", "verdict": "Auto-merge: low risk",
                                  "at": "2026-10-14T22:50:12Z"},
                                 {"pr": "beta#3", "title": "t", "url": "u", "verdict": "v", "at": "2026-10-14T00:00:00Z"}]}
        board = self.build(state=state, merged=[{"number": 14, "title": "t", "url": "u", "mergedAt": "2026-10-14T22:50:12Z"},
                                                {"number": 12, "title": "t", "url": "u", "mergedAt": "2026-10-13"}])
        notes = {c.number: c.note for c in board.columns["Done"]}
        self.assertTrue(notes[14].startswith("auto-merged"))
        self.assertTrue(notes[12].startswith("merged"))
        self.assertEqual([a["pr"] for a in board.recent_auto_merges], ["alpha#14"])

    def test_inbox_collects_needs_you_across_projects(self):
        a = self.build(issues=[issue(1, ["needs-decision"])])
        c = self.build(project=BETA, prs=[pr(2, labels=["needs-decision"])])
        self.assertEqual([(x.project, x.number) for x in b.inbox([a, c])], [("alpha", 1), ("beta", 2)])


class FakeSource:
    """Read methods only, like the real ReadOnlySource."""

    def __init__(self):
        self.calls = []

    def projects(self):
        return [ALPHA, BETA], []

    def state(self):
        return {"auto_merges": [{"pr": "alpha#14", "title": "Timeout", "url": "u", "verdict": "Auto-merge: low risk",
                                 "at": "2026-10-14T22:50:12Z"}]}

    def board(self, project, state, refresh=False):
        self.calls.append(project.name)
        prs = [pr(5, labels=["needs-decision"], title="Risky change")] if project is ALPHA else []
        return b.build_board(project, {"auto_fix": project.auto_fix, "merge_mode": project.merge_mode},
                             [issue(1, ["needs-triage"], title="Bug <script>")], prs, [], state)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FakeSource()
        cls.httpd = server.serve(cls.source, 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.read().decode("utf-8")

    def test_binds_to_localhost_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_default_view_is_needs_you_inbox_with_selector_settings_and_auto_merges(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("Needs you, all projects", body)
        self.assertIn("Risky change", body)
        self.assertIn('href="/p/alpha"', body)
        self.assertIn('href="/p/beta"', body)
        self.assertIn("auto_fix: <b>off</b>", body)
        self.assertIn("merge_mode: <b>manual</b>", body)
        self.assertIn("Recent auto-merges", body)
        self.assertIn("alpha#14", body)

    def test_project_board_has_every_column(self):
        status, body = self.get("/p/alpha")
        self.assertEqual(status, 200)
        for column in b.COLUMNS:
            self.assertIn(f"<h3>{column} (", body)
        self.assertIn("vscode://file/", body)

    def test_titles_are_escaped(self):
        self.assertIn("Bug &lt;script&gt;", self.get("/p/alpha")[1])

    def test_writes_are_refused(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method):
                req = urllib.request.Request(self.base + "/", data=b"x", method=method)
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 405)

    def test_unknown_page_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/p/nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_read_only_source_has_no_write_methods(self):
        public = {m for m in dir(server.ReadOnlySource) if not m.startswith("_")}
        self.assertEqual(public, {"projects", "state", "board"})


class TasksTest(unittest.TestCase):
    def test_vscode_tasks_parse_and_cover_the_build_plan(self):
        import json
        import re
        text = (Path(__file__).resolve().parent.parent / ".vscode" / "tasks.json").read_text(encoding="utf-8")
        tasks = json.loads(re.sub(r"(?m)^\s*//.*$", "", text))["tasks"]
        labels = {t["label"] for t in tasks}
        for needed in ("FactoryKit: start dispatcher", "FactoryKit: open dashboard",
                       "FactoryKit: set up a project", "FactoryKit: sync skills"):
            self.assertIn(needed, labels)


if __name__ == "__main__":
    unittest.main()
