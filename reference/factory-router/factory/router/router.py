#!/usr/bin/env python3
"""
Factory feedback router.

Watches open pull requests owned by the factory and routes two kinds of feedback
back to the Claude Code agent that owns each PR branch:

  - CI failures on the PR's current head commit
  - Review comments that match configurable triggers

Ownership is derived, not registered: the owning agent is whatever git worktree
has the PR's head branch checked out. GitHub stays the system of record, and
.factory/ holds local router state, an event log and per-run agent logs.

Usage:
  python factory/router/router.py setup              create labels and .factory/
  python factory/router/router.py once [--dry-run]   run one routing cycle
  python factory/router/router.py watch              poll continuously
  python factory/router/router.py status             show PRs, owners, budgets, events

Requires Python 3.11+, git, an authenticated GitHub CLI (gh) and Claude Code.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Callable, Protocol

MARKER = "<!-- factory-router -->"
NEEDS_DECISION = "NEEDS_DECISION:"
ROUTER_DIR = Path(__file__).resolve().parent
CI_FAILED = {"failure", "timed_out", "startup_failure"}


# --------------------------------------------------------------------------- config

@dataclass
class Config:
    # GitHub
    require_label: str = "factory"
    escalation_label: str = "needs-decision"
    # Routing rules
    route_ci: bool = True
    route_reviews: bool = True
    trigger_prefixes: list[str] = field(default_factory=lambda: ["/agent", "/fix"])
    trigger_tags: list[str] = field(default_factory=lambda: ["[blocking]"])
    route_changes_requested: bool = True
    reviewer_allowlist: list[str] = field(default_factory=list)
    allow_bot_authors: list[str] = field(default_factory=list)
    ignore_authors: list[str] = field(default_factory=list)
    baseline_existing: bool = True
    max_ci_attempts: int = 3
    max_review_attempts: int = 5
    max_log_lines: int = 200
    # Runtime
    poll_seconds: int = 60
    max_concurrent: int = 3
    max_run_minutes: int = 45
    state_dir: str = ".factory"
    # Agent invocation
    claude_command: str = "claude"
    session: str = "fork"  # fork | continue | new
    model: str = ""
    permission_mode: str = "acceptEdits"
    max_turns: int = 30
    allowed_tools: list[str] = field(default_factory=lambda: [
        "Read", "Edit", "Write", "Grep", "Glob",
        "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)",
        "Bash(git add:*)", "Bash(git commit:*)", "Bash(git push:*)",
    ])
    disallowed_tools: list[str] = field(default_factory=lambda: [
        "Bash(git push --force:*)", "Bash(git push -f:*)",
        "Bash(git push --force-with-lease:*)", "Bash(gh pr merge:*)",
    ])

    @classmethod
    def load(cls, path: Path | None) -> "Config":
        if path is None or not path.exists():
            return cls()
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        flat: dict[str, Any] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                flat.update(value)
            else:
                flat[key] = value
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(flat) - known)
        if unknown:
            raise ValueError(f"Unknown config keys in {path}: {unknown}")
        cfg = cls(**flat)
        if cfg.session not in ("fork", "continue", "new"):
            raise ValueError("session must be one of: fork, continue, new")
        return cfg


# --------------------------------------------------------------------------- helpers

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_multi_json(text: str) -> list[Any]:
    """Parse output of `gh api --paginate`, which concatenates one JSON array per page."""
    decoder = json.JSONDecoder()
    text = text.strip()
    items: list[Any] = []
    i = 0
    while i < len(text):
        obj, i = decoder.raw_decode(text, i)
        if isinstance(obj, list):
            items.extend(obj)
        else:
            items.append(obj)
        while i < len(text) and text[i].isspace():
            i += 1
    return items


def parse_worktrees(porcelain: str) -> dict[str, Path]:
    """Map branch name -> worktree path from `git worktree list --porcelain`."""
    mapping: dict[str, Path] = {}
    path: Path | None = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line.startswith("branch ") and path is not None:
            mapping[line[len("branch "):].removeprefix("refs/heads/")] = path
    return mapping


def worktrees_by_branch(repo_root: Path) -> dict[str, Path]:
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout
    return parse_worktrees(out)


def repo_root_from_cwd() -> Path:
    """Main repo root, even when invoked from inside a linked worktree."""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(common).parent
    except subprocess.CalledProcessError:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(top)


def tail(text: str, lines: int) -> str:
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


# --------------------------------------------------------------------------- GitHub

class GitHub:
    """Thin wrapper over the gh CLI. All GitHub access goes through here."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def _gh(self, *args: str) -> str:
        result = subprocess.run(["gh", *args], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args[:3])} failed: {result.stderr.strip()}")
        return result.stdout

    def _json(self, *args: str) -> list[Any]:
        out = self._gh(*args)
        return parse_multi_json(out) if out.strip() else []

    def open_prs(self, label: str) -> list[dict]:
        args = ["pr", "list", "--state", "open", "--limit", "100", "--json",
                "number,title,headRefName,headRefOid,isDraft,labels,url"]
        if label:
            args += ["--label", label]
        return self._json(*args)

    def runs_for(self, branch: str) -> list[dict]:
        return self._json("run", "list", "--branch", branch, "--limit", "30", "--json",
                          "databaseId,status,conclusion,headSha,workflowName,url")

    def failed_log(self, run_id: int) -> str:
        return self._gh("run", "view", str(run_id), "--log-failed")

    def reviews(self, number: int) -> list[dict]:
        return self._json("api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{number}/reviews")

    def review_comments(self, number: int) -> list[dict]:
        return self._json("api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{number}/comments")

    def issue_comments(self, number: int) -> list[dict]:
        return self._json("api", "--paginate", f"repos/{{owner}}/{{repo}}/issues/{number}/comments")

    def add_label(self, number: int, label: str) -> None:
        if self.dry_run:
            print(f"[dry-run] would add label '{label}' to PR #{number}")
            return
        self._gh("pr", "edit", str(number), "--add-label", label)

    def comment(self, number: int, body: str) -> None:
        if self.dry_run:
            print(f"[dry-run] would comment on PR #{number}: {body.splitlines()[1][:80]}")
            return
        self._gh("pr", "comment", str(number), "--body", body)

    def ensure_label(self, name: str, color: str, description: str) -> None:
        self._gh("label", "create", name, "--color", color, "--description", description, "--force")


