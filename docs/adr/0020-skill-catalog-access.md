# 0020 — Skill access is a catalog plus a search tool, not a sorted picker

## Status

Accepted (2026-11-12; Step 105). Implementation is in this change.

## Context

OpenCode discovers every `SKILL.md` under `.opencode/skills` and advertises each
skill with a description in the model prompt. On the development host,
`master-node/` discovered 1,655 skill entries and ~134,000 description tokens against a
131,072-token engine context. The peer discovered 181. Ordering is filesystem
discovery order across global and project sources; `.inventory.json` is already
alphabetically sorted and is not read by OpenCode or Open WebUI.

Two further facts shaped the decision:

- OpenCode 1.18.35 ignores `disable-model-invocation` and
  `metadata.opencode/autoinvoke: false`; the skill still appears in the system
  prompt. It does honour `permission.skill`, including a `*` deny followed by
  an exact allow.
- The Open WebUI models route through the OpenCode engine, and the sandbox
  mounted only the user vault and a generated `opencode.json`; it had no skills
  at all.

## Decision

Keep the vendored skill trees exactly where they are. Add a derived catalog and
a read-only access surface:

- `contracts/skill-catalog-schema.json` defines `sparknet-skill-catalog/1`:
  sorted `(group, id)` entries with description, provenance, license, role,
  path and sha256.
- `contracts/skill-policy.json` defines source→group mapping, the 25–35
  featured ids per role, denied groups and the WebUI subset.
- `scripts/sparknet-skills.py index` writes `.opencode/skills/.catalog.json` for
  the base, peer and master trees. `check` rebuilds in memory and refuses drift.
- `shared/sparknet-skills-mcp.py` exposes `skills_groups`, `skills_list`,
  `skills_search`, `skills_load` and `skills_path` over stdio. It reads only the
  catalog and files beneath its root; it writes nothing.
- `opencode.json` uses `permission.skill` with `*: deny` and the featured ids
  allowed. The full catalog remains searchable and loadable through the MCP.
- The OpenCode engine mounts the base and role catalogs read-only, injects the
  same MCP server and the same featured permission set, and filters the WebUI
  catalog by denied groups.
- Peer and master configs add `../.opencode/skills` to `skills.paths`; a role
  session is its own project root, so without it the base suite was invisible.

## Consequences

- A master session advertises the 35-id featured set plus the built-in, not the full corpus.
- The long tail costs nothing until the model searches for it.
- `.inventory.json` keeps its shape; the catalog is a separate artifact. A
  future manifest migration is still a separate decision.
- A model can still read a hidden skill through `skills_load`; that is an
  instruction read, not authority. Denied groups are removed from the catalog a
  WebUI sandbox mounts, not merely hidden in the prompt.
- Sorting is enforced in the catalog, CLI, console and import outputs. The
  OpenCode and Open WebUI pickers remain third-party and are not patched.
