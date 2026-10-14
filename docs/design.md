# FactoryKit v1 - Design

This is the source of truth for FactoryKit v1. Every decision here was reviewed and confirmed by the owner. Do not change a decision without asking the owner first; if something cannot be built as designed, stop and propose options (see `CLAUDE.md`).

## 1. Purpose and principles

FactoryKit is a light, reusable way to deliver software on any GitHub repo with Claude Code agents, without building a heavy factory.

- Deliver software; do not build a factory to maintain.
- One repeatable process for new ideas, defects and PRs, identical on every project.
- The owner approves **what** gets built (spec, design, tickets). Machines verify **how** (CI, independent review, code-enforced guards). The owner sees exceptions, not details.
- Every decision and state change for a PR lives in the PR, or one readable link away.
- Claude Code + VS Code first. Cursor and Codex compatibility later (section 16).
- Simplicity wins ties. If a feature needs a second mechanism, look for a way to fold it into an existing one.

## 2. Operating model

- One VS Code window per project, at most 2 projects at a time. The owner always works in the project's normal folder and never manages git worktrees.
- Planning phases (shape, spec, design, tickets, triage) run interactively in the owner's main Claude Code session.
- Builders are Claude Code background subagents with `isolation: worktree`. Claude creates their worktrees; the dispatcher removes each one after its PR is merged or closed (ADR 0016).
- Up to `max_parallel` items build at once per project (default 2, range 1 to 3). Only tickets whose blockers are all merged may start.
- Projects are GitHub repos. Issues, PRs, checks, labels and rules on `main` are the system of record.

## 3. Components

### Installed, not written by us
- **Matt Pocock's skills** (`mattpocock/skills`): the workflow's skill layer. Installed once at user level, never edited, pinned to a tagged version by `scripts/sync-skills`.

### Written by us (this repo)
| Component | Purpose |
|---|---|
| `agents/builder.md` | Background, worktree-isolated builder subagent |
| `agents/reviewer.md` | Read-only reviewer definition used by the dispatcher |
| `skills/design-doc/` | High-level design, low-level design and sequence diagrams |
| `skills/address-feedback/` | Manual fix path when `auto_fix` is off |
| `templates/` | `AGENTS.md`, `CLAUDE.md`, `factory.md`, PR description |
| `scripts/setup-project` | One-time setup of a project repo |
| `scripts/sync-skills` | Pin and install Matt's skills and our agents/skills |
| `dispatcher/` | Watcher: reviewer runs, merge verdicts, auto_fix with guards |
| `dispatcher/dashboard` | Local read-only dashboard |
| `.vscode/tasks.json` | Start dispatcher, open dashboard, run setup |

## 4. Workflow

### Lane A: new idea or feature
| Phase | Skill | Output | Gate |
|---|---|---|---|
| Shape | `/grill-with-docs` | Decision records (ADRs) and glossary entries | |
| Spec | `/to-spec` | Spec issue | |
| Design | `/design-doc` | HLD update and LLD with sequence diagrams (when needed) | **Gate 1: owner approves spec + design by merging the docs PR** |
| Plan | `/to-tickets` | Ticket issues with acceptance criteria and blockers | **Gate 2: owner checks every acceptance criterion is testable; starting the build is the approval** |
| Build | builder subagent | Draft PR early, marked ready with the handback description | |
| Review | dispatcher reviewer | PR review "Round N of 2" + `dispatcher/review` status | |
| Fix | auto_fix, or `/address-feedback` | Fix commits, reply per comment, summary | |
| Merge | GitHub auto-merge or owner | Merged PR with verdict recorded | **Gate 3: only PRs held for the owner** |

`/retro` runs every few items to tighten checks and rules.

### Lane B: defect or PR
| Phase | Skill | Output |
|---|---|---|
| Triage | `/triage` | Agent brief, or `needs-info` / `wontfix` / `needs-decision` |
| Diagnose (hard bugs only) | `/diagnosing-bugs` | Root cause before any fix |
| Design (only if triage finds an architectural fix) | `/design-doc` | LLD update |
| Build to Merge | as Lane A | |

