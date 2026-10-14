# 0017 - Public repos for now

Status: accepted (owner, 2026-10-14, Step 0 verification V6)

## Context
Design section 12 relies on a ruleset on `main` (PR only, required checks `ci` and `dispatcher/review`, no force-push or deletion) and on GitHub auto-merge. Verification V6 showed the owner's account `debudash` is on GitHub Free. The owner's Pro subscription is Copilot Pro, which does not include GitHub Pro features. On Free, GitHub refuses rulesets, classic branch protection and auto-merge on private repos (HTTP 403). On a public repo all three work, and the full chain was verified end to end.

## Decision
FactoryKit projects use public repos for now, so the merge policy in design section 12 applies unchanged. If a project must stay private, `setup-project` detects the 403, explains it, and sets that project to `merge_mode = manual`. In that case `main` is protected by convention only.

## Rejected alternatives
- Upgrade the account to GitHub Pro: keeps private repos fully protected. Deferred, not ruled out; switching later needs no design change, only re-running `setup-project`.
- `merge_mode = manual` everywhere: loses auto-merge for low-risk PRs and leaves `main` unprotected.
- The dispatcher merges low-risk PRs itself with `gh pr merge`: a second merge mechanism, and still no enforcement on `main`.

## Consequences
- Project code is publicly visible. The owner decides per project whether that is acceptable.
- Secrets must never be committed (already a rule). Public repos make a mistake there more costly.
- If the owner upgrades to GitHub Pro, private repos get the same protection by re-running `setup-project`.
