# 0010 - No custom brief template; Matt's ticket and brief formats

Status: accepted (design review, 2026-10-14; decision log row 10 in `docs/design.md` section 19)

## Context
Builders need a clear statement of the work. Matt's `/to-tickets` and `/triage` already produce tickets with acceptance criteria and agent briefs.

## Decision
Builders work from Matt's ticket (Lane A) and agent brief (Lane B) formats, plus the parent spec and LLD. We add no brief template of our own.

## Rejected alternatives
- A firstmate-style brief listing file paths: goes stale quickly and duplicates the LLD.

## Consequences
- One less template to maintain.
- Gate 2 checks that every acceptance criterion is testable, because the builder relies on them.