### Q&A standard for interactive phases
Matt's grilling format: numbered rounds, a recommended answer per question, each question worded so "yes" accepts the recommendation, no action until the owner confirms. A phase ends only when its artifact has no TBDs and every acceptance criterion is testable.

### Planning documents go through a docs PR
`main` is protected, so `/to-spec` and `/design-doc` output (ADRs, glossary, HLD, LLD) is committed on a `docs/spec-<issue#>` branch and opened as a docs PR linked from the spec issue. Merging it records Gate 1. This is a rule in `factory.md`, not an edit to Matt's skills.

## 5. Architecture documents (`/design-doc`)

- **HLD**: one living document per repo, `docs/architecture/hld.md`. Context, components and responsibilities, data flows, deployment, non-functional requirements (reliability, security, performance). Created on the project's first idea; updated only when a spec changes the architecture.
- **LLD**: one per spec when non-trivial, `docs/architecture/lld/<spec#>-<name>.md`. Modules and interfaces, data model, error handling and retries, sequence diagrams.
- **"Needed" test**: an LLD is required when a spec touches more than one module, adds an interface or data model, or integrates something external. Sequence diagrams are required for any interaction between two or more parties with async work, retries or failure paths. The skill states its classification explicitly in the docs PR so the owner can overrule it at Gate 1.
- Diagrams are Mermaid inside markdown (GitHub renders them).
- Q&A only for architecture choices still open after shaping, in the grilling format.
- Builders read the LLD; the reviewer's Spec axis includes it. A builder that must deviate updates the LLD in the same PR.

## 6. Labels (8)

| Label | Meaning | Applied by |
|---|---|---|
| `bug`, `enhancement` | Category | `/triage` |
| `needs-triage`, `needs-info`, `ready-for-agent`, `wontfix` | Triage state | Matt's skills |
| `needs-decision` | A human must decide before work continues | `/triage` (issues), dispatcher (PRs) |
| `no-dispatch` | Dispatcher ignores this PR entirely | Owner |

`ready-for-human` is not used. `triage-labels.md` records: "ready-for-human: not used. If an agent should not implement an issue, apply needs-decision and state why."

## 7. The PR is the record

### PR description (template in `templates/pr-description.md`)
```
Closes #42
Trace: ticket #42 "<title>" -> spec #30 "<title>" -> docs PR #31
Started by @<owner> on <date> from ticket #42

## What changed
## Verification
<commands run and their results>
## Review notes and open questions
<self-review findings not fixed, judgement calls; marked AI-generated>
```

### Comments on the PR
- Independent reviews titled "Round N of 2", with `[blocking]` tags, marked AI-generated.
- Each automatic or manual fix: reply per addressed comment plus a one-line summary, the auto_fix mode it ran under, guard results, run cost.
- Escalations with the reason.
- Any decision the owner gives in chat, posted as "Decision by @<owner>: ..." before the agent acts on it.
- The merge verdict: "Auto-merge: low risk (212 lines, no risky paths)" or "Held for you: touches migrations/".

### Deliberately outside the PR
Dispatcher state, running processes, Claude sessions, temporary worktrees (rebuildable or disposable), the dashboard (a view), and the shaping conversation itself (its decisions are kept as ADRs).

## 8. Builder agent

- Claude Code subagent, `isolation: worktree`, `background: true`.
- Before starting: read the ticket (Lane A) or agent brief (Lane B), its parent spec, the LLD if any, and `docs/agents/factory.md`.
- Follows Matt's `/implement` flow: `tdd` at agreed seams, typecheck and single tests regularly, full suite at the end, `code-review` self-check, fix every hard standards violation and every spec gap (missing, wrong, out of scope) before committing. If a subagent cannot invoke `/implement` (verification V3), the builder definition repeats those steps and calls `tdd` and `code-review` directly.
- Opens a draft PR right after its first commit with the trace block; marks it ready when done with the full handback description.
- Pushes only its own branch. Never pushes `main`, never merges, never force-pushes.
- Emits `NEEDS_DECISION: <question and options>` instead of guessing on ambiguity, tradeoffs, scope, security, data handling or public interfaces.

