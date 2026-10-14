# 0008 - `max_parallel` default 2, blockers respected

Status: accepted (design review, 2026-10-14; decision log row 8 in `docs/design.md` section 19)

## Context
Building several tickets at once is faster, but review attention and merge conflicts limit how much parallel work is useful.

## Decision
Up to `max_parallel` tickets build at once per project: default 2, range 1 to 3, set in `docs/agents/factory.md`. Only tickets whose blockers are all merged may start.

## Rejected alternatives
- One item at a time: slower, and it wastes the parallel tooling.

## Consequences
- `/to-tickets` must record blocking edges correctly, because they decide which tickets may start.
- Fix agents are capped separately: at most 2 across all projects.
