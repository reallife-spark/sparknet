# Vendored wiki skill suite

These skills are **vendored copies**, not a symlink farm. They live in the
repository so that a bare clone of this vault can run `/wiki-status`,
`/wiki-ingest`, `/wiki-query` and the rest without a machine-global skill farm
— which is the whole point, because the deployment target is a DGX Spark node
that has never seen `/mnt/nvme`.

- **Upstream**: <https://github.com/Ar9av/obsidian-wiki> (`.skills/`)
- **Pinned commit**: `ec2b6bc` — "fix(wiki-ingest): archive promoted _raw/ drafts instead of deleting them"
- **License**: MIT, © 2026 Ar9av — see [`LICENSE`](LICENSE)
- **Farm source** (what this cluster runs today): `/mnt/nvme/skills/wiki`
- **Shipped**: 32 skills · **Withheld**: 4 · **Local**: 1

## Where they live and why not in `skills/`

```
.opencode/skills/<name>/SKILL.md
```

`.opencode/skills/` is opencode's project-skill location — it is discovered
automatically, with no `opencode.json` entry needed. The vault's own `skills/`
directory is a **knowledge category for how-to pages**, per `AGENTS.md`.
Dropping agent skills there would blur two unrelated things and would make the
category listing lie. Do not move them.

## Role-local catalogs are separate

This directory is the **base** suite shared by the fabric root and both roles.
The roles add their own generated catalogs under `peer-node/.opencode/skills/`
and `master-node/.opencode/skills/`. Those are not managed by
`make wiki-sync`; they are built by `scripts/sync-role-skills.py`, carry their
own `.inventory.json`, and are restricted to licenses that permit commercial
redistribution. The master catalog excludes the twelve restricted names and
keeps the Apache-2.0 `claude-api` as optional only.

## Re-syncing

```bash
make wiki-sync     # copy + patch + prune, then verify no host paths remain
make wiki-verify   # drift check only; fails if upstream moved
```

The sync is declarative. What ships and what does not is decided by two
constants in [`../../scripts/sync-wiki-skills.py`](../../scripts/sync-wiki-skills.py),
`EXCLUSIONS` and `GIT_SOURCES` — not by whatever happened to be on disk. To add
or drop a skill, edit that list and re-run `make wiki-sync`; the diff in git is
the review artifact.

A third constant, `LOCAL_SKILLS`, names skills **authored in this repository**
rather than copied from the farm. A local skill has no upstream to drift
against, so the sync never copies it, never prunes it, and `--check` accepts it
at face value. It exists at `.opencode/skills/<name>/SKILL.md` in the repo
itself. To add one, author the directory first, then add the name to
`LOCAL_SKILLS` (in the same edit) so the next sync does not prune it.

State after each sync lives in [`.sync.json`](.sync.json): source path and
content hash per skill, the pinned commit, the exclusion reasons, and which
patches were applied.

## What was withheld, and why

Withholding is a deliberate decision recorded per skill, so that shipping one
later is a one-line change rather than an accident.

| Skill | Reason |
|---|---|
| `rlspark-sourcewatch` | raxxar-local (not upstream). Hard-codes `/mnt/knowledge/raxxar` and drives the RLSpark dossier workflow, which is this cluster's project — not a node's. |
| `memory-bridge` | Compares what each AI tool knew by mining per-tool histories (`~/.codex`, `~/.claude`, …). A node running opencode has none of those sources. |
| `wiki-agent` | Targeted search over those same per-tool histories. |
| `wiki-history-ingest` | Ingests those same per-tool histories. |

The common thread: all four read state that exists only on the development
cluster. Shipping them would give a node commands that can only fail, and their
presence would imply the node has agent histories worth mining. If a node later
runs one of those tools too, move the name out of `EXCLUSIONS` and re-sync.

## Local modifications to upstream

Upstream files are copied verbatim except where a patch says otherwise. Patches
live in [`../../scripts/wiki-skill-patches/`](../../scripts/wiki-skill-patches/)
and are applied on every sync, so the difference from upstream stays reviewable
instead of rotting invisibly.

| Patch | What it changes |
|---|---|
| `daily-update.patch` | The housekeep step called `/mnt/knowledge/raxxar/06_knowledge/scripts/housekeep.py` by absolute path and referenced a `raxxar-cluster.md` that does not exist in a node's vault. Now resolved from `$SPARKNET_HOUSEKEEP` (or `~/.local/bin/housekeep.py`) and skipped cleanly when absent, pointing at the vault's own `AGENTS.md` for placement policy. |

