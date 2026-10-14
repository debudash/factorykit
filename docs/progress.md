# Build progress

| Step | Status | PR | Notes |
|---|---|---|---|
| 0 Verify unknowns | done | #1 | V1 to V6 recorded in `docs/verification.md`. ADR 0016 (dispatcher cleans up builder worktrees), ADR 0017 (public repos for now). Scratch: `D:\Dev\factorykit-scratch\repo`, GitHub `debudash/factorykit-scratch` (public) |
| 1 Skeleton and docs | done | #2 | README, workflow, settings, upgrades, ADRs 0001-0015. Open: poll interval fixed or a setting (Step 5); order of Matt's setup vs `AGENTS.md` (Step 3) |
| 2 Templates and skill sync | done | #3 | 5 templates, `scripts/fk_templates.py` (render), `scripts/sync-skills`, `skills.lock` (v1.3.1). 24 tests pass. Real sync done with `--adopt`; `--check` clean. Step 3 note: Matt's setup edits `CLAUDE.md` if present, else `AGENTS.md`, so write `AGENTS.md` first, then Matt's setup, then `CLAUDE.md` |
| 3 Project setup script | done, awaiting owner review | #4 | `scripts/setup-project`, 21 new tests (45 total). Order: AGENTS.md, then owner runs Matt's setup, then CLAUDE.md and setup PR. ADR 0018 (admin bypass through PR only). Scratch repo fully set up (setup PR #3 merged), re-run reports nothing to change. Scratch has no CI workflow yet; needed for Step 5 |
| 4 Agents and skills | not started | | |
| 5 Dispatcher v1 | not started | | |
| 6 Dashboard and tasks | not started | | |
| 7 Dogfood | not started | | |

Handoff created from the design review on 2026-10-14. The design review conversation is summarized in `docs/design.md`; nothing else from it is needed to build.
