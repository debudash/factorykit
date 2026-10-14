# 0005 - A label set of 8, no `ready-for-human`, no opt-in label

Status: accepted (design review, 2026-10-14; decision log row 5 in `docs/design.md` section 19)

## Context
Labels carry triage state and escalation. Too many labels become a second state machine to maintain.

## Decision
Use 8 labels: `bug`, `enhancement`, `needs-triage`, `needs-info`, `ready-for-agent`, `wontfix`, `needs-decision`, `no-dispatch`. `ready-for-human` is not used; an issue an agent should not implement gets `needs-decision` with the reason. The dispatcher acts on every non-draft PR unless it has `no-dispatch`.

## Rejected alternatives
- Phase labels: duplicate what PR state, checks and issues already show.
- A `factory` opt-in label (as in v0): every PR should get the same process, so opting out is the exception.

## Consequences
- The dashboard derives board columns from labels, PR state and checks, not from phase labels.
- `triage-labels.md` records that `ready-for-human` is not used.
