# 0001 - Keep orchestration in our own repo

Status: accepted (design review, 2026-10-14; decision log row 1 in `docs/design.md` section 19)

## Context
FactoryKit needs something to watch PRs, run a reviewer, apply fixes and decide merges. Agent Orchestrator does similar work, and the v0 router (`reference/factory-router/`) showed the core fits in about 700 lines of standard-library Python.

## Decision
Orchestration lives in this repo: a small dispatcher (Python 3.11+, standard library, `git`, `gh`, Claude Code CLI), the builder and reviewer definitions, templates and scripts. It evolves from the v0 router and its tests.

## Rejected alternatives
- Agent Orchestrator: young, with ownership churn, and a larger surface than we need.

## Consequences
- We own and maintain the dispatcher, so it must stay small and fully unit-tested with fakes.
- No hosted service, no new SaaS, no dependencies beyond the standard library unless an ADR approves one.
- Behaviour can be changed by a PR to this repo.
