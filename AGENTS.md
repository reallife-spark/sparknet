---
title: sparknet Charter
updated: 2026-10-03
---

# sparknet — agent charter

sparknet knowledge vault.

This vault is the **active knowledge base** for sessions started with
`opencode sparknet`. It is standalone and self-managing: the raxxar
cluster charter, Aegis context and its Plan Protocol do **not** apply here.

## Layout (wiki category layout)

| Path | Holds |
|---|---|
| `concepts/` | distilled ideas and definitions — one concept per page |
| `entities/` | people, organisations, systems, products |
| `skills/` | reusable procedures (how-to pages, not agent skills) |
| `references/` | external material: docs, specs, transcripts, datasets |
| `synthesis/` | pages that draw conclusions ACROSS two or more concept/entity pages |
| `journal/` | dated entries and session notes |
| `projects/` | per-project knowledge, scoped by the ingest skills |
| `sessions/` | per-session agent memory (`YYYY-MM-DD.md`), see Memory Protocol |
| `_raw/` | unprocessed captures — **nothing is deleted from here**, ingest moves it |
| `_staging/` | LLM-written pages awaiting review (only used when `WIKI_STAGED_WRITES=true`) |
| `_archives/` | vault snapshots for rebuild/restore (`/wiki-rebuild`) |

Wiki skills read the vault location from `.env` in this directory
(`OBSIDIAN_VAULT_PATH`) — never hard-code the path in a page.

## Memory Protocol

- `MEMORY.md` — **standing state only**, tiny: plan cursor, durable facts,
  blockers. Replace, never append indefinitely.
- `sessions/YYYY-MM-DD.md` — that session's full record (progress, decisions,
  gotchas). One file per day; sessions spanning midnight use the start date.
- Read `MEMORY.md` and today's session file at session start; write detail only
  to today's session file. Never back-write history into `MEMORY.md`.

## Plan Protocol

`PLAN.md` is the single source of truth for multi-step work.

- Frontmatter `current:` marks the step being worked.
- Mark a step `[x]` **only** after its DoD is verified, then advance the cursor
  and write `PLAN.md` back **immediately** — never defer to session end.
- Append one line per transition to `log.md` (append-only audit trail).
- Terminal state is `current: done`. New roadmap work gets a **new** step; do
  not silently reuse a finished plan.
- A step whose DoD cannot be auto-verified is marked `DoD: confirm: user` and
  the user is asked.

## Canonical placement

- Distilled page → its category dir. Raw capture → `_raw/` or `01_Inbox`-style
  intake until distilled. Never scatter copies across home roots.
- Logs and telemetry → `/mnt/log/`, not the vault and not `~/`.
- Runtime caches → `$OPENCODE_DATA_DIR`. Trash/archives → dated trash dir.
- One page per file; no duplicate copies of the same page. The daily housekeep
  pass counts broken symlinks and junk files — keep both at `0`.

## Wiki skill suite

Available from the global skill farm (`/mnt/nvme/skills/wiki`); run
`/wiki-status` first to see the ingest delta, then:

| Command | Use |
|---|---|
| `/wiki-status` | what is ingested, what is pending, delta + recommendation |
| `/wiki-ingest` | add sources → distilled pages (delta or rebuild mode) |
| `/wiki-query` | answer from the wiki with page citations |
| `/wiki-lint` | audit health (orphans, stale, broken links); `--consolidate` to fix |
| `/wiki-capture` | save a finding from the current session; `--quick` for raw drops |
| `/wiki-synthesize` | create cross-cutting `synthesis/` pages |
| `/wiki-digest` | human-readable digest of what changed over a period |
| `/wiki-rebuild` | archive + rebuild, or restore an archive |
| `/daily-update` | daily maintenance cycle; regenerates `index.md` + `hot.md` |

## Boundaries

- **Scope discipline.** This vault holds sparknet knowledge vault. Nothing unrelated
  belongs here; a page that serves another domain goes in that domain's vault.
- **No secrets.** Never commit tokens, keys or `.env` contents. Reference the
  secret *path* only.
- **Offensive security is out of scope** for a general/default agent session.
  Route offensive work to the `red` role and defensive work to `blue`.
- Cite sources. A distilled page without provenance is a guess — mark it as one.
- Prefer editing an existing page over adding a near-duplicate; cross-link
  instead of copying.