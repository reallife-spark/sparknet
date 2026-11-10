# 0010 — Skill catalog: one engine, four family adapters

## Status

Accepted (fabric Step 92C; implemented 93C).

## Context

Four build-time scripts maintain the skill tree:

- `sync-wiki-skills.py` vendors, patches, rewrites, prunes and protects sibling
  families.
- `sync-mattpocock-skills.py` copies a family and overwrites descriptions.
- `sync-understand-skills.py` pins authored directories without copying.
- `sync-role-skills.py` scans multiple sources, chooses variants, enforces
  licenses and builds the peer/master catalogs.

They repeat tree copying, digesting, manifest writing/checking and host-path
refusal. Their manifests differ: `.sync.json`, `.mattpocock.json`,
`.understand.json` and the role `.inventory.json`. Only the wiki and role paths
have dedicated tests.

## Decision

- **One build-time engine lives under `scripts/skill_catalog/`.** It owns tree
  copy, tree digest, manifest read/write/check, host-path refusal and
  missing-source handling.
- **Four family adapters** supply source, destination, exclusions, names and
  transforms: `wiki`, `mattpocock`, `understand` and `role`.
- **The four existing script paths and CLI flags stay stable.** They become thin
  adapters over the engine; Makefile, bundle and test paths do not move.
- **Manifest convergence is internal for now.** One internal manifest model is
  used, while the four external manifest shapes remain unchanged. An on-disk
  schema migration is a separate decision.
- **Family-specific behavior stays with the adapter.** Wiki patches, dialect
  rewrites and pruning; Matt description overrides and fallback source;
  Understand pin-only behavior; role source scanning, variant choice, license
  policy, README/notices, `skill-template` and peer/master selection.
- **The host-path guard is shared.** It checks shipped skill content against
  family-specific allowlists. Role source paths recorded as provenance are not
  skill content and are not flagged.
- **Check and apply have one meaning.** `--check` verifies committed bytes and
  reports an absent farm source as unverifiable, not failure. `--apply` requires
  its sources and fails clearly when they are absent.
- **Existing gates and SBOM inputs stay.** `wiki-sync`, `wiki-verify`,
  `understand-skills-check`, `mattpocock-check`, `role-skills-check`, bundle and
  goagx continue to work. SBOM keeps the wiki manifest as its authoritative
  list.
- **Tests get one catalog surface.** Add `tests/test_skill_catalog.py` for engine
  mechanics and adapter contracts, plus dedicated Matt and Understand checks.

## Consequences

- Copy, digest, manifest and host-path logic has one home.
- The role adapter remains the largest because role catalog policy is real work,
  not accidental duplication.
- The four external manifests stay compatible with bundles, SBOM and current
  tests.
- A future manifest migration is explicit and separately reviewed.
- A new vendored family supplies an adapter rather than another copy of the
  engine.
