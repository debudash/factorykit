# 0018 - Admins may bypass the ruleset through a PR only

Status: accepted (owner, 2026-10-14, Step 3)

## Context
The ruleset on `main` (design section 12) requires the CI check and `dispatcher/review`. A test on the scratch repo showed that, with no bypass list, even the repo admin cannot merge a PR whose checks never report: `gh pr merge` and `gh pr merge --admin` were both refused. That blocks every `no-dispatch` PR (the dispatcher never posts `dispatcher/review` on it) and the FactoryKit setup PR.

## Decision
The ruleset lists the repository admin role as a bypass actor in `pull_request` mode. The owner can merge any PR by choosing to bypass the rules on that PR. Direct pushes, force-pushes and deletion of `main` stay blocked for everyone; verified on the scratch repo (GH013 on a direct push after the change).

## Rejected alternatives
- No bypass, with the owner posting the missing statuses by hand: awkward and easy to get wrong.
- No bypass, and `no-dispatch` PRs never merge through FactoryKit: makes the label much less useful.

## Consequences
- Agents run with the owner's `gh` login, so builder and fix agents must stay denied `gh pr merge`. The dispatcher only ever enables GitHub auto-merge, which still waits for the checks.
- The owner's login can also edit the ruleset itself, so the ruleset was never absolute protection against a misbehaving agent; the guards and tool restrictions remain the real control.
- `setup-project` updates an existing ruleset that lacks the bypass.
