# Settings

FactoryKit has two settings files. The rule of thumb: **settings agents read live in the repo; settings only the dispatcher reads live in `projects.toml`.**

| File | Where | Read by | Changed by |
|---|---|---|---|
| `~/factory/projects.toml` | Your machine, one file for all projects | Dispatcher only | Editing and saving it, any time |
| `docs/agents/factory.md` | Each project repo | Agents and the dispatcher | A PR to the project |

## `~/factory/projects.toml`

One table per project. `setup-project` adds the table; you edit it by hand afterwards.

```toml
[notify-service]
path = "~/code/notify-service"
auto_fix = "ci_and_review"     # off | ci | ci_and_review
merge_mode = "auto-low-risk"   # manual | auto-low-risk
```

| Key | Values | Default | Meaning |
|---|---|---|---|
| table name | text | set by `setup-project` | The project's name |
| `path` | folder path (`~` allowed) | set by `setup-project` | The project's normal working folder |
| `auto_fix` | `off`, `ci`, `ci_and_review` | `ci_and_review` | What the dispatcher may fix by itself (below) |
| `merge_mode` | `manual`, `auto-low-risk` | `auto-low-risk` | Whether low-risk PRs merge without you (below) |

The dispatcher reloads this file every poll (every 60 seconds), so a change applies to the next event. There is no per-PR or global override; this file is the only place these two settings live.

### `auto_fix`

| Value | When CI fails on a ready PR | When the review has blocking findings |
|---|---|---|
| `off` | Posts once that `/address-feedback` is needed | Posts once that `/address-feedback` is needed |
| `ci` | Runs a fix agent | Posts once that `/address-feedback` is needed |
| `ci_and_review` | Runs a fix agent | Runs a fix agent |

How a fix runs, whatever the value:
- Only on ready PRs, never drafts. A draft means a builder is still working.
- One fix per PR at a time, and at most 2 fixes at once across all projects (separate from builders).
- The fix agent is headless Claude Code in a temporary worktree on the PR branch, given the failing CI log or the blocking comments. It commits only; the dispatcher does the push.
- The dispatcher inspects the fix diff in code and pushes only if every guard passes:

  | Guard | Rejects a fix that |
  |---|---|
  | Tests | deletes a test file or adds a skip marker (`.skip`, `xit`, `@pytest.mark.skip` and equivalents) |
  | CI | changes CI configuration |
  | Risky paths | touches a file under `risky_paths` |
  | Dependencies | changes a dependency manifest |

  A rejected fix is not pushed; the PR gets `needs-decision` with the guard that failed.
- Limits per PR: 3 CI fix attempts and 2 review rounds. After that the PR gets `needs-decision`.
- Every fix, its guard results and its cost are posted on the PR.

These rules are fixed in v1. Only `auto_fix` itself is a setting.

### `merge_mode`

| Value | When CI and review pass |
|---|---|
| `auto-low-risk` | A low-risk PR gets "Auto-merge: low risk (...)" and GitHub auto-merge is enabled. Anything else gets "Held for you: <reason>" |
| `manual` | Every PR gets "Held for you" and you merge it |

Low risk means all of: CI green, review passed, no `needs-decision`, fewer than about 400 changed lines, no dependency manifest change, no files under `risky_paths`.

`auto-low-risk` relies on the ruleset on `main` (PR only; required checks: CI and `dispatcher/review`; force-push and deletion blocked; repo admins may bypass through a PR only, ADR 0018). No approval count is required, because GitHub does not let a PR's author approve it. `setup-project` creates the ruleset. On a private repo under a GitHub Free account, GitHub refuses rulesets and auto-merge, so that project uses `manual` (ADR 0017).

The dashboard lists recent auto-merges for a weekly skim. If problems show up, switch that project to `manual` or lower its `auto_fix`.

### Changing `auto_fix` or `merge_mode` mid-build

1. Open `~/factory/projects.toml` and change the value in that project's table.
2. Save. Nothing else to restart.

What happens next:
- The dispatcher picks the change up within one poll (about 60 seconds).
- A fix already running finishes, and its diff still goes through the guards.
- Nothing new starts under the old value.
- A PR that already has GitHub auto-merge enabled keeps it. To stop that one PR merging, disable auto-merge on it (the PR page, or `gh pr merge <N> --disable-auto`).
- Builders are unaffected; neither setting changes how builders work.

## `docs/agents/factory.md`

Written by `setup-project` from `templates/factory.md` (Step 2). Agents read it before every build and review; the dispatcher reads `risky_paths` and the reviewer model from it. Change it through a PR like any other file.

| Setting | Default | Used by | Meaning |
|---|---|---|---|
| Verify commands: test, typecheck, lint, build | asked by `setup-project` | Builder, fix agent, reviewer | Exact commands to prove a change works. Leave a command empty if the project does not have it |
| `risky_paths` | auth, migrations, CI config, infrastructure (exact globs shown by `setup-project`) | Dispatcher guards and merge verdict | Paths a fix may never touch and that always hold a PR for you |
| `max_parallel` | 2 (range 1 to 3) | Main session when starting builders | How many tickets build at once in this project |
| Reviewer model | a model different from the builder's | Dispatcher | The model the independent reviewer runs on. Same harness as the builder |
| FactoryKit rules block | from the template | All agents | The rules below |

The rules block contains:
- **Docs PR for planning output:** `/to-spec` and `/design-doc` output goes on a `docs/spec-<issue#>` branch and is opened as a docs PR linked from the spec issue.
- **Trace block:** every PR description starts with `Closes #N`, the trace line (ticket, spec, docs PR) and who started it.
- **Post decisions before acting:** a decision given in chat is posted on the PR as "Decision by @<owner>: ..." before the agent acts on it.
- **Builder rules:** push only its own branch; never push `main`, merge or force-push; print `NEEDS_DECISION:` instead of guessing.

## `.claude/settings.json` deny rules

`setup-project` adds these to the project's `.claude/settings.json` (keeping anything already there). They apply to your Claude Code sessions in the project and to every agent, because agents run with your `gh` login:

| Rule | Why |
|---|---|
| `Bash(gh pr merge *)` | Merging is GitHub's job (auto-merge) or yours on the PR page |
| `Bash(git push --force *)`, `Bash(git push -f *)`, `Bash(git push --force-with-lease *)` | Pushed history is never rewritten |
| `Bash(gh api *rulesets*)`, `Bash(gh api *branches/*/protection*)` | Agents never change the rules on `main` |

Remove a rule through a PR if a project needs to. Agent definition files cannot deny single commands, which is why these live here.

## Fixed values in v1

These are not settings. They are listed so you know where the numbers come from.

| Value | Where it applies |
|---|---|
| Poll every 60 seconds (design: "default 60 s"; whether it becomes a setting is decided in Step 5) | Dispatcher |
| 2 concurrent fixes across all projects | `auto_fix` |
| 3 CI fix attempts, 2 review rounds per PR | `auto_fix`, escalation |
| About 400 changed lines | Low-risk test |
| At most 2 projects at a time | Operating model |

## Labels

Not settings, but created by `setup-project` and read by the dispatcher.

| Label | Meaning | Applied by |
|---|---|---|
| `bug`, `enhancement` | Category | `/triage` |
| `needs-triage`, `needs-info`, `ready-for-agent`, `wontfix` | Triage state | Matt's skills |
| `needs-decision` | A human must decide before work continues | `/triage` (issues), dispatcher (PRs) |
| `no-dispatch` | The dispatcher ignores this PR entirely | You |

`ready-for-human` is not used. If an agent should not implement an issue, apply `needs-decision` and state why.
