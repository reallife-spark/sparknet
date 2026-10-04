---
title: sparknet Charter
updated: 2026-10-04
---

# sparknet — agent charter

sparknet knowledge vault — and the fabric root.

This vault is the **active knowledge base** for sessions started with
`opencode sparknet`. It is standalone and self-managing: the raxxar
cluster charter, Aegis context and its Plan Protocol do **not** apply here.

## The fabric: two roles and one contract

This repository is not one node. It is a **fabric** with two node roles and a
shared contract, and most confusion here comes from reading a page that belongs
to one role as though it described the whole system.

| Path | Role | State |
|---|---|---|
| `contracts/` | both | the cross-role contract: overlay, capabilities, identity, ports, guard protocol. **Single source of truth.** |
| `shared/` | both | `sparknet-authz.py` — the one signed-authorization implementation |
| `peer-node/` | peer | a working node: guard, anchor, dispatch, its own wiki vault |
| `master-node/` | master | the signing role — **specified, not built** (see its `plans/MASTER_BUILD_PLAN.md`) |
| `scripts/` | both | fabric-level tooling: vendoring, env, bundling |
| `.opencode/skills/` | both | the vendored wiki suite |

Three consequences worth holding onto:

1. **A role subvault alone is not a deployment.** A peer cannot verify a
   signature without `contracts/` and `shared/`, so a bare `peer-node/` copy
   deliberately fails validation rather than pretending to work. `make bundle`
   assembles what a node actually needs.
2. **Authority comes from key possession, not a capability grant.** The Master
   signs; a peer verifies. A peer with the full capability vocabulary but without
   the private key can never grant, revoke or escalate.
3. **Cross-role changes are atomic.** Editing anything a peer depends on means
   editing `contracts/` *and* both roles in the same commit, then running
   `make contract-test`. `tests/test_contracts.py` exists to fail when one role's
   copy of the contract drifts from the other's.

Read the role's own `AGENTS.md` before working inside it. The peer and master
charters differ in substance, and the peers are not a subset of the masters.

## Commands

Run everything through `make`; it picks the venv interpreter and the optional
tooling consistently.

| Command | Use |
|---|---|
| `make help` / `make -C peer-node help` | what the fabric and each role can do |
| `make layout` / `make help-role` | what exists, and what is merely specified |
| `make validate` | both roles' charters, plans and manifests |
| `make test-all` | **every** suite: contract, fabric, peer, master |
| `make contract-test` | the peer still matches `contracts/` |
| `make wiki-sync` / `make wiki-verify` | re-vendor the wiki suite / prove no drift |
| `make wiki-preflight` | prove the skills resolve *this* vault |
| `make bundle ROLE=peer\|master` | build a standalone node bundle in `dist/` |
| `make bundle-verify ROLE=…` | extract it elsewhere and prove it runs |

Bare `pytest` at the root runs only `tests/` (fabric level). Use `make test-all`
when you mean the whole repository.

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
(`VAULT_PATH`) — never hard-code the path in a page.

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

**Vendored in this repository** at `.opencode/skills/` (31 skills, MIT, pinned
upstream) — there is no global skill farm dependency, so a bare clone or an
extracted node bundle can run the whole suite. Re-vendor with
`make wiki-sync`, verify with `make wiki-verify`.

Skills resolve the vault from the **nearest** `.env`, which is what keeps a role
subvault honest. Run `make wiki-preflight` before using one; if it fails, run
`./scripts/sparknet-env-init.sh <role-dir>` once. Never work around the failure:
the skills would silently resolve a different vault and every page you write would
land there instead, with nothing to tell you.

Run `/wiki-status` first to see the ingest delta, then:

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

- **Scope discipline.** This vault holds cross-role sparknet knowledge. Nothing
  unrelated belongs here; a page that serves another domain goes in that domain's
  vault, and a page that serves exactly one role belongs in that role's subvault.
- **No secrets.** Never commit tokens, keys or `.env` contents. Reference the
  secret *path* only.
- **Offensive security is out of scope** for a general/default agent session.
  Route offensive work to the `red` role and defensive work to `blue`.
- Cite sources. A distilled page without provenance is a guess — mark it as one.
- Prefer editing an existing page over adding a near-duplicate; cross-link
  instead of copying.