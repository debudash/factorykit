# FactoryKit - instructions for coding agents

FactoryKit is a light, reusable kit for delivering software on GitHub repos with Claude Code agents. This repo builds the kit itself.

## Sources of truth
- `docs/design.md` - the confirmed design. Do not change a decision without asking the owner.
- `docs/build-plan.md` - the build sequence and each step's "done when" criteria.
- `docs/progress.md` - where the build stands. Read it at the start of every session; update it at the end of every step.
- `reference/factory-router/` - v0 code and tests to evolve into `dispatcher/`. Do not edit it in place.

## How to work
- Work one build-plan step at a time, on a branch `build/step-N-<name>`, opened as a PR.
- At the end of a step: run its checks, update `docs/progress.md`, open the PR, summarize in plain language, then stop and wait for the owner.
- If something cannot be built as designed, stop and ask. Present options in numbered rounds, each with your recommended answer, worded so "yes" accepts it. Record the outcome as an ADR in `docs/adr/`.
- Find facts yourself (files, commands, docs); ask the owner only for decisions.
- Never ask for, store or print secrets. Use the owner's existing `gh` and `git` authentication.
- Run experiments only in a scratch repo outside this repo, never against the owner's real projects without asking.

## Code conventions
- Python 3.11+, standard library only for `dispatcher/` and `scripts/`, unless an ADR approves a dependency.
- Every rule in the dispatcher gets a unit test with fakes (see `reference/factory-router/tests/`).
- Scripts support `--dry-run` where they change anything.

## Writing style
- Plain, direct language. Prefer short paragraphs and tables over long bullet lists.
- Never use em dashes or double dashes; use a single hyphen instead.
