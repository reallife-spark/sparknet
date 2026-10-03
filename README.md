# sparknet

sparknet knowledge vault.

This is a **self-managing knowledge vault**: an Obsidian/wiki-structured
directory plus the agent charter, configuration and skill wiring needed for an
opencode session to run it without further setup.

## Use it

```bash
opencode sparknet          # open this vault as the AI's knowledge base
cd /mnt/knowledge/sparknet && opencode    # same - the vault you stand in is selected
opencode vaults                  # list all registered vaults
```

The launcher is `~/.local/bin/opencode`; the registry of known vaults is
`/mnt/knowledge/.config/opencode/vaults.json`. This vault is registered there
under `sparknet`.

## What is wired

| Piece | Where | Why |
|---|---|---|
| Agent charter | `AGENTS.md` | layout, Memory + Plan Protocol, placement rules, boundaries — auto-loaded as the instruction file |
| Project config | `opencode.json` | `references.knowledge` → this vault, slim system-path deny-list, compaction |
| Vault config | `.env` | `OBSIDIAN_VAULT_PATH` — the wiki skills find the vault by walking up from the CWD |
| Tracked template | `.env.example` | `.env` is gitignored |
| Vault agent | `.opencode/agent/vault.md` | dedicated maintenance agent (`/agent vault`) |
| Plan state | `PLAN.md` | single source of truth, `current:` cursor |
| Standing memory | `MEMORY.md` + `sessions/` | tiny standing state, per-session detail |
| Audit trail | `log.md` | append-only transitions |
| Navigation | `index.md`, `hot.md`, `MISSION.md`, `TODO.md` | curated index + recent-activity snapshot |

Skills come from the global farm (`/mnt/nvme/skills/wiki`) — deliberately not
duplicated here, because opencode does not de-duplicate skills by name and a
second path would list every skill twice.

## Layout

```
concepts/  entities/  skills/  references/  synthesis/  journal/  projects/
sessions/          per-session agent memory
_raw/              unprocessed captures (never deleted)
_staging/          LLM-written pages awaiting review (WIKI_STAGED_WRITES=true)
_archives/         snapshots for /wiki-rebuild
.obsidian/         vault recognition
```

## First session

1. `opencode sparknet`
2. Fill in `MISSION.md` (scope + success) — it is the page that keeps scope drift
   out.
3. `/wiki-status` to confirm the skill suite resolves this vault.
4. `/wiki-ingest` with your first sources.
5. Verify `PLAN.md` Step 1, mark it done, set `current: done`, log the transition.

## Conventions

- Internal links are `wikilinks` (`[[Page]]`); page filenames are the page title.
- Add frontmatter (`title`, `tags`, `updated`) when a page needs it; do not add
  fields to every page by reflex.
- Raw capture → `_raw/`; distilled page → its category dir. Nothing stays in the
  vault root except the state files listed above.