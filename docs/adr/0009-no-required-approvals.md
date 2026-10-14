# 0009 - No required approvals; checks plus `merge_mode`

Status: accepted (design review, 2026-10-14; decision log row 9 in `docs/design.md` section 19)

## Context
FactoryKit is for a solo developer. GitHub does not allow a PR's author to approve their own PR, so a required approval would block every merge.

## Decision
The ruleset on `main` requires a PR, the CI check and `dispatcher/review`, and blocks force-push and deletion, with no approval count. `merge_mode` per project decides whether low-risk PRs auto-merge (`auto-low-risk`, the default) or all are held (`manual`).

## Rejected alternatives
- Required self-approval: impossible on GitHub.

## Consequences
- Quality rests on CI, the independent review and the guards, not on an approval.
- Rulesets need a public repo or a paid plan (ADR 0017).
