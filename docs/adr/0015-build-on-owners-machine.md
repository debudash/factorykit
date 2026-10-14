# 0015 - Build the kit with Claude Code on the owner's machine

Status: accepted (design review, 2026-10-14; decision log row 15 in `docs/design.md` section 19)

## Context
The kit needs the owner's `gh` and `git` authentication, Claude Code and real repos to build and test against.

## Decision
FactoryKit is built with Claude Code on the owner's machine, using the owner's existing `gh` and `git` authentication. Experiments run in a scratch repo outside this repo.

## Rejected alternatives
- Building in a remote sandbox with a token: means creating and handing over a token, and the sandbox is not where the kit will run.

## Consequences
- No secrets are created, stored or printed for the build.
- Verification (Step 0) runs against the same tools the kit will use.
