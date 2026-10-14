# 0011 - The PR is the record; links to issues are fine

Status: accepted (design review, 2026-10-14; decision log row 11 in `docs/design.md` section 19)

## Context
The owner needs to understand any PR later without reconstructing it from sessions or logs.

## Decision
Every decision and state change for a PR lives on the PR, or one link away: the trace block (`Closes #N`, ticket, spec, docs PR), review rounds, fixes with guard results and cost, escalations, owner decisions, and the merge verdict.

## Rejected alternatives
- Restating the spec in every PR: duplication that drifts.

## Consequences
- The dispatcher flags PRs missing `Closes #N` or the trace block.
- Dispatcher state, sessions, worktrees and the dashboard are deliberately not records.
