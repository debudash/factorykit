# 0007 - One VS Code window per project; agents own worktrees

Status: accepted (design review, 2026-10-14; decision log row 7 in `docs/design.md` section 19)

## Context
Parallel builders need isolated working copies, but managing git worktrees by hand is error-prone and distracting.

## Decision
The owner opens one VS Code window per project (at most 2 projects at a time) and always works in the project's normal folder. Builders are background subagents with `isolation: worktree`; Claude creates their worktrees, and the dispatcher removes them after the PR is merged or closed (ADR 0016).

## Rejected alternatives
- Owner-managed worktrees (as in v0): more work and more mistakes.
- Headless builds started from the dashboard: deferred; planning stays interactive.

## Consequences
- Worktrees live under `.claude/worktrees/`, which `setup-project` adds to `.gitignore`.
- The owner never runs `git worktree`.
