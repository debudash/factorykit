# Step 0 - Verification results

Date: 2026-10-14. Machine: owner's Windows 11 laptop. Claude Code 2.1.300, git 2.54.0, Python 3.13.5, gh 2.102.0 (installed during this step via `winget install --id GitHub.cli`).

Scratch area: `D:\Dev\factorykit-scratch\` (outside this repo). It holds `repo/` (a tiny Python project with `TICKET-1.md` and two test subagents), the cloned skills at `mp-skills-v1.3.1/`, and the raw JSON output of each run (`v3.json`, `v4.json`, `v5.json`, `v5b.json`).

## Summary

| Check | Result | Chosen path |
|---|---|---|
| V1 CLI flags | All present. `--max-turns` works but is hidden from `--help` | Adapter uses the flags below; also caps spend with `--max-budget-usd` |
| V2 Pinned skills | `v1.3.1` copied to `~/.claude/skills/`; plugin uninstalled | `sync-skills` copies the plugin's skill list at a tag and writes a lock file |
| V3 `/implement` from a subagent | Refused (`disable-model-invocation`). `tdd` loads | Fallback: builder definition repeats `/implement`'s steps, calls `tdd` and `code-review` |
| V4 `code-review` headless | Works; Matt's user-level skill shadows the built-in one | Reviewer calls the skill; dispatcher passes merge-base SHA and diff in the prompt |
| V5 Worktree subagents | Background and worktree work. Worktrees with commits are **not** cleaned up | Dispatcher removes them after merge or close (ADR 0016) |
| V6 GitHub plan | Rulesets, branch protection and auto-merge refused on a private repo: GitHub treats `debudash` as Free | Needs owner decision (see V6) |

## V1 - CLI flags

Commands: `claude --version`, `claude --help`, plus real `-p` runs in V3 to V5.

| Flag | Status | Notes |
|---|---|---|
| `-p` / `--print` | OK | Skips the workspace trust dialog |
| `--output-format json` | OK | Single object. Useful keys: `result`, `is_error`, `subtype`, `num_turns`, `total_cost_usd`, `session_id`, `permission_denials`, `subagent_stats` |
| `--permission-mode` | OK | Choices: `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan` |
| `--allowedTools` / `--disallowedTools` | OK | Space or comma separated, patterns like `Bash(git diff:*)` |
| `--append-system-prompt` | OK | Listed in help |
| `--model` | OK | Aliases (`sonnet`, `opus`, `haiku`, `fable`) or full names |
| `--max-turns` | OK, hidden | Not in `--help`; accepted in a real run (`num_turns: 1`). Unknown flags fail with `unknown option` |
| `--continue` / `--resume` | OK | Listed in help |

Useful extras for the adapter: `--max-budget-usd` (per-run spend cap, `-p` only), `--permission-prompts none` (auto-deny anything that would prompt), `--no-session-persistence`, `--json-schema` (structured output), `--fallback-model`.

## V2 - Pinned skills

- Latest tag: `v1.3.1` (commit `24fe0ef`), from `git ls-remote --tags https://github.com/mattpocock/skills.git`.
- Found: the owner already had the auto-updating plugin `mattpocock-skills@claude-plugins-official` v1.2.3. Matt's README warns that the plugin plus a copied set gives every skill twice.
- Owner decision: replace the plugin with a pinned copy.
- Method that worked:
  1. `git clone --depth 1 --branch v1.3.1 https://github.com/mattpocock/skills.git`
  2. Copy each path in `.claude-plugin/plugin.json` `"skills"` (27 skills) to `~/.claude/skills/<name>/`, refusing on name collision (none).
  3. Write `~/.claude/skills/.mattpocock-skills.lock` (source, tag, commit, method).
  4. `claude plugins uninstall mattpocock-skills@claude-plugins-official`
- Result: skills appear at user level with plain names (`tdd`, `code-review`, `pr`, ...), no plugin prefix.
- For Step 2: `sync-skills` should use the plugin manifest as the list of skills, so it follows Matt's own choice of what ships. It also needs a manifest of copied names so it can remove skills he deletes upstream (v1.3.0 removed `resolving-merge-conflicts`).

Worth knowing from the v1.3.x changelog (no design change proposed):
- `CONTEXT.md` was renamed to `GLOSSARY.md` everywhere.
- New `implement-spec` skill: runs a whole spec with parallel worktree implementers onto an integration branch. It overlaps our builder plus `max_parallel`, but it is user-invoked and not part of our flow.
- New `pr` skill (model-invoked): a PR body format. Our builder's handback description follows `templates/pr-description.md`; the `pr` skill may get invoked automatically when a builder writes a PR body. Watch for this in Step 4.

## V3 - `/implement` from a subagent

Setup: `repo/.claude/agents/v3-implementer.md` tells the subagent to call the Skill tool with `implement` on `TICKET-1.md`, then try `tdd`.

```
claude -p "Use the v3-implementer subagent ..." --output-format json --permission-mode dontAsk \
  --allowedTools "Agent Skill Read Glob Grep" --model sonnet --max-budget-usd 2
```

