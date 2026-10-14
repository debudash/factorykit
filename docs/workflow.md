# Workflow: lanes, phases and gates

The same process runs on every project. You approve **what** gets built at Gates 1 and 2. Machines verify **how**: CI, an independent reviewer, and guards enforced in code. You only see exceptions at Gate 3.

Planning phases run interactively in your main Claude Code session, in the project's normal folder. Building, reviewing and fixing run in the background.

## Lane A: new idea or feature

| Phase | Run | Output | Gate |
|---|---|---|---|
| Shape | `/grill-with-docs` | ADRs and glossary entries | |
| Spec | `/to-spec` | Spec issue | |
| Design | `/design-doc` | HLD update; LLD with sequence diagrams when needed | **Gate 1** |
| Plan | `/to-tickets` | Ticket issues with acceptance criteria and blockers | **Gate 2** |
| Build | Builder subagent | Draft PR after the first commit; marked ready with the handback description | |
| Review | Dispatcher reviewer | PR review "Round N of 2" and the `dispatcher/review` status | |
| Fix | `auto_fix`, or `/address-feedback` | Fix commits, a reply per comment, a summary | |
| Merge | GitHub auto-merge, or you | Merged PR with the verdict recorded | **Gate 3** (held PRs only) |

Run `/retro` every few items to tighten checks and rules.

## Lane B: defect or PR

| Phase | Run | Output |
|---|---|---|
| Triage | `/triage` | Agent brief, or `needs-info` / `wontfix` / `needs-decision` |
| Diagnose (hard bugs only) | `/diagnosing-bugs` | Root cause before any fix |
| Design (only if triage finds an architectural fix) | `/design-doc` | LLD update |
| Build to Merge | As Lane A | |

## The gates: what you check

### Gate 1: spec and design (merge the docs PR)
Planning output (ADRs, glossary, HLD, LLD) is committed on a `docs/spec-<issue#>` branch and opened as a docs PR linked from the spec issue. Merging it is your approval. Before merging, check:

| Check | Where |
|---|---|
| The spec says what you want, and nothing you don't | Spec issue |
| No TBDs remain in any document | Docs PR diff |
| The "LLD needed" classification is right. An LLD is required when the spec touches more than one module, adds an interface or data model, or integrates something external | The classification statement in the docs PR |
| Sequence diagrams exist for every interaction between two or more parties with async work, retries or failure paths | LLD |
| Architecture choices match the decisions made while shaping | HLD, LLD, ADRs |

To overrule the classification or a design choice, comment on the docs PR and ask Claude to revise it.

### Gate 2: tickets (starting the build is the approval)
After `/to-tickets`, check:

| Check | Where |
|---|---|
| Every acceptance criterion is testable: a test or command could prove it | Each ticket issue |

Then ask Claude to build. Up to `max_parallel` tickets build at once, and only tickets whose blockers are all merged may start.

### Gate 3: held PRs only
Most PRs need nothing from you. Gate 3 is a PR held for you. The table also lists the other signals that need you:

| Signal | Meaning | What you do |
|---|---|---|
| "Held for you: <reason>" | CI and review passed, but the PR is not low risk (about 400 or more changed lines, a dependency manifest change, or a file under `risky_paths`), or the project is `merge_mode = "manual"` | Read the PR and its review rounds, then merge or comment |
| `needs-decision` label | A fix failed a guard, 2 review rounds still had blockers, or 3 CI fix attempts failed | Read the escalation comment, decide, and post the decision |
| One-time "missing `Closes #N` or trace block" comment | The PR is not linked to its ticket | Ask the builder (or edit the description) to add it |

A builder that hits a question prints `NEEDS_DECISION:` with options; it reaches you in the Claude Code session that started it.

When you decide something in chat, Claude posts it on the PR as "Decision by @<you>: ..." before acting on it.

## Questions during interactive phases

Claude asks in numbered rounds, with a recommended answer for each question, worded so "yes" accepts the recommendation. Nothing happens until you confirm. A phase ends only when its artifact has no TBDs and every acceptance criterion is testable.

## What a builder does

- Reads the ticket (Lane A) or agent brief (Lane B), the parent spec, the LLD if any, and `docs/agents/factory.md`.
- Follows `/implement`'s steps itself (a subagent cannot call `/implement`; see `docs/verification.md` V3): `tdd` at agreed seams, typecheck and single tests regularly, the full suite at the end, a `code-review` self-check, and fixes for every hard standards violation and spec gap.
- Opens a draft PR right after its first commit, with the trace block. Marks it ready when done, with the full handback description.
- Pushes only its own branch. Never pushes `main`, never merges, never force-pushes.
- Prints `NEEDS_DECISION: <question and options>` instead of guessing on ambiguity, tradeoffs, scope, security, data handling or public interfaces.

Its worktree lives under `.claude/worktrees/`. The dispatcher removes it after the PR is merged or closed (ADR 0016).

## What the dispatcher does each poll

For each registered project:
1. Skips draft PRs and PRs labelled `no-dispatch`.
2. Flags PRs missing `Closes #N` or the trace block (comments once).
3. On a ready PR or a new push: runs the reviewer, posts the review, sets `dispatcher/review`.
4. On blocking findings or failed CI: applies `auto_fix`, or posts once that `/address-feedback` is needed.
5. After 2 review rounds with blockers, or 3 CI fix attempts: applies `needs-decision` with the reason.
6. When CI and review pass: posts the merge verdict and enables GitHub auto-merge if allowed.
7. Reloads `~/factory/projects.toml`.

The dispatcher never edits code. It runs agents, inspects their diffs, pushes guarded fixes and writes to GitHub.

## The PR is the record

Everything about a PR is on the PR, or one link away: the trace block (ticket, spec, docs PR), each review round, each fix with its guard results and cost, escalations, your decisions, and the merge verdict. Things deliberately not kept there: dispatcher state, processes, Claude sessions, temporary worktrees, the dashboard, and the shaping conversation (its decisions become ADRs).
