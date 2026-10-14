# 0002 - VS Code and Claude Code first; Cursor and Codex later

Status: accepted (design review, 2026-10-14; decision log row 2 in `docs/design.md` section 19)

## Context
The owner works in VS Code. Claude Code has the agent features the design relies on: subagents with worktree isolation, background runs, skills, and a headless CLI.

## Decision
v1 targets Claude Code in VS Code only. Choices that keep Cursor and Codex possible later are kept (design section 16): `AGENTS.md` as the single instructions source, enforcement outside any harness, and one adapter function for agent calls.

## Rejected alternatives
- Visual Studio: weaker agent support.
- Cursor first: Claude Code's subagent and headless features are what the design is built on.

## Consequences
- No Cursor or Codex adapter in v1; adding one should need no redesign.
- `CLAUDE.md` is one line importing `@AGENTS.md`.
