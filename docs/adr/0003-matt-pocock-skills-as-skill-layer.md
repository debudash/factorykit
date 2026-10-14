# 0003 - Matt Pocock's skills as the skill layer

Status: accepted (design review, 2026-10-14; decision log row 3 in `docs/design.md` section 19)

## Context
The workflow needs skills for shaping, specs, tickets, triage, diagnosis, TDD, implementation and code review. `mattpocock/skills` covers these with a coherent grilling format and issue-tracker conventions.

## Decision
Use Matt's skills as the skill layer, installed once at user level and pinned to a tagged version. We write only what is missing: `/design-doc` and `/address-feedback`.

## Rejected alternatives
- Writing six custom skills: more to build and maintain, and no better.
- firstmate: does not fit the GitHub-issue-centred flow as well.
- An MVF-style LangGraph factory: far heavier than the problem needs.

## Consequences
- Our workflow depends on his skill names and formats; upgrades follow `docs/upgrades.md`.
- Some of his skills are user-invoked only (Step 0 V3), so the builder repeats `/implement`'s steps itself.
