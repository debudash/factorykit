# 0004 - Never edit upstream skills; config, wrappers, owned copy last

Status: accepted (design review, 2026-10-14; decision log row 4 in `docs/design.md` section 19)

## Context
We depend on Matt's skills but need some project-specific behaviour, such as planning output going through a docs PR.

## Decision
Never edit upstream skill files. Customize in this order: per-repo config (`docs/agents/*.md`, `AGENTS.md`), then wrapper skills that call his, and only as a last resort an owned copy under our own name.

## Rejected alternatives
- Forking and editing: every upgrade becomes a merge, and edits are invisible to anyone reading his docs.

## Consequences
- Upgrades stay a pin bump plus a diff review.
- Rules such as the docs PR live in `factory.md`, not in his skills.
- An owned copy, if ever needed, is ours to maintain.
