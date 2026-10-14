# FactoryKit

A light, reusable kit for delivering software on any GitHub repo with Claude Code agents: one repeatable process for new ideas, defects and PRs, an independent AI reviewer, guarded automatic fixes, and a local dashboard. You approve what gets built; machines verify how.

**Status:** build in progress. See `docs/progress.md`. Commands below that are not built yet are marked with the build step that adds them.

## What you get

| Piece | What it does |
|---|---|
| Matt Pocock's skills | The workflow's skill layer (`/grill-with-docs`, `/to-spec`, `/to-tickets`, `/triage`, `tdd`, `code-review`, ...), pinned to a tagged version |
| `/design-doc` | High-level design, low-level design and Mermaid sequence diagrams |
| Builder agent | Background Claude Code subagent that builds one ticket in its own worktree and opens the PR |
| Dispatcher | Local watcher: runs an independent reviewer on every ready PR, fixes CI and review failures under guards, decides auto-merge or "held for you" |
| `/address-feedback` | Manual fix path when automatic fixes are off |
| Dashboard | Local, read-only page with a "Needs you" inbox and a board per project |

## Prerequisites

- Windows, macOS or Linux with VS Code and Claude Code (CLI on your PATH).
- `git`, and the GitHub CLI `gh` logged in (`gh auth login`).
- Python 3.11 or newer.
- Project repos on GitHub. Branch rules on `main` need a public repo or a GitHub Pro (or higher) account; otherwise a project runs with `merge_mode = "manual"` (see `docs/adr/0017-public-repos-for-now.md`).

## Install (once per machine)

1. Clone this repo.
2. Install the pinned skills and our agents and skills at user level (Step 2):
   ```
   python scripts/sync-skills
   ```
   If you have Matt's skills as the Claude Code plugin, uninstall it first; having both gives every skill twice.

## Set up a project (once per repo)

1. Run the setup script. Start with a dry run:
   ```
   python scripts/setup-project <path-to-repo> --dry-run
   python scripts/setup-project <path-to-repo>
   ```
   It asks for your verify commands, the name of the CI check, and your settings. It writes `AGENTS.md` and `docs/agents/factory.md`, creates the 8 labels and the ruleset on `main`, and registers the project in `~/factory/projects.toml`.
2. In the project, run Matt's `/setup-matt-pocock-skills` in Claude Code and accept its defaults. It creates `docs/agents/` and edits `AGENTS.md`. (`CLAUDE.md` must not exist yet, or his setup edits that instead; the script takes care of this.)
3. Run `python scripts/setup-project <path-to-repo>` again. It writes the one-line `CLAUDE.md` and the triage note, and opens a setup PR labelled `no-dispatch`. Merge it yourself (choose "bypass rules" on the PR, see ADR 0018).

Re-running the script is safe: it only changes what is missing or out of date, and never overwrites `docs/agents/factory.md` or your own text.

## Daily use

1. Start the dispatcher once for all your projects: `python -m dispatcher watch` from this repo (Step 6 adds a VS Code task "FactoryKit: start dispatcher" and the dashboard). `python -m dispatcher once --dry-run` shows what it would do without changing anything; `python -m dispatcher status` lists what it is tracking.
2. **New idea (Lane A):** in Claude Code, run `/grill-with-docs`, then `/to-spec`, then `/design-doc`. Review and merge the docs PR (Gate 1). Run `/to-tickets` and check that every acceptance criterion is testable (Gate 2). Ask Claude to build a ticket; the builder runs in the background.
3. **Defect or outside PR (Lane B):** run `/triage`. Use `/diagnosing-bugs` for hard bugs. Then build as in Lane A.
4. **Then wait for exceptions.** The dispatcher reviews, fixes and merges low-risk PRs. You only look at PRs "Held for you" (Gate 3) or labelled `needs-decision`. The dashboard's "Needs you" inbox lists them.
5. Every few items, run `/retro` to tighten checks and rules.

What you check at each gate is in `docs/workflow.md`. Every setting is in `docs/settings.md`. Upgrading Matt's skills is in `docs/upgrades.md`.

## Repo layout

| Path | Contents |
|---|---|
| `docs/design.md` | The confirmed design (source of truth) |
| `docs/build-plan.md`, `docs/progress.md` | How the kit is being built, and where it stands |
| `docs/adr/` | Decision records |
| `docs/verification.md` | Step 0 checks of Claude Code and GitHub behaviour |
| `agents/`, `skills/` | Builder and reviewer agents, `/design-doc`, `/address-feedback` (Step 4) |
| `templates/` | Files written into each project (Step 2) |
| `scripts/` | `sync-skills` (Step 2), `setup-project` (Step 3) |
| `dispatcher/` | The watcher and dashboard (Steps 5 and 6) |
| `reference/factory-router/` | v0 of the dispatcher, kept unchanged as a baseline |
