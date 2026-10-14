# Pinning and upgrading Matt's skills

FactoryKit uses Matt Pocock's skills (`mattpocock/skills`) as its skill layer. They are installed once per machine at user level (`~/.claude/skills/`), pinned to a tagged version, and never edited.

## How the pin works

- `skills.lock` in this repo records the pinned tag and its commit.
- `scripts/sync-skills` (Step 2) clones `mattpocock/skills` at that tag and copies every skill listed in its `.claude-plugin/plugin.json` into `~/.claude/skills/<name>/`. It also installs our own `agents/` and `skills/`.
- `sync-skills --check` reports drift: a skill missing, changed, or left over from an older version.
- Use the copy, not the Claude Code plugin. The plugin updates whenever Matt ships, and having both installed gives every skill twice. If the plugin is installed, uninstall it: `claude plugins uninstall mattpocock-skills@claude-plugins-official`.

Current pin: `v1.3.1` (commit `24fe0ef`), installed during Step 0 (see `docs/verification.md` V2).

## Customizing without editing his files

Never edit an upstream skill file; the next sync would overwrite it and the change would be invisible. Customize in this order:

1. **Per-repo config:** `docs/agents/*.md` (written by `/setup-matt-pocock-skills`), `docs/agents/factory.md` and `AGENTS.md`. Most needs end here, for example the docs PR rule for `/to-spec` output.
2. **A wrapper skill** under our own name that calls his skill and adds steps.
3. **Last resort: an owned copy** under our own name in `skills/`, with a note saying which upstream version it came from. We then maintain it ourselves.

## Upgrade procedure

Do not upgrade while any item is mid-build.

1. **Read the changelog** between the pinned tag and the new one: `CHANGELOG.md` in `mattpocock/skills`. Note renames, removals and changed behaviour.
2. **Diff the skills we use.** At minimum: `grill-with-docs`, `to-spec`, `to-tickets`, `triage`, `diagnosing-bugs`, `implement`, `tdd`, `code-review`, `setup-matt-pocock-skills`, `retro`.
   ```
   git clone https://github.com/mattpocock/skills.git
   cd skills
   git diff <old-tag> <new-tag> -- skills/engineering/code-review skills/engineering/tdd ...
   ```
   Check especially for changes to `disable-model-invocation` (whether a subagent can call it), to file names the skills read or write (v1.3.0 renamed `CONTEXT.md` to `GLOSSARY.md`), and to the review output format the dispatcher parses.
3. **Bump the pin** in `skills.lock` on a branch, and run `python scripts/sync-skills`, then `python scripts/sync-skills --check`.
4. **Dogfood one item** end to end on a real project: one ticket from build to merge.
5. **Commit** the pin change through a PR, noting what you checked.

## Rolling back

Revert the commit that bumped `skills.lock`, then run `python scripts/sync-skills`. The previous version is copied back.
