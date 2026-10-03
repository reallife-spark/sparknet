---
title: sparknet Plan
updated: 2026-10-03
current: 1
---

# sparknet — Active Plan

> Single source of truth for multi-step work. The `current:` cursor marks the
> step being worked. Write this file back **immediately** on every advance;
> append the matching transition line to `log.md`.

## Status Legend

- `[ ]` not started / in progress
- `[x]` complete — DoD verified
- **DoD** — the check that proves the step is done; `DoD: confirm: user` when a human must confirm
- `current: N` — step being worked now; `current: done` — terminal

## Step 1 — Verify the scaffold

- [ ] **Step 1** — Confirm the generated vault is wired correctly.
      - **DoD**: (1) `opencode sparknet` starts with this vault as the
        knowledge reference and `AGENTS.md` as the instruction file;
        (2) `/wiki-status` resolves `.env` to `/mnt/knowledge/sparknet`;
        (3) directory layout matches `AGENTS.md`; (4) `git status` clean after
        the initial commit; (5) registry entry present in
        `/mnt/knowledge/.config/opencode/vaults.json`.
      - **Status**: pending — run the checks, then set `[x]` and `current: done`.

## Next

Add roadmap steps here as work is identified. New roadmap work after
`current: done` becomes a new step, not a reuse of this plan.
