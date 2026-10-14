"""Local read-only dashboard: standard-library HTTP server on 127.0.0.1 (design section 14).

The data source only has read methods, and the server only answers GET, so nothing here can
change GitHub, the repos or the dispatcher's state. Decisions and merges happen on GitHub.
"""
import html
import json
import shutil
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from ..settings import load_registry, parse_factory_md
from .board import COLUMNS, build_board, inbox

CACHE_SECONDS = 30


class ReadOnlySource:
    """Everything the dashboard reads: registry, dispatcher state, and gh read calls."""

    def __init__(self, registry_path, state_path):
        self.registry_path, self.state_path = Path(registry_path), Path(state_path)
        self.gh = shutil.which("gh") or "gh"
        self._cache = {}

    def _gh(self, cwd, *args):
        p = subprocess.run([self.gh, *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8")
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or f"gh {args[0]} failed")
        return p.stdout

    def _json(self, cwd, *args):
        return json.loads(self._gh(cwd, *args) or "[]")

    def projects(self):
        return load_registry(self.registry_path)

    def state(self):
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def board(self, project, state, refresh=False):
        hit = self._cache.get(project.name)
        if hit and not refresh and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        settings = {"auto_fix": project.auto_fix, "merge_mode": project.merge_mode}
        try:
            cwd = project.path
            try:
                raw = self._gh(cwd, "api", "repos/{owner}/{repo}/contents/docs/agents/factory.md",
                               "-H", "Accept: application/vnd.github.raw")
                repo = parse_factory_md(raw)
                settings.update(max_parallel=repo.max_parallel, reviewer_model=repo.reviewer_model,
                                risky_paths=", ".join(repo.risky_paths))
            except RuntimeError:
                settings["factory.md"] = "not on the default branch yet (defaults apply)"
            issues = self._json(cwd, "issue", "list", "--state", "open", "--limit", "200", "--json",
                                "number,title,labels,url,subIssuesSummary")
            open_prs = self._json(cwd, "pr", "list", "--state", "open", "--limit", "100", "--json",
                                  "number,title,headRefOid,isDraft,labels,body,url")
            merged = self._json(cwd, "pr", "list", "--state", "merged", "--limit", "10", "--json",
                                "number,title,url,mergedAt")
            board = build_board(project, settings, issues, open_prs, merged, state)
        except Exception as exc:
            board = build_board(project, settings, [], [], [], state, error=str(exc))
        self._cache[project.name] = (time.time(), board)
        return board


# ---------------------------------------------------------------- HTML

CSS = """
:root { --bg:#f7f7f5; --panel:#fff; --ink:#1d1d1b; --muted:#6b6b66; --line:#e2e1dc; --accent:#1f6feb;
        --you:#b42318; --you-bg:#fdecea; --ok:#1a7f37; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151515; --panel:#1e1e1e; --ink:#ececec; --muted:#9a9a95; --line:#333; --accent:#58a6ff;
          --you:#ff8c82; --you-bg:#3a1d1b; --ok:#56d364; } }
* { box-sizing:border-box; } body { margin:0; font:14px/1.45 system-ui,sans-serif; background:var(--bg); color:var(--ink); }
header { display:flex; gap:16px; align-items:center; flex-wrap:wrap; padding:12px 16px; border-bottom:1px solid var(--line); background:var(--panel); }
header h1 { font-size:16px; margin:0 12px 0 0; } nav a { margin-right:12px; } a { color:var(--accent); text-decoration:none; }
nav a.on { font-weight:600; color:var(--ink); } main { padding:16px; } h2 { font-size:15px; margin:20px 0 8px; }
.muted { color:var(--muted); } .err { color:var(--you); }
table { border-collapse:collapse; width:100%; background:var(--panel); } td, th { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
.settings { display:flex; gap:8px 20px; flex-wrap:wrap; margin:0 0 12px; } .settings b { font-weight:600; }
.board { display:grid; grid-template-columns:repeat(8, minmax(170px, 1fr)); gap:10px; overflow-x:auto; }
.col { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:8px; min-height:80px; }
.col h3 { font-size:13px; margin:0 0 6px; } .col.you { border-color:var(--you); } .col.you h3 { color:var(--you); }
.card { border:1px solid var(--line); border-radius:5px; padding:6px; margin-bottom:6px; } .card .note { color:var(--muted); font-size:12px; }
.pill { display:inline-block; padding:0 6px; border-radius:9px; background:var(--you-bg); color:var(--you); font-size:12px; }
@media (max-width: 700px) { .board { grid-template-columns:1fr; } }
"""


def esc(value):
    return html.escape(str(value), quote=True)


def card_html(c, show_project=False):
    kind = "PR" if c.kind == "pr" else "Issue"
    links = " ".join(f'<a href="{esc(u)}">{esc(t)}</a>' for t, u in c.links)
    cost = f' <span class="muted">${c.cost:.2f}</span>' if c.cost else ""
    project = f'<span class="muted">{esc(c.project)}</span> ' if show_project else ""
    return (f'<div class="card">{project}<a href="{esc(c.url)}">{kind} #{c.number}</a>{cost}<br>{esc(c.title)}'
            f'{"<br>closes " + links if links else ""}<div class="note">{esc(c.note)}</div></div>')


def page(title, nav, body):
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta http-equiv=refresh content=60><title>{esc(title)}</title><style>{CSS}</style></head>"
            f"<body><header><h1>FactoryKit</h1><nav>{nav}</nav>"
            f'<span class="muted">read-only, refreshes every minute</span></header><main>{body}</main></body></html>')