# --------------------------------------------------------------------------- events and filters

@dataclass
class Comment:
    source: str  # inline | review | conversation
    id: int
    author: str
    author_type: str
    body: str
    state: str = ""
    path: str = ""
    line: int | None = None
    url: str = ""

    @property
    def key(self) -> str:
        return f"review:{self.source}:{self.id}"


@dataclass
class Event:
    kind: str  # ci | review
    key: str
    summary: str
    detail: str


def should_route(c: Comment, cfg: Config) -> bool:
    body = (c.body or "").strip()
    if MARKER in body:
        return False  # the router's own comments
    if c.author in cfg.ignore_authors:
        return False
    is_allowed_bot = c.author in cfg.allow_bot_authors
    if c.author_type == "Bot" and not is_allowed_bot:
        return False
    if cfg.reviewer_allowlist and c.author not in cfg.reviewer_allowlist and not is_allowed_bot:
        return False
    lowered = body.lower()
    if any(lowered.startswith(p.lower()) for p in cfg.trigger_prefixes):
        return True
    if any(t.lower() in lowered for t in cfg.trigger_tags):
        return True
    return cfg.route_changes_requested and c.state == "CHANGES_REQUESTED"


def render_review_item(c: Comment) -> str:
    where = f" on `{c.path}` line {c.line}" if c.path else ""
    quoted = "\n".join("> " + line for line in (c.body or "(no text)").splitlines()) or "> (no text)"
    return f"### [{c.key}] Review comment by @{c.author}{where}\n{c.url}\n\n{quoted}"


def render_ci_item(key: str, run: dict, log: str, max_lines: int) -> str:
    return (f"### [{key}] CI failure: {run.get('workflowName', 'workflow')}\n{run.get('url', '')}\n\n"
            f"Failing step output (last {max_lines} lines):\n```\n{log}\n```")