## 9. Reviewer

- Run by the dispatcher on every PR that is ready (not draft), and after every push to a ready PR.
- Separate process, fresh session, read-only tools, in a temporary worktree at the PR head that the dispatcher creates and deletes.
- Default: same harness as the builder, different model (configurable).
- Runs Matt's `code-review` skill against the merge-base. Inputs: diff, linked ticket and spec, LLD, repo standards.
- Posts one PR review per round. Blocking = hard standards violations, missing or wrong spec items, out-of-scope work.
- Round 2 and later: only new commits and previously raised items; no new nitpicks.

## 10. Dispatcher v1

Evolves from `reference/factory-router/` (v0, with tests). Python 3.11+, standard library, `git`, `gh`, Claude Code CLI.

For each project in `~/factory/projects.toml`, each poll (default 60 s):
1. Skip draft PRs and PRs labeled `no-dispatch`.
2. Flag PRs missing `Closes #N` or the trace block (comment once).
3. On a ready PR or new push: run the reviewer, post the review, set commit status `dispatcher/review` (success if no blocking findings).
4. If blocking findings or failed CI: apply `auto_fix` (section 11), or post once that `/address-feedback` is needed.
5. After 2 review rounds with blockers, or 3 CI fix attempts: apply `needs-decision` with the reason.
6. When CI and review pass: evaluate merge eligibility (section 12), post the verdict, enable GitHub auto-merge if allowed.
7. Reload `projects.toml` every poll; changes apply to the next event.

The dispatcher never edits code itself. It runs agents, inspects their diffs, pushes guarded fixes, and writes to GitHub.

## 11. auto_fix

- Values: `off`, `ci`, `ci_and_review`. Default `ci_and_review`. Set per project in `projects.toml`.
- Acts only on ready PRs, never drafts (a draft means a builder is still working).
- One fix per PR at a time (lock). At most 2 concurrent fixes across all projects, separate from builders.
- Fix agent: headless Claude Code in a temporary worktree on the PR branch, given the failing CI log or blocking comments. It **commits only**.
- The dispatcher inspects the fix diff **in code** and pushes only if all guards pass; otherwise it applies `needs-decision`:
  - no deleted test files and no added skip markers (`.skip`, `xit`, `@pytest.mark.skip`, and equivalents)
  - no CI configuration changes
  - no files under `risky_paths`
  - no dependency manifest changes
- Limits per PR: 3 CI fix attempts, 2 review rounds.
- Every fix, guard result and cost is posted on the PR.
- Changing the setting mid-build: edit `projects.toml` and save. Picked up within one poll; a running fix finishes (still guarded); nothing new starts under the old value.

## 12. Merge policy (solo developer)

- GitHub does not allow a PR author to approve their own PR, so no approval count is required.
- Ruleset on `main`: changes through a PR only; required checks: CI and `dispatcher/review`; force-push and deletion blocked.
- `merge_mode` per project in `projects.toml`: `auto-low-risk` (default) or `manual`.
- Low risk = CI green, review passed, no `needs-decision`, fewer than about 400 changed lines, no dependency manifest change, no files under `risky_paths`.
- Everything else is held for the owner with the reason posted.
- The dashboard lists recent auto-merges for a weekly skim. If problems show up, switch that project to `manual` or lower its `auto_fix`.

## 13. Settings

### `~/factory/projects.toml` (local, dispatcher-only, change any time)
```toml
[notify-service]
path = "~/code/notify-service"
auto_fix = "ci_and_review"     # off | ci | ci_and_review
merge_mode = "auto-low-risk"   # manual | auto-low-risk
```

### `docs/agents/factory.md` (in each project repo, read by agents and dispatcher, changed via PR)
- Verify commands (test, typecheck, lint, build).
- `risky_paths` (defaults: auth, migrations, CI config, infrastructure).
- `max_parallel` (default 2, range 1 to 3).
- Reviewer model.
- The FactoryKit rules block: docs PR for planning output, trace block, post decisions before acting, builder rules.