def nav_html(projects, current):
    items = [("/", "Needs you", current is None)] + [(f"/p/{quote(p.name)}", p.name, current == p.name) for p in projects]
    return "".join(f'<a class="{"on" if on else ""}" href="{href}">{esc(text)}</a>' for href, text, on in items)


def settings_html(board):
    rows = "".join(f"<span>{esc(k)}: <b>{esc(v)}</b></span>" for k, v in board.settings.items())
    vscode = f'<a href="vscode://file/{quote(Path(board.path).as_posix())}">Open in VS Code</a>'
    err = f'<p class="err">Could not read GitHub: {esc(board.error)}</p>' if board.error else ""
    return f'<div class="settings">{rows}<span>{vscode}</span></div>{err}'


def auto_merges_html(items):
    if not items:
        return '<p class="muted">No auto-merges yet.</p>'
    rows = "".join(f'<tr><td><a href="{esc(a["url"])}">{esc(a["pr"])}</a></td><td>{esc(a["title"])}</td>'
                   f'<td>{esc(a["verdict"])}</td><td class="muted">{esc(a["at"][:16].replace("T", " "))}</td></tr>'
                   for a in items)
    return f"<table><tr><th>PR</th><th>Title</th><th>Verdict</th><th>When (UTC)</th></tr>{rows}</table>"


def render_inbox(projects, boards, errors):
    cards = inbox(boards)
    rows = "".join(f'<tr><td>{esc(c.project)}</td><td>{card_html(c)}</td></tr>' for c in cards) \
        or '<tr><td colspan=2 class="muted">Nothing needs you right now.</td></tr>'
    summary = "".join(
        f'<h2><a href="/p/{quote(b.project)}">{esc(b.project)}</a> '
        f'<span class="pill">{len(b.columns["Needs you"])} need you</span></h2>{settings_html(b)}' for b in boards)
    recent = [a for b in boards for a in b.recent_auto_merges]
    recent.sort(key=lambda a: a["at"], reverse=True)
    errs = "".join(f'<p class="err">{esc(e)}</p>' for e in errors)
    body = (f"{errs}<h2>Needs you, all projects</h2><table>{rows}</table>{summary}"
            f"<h2>Recent auto-merges (skim weekly)</h2>{auto_merges_html(recent[:15])}")
    return page("FactoryKit: needs you", nav_html(projects, None), body)


def render_board(projects, board):
    cols = "".join(
        f'<div class="col{" you" if name == "Needs you" else ""}"><h3>{esc(name)} ({len(board.columns[name])})</h3>'
        + ("".join(card_html(c) for c in board.columns[name]) or '<span class="muted">none</span>') + "</div>"
        for name in COLUMNS)
    body = (f"<h2>{esc(board.project)}</h2>{settings_html(board)}<div class=board>{cols}</div>"
            f"<h2>Recent auto-merges</h2>{auto_merges_html(board.recent_auto_merges)}")
    return page(f"FactoryKit: {board.project}", nav_html(projects, board.project), body)


# ---------------------------------------------------------------- HTTP

def make_handler(source):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            refresh = "refresh" in url.query
            projects, errors = source.projects()
            state = source.state()
            if url.path == "/":
                boards = [source.board(p, state, refresh) for p in projects]
                return self._send(200, render_inbox(projects, boards, errors))
            if url.path.startswith("/p/"):
                name = unquote(url.path[3:])
                match = next((p for p in projects if p.name == name), None)
                if match:
                    return self._send(200, render_board(projects, source.board(match, state, refresh)))
            self._send(404, page("Not found", nav_html(projects, None), "<p>No such page.</p>"))

        def _refuse(self):
            self._send(405, "The FactoryKit dashboard is read-only.", "text/plain")

        do_POST = do_PUT = do_PATCH = do_DELETE = _refuse

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    return Handler


def serve(source, port):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(source))
    return server