def load_prompt(name: str) -> Template:
    return Template((ROUTER_DIR / "prompts" / name).read_text(encoding="utf-8"))


def build_prompt(pr: dict, events: list[Event]) -> str:
    items = "\n\n".join(e.detail for e in events)
    return load_prompt("feedback.md").safe_substitute(
        pr_number=pr["number"], pr_title=pr.get("title", ""), branch=pr["headRefName"], items=items)


def build_command(cfg: Config, prompt: str, branch: str) -> list[str]:
    rules = load_prompt("rules.md").safe_substitute(branch=branch)
    cmd = [cfg.claude_command, "-p", prompt, "--output-format", "json",
           "--permission-mode", cfg.permission_mode, "--max-turns", str(cfg.max_turns)]
    if cfg.session in ("fork", "continue"):
        cmd.append("--continue")
    if cfg.session == "fork":
        cmd.append("--fork-session")
    if cfg.model:
        cmd += ["--model", cfg.model]
    if cfg.allowed_tools:
        cmd += ["--allowedTools", ",".join(cfg.allowed_tools)]
    if cfg.disallowed_tools:
        cmd += ["--disallowedTools", ",".join(cfg.disallowed_tools)]
    cmd += ["--append-system-prompt", rules]
    return cmd


# --------------------------------------------------------------------------- agent processes