Rule of thumb: settings agents read live in the repo; settings only the dispatcher reads live in `projects.toml`.

## 14. Dashboard v1

- Local web page (standard library HTTP server, bound to 127.0.0.1), opened in VS Code's built-in browser.
- Project selector; default view is a "Needs you" inbox across all projects.
- Per-project board: Triage, Spec, Ready, Building, In review, Needs you, Ready to merge, Done (with recent auto-merges).
- Shows each project's current `auto_fix` and `merge_mode`, and per-PR cost.
- Read-only. Links only (PR, issue, open in VS Code). Decisions and merges happen on GitHub.

Columns are derived, not maintained: labels for triage states, PR draft/ready state, checks, dispatcher state.

## 15. Managing Matt's skills

- Never edit upstream skill files.
- Customize in this order: per-repo config (`docs/agents/*.md`, `AGENTS.md`), then wrapper skills that call his, and only as a last resort an owned copy under our own name.
- `scripts/sync-skills` installs a specific tagged version at user level.
- Upgrade procedure: read his changelog, diff the skills we use, bump the pin, dogfood one item, commit. Roll back by reverting the commit. Do not upgrade with items mid-build.

## 16. Portability (side note, not v1 work)

Keep these choices so Cursor and Codex can be added later without redesign:
- `AGENTS.md` is the single instructions source; `CLAUDE.md` imports it (`@AGENTS.md`). Run Matt's setup before creating `CLAUDE.md`, because his setup edits whichever file exists.
- Enforcement lives outside any harness: dispatcher guards, branch rules, disposable worktrees.
- The dispatcher's agent calls go through one adapter function so other CLIs can be added.

## 17. Deferred

Starting builds from the dashboard; Cursor and Codex adapters; a bot account for the reviewer; a LangGraph layer; GitHub Projects boards; visual design review (lavish).

## 18. Verifications before building (see build plan step 0)

- V1: current Claude Code CLI flags for headless runs.
- V2: installing Matt's skills pinned to a tag at user level.
- V3: can a subagent run `/implement` (marked user-invoked only)?
- V4: can a headless run invoke the `code-review` skill?
- V5: `isolation: worktree` + `background: true` subagents behave as documented.
- V6: does the owner's GitHub plan support rulesets and required checks on private repos?

## 19. Decision log (basis for `docs/adr/`)

| # | Decision | Rejected alternatives |
|---|---|---|
| 1 | Keep orchestration in our own repo | Agent Orchestrator (young, ownership churn, extra surface) |
| 2 | VS Code + Claude Code first; Cursor/Codex later | Visual Studio (weaker agent support); Cursor first |
| 3 | Matt Pocock's skills as the skill layer | Writing six custom skills; firstmate; MVF-style LangGraph factory |
| 4 | Never edit upstream skills; config, wrappers, owned copy last | Forking and editing |
| 5 | Label set of 8, no `ready-for-human`, no opt-in label | Phase labels; a `factory` opt-in label |
| 6 | Independent reviewer run by the dispatcher, 2 rounds | Self-review only; human relay; custom `/review-pr` |
| 7 | One VS Code window per project; agents own worktrees | Owner-managed worktrees; headless builds from dashboard |
| 8 | `max_parallel` default 2, blockers respected | Single item at a time |
| 9 | No required approvals; checks plus `merge_mode` | Required self-approval (impossible on GitHub) |
| 10 | No custom brief template; Matt's ticket and brief formats | firstmate-style brief with paths |
| 11 | PR as the record, links to issues are fine | Restating spec in every PR |
| 12 | `/design-doc` for HLD/LLD with Mermaid sequence diagrams | Overloading `/to-spec`; ad hoc docs |
| 13 | auto_fix in v1 with code-enforced guards | Deferring auto_fix |
| 14 | One local `projects.toml` for dispatcher settings | Three-level override scheme |
| 15 | Build the kit with Claude Code on the owner's machine | Building in a remote sandbox with a token |