A sync **fails loudly** if a patch no longer applies, so an upstream rewrite can
never silently drop a local fix.

## The orchestrator dialect

Two further transforms run on every copy, both declared in
`scripts/sync-wiki-skills.py` so they stay visible in git instead of being
silent edits:

- **`RENAMES`** — upstream skill dirs that are vendored under a different name.
  The three `obsidian-*` skills (`obsidian-bases`, `obsidian-cli`,
  `obsidian-markdown`) are vendored as `orchestrator-*` because the vault no
  longer names itself after that editor. The farm copy is untouched; the dest
  dir and `.sync.json` record the renamed name, with the farm path still the
  verified source.
- **`dialect_rewrite`** — a conservative prose rewrite applied to every vendored
  file. Bare "Obsidian" (the editor's name) becomes "orchestrator"; product
  phrases like "Obsidian Bases" become "orchestrator Bases". External artifacts
  are deliberately left alone, because they are real third-party names, not
  sparknet prose: `.obsidian/` (the editor's config dir), `Obsidian CLI` (the
  external tool some skills drive), docs URLs on `help.obsidian.md`, and the
  `obsidian-wiki` upstream repo. If upstream later changes "Obsidian Bases" to
  a different product phrase, the phrase table above needs re-review.

## Source integrity: why `skill-creator` is read from git

Both the farm copy *and* the upstream checkout of `skill-creator` contain 29
sibling skills symlinked **inside** it, forming a 40-deep self-symlink chain.
In the upstream checkout those symlinks are untracked (`??` in `git status`) —
local damage from a bad loop, not upstream content. Only 18 files are actually
tracked.

This matters twice over:

1. A naive copy raises `Too many levels of symbolic links`.
2. A copy that *did* succeed would register all 29 sibling skills a second time,
   because opencode discovers `**/SKILL.md` recursively.

So `skill-creator` is read with `git archive HEAD`, which returns the committed
tree and nothing else. Copy every other skill with symlinks preserved-then-pruned
rather than followed, so the same failure cannot recur unnoticed.

## Known dangling references

Vendored skills mention skills that are not vendored. These are **pre-existing
upstream references**, not damage from vendoring, and they are listed here so a
reader is not surprised by them. `tests/test_wiki_skills.py` asserts this set
exactly — if an upstream sync resolves or adds a reference, the test fails and
this table gets updated on purpose.

| Referencing skill | Mentions | Why |
|---|---|---|
| `daily-update` | `wiki-history-ingest` | withheld above |
| `daily-update` | `wiki-daily`, `wiki-notify` | never existed upstream — stale names |
| `impl-validator` | `memory-bridge` | withheld above |
| `llm-wiki`, `wiki-ingest`, `wiki-rebuild`, `wiki-setup`, `wiki-status` | `claude-history-ingest`, `codex-history-ingest` | consolidated upstream into `wiki-history-ingest`, which is withheld; old names linger in prose |
| `wiki-setup` | `wiki-stop-capture`, `wiki-vault` | never existed upstream — stale names |

None of these block a skill from loading. Every reference is prose guidance, not
a dispatched tool call.

## Requirements on the host

The skills themselves are markdown and need nothing. What they *drive* is
conditional, and each is optional:

| Need | Used by | If missing |
|---|---|---|
| `python3` | ingest helpers, `wiki-setup` | most skills degrade |
| `defuddle` CLI | `wiki-ingest`, `wiki-research` on URLs | URL sources fall back |
| Obsidian CLI | `orchestrator-cli` | that skill is inert |
| Dataview plugin | `wiki-dashboard` queries | use Bases instead |
| a Markdown renderer | `wiki-export` HTML output | export JSON/GraphML only |

None of these are vendored: they are third-party binaries or an editor plugin,
not skill content. `wiki-dashboard` deliberately prefers orchestrator Bases, which
needs no community plugin.

## Vault scoping

These skills resolve their vault by **walking up from the CWD** for a `.env`
containing `VAULT_PATH` (the Config Resolution Protocol in `llm-wiki`), falling
back to `~/.wiki/config`. That is what lets one vendored copy serve the parent
fabric vault *and* each role subvault.

It is also a trap worth stating plainly: **`.env` is gitignored, so a fresh
clone has none, and resolution then falls back to `~/.wiki/config`** — which on
a node may point at a different vault entirely. `make env-init` writes the role
`.env`, and `scripts/sparknet-wiki-env.sh` refuses to run a skill when the
resolved vault is not the expected one. Do not bypass that check.