class Handle(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...


class ProcessHandle:
    def __init__(self, proc: subprocess.Popen, out, err):
        self.proc, self._out, self._err = proc, out, err

    def poll(self) -> int | None:
        rc = self.proc.poll()
        if rc is not None:
            self._out.close()
            self._err.close()
        return rc

    def terminate(self) -> None:
        self.proc.terminate()


class DetachedHandle:
    """A run started by a previous router process. Done when its JSON output is complete."""

    def __init__(self, out_path: Path, started: float, max_seconds: float):
        self.out_path, self.started, self.max_seconds = out_path, started, max_seconds

    def poll(self) -> int | None:
        try:
            json.loads(self.out_path.read_text(encoding="utf-8"))
            return 0
        except (OSError, ValueError):
            return -1 if time.time() - self.started > self.max_seconds else None

    def terminate(self) -> None:
        pass  # cannot signal a process we did not start; timeout escalates instead


class ProcessSpawner:
    def spawn(self, cmd: list[str], cwd: Path, out_path: Path, err_path: Path) -> Handle:
        out = open(out_path, "w", encoding="utf-8")
        err = open(err_path, "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=err, stdin=subprocess.DEVNULL, text=True)
        return ProcessHandle(proc, out, err)


@dataclass
class Run:
    pr: int
    branch: str
    worktree: str
    keys: list[str]
    out_path: Path
    started: float
    handle: Handle


# --------------------------------------------------------------------------- router

class Router:
    def __init__(self, cfg: Config, repo_root: Path, gh, spawner, *,
                 owners_fn: Callable[[Path], dict[str, Path]] = worktrees_by_branch,
                 dry_run: bool = False, echo: bool = True):
        self.cfg, self.repo_root, self.gh, self.spawner = cfg, repo_root, gh, spawner
        self.owners_fn, self.dry_run, self.echo = owners_fn, dry_run, echo
        self.state_dir = repo_root / cfg.state_dir
        self.logs_dir = self.state_dir / "logs"
        self.state_path = self.state_dir / "router-state.json"
        self.events_path = self.state_dir / "events.jsonl"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()
        self.handled: set[str] = set(self.state["handled"])
        self.running: dict[str, Run] = {}
        self._recover_runs()

    # ---- persistence

    def _load_state(self) -> dict:
        base = {"handled": [], "attempts": {}, "escalated": [], "seen": [], "running": {}}
        if self.state_path.exists():
            base.update(json.loads(self.state_path.read_text(encoding="utf-8")))
        return base

    def _save(self) -> None:
        if self.dry_run:
            return
        self.state["handled"] = sorted(self.handled)
        self.state["running"] = {
            wt: {"pr": r.pr, "branch": r.branch, "keys": r.keys,
                 "out": str(r.out_path), "started": r.started}
            for wt, r in self.running.items()
        }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def _log(self, event: str, **data: Any) -> None:
        record = {"ts": now_iso(), "event": event, **data}
        if self.echo:
            detail = " ".join(f"{k}={v}" for k, v in data.items())
            print(f"[{record['ts']}] {event} {detail}", flush=True)
        if not self.dry_run:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    def _recover_runs(self) -> None:
        max_s = self.cfg.max_run_minutes * 60
        for wt, r in self.state.get("running", {}).items():
            out = Path(r["out"])
            self.running[wt] = Run(r["pr"], r["branch"], wt, r["keys"], out, r["started"],
                                   DetachedHandle(out, r["started"], max_s))

    # ---- main cycle

    def cycle(self) -> None:
        self._reap()
        owners = self.owners_fn(self.repo_root)
        for pr in self.gh.open_prs(self.cfg.require_label):
            try:
                self._handle_pr(pr, owners)
            except Exception as exc:  # one bad PR must not stop the others
                self._log("error", pr=pr.get("number"), error=str(exc))
        self._save()

    def _handle_pr(self, pr: dict, owners: dict[str, Path]) -> None:
        number, key = int(pr["number"]), str(pr["number"])
        if pr.get("isDraft"):
            return
        labels = {lbl["name"] for lbl in pr.get("labels") or []}
        if self.cfg.escalation_label in labels:
            return  # a human owns this PR right now
        if key in self.state["escalated"]:
            self.state["escalated"].remove(key)
            self.state["attempts"].pop(key, None)
            self._log("resumed", pr=number)
        if self.cfg.baseline_existing and key not in self.state["seen"]:
            self._baseline(pr)
        owner = owners.get(pr["headRefName"])
        if owner is None or str(owner) in self.running:
            return
        if len(self.running) >= self.cfg.max_concurrent:
            return
        events = self._collect(pr)
        if not events:
            return
        attempts = self.state["attempts"].setdefault(key, {"ci": 0, "review": 0})
        limits = {"ci": self.cfg.max_ci_attempts, "review": self.cfg.max_review_attempts}
        exhausted = sorted(k for k in {e.kind for e in events} if attempts[k] >= limits[k])
        if exhausted:
            self._escalate(number, f"Retry budget exhausted for: {', '.join(exhausted)}. "
                                   f"Pending items: {', '.join(e.key for e in events)}.")
            if not self.dry_run:
                self.handled.update(e.key for e in events)
            return
        self._dispatch(pr, owner, events, attempts)

    def _baseline(self, pr: dict) -> None:
        """First time a PR is seen: treat existing review comments as already handled."""
        if self.dry_run:
            return
        for c in self._comments(pr["number"]):
            self.handled.add(c.key)
        self.state["seen"].append(str(pr["number"]))
        self._log("baselined", pr=pr["number"])

    # ---- feedback collection

    def _collect(self, pr: dict) -> list[Event]:
        events: list[Event] = []
        if self.cfg.route_ci:
            events += self._ci_events(pr)
        if self.cfg.route_reviews:
            events += self._review_events(pr)
        return events

    def _ci_events(self, pr: dict) -> list[Event]:
        runs = [r for r in self.gh.runs_for(pr["headRefName"]) if r.get("headSha") == pr["headRefOid"]]
        failed = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") in CI_FAILED]
        attempts = self.state["attempts"].get(str(pr["number"]))
        if runs and attempts and not failed and all(r.get("status") == "completed" for r in runs):
            attempts["ci"] = 0  # green again: reset the CI retry budget
        events = []
        for run in failed:
            key = f"ci:{run['databaseId']}"
            if key in self.handled:
                continue
            log = tail(self.gh.failed_log(run["databaseId"]), self.cfg.max_log_lines)
            events.append(Event("ci", key, f"{run.get('workflowName')} failed",
                                render_ci_item(key, run, log, self.cfg.max_log_lines)))
        return events

    def _comments(self, number: int) -> list[Comment]:
        reviews = self.gh.reviews(number)
        inline = self.gh.review_comments(number)
        changes_requested = {r["id"] for r in reviews if r.get("state") == "CHANGES_REQUESTED"}
        reviews_with_inline = {c.get("pull_request_review_id") for c in inline}
        comments: list[Comment] = []
        for r in reviews:
            user = r.get("user") or {}
            has_body = bool((r.get("body") or "").strip())
            lone_cr = r.get("state") == "CHANGES_REQUESTED" and r["id"] not in reviews_with_inline
            if has_body or lone_cr:
                comments.append(Comment("review", r["id"], user.get("login", ""), user.get("type", ""),
                                        r.get("body") or "", r.get("state", ""), url=r.get("html_url", "")))
        for c in inline:
            user = c.get("user") or {}
            state = "CHANGES_REQUESTED" if c.get("pull_request_review_id") in changes_requested else ""
            comments.append(Comment("inline", c["id"], user.get("login", ""), user.get("type", ""),
                                    c.get("body") or "", state, c.get("path", ""),
                                    c.get("line") or c.get("original_line"), c.get("html_url", "")))
        for c in self.gh.issue_comments(number):
            user = c.get("user") or {}
            comments.append(Comment("conversation", c["id"], user.get("login", ""), user.get("type", ""),
                                    c.get("body") or "", url=c.get("html_url", "")))
        return comments

    def _review_events(self, pr: dict) -> list[Event]:
        return [Event("review", c.key, f"@{c.author} {c.source}", render_review_item(c))
                for c in self._comments(pr["number"])
                if c.key not in self.handled and should_route(c, self.cfg)]

    # ---- dispatch, completion, escalation

    def _dispatch(self, pr: dict, owner: Path, events: list[Event], attempts: dict) -> None:
        number, branch = int(pr["number"]), pr["headRefName"]
        cmd = build_command(self.cfg, build_prompt(pr, events), branch)
        keys = [e.key for e in events]
        if self.dry_run:
            print(f"[dry-run] PR #{number} -> {owner}: {len(events)} item(s): {', '.join(keys)}")
            print(f"[dry-run] command: {cmd[0]} -p <prompt> {' '.join(cmd[3:12])} ...")
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        out_path = self.logs_dir / f"pr{number}-{stamp}.json"
        err_path = self.logs_dir / f"pr{number}-{stamp}.err"
        handle = self.spawner.spawn(cmd, owner, out_path, err_path)
        self.running[str(owner)] = Run(number, branch, str(owner), keys, out_path, time.time(), handle)
        self.handled.update(keys)
        for kind in {e.kind for e in events}:
            attempts[kind] += 1
        self._log("dispatched", pr=number, worktree=owner.name, items=",".join(keys))

    def _reap(self) -> None:
        for wt, run in list(self.running.items()):
            rc = run.handle.poll()
            if rc is None:
                if time.time() - run.started > self.cfg.max_run_minutes * 60:
                    run.handle.terminate()
                    del self.running[wt]
                    self._escalate(run.pr, f"Agent run exceeded {self.cfg.max_run_minutes} minutes "
                                           f"and was stopped. Log: `{run.out_path.name}`.")
                continue
            del self.running[wt]
            self._complete(run, rc)

    def _complete(self, run: Run, rc: int) -> None:
        try:
            data = json.loads(run.out_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        result = str(data.get("result") or "")
        failed = rc != 0 or not data or bool(data.get("is_error"))
        cost = data.get("total_cost_usd")
        if failed:
            self._escalate(run.pr, f"Agent run failed (exit {rc}). Log: `{run.out_path.name}`.")
            return
        decisions = [line.split(NEEDS_DECISION, 1)[1].strip()
                     for line in result.splitlines() if NEEDS_DECISION in line]
        if decisions:
            self._escalate(run.pr, "The agent needs a human decision:\n\n"
                           + "\n".join(f"- {q}" for q in decisions))
        cost_line = f"\n\nRun cost: ${cost:.2f}" if isinstance(cost, (int, float)) else ""
        self.gh.comment(run.pr, f"{MARKER}\n**Factory router** routed {len(run.keys)} item(s) to the "
                                f"owning agent on `{run.branch}`.\n\n<details><summary>Agent summary"
                                f"</summary>\n\n{result[:3000]}\n\n</details>{cost_line}")
        self._log("completed", pr=run.pr, items=",".join(run.keys),
                  needs_decision=bool(decisions), cost=cost)

    def _escalate(self, number: int, reason: str) -> None:
        label = self.cfg.escalation_label
        self.gh.add_label(number, label)
        self.gh.comment(number, f"{MARKER}\n**Factory router - human decision needed**\n\n{reason}\n\n"
                                f"Remove the `{label}` label to resume automatic routing.")
        if not self.dry_run and str(number) not in self.state["escalated"]:
            self.state["escalated"].append(str(number))
        self._log("escalated", pr=number, reason=reason.splitlines()[0])

    # ---- status view

    def status(self) -> None:
        owners = self.owners_fn(self.repo_root)
        running = self.state.get("running", {})
        running_by_pr = {r["pr"]: r for r in running.values()}
        rows = [("PR", "Branch", "Owner", "CI", "Review", "State")]
        for pr in self.gh.open_prs(self.cfg.require_label):
            n = int(pr["number"])
            labels = {lbl["name"] for lbl in pr.get("labels") or []}
            owner = owners.get(pr["headRefName"])
            att = self.state["attempts"].get(str(n), {"ci": 0, "review": 0})
            if n in running_by_pr:
                mins = int((time.time() - running_by_pr[n]["started"]) / 60)
                state = f"agent running {mins}m"
            elif self.cfg.escalation_label in labels:
                state = "NEEDS YOU"
            elif pr.get("isDraft"):
                state = "draft (ignored)"
            elif owner is None:
                state = "no local worktree"
            else:
                state = "watching"
            rows.append((f"#{n}", pr["headRefName"], owner.name if owner else "-",
                         f"{att['ci']}/{self.cfg.max_ci_attempts}",
                         f"{att['review']}/{self.cfg.max_review_attempts}", state))
        widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
        for r in rows:
            print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))
        if self.events_path.exists():
            print("\nRecent events:")
            for line in self.events_path.read_text(encoding="utf-8").splitlines()[-10:]:
                e = json.loads(line)
                extra = " ".join(f"{k}={v}" for k, v in e.items() if k not in ("ts", "event"))
                print(f"  {e['ts']}  {e['event']:<11} {extra}")


# --------------------------------------------------------------------------- setup and CLI

def setup(cfg: Config, repo_root: Path, gh: GitHub) -> None:
    gh.ensure_label(cfg.require_label, "5319e7", "Owned by the agent factory; feedback is auto-routed")
    gh.ensure_label(cfg.escalation_label, "d93f0b", "Factory paused; a human decision is needed")
    (repo_root / cfg.state_dir / "logs").mkdir(parents=True, exist_ok=True)
    gitignore = repo_root / ".gitignore"
    entry = f"{cfg.state_dir}/"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if entry not in existing.splitlines():
        with gitignore.open("a", encoding="utf-8") as f:
            f.write(("" if existing.endswith("\n") or not existing else "\n") + entry + "\n")
    print(f"Labels '{cfg.require_label}' and '{cfg.escalation_label}' ready; state in {entry}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route CI failures and review comments to owning agents.")
    parser.add_argument("command", choices=["setup", "once", "watch", "status"])
    parser.add_argument("--config", type=Path, default=ROUTER_DIR / "config.toml")
    parser.add_argument("--dry-run", action="store_true", help="read GitHub, change nothing, spawn nothing")
    args = parser.parse_args(argv)

    cfg = Config.load(args.config)
    repo_root = repo_root_from_cwd()
    gh = GitHub(dry_run=args.dry_run)
    if args.command == "setup":
        setup(cfg, repo_root, gh)
        return 0
    router = Router(cfg, repo_root, gh, ProcessSpawner(), dry_run=args.dry_run)
    if args.command == "status":
        router.status()
    elif args.command == "once":
        router.cycle()
    else:
        print(f"Factory router watching (poll {cfg.poll_seconds}s, max {cfg.max_concurrent} concurrent). "
              f"Ctrl+C to stop; running agents keep going and are picked up on restart.")
        try:
            while True:
                try:
                    router.cycle()
                except Exception as exc:
                    router._log("error", error=str(exc))
                time.sleep(cfg.poll_seconds)
        except KeyboardInterrupt:
            router._save()
            print("Router stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
