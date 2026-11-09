# Domain docs

This repository uses the **single-context** layout.

## What to read

1. `AGENTS.md` — the operating charter; it wins on conflict.
2. `CONTEXT.md` — the generated fabric context and channel map.
3. `GLOSSARY.md` — the domain vocabulary.
4. `docs/adr/` — accepted architecture decisions, one file per decision.
5. `contracts/` — the normative contracts; prose in a role does not override
   them.

## Rules

- Use the glossary's spelling for a domain term in a plan, an issue, a commit
  or a page. A synonym that is not in the glossary is a new term, not a
  shortcut.
- An ADR records a decision and its consequences, not a status report. Give it
  a number, a title and a status (`proposed`, `accepted`, `superseded`).
- Do not copy a contract's rules into a role document. Link to the contract.
- Personal pages, secrets and live host state do not enter `docs/agents/` or
  `docs/adr/`.
