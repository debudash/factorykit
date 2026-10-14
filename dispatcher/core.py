"""Dispatcher v1: the per-PR rules of design sections 10 to 12.

Each poll, for every project in ~/factory/projects.toml (reloaded every time):
  skip drafts and no-dispatch -> flag a missing trace once -> review every new head ->
  fix blocking findings or failed CI under auto_fix and the guards -> escalate at the limits ->
  post the merge verdict and enable auto-merge for low-risk PRs -> remove merged builders' worktrees.
The dispatcher never edits code. It runs agents, inspects their diffs, pushes guarded fixes and
writes to GitHub, and every one of those writes is visible on the PR.
"""
import json
import string
import time
from datetime import datetime, timezone
from pathlib import Path

from . import rules
from .agent import PROMPTS, DetachedHandle, build_agent_command, parse_agent_output
from .settings import load_registry, parse_factory_md

MARKER = "<!-- factorykit-dispatcher -->"
NEEDS_DECISION = "needs-decision"
NO_DISPATCH = "no-dispatch"
FACTORY_MD = "docs/agents/factory.md"
MAX_REVIEW_ROUNDS = 2
MAX_CI_ATTEMPTS = 3
MAX_CONCURRENT_FIXES = 2
MAX_RUN_MINUTES = 45
MAX_DIFF_CHARS = 60_000
MAX_LOG_LINES = 200
AI = "_AI-generated._"


def new_pr_state():
    return {"rounds": 0, "reviewed_sha": None, "blocking": None, "last_review": "", "ci_attempts": 0,
            "fix_sha": None, "notified": [], "verdict_sha": None, "trace_flagged": False,
            "escalated": False, "cost": 0.0}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tail(text, lines):
    return "\n".join((text or "").splitlines()[-lines:])


def money(cost):
    return f"${cost:.2f}" if isinstance(cost, (int, float)) else "unknown"


