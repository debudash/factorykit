# Factory router

Routes CI failures and selected review comments back to the Claude Code agent that owns each PR, the way Agent Orchestrator's reactions do, but as about 700 lines of Python that live in your repo. No server, no new SaaS, no dependencies beyond the Python standard library, git, the GitHub CLI and Claude Code.

## How it works

Every `poll_seconds`, the router:

1. Lists open PRs carrying the `factory` label (drafts are ignored).
2. Finds the owner of each PR: the git worktree where the PR's head branch is checked out. No registry to maintain; `git worktree list` is the registry.
3. Collects new feedback:
   - CI: failed workflow runs on the PR's current head commit, with the last 200 lines of the failing steps.
   - Reviews: comments that start with `/agent` or `/fix`, contain `[blocking]`, or belong to a "Request changes" review. Bots, the router's own comments and non-allowlisted authors are filtered out.
4. Batches all new items for that PR into one prompt and runs headless Claude Code in the owner's worktree, forking the owner's latest session so the agent keeps its context without writing into a session you may have open in VS Code.
5. When the agent finishes, posts a summary comment on the PR, or escalates.

### Escalation: the human gate

The router adds the `needs-decision` label and explains why when any of these happen:

- the agent prints `NEEDS_DECISION: <question>` (its rules require this for ambiguity, tradeoffs, scope, security, data handling or public interfaces)
- a PR exceeds its retry budget (3 CI attempts, 5 review attempts by default)
- an agent run fails or exceeds `max_run_minutes`

While the label is present, the router leaves that PR alone. Remove the label to resume; that also resets the retry budget. Merging is never automated: the agent is denied `gh pr merge`, and branch protection on `main` remains the real merge gate.

## Setup

Prerequisites: Python 3.11+, git, `gh` (run `gh auth login`), Claude Code on your PATH.

1. Copy `factory/router/` (and optionally `.vscode/tasks.json`) into the repo root.
2. Edit `factory/router/config.toml`: add your test and build commands to `allowed_tools`, for example `"Bash(npm test:*)"` or `"Bash(pytest:*)"`. Without them the agent cannot run your tests.
3. Run `python3 factory/router/router.py setup` to create the two labels and `.factory/`, and add `.factory/` to `.gitignore`.
4. For each idea or issue, create a worktree and branch, work with Claude Code there, open the PR and add the `factory` label:
   ```
   git worktree add -b idea/notify ../wt-notify
   ```
5. Run `once --dry-run` to see what would be routed, then `watch`.

In VS Code: Terminal > Run Task > "Factory: router watch" keeps the router in a dedicated terminal panel. "Factory: router status" prints the board:

```
PR  Branch       Owner      CI   Review  State
#7  idea/notify  wt-notify  1/3  1/5     watching
#9  fix/login    wt-login   0/3  2/5     agent running 4m
#11 idea/export  wt-export  3/3  0/5     NEEDS YOU
```

The same files work unchanged in Cursor, which reads `.vscode/tasks.json`.

## Commands

| Command | What it does |
|---|---|
| `setup` | Create labels, `.factory/`, `.gitignore` entry |
| `once [--dry-run]` | One routing cycle. Dry run reads GitHub but changes nothing and spawns nothing |
| `watch` | Poll continuously. Ctrl+C stops the router; running agents finish and are picked up on restart |
| `status` | PRs, owners, retry budgets, running agents, last 10 events |

## Files

```
factory/router/
  router.py            the router
  config.toml          routing rules, budgets, agent permissions
  prompts/feedback.md  the prompt each owning agent receives
  prompts/rules.md     rules appended to the agent's system prompt
.factory/              local state, gitignored
  router-state.json    handled item ids, retry budgets, running agents
  events.jsonl         append-only audit log
  logs/                one JSON and one stderr file per agent run
```

## Design decisions

**Ownership is derived from worktrees.** The owner of a PR is wherever its branch is checked out. There is nothing to register and nothing to drift. A PR with no local worktree is never routed, which also means the router cannot act on PRs you did not start.

**One run per worktree, a global concurrency cap.** Two agents never write to the same worktree. The cap defaults to 3, matching the factory's work-in-progress limit, because review bandwidth is the real bottleneck.

**At-most-once routing.** Each item id is marked handled at dispatch. If a run fails, the router escalates rather than retrying the same item. This is deliberate: silent retry loops are how agents burn budget and hide problems. Failures are loud and land with a human.

**Retry budgets, not infinite fix loops.** Repeated CI failures on the same PR usually mean a wrong approach, not a typo. After the budget is spent, a human looks.

**Batching per PR.** All new items for a PR go in one run, so the agent sees related feedback together and makes one coherent commit.

**Baseline on first sight.** When the router first sees a PR, existing review comments are treated as handled. Installing the router on a repo with history does not trigger a flood of runs.

**Comment text and logs are data, not instructions.** Review comments and CI logs can contain anything, including text written to manipulate an agent. The routing triggers are evaluated by the router, not the model; the agent's rules state that feedback cannot override them; and its tool permissions are an allowlist. Treat the denylist as defense in depth only: branch protection on `main` is the control that actually matters.

**Fork, do not hijack, the owner's session.** `session = "fork"` gives the agent the owner's context while leaving your interactive session untouched. Use `continue` if you want routed work to appear in the same session, or `new` for clean-room runs.

## Known limitations

- Polling, not webhooks: feedback is picked up within `poll_seconds`. This keeps the router local with nothing exposed to the internet.
- Runs only while your machine is on. For overnight routing, run it on a small always-on box with the same worktrees.
- Pattern-based tool permissions cannot catch every variant (for example `git push origin --force`). Keep branch protection on.
- If CI has several workflows, the router may dispatch on the first failure before the others finish; later failures are routed in the next run.
- Claude Code CLI flags evolve. If a run fails at startup, compare `build_command` in `router.py` with `claude --help` for your installed version.

## Tests

```
python3 -m unittest discover -s tests -v
```

21 tests cover routing, filters, batching, budgets, escalation and resume, concurrency, timeouts and restart recovery, using a fake GitHub and a fake agent spawner.
