"""Thin wrapper over the owner's authenticated gh CLI, for one project repo. All GitHub access goes here."""
import json
import re
import shutil
import subprocess

REVIEW_CONTEXT = "dispatcher/review"
RUN_ID = re.compile(r"/actions/runs/(\d+)")


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, repo_dir):
        self.dir = str(repo_dir)
        self.exe = shutil.which("gh") or "gh"

    def _gh(self, *args, stdin=None):
        p = subprocess.run([self.exe, *args], cwd=self.dir, input=stdin, capture_output=True,
                           text=True, encoding="utf-8")
        if p.returncode != 0:
            raise GitHubError(f"gh {' '.join(args[:3])}: {p.stderr.strip()}")
        return p.stdout

    def _json(self, *args):
        out = self._gh(*args)
        return json.loads(out) if out.strip() else None

    # ---- reads
    def open_prs(self):
        return self._json("pr", "list", "--state", "open", "--limit", "100", "--json",
                          "number,title,headRefName,headRefOid,baseRefName,isDraft,labels,body,url,additions,deletions")

    def checks(self, number):
        """CI state of the PR head, ignoring our own dispatcher/review status: (state, failed runs).

        state is "green", "pending", "failed" or "none" (no CI reported yet).
        """
        rollup = self._json("pr", "view", str(number), "--json", "statusCheckRollup")["statusCheckRollup"] or []
        return summarize_checks(rollup)

    def changed_files(self, number):
        return [f["path"] for f in self._json("pr", "view", str(number), "--json", "files")["files"]]

    def issue_text(self, number):
        d = self._json("issue", "view", str(number), "--json", "title,body")
        return f"#{number} {d['title']}\n\n{d['body']}"

    def failed_log(self, run_id):
        return self._gh("run", "view", str(run_id), "--log-failed")

    def pr_for_branch(self, branch):
        prs = self._json("pr", "list", "--state", "all", "--head", branch, "--limit", "1", "--json",
                         "number,state,headRefOid")
        return prs[0] if prs else None

    # ---- writes (every one is visible on the PR)
    def comment(self, number, body):
        self._gh("pr", "comment", str(number), "--body-file", "-", stdin=body)

    def review(self, number, body):
        self._gh("pr", "review", str(number), "--comment", "--body-file", "-", stdin=body)

    def set_review_status(self, sha, success, description):
        self._gh("api", "-X", "POST", f"repos/{{owner}}/{{repo}}/statuses/{sha}",
                 "-f", f"state={'success' if success else 'failure'}", "-f", f"context={REVIEW_CONTEXT}",
                 "-f", f"description={description[:140]}")

    def add_label(self, number, label):
        self._gh("pr", "edit", str(number), "--add-label", label)

    def enable_auto_merge(self, number):
        self._gh("pr", "merge", str(number), "--auto", "--squash")


def summarize_checks(rollup):
    failed, pending, seen = [], False, False
    for c in rollup:
        name = c.get("name") or c.get("context") or ""
        if name == REVIEW_CONTEXT:
            continue
        seen = True
        if c.get("__typename") == "StatusContext" or "state" in c and "conclusion" not in c:
            state = (c.get("state") or "").upper()
            if state in ("PENDING", "EXPECTED"):
                pending = True
            elif state in ("FAILURE", "ERROR"):
                failed.append({"name": name, "run_id": None, "url": c.get("targetUrl", "")})
            continue
        if (c.get("status") or "").upper() != "COMPLETED":
            pending = True
        elif (c.get("conclusion") or "").upper() in ("FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED"):
            m = RUN_ID.search(c.get("detailsUrl") or "")
            failed.append({"name": name, "run_id": int(m.group(1)) if m else None, "url": c.get("detailsUrl", "")})
    if failed:
        return "failed", failed
    if pending:
        return "pending", []
    return ("green" if seen else "none"), []
