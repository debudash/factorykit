# 0014 - One local `projects.toml` for dispatcher settings

Status: accepted (design review, 2026-10-14; decision log row 14 in `docs/design.md` section 19)

## Context
The dispatcher needs per-project settings that the owner can change quickly, including mid-build.

## Decision
One file, `~/factory/projects.toml`, holds each project's `path`, `auto_fix` and `merge_mode`. It is reloaded every poll. Settings agents read live in the repo in `docs/agents/factory.md`.

## Rejected alternatives
- A three-level override scheme (global, project, PR): more to explain and debug for little gain.

## Consequences
- Changing `auto_fix` or `merge_mode` is an edit and a save, picked up within one poll.
- These settings are local to the owner's machine and not versioned with the project.
