"""Derive the board from GitHub data and dispatcher state. Pure functions: no I/O, no writes.

Columns are derived, not maintained (design section 14): labels for triage states, PR draft or
ready state, the dispatcher's verdict and running work, and recently merged PRs.
"""
import re
from dataclasses import dataclass, field

COLUMNS = ["Triage", "Spec", "Ready", "Building", "In review", "Needs you", "Ready to merge", "Done"]
TRIAGE_LABELS = {"needs-triage", "needs-info"}
CLOSES = re.compile(r"(?im)^\s*(closes|fixes|resolves)\s+#(\d+)\b")
DESIGN_FOR = re.compile(r"(?i)^design for #(\d+)")


@dataclass
class Card:
    project: str
    kind: str  # issue | pr
    number: int
    title: str
    url: str
    note: str = ""
    cost: float = 0.0
    links: list = field(default_factory=list)  # (text, url) pairs, e.g. the ticket a PR closes


@dataclass
class Board:
    project: str
    path: str
    settings: dict
    columns: dict
    recent_auto_merges: list
    error: str = ""


def labels_of(item):
    return {label["name"] for label in item.get("labels") or []}


def is_spec(issue, design_targets):
    return (bool((issue.get("subIssuesSummary") or {}).get("total"))
            or issue["number"] in design_targets
            or issue.get("title", "").lower().startswith("spec"))


def pr_column(pr, st, running_kind):
    """(column, note) for an open PR."""
    labels = labels_of(pr)
    if "needs-decision" in labels:
        return "Needs you", "needs-decision: read the dispatcher's last comment"
    if pr.get("isDraft"):
        return "Building", "draft: a builder is working on it"
    if "no-dispatch" in labels:
        gate = " (Gate 1: approve the design by merging)" if DESIGN_FOR.match(pr.get("title", "")) else ""
        return "Needs you", "no-dispatch: review and merge it yourself" + gate
    verdict = (st or {}).get("verdict")
    if verdict and verdict.get("sha") == pr.get("headRefOid"):
        if verdict.get("auto"):
            return "Ready to merge", "auto-merge enabled, waiting for GitHub"
        return "Needs you", verdict.get("message", "Held for you")
    if running_kind:
        return "In review", f"{running_kind} running"
    if not st or st.get("reviewed_sha") != pr.get("headRefOid"):
        return "In review", "waiting for review"
    if (st.get("blocking") or 0) > 0:
        return "In review", f"{st['blocking']} blocking finding(s), round {st.get('rounds', 0)}"
    return "In review", "review passed, waiting for CI"


def build_board(project, settings, issues, open_prs, merged_prs, state, repo_name="", error=""):
    """project: settings.Project; settings: dict shown as-is; state: the dispatcher's state dict."""
    columns = {c: [] for c in COLUMNS}
    prs_state, runs = state.get("prs", {}), state.get("runs", {})
    key = lambda n: f"{project.name}#{n}"
    issue_urls = {i["number"]: i.get("url", "") for i in issues}

    closed_by_open_pr = set()
    design_targets = set()
    for pr in open_prs + merged_prs:
        if m := DESIGN_FOR.match(pr.get("title", "")):
            design_targets.add(int(m.group(1)))
    for pr in open_prs:
        refs = [int(m.group(2)) for m in CLOSES.finditer(pr.get("body") or "")]
        closed_by_open_pr.update(refs)
        st = prs_state.get(key(pr["number"]))
        column, note = pr_column(pr, st, (runs.get(key(pr["number"])) or {}).get("kind"))
        columns[column].append(Card(
            project.name, "pr", pr["number"], pr.get("title", ""), pr.get("url", ""), note,
            (st or {}).get("cost", 0.0), [(f"#{r}", issue_urls.get(r, "")) for r in refs]))

    for issue in issues:
        n, labels = issue["number"], labels_of(issue)
        if n in closed_by_open_pr:
            continue  # shown on its PR's card
        card = Card(project.name, "issue", n, issue.get("title", ""), issue.get("url", ""))
        if "needs-decision" in labels:
            card.note = "needs-decision"
            columns["Needs you"].append(card)
        elif "wontfix" in labels:
            continue
        elif is_spec(issue, design_targets):
            card.note = "design PR open or merged" if n in design_targets else "spec"
            columns["Spec"].append(card)
        elif labels & TRIAGE_LABELS or "ready-for-agent" not in labels:
            card.note = ", ".join(sorted(labels & TRIAGE_LABELS)) or "not triaged"
            columns["Triage"].append(card)
        else:
            card.note = "ready-for-agent"
            columns["Ready"].append(card)

    auto = {a["pr"]: a for a in state.get("auto_merges", [])}
    for pr in merged_prs:
        st = prs_state.get(key(pr["number"])) or {}
        note = "auto-merged" if key(pr["number"]) in auto else "merged"
        columns["Done"].append(Card(project.name, "pr", pr["number"], pr.get("title", ""), pr.get("url", ""),
                                    f"{note} {str(pr.get('mergedAt', ''))[:10]}".strip(), st.get("cost", 0.0)))
    recent = [a for a in reversed(state.get("auto_merges", [])) if a["pr"].startswith(f"{project.name}#")][:10]
    return Board(project.name, str(project.path), settings, columns, recent, error)


def inbox(boards):
    """The default view: every Needs-you card across all projects."""
    return [card for b in boards for card in b.columns["Needs you"]]
