# FactoryKit v1 - Build plan

Build in order. One step per branch and PR (`build/step-N-<name>`). At the end of each step: run its checks, update `docs/progress.md`, open the PR, summarize for the owner, and stop until the owner says to continue.

Source of truth: `docs/design.md`. Starting code for the dispatcher: `reference/factory-router/` (v0, with tests).

---

## Step 0 - Verify the unknowns (no product code)

Create a throwaway scratch repo outside this repo for the experiments. Record every result, command and output summary in `docs/verification.md`, with the chosen path for each.

| Check | How | If it fails |
|---|---|---|
| V1 CLI flags | `claude --version`, `claude --help`. Confirm `-p`, `--output-format json`, `--permission-mode`, `--allowedTools`, `--disallowedTools`, `--append-system-prompt`, `--model`, `--max-turns`, `--continue`/`--resume` | Record the actual flags; the dispatcher's adapter uses them |
| V2 Pinned skills | Find the latest tag of `mattpocock/skills`; install that version at user level (copy, not the auto-updating plugin) | Record the working install method |
| V3 `/implement` from a subagent | In the scratch repo, define a test subagent and ask it to run `/implement` on a tiny ticket | Builder definition repeats `/implement`'s steps and calls `tdd` and `code-review` |
| V4 `code-review` headless | `claude -p` in the scratch repo asking it to use the code-review skill on a small diff | Reviewer prompt embeds the review instructions |
| V5 Worktree subagents | Subagent with `isolation: worktree` and `background: true`; confirm `/tasks` shows it, the worktree is created and cleaned up | Record actual behavior; adjust builder definition |
| V6 GitHub plan | Ask the owner for their plan; on a scratch private repo, try creating a ruleset with required checks via `gh api` | Fallback: `merge_mode = manual` for private repos on unsupported plans |

**Done when:** `docs/verification.md` has a result and a chosen path for V1 to V6, and the owner has reviewed it. If any result changes a design decision, stop and propose options before continuing.

---

## Step 1 - Repo skeleton and documentation

- `README.md`: what FactoryKit is, prerequisites, install, daily use on one page.
- `docs/workflow.md`: lanes, phases, gates, and exactly what the owner checks at each gate.
- `docs/settings.md`: `projects.toml` and `factory.md`, every setting, defaults, and how to change `auto_fix` and `merge_mode` mid-build.
- `docs/upgrades.md`: pinning and upgrading Matt's skills.
- `docs/adr/0001-*.md` to `0015-*.md`: one decision record per row of the decision log in `docs/design.md` section 19 (context, decision, rejected alternatives, consequences).

**Done when:** every setting in design sections 11 to 13 is documented in `docs/settings.md`; 15 ADRs exist; no doc contradicts `docs/design.md`.

---

## Step 2 - Templates and skill sync

- `templates/AGENTS.md`: project instructions including the FactoryKit rules block.
- `templates/CLAUDE.md`: a single line importing `@AGENTS.md`.
- `templates/factory.md`: verify commands, `risky_paths`, `max_parallel`, reviewer model, rules block (docs PR for planning output, trace block, post decisions before acting, builder rules).
- `templates/pr-description.md`: trace block and sections from design section 7.
- `templates/triage-labels-note.md`: the `ready-for-human` rule.
- `scripts/sync-skills`: installs Matt's skills at the pinned tag plus our `agents/` and `skills/` at user level; `--check` mode reports drift; pin stored in `skills.lock`.

**Done when:** `sync-skills --check` runs cleanly after a sync; templates render with placeholder values; tests for the sync script pass.

---

## Step 3 - Project setup script

`scripts/setup-project <path-to-repo>`:
1. Checks prerequisites (`git`, `gh` authenticated, `claude`, Python 3.11+).
2. Asks: verify commands, `max_parallel` (default 2), `merge_mode` (default auto-low-risk), `auto_fix` (default ci_and_review), `risky_paths` (show defaults), reviewer model.
3. Tells the owner to run Matt's `/setup-matt-pocock-skills` first (it creates `docs/agents/*` and edits the instructions file), then writes `AGENTS.md`, the one-line `CLAUDE.md`, and `docs/agents/factory.md`.
4. Creates the 8 labels (design section 6).
5. Creates the ruleset on `main` (design section 12), or explains the fallback from V6.
6. Registers the project in `~/factory/projects.toml`.
7. Supports `--dry-run` (prints every change, makes none).

**Done when:** a dry run against the scratch repo prints the full plan; a real run on the scratch repo produces labels, ruleset, files and a registry entry; re-running is safe (idempotent).

---

## Step 4 - Agents and our two skills

- `agents/builder.md`: design section 8 (uses V3 and V5 results).
- `agents/reviewer.md`: design section 9, read-only tools.
- `skills/design-doc/SKILL.md`: design section 5, including the "needed" classification statement and Mermaid sequence diagram rules.
- `skills/address-feedback/SKILL.md`: checks out the PR branch, refuses with uncommitted changes, pulls failing CI logs and `[blocking]` comments, fixes via a background builder, replies per comment, posts a summary with the trace of what changed.

**Done when:** on the scratch repo, one tiny ticket goes from `ready-for-agent` to a ready PR via the builder, with a correct trace block and handback description; `/design-doc` produces an LLD with a sequence diagram for a sample multi-party spec.

---

## Step 5 - Dispatcher v1

Evolve `reference/factory-router/` into `dispatcher/` (keep its test approach: fake GitHub, fake spawner). Implement design sections 10 to 12:
- Multi-project registry from `~/factory/projects.toml`, reloaded every poll.
- Reviewer runs in a temporary worktree at PR head; review posted as "Round N of 2"; `dispatcher/review` commit status.
- Trace block and `Closes #N` check.
- auto_fix with modes, per-PR lock, global cap of 2, fix agent commits only, code-enforced guards, dispatcher pushes.
- Limits (3 CI attempts, 2 review rounds) and `needs-decision` escalation.
- Merge verdict and GitHub auto-merge for low-risk PRs.
- One agent adapter function (design section 16).
- Every action recorded on the PR (design section 7).

**Done when:** unit tests cover every rule above (including each guard rejecting a bad fix, settings reload mid-run, round limits, verdicts); a live run on the scratch repo reviews a PR, auto-fixes a deliberate lint failure, and auto-merges a low-risk PR.

---

## Step 6 - Dashboard and VS Code tasks

- `dispatcher/dashboard`: design section 14.
- `.vscode/tasks.json`: start dispatcher, open dashboard, run setup on a project, run sync-skills.

**Done when:** the dashboard shows two registered projects with the selector, the Needs-you inbox, each board column, current settings, and recent auto-merges; it makes no writes.

---

## Step 7 - Dogfood

On a real project: run one Lane A item (with an LLD) and one Lane B defect end to end. Then run `/retro`, record findings in `docs/progress.md`, and fix what blocks routine use.

**Done when:** both items merged through the intended gates with complete PR records, and the owner agrees FactoryKit is ready for daily use.
