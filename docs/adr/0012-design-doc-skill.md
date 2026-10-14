# 0012 - `/design-doc` for HLD and LLD with Mermaid sequence diagrams

Status: accepted (design review, 2026-10-14; decision log row 12 in `docs/design.md` section 19)

## Context
Specs say what to build, but non-trivial changes also need architecture written down before tickets, and builders and reviewers need something to check against.

## Decision
A `/design-doc` skill maintains one living HLD per repo (`docs/architecture/hld.md`) and an LLD per non-trivial spec (`docs/architecture/lld/<spec#>-<name>.md`) with Mermaid sequence diagrams. It states its "LLD needed" classification in the docs PR so the owner can overrule it at Gate 1.

## Rejected alternatives
- Overloading `/to-spec`: mixes what and how, and means editing upstream.
- Ad hoc docs: inconsistent, and builders cannot rely on them.

## Consequences
- Builders read the LLD; a builder that must deviate updates it in the same PR.
- The reviewer's Spec axis includes the LLD.
