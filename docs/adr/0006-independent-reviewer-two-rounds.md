# 0006 - Independent reviewer run by the dispatcher, 2 rounds

Status: accepted (design review, 2026-10-14; decision log row 6 in `docs/design.md` section 19)

## Context
A builder reviewing its own work misses things, and the owner should not relay review comments by hand.

## Decision
The dispatcher runs a reviewer on every ready PR and after every push: a separate process, fresh session, read-only tools, a different model by default, in a temporary worktree at the PR head. It runs Matt's `code-review` skill and posts one PR review per round, "Round N of 2". Round 2 and later only cover new commits and earlier items.

## Rejected alternatives
- Self-review only: same blind spots as the builder.
- Human relay: costs the owner's attention on every PR.
- A custom `/review-pr` skill: Matt's `code-review` already has the Standards and Spec axes.

## Consequences
- After 2 rounds with blockers, the PR gets `needs-decision`.
- Reviews post from the owner's account; a bot account is deferred.
- Step 0 V4: the dispatcher passes the merge-base and diff in the reviewer prompt.
