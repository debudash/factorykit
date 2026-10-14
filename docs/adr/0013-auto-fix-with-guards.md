# 0013 - auto_fix in v1 with code-enforced guards

Status: accepted (design review, 2026-10-14; decision log row 13 in `docs/design.md` section 19)

## Context
Many CI failures and review findings are mechanical. Sending each one to the owner wastes attention, but an unguarded fix agent could hide problems, for example by deleting a failing test.

## Decision
v1 includes `auto_fix` (`off`, `ci`, `ci_and_review`; default `ci_and_review`). The fix agent only commits. The dispatcher checks its diff in code and pushes only if no test file was deleted, no skip marker added, and no CI config, `risky_paths` file or dependency manifest changed. Limits: 3 CI attempts and 2 review rounds per PR, one fix per PR, 2 at once overall.

## Rejected alternatives
- Deferring auto_fix: the owner would handle every red CI by hand.

## Consequences
- Guards live in code, not in prompts, so a model cannot talk its way past them.
- A failed guard means `needs-decision`, never a silent retry.
- `/address-feedback` remains the manual path when `auto_fix` is off.