class Dispatcher:
    def __init__(self, registry_path, home, make_github, make_git, spawner, *,
                 dry_run=False, out=print, clock=time.time):
        self.registry_path, self.home = Path(registry_path), Path(home)
        self.make_github, self.make_git, self.spawner = make_github, make_git, spawner
        self.dry_run, self.out, self.clock = dry_run, out, clock
        self.state_path = self.home / "state" / "dispatcher.json"
        self.runs_dir, self.wt_dir = self.home / "runs", self.home / "worktrees"
        self.state = self._load()
        self.handles = {key: DetachedHandle(r["out"], r["started"], MAX_RUN_MINUTES * 60, clock)
                        for key, r in self.state["runs"].items()}
        self._last_errors = []

    # ------------------------------------------------------------ persistence and logging
    def _load(self):
        state = {"prs": {}, "runs": {}, "auto_merges": []}
        if self.state_path.exists():
            state.update(json.loads(self.state_path.read_text(encoding="utf-8")))
        return state

    def save(self):
        if self.dry_run:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def log(self, event, **data):
        record = {"ts": now_iso(), "event": event, **data}
        self.out(f"[{record['ts']}] {event} " + " ".join(f"{k}={v}" for k, v in data.items()))
        if not self.dry_run:
            self.home.mkdir(parents=True, exist_ok=True)
            with (self.home / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    def act(self, description, fn):
        """Every write goes through here: printed in a dry run, done and logged otherwise."""
        if self.dry_run:
            self.out(f"[dry-run] would {description}")
            return
        fn()
        self.log("action", did=description)

    # ------------------------------------------------------------ the poll
    def cycle(self):
        projects, errors = load_registry(self.registry_path)  # reloaded every poll (design section 10.7)
        if errors != self._last_errors:
            for e in errors:
                self.log("registry-error", error=e)
            self._last_errors = errors
        self.projects = {p.name: p for p in projects}
        self._reap()
        for project in projects:
            try:
                self._project(project)
            except Exception as exc:  # one broken project must not stop the others
                self.log("error", project=project.name, error=str(exc))
        self.save()

    def _project(self, project):
        gh, git = self.make_github(project.path), self.make_git(project.path)
        git.fetch()
        settings = parse_factory_md(git.show("origin/HEAD", FACTORY_MD) or git.show("origin/main", FACTORY_MD))
        for pr in gh.open_prs():
            try:
                self._pr(project, gh, git, settings, pr)
            except Exception as exc:
                self.log("error", project=project.name, pr=pr.get("number"), error=str(exc))
        self._cleanup_builder_worktrees(project, gh, git)

    def _pr(self, project, gh, git, settings, pr):
        n, head = pr["number"], pr["headRefOid"]
        key = f"{project.name}#{n}"
        st = self.state["prs"].setdefault(key, new_pr_state())
        st["title"], st["url"] = pr.get("title", ""), pr.get("url", "")
        labels = {label["name"] for label in pr.get("labels") or []}

        # 1. Drafts and no-dispatch are skipped; needs-decision means a human owns the PR now.
        if pr.get("isDraft") or NO_DISPATCH in labels:
            return
        if NEEDS_DECISION in labels:
            st["escalated"] = True
            return
        if st["escalated"]:  # the owner removed the label: continue with fresh limits
            st.update(escalated=False, rounds=0, ci_attempts=0, fix_sha=None, notified=[])
            self.log("resumed", pr=key)
        if key in self.state["runs"]:  # one review or fix per PR at a time
            return

        # 2. The PR must link its ticket and carry the trace block. Flagged once.
        problems = rules.trace_problems(pr.get("body"))
        if problems and not st["trace_flagged"]:
            self.act(f"flag PR {key}: missing {' and '.join(problems)}", lambda: gh.comment(n, (
                f"{MARKER}\n**FactoryKit:** this PR is missing {' and '.join(problems)} at the top of its "
                "description, so its record does not link back to the ticket and spec. Please add them.")))
            st["trace_flagged"] = True

        # 3. Every new head of a ready PR gets an independent review.
        if st["reviewed_sha"] != head:
            self._start_review(project, gh, git, settings, pr, st)
            return

        # 4 and 5. Blocking findings or failed CI: fix under auto_fix, or escalate at the limits.
        ci_state, failed = gh.checks(n)
        review_blocked = (st["blocking"] or 0) > 0
        ci_failed = ci_state == "failed"
        if review_blocked and st["rounds"] >= MAX_REVIEW_ROUNDS:
            return self._escalate(gh, key, st, f"{MAX_REVIEW_ROUNDS} review rounds still have blocking findings. "
                                               "See the latest review on this PR.")
        if ci_failed and st["ci_attempts"] >= MAX_CI_ATTEMPTS:
            return self._escalate(gh, key, st, f"CI is still failing after {MAX_CI_ATTEMPTS} automatic fix attempts.")
        if review_blocked or ci_failed:
            return self._fix_or_notify(project, gh, settings, pr, st, review_blocked, failed)

        # 6. CI green and review passed: post the merge verdict.
        if ci_state == "green" and st["blocking"] == 0:
            self._verdict(project, gh, settings, pr, st)

    # ------------------------------------------------------------ review
    def _start_review(self, project, gh, git, settings, pr, st):
        n, head, round_ = pr["number"], pr["headRefOid"], st["rounds"] + 1
        base = git.merge_base(f"origin/{pr['baseRefName']}", head)
        links = rules.linked_numbers(pr.get("body"))
        issue_text = "\n\n".join(self._issue(gh, links[k]) for k in ("ticket", "spec") if links[k]) or "(none linked)"
        diff = git.diff(base, head)
        if len(diff) > MAX_DIFF_CHARS:
            diff = diff[:MAX_DIFF_CHARS] + f"\n... diff truncated at {MAX_DIFF_CHARS} characters; use git diff {base} HEAD"
        previous = ""
        if round_ > 1 and st["last_review"]:
            previous = (f"\n## Previous review (round {round_ - 1}, commit {st['reviewed_sha']})\n{st['last_review']}\n"
                        f"Commits since then: run `git log {st['reviewed_sha']}..HEAD`.")
        note = ("First review: review the whole change." if round_ == 1 else
                f"Round {round_}: review only the commits since the previous review and the earlier items. "
                "No new nitpicks.")
        prompt = string.Template((PROMPTS / "review.md").read_text(encoding="utf-8")).safe_substitute(
            pr_number=n, pr_title=pr.get("title", ""), round=round_, head_sha=head, base_branch=pr["baseRefName"],
            merge_base=base, ticket=f"#{links['ticket']}" if links["ticket"] else "none",
            spec=f"#{links['spec']}" if links["spec"] else "none",
            docs_pr=f"#{links['docs_pr']}" if links["docs_pr"] else "none",
            lld=f"docs/architecture/lld/{links['spec']}-*.md if it exists" if links["spec"] else "none",
            round_note=note, issue_text=issue_text, diff_stat=git.diff_stat(base, head), diff=diff, previous=previous)
        cmd = build_agent_command("reviewer", model=settings.reviewer_model, verify=settings.verify)
        self._spawn("review", project, pr, head, prompt, cmd, git,
                    {"round": round_, "model": settings.reviewer_model})
        if not self.dry_run:
            st["rounds"] = round_

    def _issue(self, gh, number):
        try:
            return gh.issue_text(number)
        except Exception:
            return f"#{number}: could not be read"

    def _complete_review(self, run, rc, gh):
        st = self.state["prs"][run["key"]]
        result, cost, failed = parse_agent_output(self._read(run["out"]))
        st["cost"] += cost or 0
        blocking = rules.parse_review_result(result)
        if rc != 0 or failed or blocking is None:
            return self._escalate(gh, run["key"], st, f"The reviewer run failed or its output had no "
                                  f"`REVIEW_RESULT` line, so round {run['round']} was not posted. "
                                  f"Log: `{Path(run['out']).name}` in ~/factory/runs.")
        title = f"Round {run['round']} of {MAX_REVIEW_ROUNDS}" if run["round"] <= MAX_REVIEW_ROUNDS \
            else f"Round {run['round']} (after {MAX_REVIEW_ROUNDS} rounds)"
        body = (f"{MARKER}\n## FactoryKit review: {title}\n{AI} Independent reviewer, model `{run['model']}`, "
                f"commit `{run['sha'][:7]}`, cost {money(cost)}.\n\n{result}")
        summary = f"Round {run['round']}: " + (f"{blocking} blocking finding(s)" if blocking else "no blocking findings")
        self.act(f"post review {title} on {run['key']} and set dispatcher/review",
                 lambda: (gh.review(run["pr"], body), gh.set_review_status(run["sha"], blocking == 0, summary)))
        st.update(reviewed_sha=run["sha"], blocking=blocking, last_review=result[-8000:])

    # ------------------------------------------------------------ fix (design section 11)
    def _fix_or_notify(self, project, gh, settings, pr, st, review_blocked, failed):
        n, head, key = pr["number"], pr["headRefOid"], f"{project.name}#{pr['number']}"
        allowed = {"review": project.auto_fix == "ci_and_review", "ci": project.auto_fix in ("ci", "ci_and_review")}
        wanted = {"review": review_blocked, "ci": bool(failed)}
        manual = [k for k in ("review", "ci") if wanted[k] and not allowed[k]]
        if manual and f"manual:{head}" not in st["notified"]:
            what = " and ".join({"review": "blocking review findings", "ci": "failing CI"}[k] for k in manual)
            self.act(f"tell {key} that /address-feedback is needed", lambda: gh.comment(n, (
                f"{MARKER}\n**FactoryKit:** this PR has {what}. `auto_fix` is `{project.auto_fix}` for this "
                f"project, so run `/address-feedback {n}` in Claude Code to fix it.")))
            st["notified"].append(f"manual:{head}")
        kinds = [k for k in ("review", "ci") if wanted[k] and allowed[k]]
        if not kinds or st["fix_sha"] == head:
            return
        if sum(r["kind"] == "fix" for r in self.state["runs"].values()) >= MAX_CONCURRENT_FIXES:
            return  # global cap across all projects; picked up on a later poll
        items = []
        if "review" in kinds:
            items.append(f"### Blocking review findings (round {st['rounds']})\n{st['last_review']}")
        if "ci" in kinds:
            for f in failed:
                log = tail(self._failed_log(gh, f), MAX_LOG_LINES)
                items.append(f"### CI failure: {f['name']}\n{f['url']}\n```\n{log}\n```")
        verify = "\n".join(f"- {k}: `{v}`" for k, v in settings.verify.items()) or "- (none listed)"
        prompt = string.Template((PROMPTS / "fix.md").read_text(encoding="utf-8")).safe_substitute(
            pr_number=n, pr_title=pr.get("title", ""), branch=pr["headRefName"], head_sha=head,
            verify=verify, items="\n\n".join(items))
        cmd = build_agent_command("fixer", verify=settings.verify)
        git = self.make_git(project.path)
        self._spawn("fix", project, pr, head, prompt, cmd, git, {
            "mode": project.auto_fix, "kinds": kinds, "branch": pr["headRefName"],
            "risky_paths": settings.risky_paths})
        if not self.dry_run:
            st["fix_sha"] = head
            if "ci" in kinds:
                st["ci_attempts"] += 1

    def _failed_log(self, gh, failed):
        if not failed.get("run_id"):
            return "(no GitHub Actions log for this check; see the link)"
        try:
            return gh.failed_log(failed["run_id"])
        except Exception as exc:
            return f"(could not read the log: {exc})"

    def _complete_fix(self, run, rc, gh, git):
        key, n, base, wt = run["key"], run["pr"], run["sha"], run["worktree"]
        st = self.state["prs"][key]
        result, cost, failed = parse_agent_output(self._read(run["out"]))
        st["cost"] += cost or 0
        what = " and ".join({"review": "blocking review findings", "ci": "failing CI"}[k] for k in run["kinds"])
        header = f"**FactoryKit auto_fix** (mode `{run['mode']}`) for {what}. Run cost {money(cost)}."
        summary = f"<details><summary>Fix agent summary</summary>\n\n{result[-4000:]}\n\n</details>\n\n{AI}"
        if rc != 0 or failed:
            return self._escalate(gh, key, st, f"{header}\n\nThe fix agent run failed (exit {rc}). Nothing was pushed.")
        questions = rules.needs_decision_questions(result)
        if questions:
            return self._escalate(gh, key, st, f"{header}\n\nThe fix agent needs a decision. Nothing was pushed.\n\n"
                                  + "\n".join(f"- {q}" for q in questions))
        commits = git.commits(base, wt)
        if not commits:
            return self._escalate(gh, key, st, f"{header}\n\nThe fix agent made no commits. Nothing was pushed.\n\n{summary}")
        remote = git.remote_head(run["branch"])
        if remote != base:
            return self._escalate(gh, key, st, f"{header}\n\nThe PR branch moved while the fix ran (it was "
                                  f"`{base[:7]}`, now `{(remote or 'deleted')[:7]}`). The fix was not pushed.")
        results = rules.check_fix(git.changes(base, wt), git.added_lines(base, wt), run["risky_paths"])
        table = rules.guard_table(results)
        commit_list = "\n".join(f"- {c}" for c in commits)
        if not rules.guards_passed(results):
            return self._escalate(gh, key, st, f"{header}\n\nThe fix failed a guard and was **not pushed**.\n\n"
                                  f"{table}\n\nCommits held back:\n{commit_list}\n\n{summary}")
        pushed = {}
        self.act(f"push guarded fix to {key} ({len(commits)} commit(s))",
                 lambda: pushed.update(result=git.push(wt, run["branch"])))
        ok, err = pushed.get("result", (True, ""))
        if not ok:
            return self._escalate(gh, key, st, f"{header}\n\nThe push was rejected: {err}")
        self.act(f"post fix summary on {key}", lambda: gh.comment(n, (
            f"{MARKER}\n{header}\n\nPushed:\n{commit_list}\n\n{table}\n\n{summary}")))

    # ------------------------------------------------------------ merge verdict (design section 12)
    def _verdict(self, project, gh, settings, pr, st):
        n, head, key = pr["number"], pr["headRefOid"], f"{project.name}#{pr['number']}"
        if st["verdict_sha"] == head:
            return
        lines = int(pr.get("additions") or 0) + int(pr.get("deletions") or 0)
        verdict = rules.merge_verdict(lines, gh.changed_files(n), settings.risky_paths, project.merge_mode)
        self.act(f"post verdict on {key}: {verdict.message}", lambda: gh.comment(n, f"{MARKER}\n{verdict.message}"))
        if verdict.auto_merge:
            self.act(f"enable GitHub auto-merge on {key}", lambda: gh.enable_auto_merge(n))
            if not self.dry_run:
                self.state["auto_merges"] = (self.state["auto_merges"] + [{
                    "pr": key, "title": pr.get("title", ""), "url": pr.get("url", ""),
                    "verdict": verdict.message, "at": now_iso()}])[-50:]
        if not self.dry_run:
            st["verdict_sha"] = head
            st["verdict"] = {"sha": head, "auto": verdict.auto_merge, "message": verdict.message}

    # ------------------------------------------------------------ escalation
    def _escalate(self, gh, key, st, reason):
        n = int(key.rsplit("#", 1)[1])
        self.act(f"label {key} needs-decision: {reason.splitlines()[0][:100]}", lambda: (
            gh.add_label(n, NEEDS_DECISION),
            gh.comment(n, f"{MARKER}\n**FactoryKit: needs your decision**\n\n{reason}\n\n"
                          f"Remove the `{NEEDS_DECISION}` label to let the dispatcher continue; its limits reset.")))
        if not self.dry_run:
            st["escalated"] = True

    # ------------------------------------------------------------ agent runs
    def _spawn(self, kind, project, pr, sha, prompt, cmd, git, extra):
        n, key = pr["number"], f"{project.name}#{pr['number']}"
        if self.dry_run:
            self.out(f"[dry-run] would start {kind} for {key} at {sha[:7]}")
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        name = f"{project.name}-pr{n}-{kind}-{stamp}"
        worktree = self.wt_dir / project.name / name
        git.add_worktree(worktree, sha)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = self.runs_dir / f"{name}.prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        out, err = self.runs_dir / f"{name}.json", self.runs_dir / f"{name}.err"
        self.handles[key] = self.spawner.spawn(cmd, worktree, prompt_path, out, err)
        self.state["runs"][key] = {"kind": kind, "key": key, "project": project.name, "path": str(project.path),
                                   "pr": n, "sha": sha, "worktree": str(worktree), "out": str(out),
                                   "started": self.clock(), **extra}
        self.log("started", kind=kind, pr=key, sha=sha[:7])

    def _reap(self):
        for key, run in list(self.state["runs"].items()):
            handle = self.handles[key]
            rc = handle.poll()
            gh, git = self.make_github(Path(run["path"])), self.make_git(Path(run["path"]))
            if rc is None:
                if self.clock() - run["started"] > MAX_RUN_MINUTES * 60:
                    handle.terminate()
                    self._finish(key)
                    git.remove_worktree(run["worktree"])
                    self._escalate(gh, key, self.state["prs"][key],
                                   f"The {run['kind']} run took over {MAX_RUN_MINUTES} minutes and was stopped.")
                continue
            self._finish(key)
            try:
                if run["kind"] == "review":
                    self._complete_review(run, rc, gh)
                else:
                    self._complete_fix(run, rc, gh, git)
                self.log("completed", kind=run["kind"], pr=key)
            except Exception as exc:
                self.log("error", pr=key, error=str(exc))
            finally:
                git.remove_worktree(run["worktree"])

    def _finish(self, key):
        self.state["runs"].pop(key, None)
        self.handles.pop(key, None)

    @staticmethod
    def _read(path):
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            return ""

    # ------------------------------------------------------------ builder worktrees (ADR 0016)
    def _cleanup_builder_worktrees(self, project, gh, git):
        root = (Path(project.path) / ".claude" / "worktrees").resolve()
        for wt in git.worktrees():
            path = Path(wt["path"]).resolve()
            if root not in path.parents or not wt["branch"] or wt["locked"]:
                continue
            pr = gh.pr_for_branch(wt["branch"])
            if not pr or pr["state"] not in ("MERGED", "CLOSED"):
                continue
            if pr["headRefOid"] != wt["head"] or git.has_tracked_changes(path):
                continue  # local work that never reached the PR: leave it for the owner
            self.act(f"remove builder worktree {path.name} (PR #{pr['number']} {pr['state'].lower()})",
                     lambda p=path, b=wt["branch"]: git.remove_builder_worktree(p, b))

    # ------------------------------------------------------------ status view
    def status(self):
        rows = [("PR", "Rounds", "Blocking", "CI fixes", "Cost", "State")]
        running = self.state["runs"]
        for key, st in sorted(self.state["prs"].items()):
            state = (f"{running[key]['kind']} running" if key in running else
                     "NEEDS YOU" if st["escalated"] else
                     "verdict posted" if st["verdict_sha"] else "watching")
            rows.append((key, str(st["rounds"]), str(st["blocking"]), f"{st['ci_attempts']}/{MAX_CI_ATTEMPTS}",
                         money(st["cost"]), state))
        widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
        for r in rows:
            self.out("  ".join(v.ljust(w) for v, w in zip(r, widths)))