Result (cost $0.22): `V3_RESULT: implement=refused tdd=ok`. The main headless session was refused too, with "the skill has disable-model-invocation set". The same flag is on `triage`, `to-spec`, `to-tickets`, `retro`, `grill-with-docs` and `setup-matt-pocock-skills`, which are all owner-driven phases, so that matches the design.

Chosen path: the design's fallback. `agents/builder.md` repeats `/implement`'s steps (read ticket, spec, LLD; `tdd` at seams; typecheck and single tests; full suite; `code-review` self-check; fix hard violations and spec gaps; commit) and calls `tdd` and `code-review` through the Skill tool.

## V4 - `code-review` headless

Setup: branch `v4-diff` adds `subtract()` that returns `a + b` and has no test. The run happens in a temporary worktree (`git worktree add ../wt-v4 v4-diff`), as the dispatcher will do.

```
claude -p "Call the Skill tool with \"code-review\" ..." --output-format json --permission-mode dontAsk \
  --allowedTools "Skill Agent Read Glob Grep Bash(git diff:*) Bash(git log:*) ..." \
  --disallowedTools "Edit Write NotebookEdit" --model sonnet --max-budget-usd 3
```

Result (cost $0.24): `V4_RESULT: skill=loaded source=matt blocking=3`. It loaded `~/.claude/skills/code-review` (Matt's), not Claude Code's built-in `code-review`, so the user-level skill wins the name clash. It found all three real problems: wrong operator, missing test, unmet acceptance criteria.

Caveat: the model built one compound command (`cd ... && MB=$(git merge-base ...) && ...`), which the narrow allowlist denied (see `permission_denials`). It then reviewed by reading files instead of the diff, and did not spawn the skill's two parallel sub-agents.

Chosen path: the reviewer calls `code-review` through the Skill tool. The dispatcher computes the merge-base SHA and the diff itself and puts both in the reviewer prompt, along with the ticket, spec and LLD paths. Allowed tools: `Skill Agent Read Glob Grep` plus read-only git subcommands. Edits are disallowed. The worktree is disposable anyway.

## V5 - Worktree subagents (`isolation: worktree`, `background: true`)

Setup: `repo/.claude/agents/v5-worktree.md` with both settings; it writes `V5.txt` and commits.

Results:
- Background: `subagent_stats.started_in_background: 1`. The frontmatter overrode the caller's `run_in_background: false`, so the builder will always run in the background.
- Worktree created at `.claude/worktrees/agent-<id>`, on a new branch `worktree-agent-<id>` based on the current HEAD.
- Commit made in the worktree (`a22d0e7 v5 test`); main checkout untouched.
- **Cleanup: a worktree with commits is kept** (still in `git worktree list` after the session ended). A second agent that made no changes (`v5-noop`) had its worktree removed automatically.
- The main checkout shows `?? .claude/worktrees/` as untracked.
- `/tasks` is an interactive view and was not checked in a headless run. Owner can confirm it in Step 4's live builder run.

Effect on the design: section 2 says "Claude creates and cleans up their worktrees". That only holds for worktrees with no changes, and every builder commits. Section 8 also expects a meaningful branch, but the default branch name is `worktree-agent-<id>`.

Chosen path (owner decision, `docs/adr/0016-dispatcher-cleans-up-builder-worktrees.md`): the dispatcher removes a builder's leftover worktree and local branch once its PR is merged or closed. Also, `setup-project` adds `.claude/worktrees/` to `.gitignore`, and the builder creates its own branch name (for example `agent/<ticket#>-<slug>`) before its first push.

## V6 - GitHub plan and rulesets

Owner's stated plan: Pro. **GitHub treats `debudash` as Free** for private repos.

Steps:
1. `gh auth login` by the owner (account `debudash`, keyring). `gh api user` does not return the plan name with this token's scopes.
2. `gh repo create debudash/factorykit-scratch --private --source . --push`: OK.
3. `gh api -X POST repos/debudash/factorykit-scratch/rulesets --input ruleset.json` (rules: `deletion`, `non_fast_forward`, `pull_request` with 0 approvals, `required_status_checks` `ci` and `dispatcher/review`):
   `HTTP 403 "Upgrade to GitHub Pro or make this repository public to enable this feature."`
4. Classic branch protection, `PUT .../branches/main/protection`: same 403.
5. `PATCH repos/... allow_auto_merge=true`: no error, but it stays `false`. GitHub auto-merge also needs protection, so on this plan it is unavailable for private repos.

Effect on the design: sections 4 (docs PR because `main` is protected), 10 step 6 (enable GitHub auto-merge) and 12 (ruleset, `merge_mode = auto-low-risk`) assume protection on `main`. On private repos under this account, none of that is enforced by GitHub.

Chosen path: pending owner decision (options in the Step 0 summary). The scratch repo `debudash/factorykit-scratch` (private) stays for later steps until the owner says to delete it.
