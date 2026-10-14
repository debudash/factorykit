# Build progress

| Step | Status | PR | Notes |
|---|---|---|---|
| 0 Verify unknowns | done | #1 | V1 to V6 recorded in `docs/verification.md`. ADR 0016 (dispatcher cleans up builder worktrees), ADR 0017 (public repos for now). Scratch: `D:\Dev\factorykit-scratch\repo`, GitHub `debudash/factorykit-scratch` (public) |
| 1 Skeleton and docs | done | #2 | README, workflow, settings, upgrades, ADRs 0001-0015. Open: poll interval fixed or a setting (Step 5); order of Matt's setup vs `AGENTS.md` (Step 3) |
| 2 Templates and skill sync | done | #3 | 5 templates, `scripts/fk_templates.py` (render), `scripts/sync-skills`, `skills.lock` (v1.3.1). 24 tests pass. Real sync done with `--adopt`; `--check` clean. Step 3 note: Matt's setup edits `CLAUDE.md` if present, else `AGENTS.md`, so write `AGENTS.md` first, then Matt's setup, then `CLAUDE.md` |
| 3 Project setup script | done | #4 | `scripts/setup-project`, 21 new tests (45 total). Order: AGENTS.md, then owner runs Matt's setup, then CLAUDE.md and setup PR. ADR 0018 (admin bypass through PR only). Scratch repo fully set up (setup PR #3 merged), re-run reports nothing to change. Scratch has no CI workflow yet; needed for Step 5 |
| 4 Agents and skills | done | #5 | builder, reviewer, `/design-doc`, `/address-feedback`; setup-project adds deny rules. Scratch: `/design-doc 6` -> docs PR #7 (classification + 3 sequence diagrams); builder: ticket #8 -> PR #9, ticket #10 -> PR #11 (tdd, code-review, draft then ready, trace block). Scratch now has CI (job `ci`). Reviewer and `/address-feedback` get their live runs in Step 5 |
| 5 Dispatcher v1 | done, awaiting owner review | #6 | `dispatcher/` (settings, rules, agent adapter, gh/git wrappers, core, CLI). 105 tests. Live on scratch: PR #14 reviewed and auto-merged; PR #15 lint failure auto-fixed (guards passed), re-reviewed, auto-merged; closed PR #11's builder worktree removed. Found and fixed the Windows .cmd argument issue |
| 6 Dashboard and tasks | not started | | |
| 7 Dogfood | not started | | |

Handoff created from the design review on 2026-10-14. The design review conversation is summarized in `docs/design.md`; nothing else from it is needed to build.
