# {{project_name}} - instructions for coding agents

{{project_summary}}

## Verify

Run these to prove a change works. The same commands are listed in `docs/agents/factory.md`.

| Check | Command |
|---|---|
| Test | `{{test_cmd}}` |
| Typecheck | `{{typecheck_cmd}}` |
| Lint | `{{lint_cmd}}` |
| Build | `{{build_cmd}}` |

<!-- factorykit:rules:begin -->
## FactoryKit

This repo is delivered with FactoryKit. Read `docs/agents/factory.md` before any build, fix or review; its settings and rules apply to every agent.

- Planning output (ADRs, glossary, HLD, LLD) goes through a docs PR on a `docs/spec-<issue#>` branch, never straight to `main`.
- Every PR description starts with `Closes #N` and the trace block.
- Post any decision the owner gives in chat on the PR as "Decision by @{{owner}}: ..." before acting on it.
- Builders push only their own branch, never push `main`, never merge, never force-push, and print `NEEDS_DECISION: <question and options>` instead of guessing.
<!-- factorykit:rules:end -->
