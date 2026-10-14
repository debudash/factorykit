# 0016 - Dispatcher cleans up builder worktrees

Status: accepted (owner, 2026-10-14, Step 0 verification V5)

## Context
Design section 2 says Claude creates and cleans up builder worktrees. Verification V5 showed that Claude Code removes a subagent's worktree only when the subagent made no changes. A builder always commits, so its worktree under `.claude/worktrees/agent-<id>` and its local branch stay behind. The owner must never manage worktrees.

## Decision
The dispatcher removes a builder's leftover worktree and its local branch once the PR from that branch is merged or closed. It only touches worktrees under `.claude/worktrees/`, and never one with commits that are not on the remote. `setup-project` adds `.claude/worktrees/` to the project's `.gitignore`.

## Rejected alternatives
- A cleanup script or VS Code task the owner runs: simpler dispatcher, but the owner starts handling worktrees.
- The builder deletes its own worktree at handback: an agent cannot remove its own working directory without a hook, and the branch is still needed for review fixes.

## Consequences
- The dispatcher gets one more rule, with a unit test using fakes. It already creates and deletes temporary worktrees for reviews and fixes, so this adds no new mechanism.
- Worktrees stay on disk while their PR is open. That is useful, because the dispatcher can see what a builder left behind.
- Design section 2 should read "Claude creates builder worktrees; the dispatcher removes them after the PR is merged or closed."
