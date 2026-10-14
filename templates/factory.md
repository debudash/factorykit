# FactoryKit settings and rules for {{project_name}}

Every agent reads this file before building, fixing or reviewing. The dispatcher reads the settings block. Change it through a PR like any other file. Dispatcher-only settings (`auto_fix`, `merge_mode`) are in `~/factory/projects.toml` on the owner's machine, not here.

## Settings

```toml
# Paths a fix may never touch and that always hold a PR for the owner (glob patterns).
risky_paths = {{risky_paths}}

# How many tickets build at once in this project (1 to 3).
max_parallel = {{max_parallel}}

# Model for the independent reviewer. Use a different model from the builder's.
reviewer_model = "{{reviewer_model}}"

# Commands that prove a change works. Leave "" when the project has no such step.
[verify]
test = "{{test_cmd}}"
typecheck = "{{typecheck_cmd}}"
lint = "{{lint_cmd}}"
build = "{{build_cmd}}"
```

## Rules

### Planning output goes through a docs PR
`main` is protected. Output of `/to-spec` and `/design-doc` (ADRs, glossary, HLD, LLD) is committed on a `docs/spec-<issue#>` branch and opened as a docs PR linked from the spec issue. Merging it records Gate 1.

### Trace block
Every PR description starts with:
```
Closes #<ticket>
Trace: ticket #<ticket> "<title>" -> spec #<spec> "<title>" -> docs PR #<docs PR>
Started by @<owner> on <date> from ticket #<ticket>
```
For a Lane B defect, the trace starts at the triaged issue and its agent brief. Then three sections: `## What changed`, `## Verification` (commands run and their results), and `## Review notes and open questions` (self-review findings not fixed and judgement calls, marked AI-generated).

### Post decisions before acting
When the owner decides something in chat, post it on the PR as "Decision by @{{owner}}: <decision>" before acting on it.

### Builder rules
- Before starting, read the ticket (Lane A) or agent brief (Lane B), its parent spec, the LLD if any, and this file.
- Follow `/implement`'s steps: `tdd` at agreed seams, the typecheck and single tests regularly, the full suite at the end, a `code-review` self-check, and fix every hard standards violation and every spec gap (missing, wrong, out of scope) before committing.
- If you must deviate from the LLD, update the LLD in the same PR.
- Open a draft PR right after the first commit, with the trace block. Mark it ready when done, with the full handback description.
- Push only your own branch. Never push `main`, never merge, never force-push.
- On ambiguity, tradeoffs, scope, security, data handling or public interfaces, print `NEEDS_DECISION: <question and options>` instead of guessing.
