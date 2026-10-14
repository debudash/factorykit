---
name: design-doc
description: "Write or update the high-level design (HLD) and the low-level design (LLD, with Mermaid sequence diagrams) for a spec issue, and open them as a docs PR for Gate 1."
disable-model-invocation: true
argument-hint: "<spec issue number>"
---
# /design-doc

Turn an agreed spec into the architecture documents builders and the reviewer work from. Run after `/to-spec`, before `/to-tickets`. Lane B uses it only when triage finds an architectural fix (then it updates an LLD).

## Inputs
- The spec issue named in the arguments: `gh issue view <n> --comments`. If no number was given, ask for it.
- `AGENTS.md`, `docs/agents/factory.md`, `GLOSSARY.md` and `docs/adr/` (decisions from shaping).
- The current `docs/architecture/hld.md` and any LLDs it links, and the code the spec touches.

## Step 1: classify, and say so
Decide whether this spec needs an LLD. **An LLD is needed** when the spec does any of:
- touches more than one module,
- adds an interface or a data model,
- integrates something external (service, API, queue, file format, another team's system).

**Sequence diagrams are needed** for every interaction between two or more parties that involves async work, retries or a failure path.

Write the classification as a short statement, for example:
> Classification: LLD needed (adds the `WebhookDelivery` data model and integrates an external HTTP endpoint). Sequence diagrams: 2 (delivery with retries; endpoint permanently failing).

or
> Classification: no LLD needed (one module, no new interface, data model or integration). HLD unchanged.

The statement goes at the top of the docs PR description, so the owner can overrule it at Gate 1.

## Step 2: settle open choices
Only for architecture choices still open after shaping. Ask in the grilling format: numbered rounds, a recommended answer for each question, each question worded so "yes" accepts the recommendation, and no writing until the owner confirms. Record any decision with lasting consequences as an ADR in `docs/adr/`. If nothing is open, skip this step.

## Step 3: write
**HLD** (`docs/architecture/hld.md`, one living document per repo). Create it on the repo's first idea; otherwise update it only if this spec changes the architecture. Sections: Context, Components and responsibilities, Data flows, Deployment, Non-functional requirements (reliability, security, performance). Link each LLD from it.

**LLD** (`docs/architecture/lld/<spec#>-<kebab-name>.md`, when needed). Sections:
1. Summary and spec link (`#<spec>`).
2. Modules and interfaces: each module touched, its responsibility, and the exact signatures or endpoints added or changed.
3. Data model: new or changed entities, fields and types, and where they are stored.
4. Error handling and retries: each failure, how it is detected, what happens (retry policy with numbers, give-up rule, what the caller sees).
5. Sequence diagrams.
6. Testing seams: where `tdd` should put its tests (what is faked, what is real).
7. Open questions: must be empty before Gate 1.

**Mermaid rules** for sequence diagrams:
- Use `sequenceDiagram` in a fenced `mermaid` block (GitHub renders it).
- Declare every participant first with `participant` (or `actor` for people), using names from the LLD's module list.
- One diagram per scenario: the happy path, then one per retry or failure path. Title each with a heading above the block.
- Show async work with `-)` and replies with `-->>`. Use `loop`, `alt`/`else` and `opt` for retries, branches and optional steps, with the real numbers (`loop up to 3 attempts, backoff 1s/2s/4s`).
- Add a `Note over` for timeouts, idempotency keys and anything a reader could get wrong.
- Keep each diagram under about 15 messages. Split if longer.

No TBDs anywhere. Every term matches `GLOSSARY.md`; add new terms to it.

## Step 4: docs PR (Gate 1)
`main` is protected, so planning output goes through a docs PR:
1. `git switch -c docs/spec-<n>` (or reuse it if `/to-spec` already created it).
2. Commit the HLD, LLD, ADRs and glossary changes.
3. Push and open the PR: title `Design for #<n>: <spec title>`, body starting with the classification statement, then a list of documents with one line each, then `Part of #<n>`. Label it `no-dispatch` (it has no code to review).
4. Comment on the spec issue with the docs PR link.
5. Tell the owner: merging the docs PR is the Gate 1 approval, and what to check (spec matches intent, no TBDs, classification right, diagrams cover the async and failure paths).

Then switch back to the branch you started on.
