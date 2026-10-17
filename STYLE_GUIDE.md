---
title: sparknet Style Guide
updated: 2026-10-17
---

# sparknet — style guide

Conventions for both repositories of this fabric: `sparknet` (this vault) and
`goSpark`. The **provenance** is
`references/nvidia-dsx-standard-practice.md` — the 14 dsx/EleutherAI
repositories read on 2026-10-17. Nothing here is copied code: the rules are
ours, the shape is theirs.

Read this before adding a file, a gate or a commit. The charter (`AGENTS.md`)
says *what* this repository is; this page says *how* work is written in it.

## 1. Resource-first

Before building a container, model or service of our own, check what NVIDIA
already publishes:

```sh
make nv-search q="llama"                        # model ids from the integrate catalog
scripts/sparknet-nv-search.sh show <id>         # one model; a 410 names its EOL date
scripts/sparknet-nv-search.sh discover          # the browser surfaces to search by hand
```

Endpoints, their real shapes (one of them is not an API at all) and the
provenance are in `references/nvidia-build-catalog.md`. **Record the lookup** —
the query and the verdict ("nothing fit because …") — in the page or plan you
were working from, so the next agent can see the search happened.

## 2. The tree

- One page per file; distilled knowledge goes to its category directory,
  provenance to `references/`. Never scatter copies (charter: Canonical
  placement).
- Fabric modules load **by path** (`shared/sparknet_loader.py`); the
  kebab-case `sparknet-*.py` filenames are frozen — do not rename or re-package
  them.
- Cross-role changes are atomic: `contracts/` and both roles in **one** commit,
  then `make contract-test`.
- Every script answers `--help`, and answering it changes nothing (no writes,
  no side effects) — `tests/test_shell.py` runs all of them.
- Runtime caches live in `$OPENCODE_DATA_DIR`; logs go to `/mnt/log/`; nothing
  is deleted from `_raw/`.

## 3. Python

- `ruff format` for formatting. Line length **120**, target py310 (`pyproject.toml`;
  no per-file overrides), 4-space indent, double quotes.
- `make lint` is the blocking gate over the whole fabric: `E,F,I,UP` plus the
  widened `B,SIM,RUF,S` set (bugbear, simplify, Ruff-specific, bandit), all
  configured in `pyproject.toml`. Exemptions are documented there (three global,
  plus test-only S rules in `per-file-ignores`); do not add a bare `# noqa`.
  `make lint-strict` is an alias kept for older notes. New code should satisfy
  the whole set on the first try.
- Standard library first. The runtime dependency allow-list is exactly
  `cryptography`; tests assert it. Dev tooling is opt-in under `make devtools`.
- Tests are pytest, tiered by the registered markers (`unit`, `integration`,
  `contract`, `layout`, `slow`). A test that can state *why it exists* in its
  docstring does.
- Comments explain **why**; a comment that restates the code is deleted.

## 4. Shell

- `set -euo pipefail`; never rely on `bash -n` as a test
  (`tests/test_shell.py` covers what it cannot see).
- Write for bash 3.2 as well as 5 — the deployment hosts and macOS both run
  the scripts (`${array[@]+"${array[@]}"}`, no `mapfile`).
- shellcheck clean under `.shellcheckrc` (`make shellcheck`; the gate skips
  with a note when the binary is absent).
- Quote expansions, prefer `[[ ]]`, use absolute paths rather than `cd` chains.
- A script that mutates state fails **closed** and says what it refused.

## 5. Makefiles

- `help` is the default goal and lists targets via `##` comments.
- The Makefile is a **router**: role work lives in the role's own Makefile.
- Long recipes live in `scripts/`, not inline.

## 6. Commits

- Conventional commits — `feat|fix|docs|style|refactor|perf|test|build|ci|chore`
  (adopted from dsx-exchange) — one logical change per commit.
- A cross-role contract edit is one commit, never split across roles.
- Run `make hooks` once per clone: the pre-commit hook runs `keys-check` and a
  staged `ruff format` pass (it re-stages any reformatted Python and stops, so
  the formatted diff is reviewed before the commit lands).
- Never commit a secret; a leaked one is rotated, not rewritten silently
  (see §7).

## 7. Secrets

- No secret in any tracked file — not even a plausible-looking placeholder in
  docs (pattern: run-ai's `AGENTS.md`). Write `<redacted>` instead.
- Secret material lives under `.state/` (directory 0700, files 0600,
  gitignored). `make keys-check` enforces that for **both** `.state/keys/` and
  `.state/secrets/`; the resource-first helper reads
  `.state/secrets/build-nvidia.env` from there.
- Reference the secret **path only**. If one is found committed: rotate it,
  and report it per `SECURITY.md` rather than in a public change.

## 8. CI

- The **local pre-merge gate is authoritative**: `make ci` (add
  `CI_QUICK=1` for the fast pass) plus `make test-all` when the full suite
  matters.
- GitHub Actions **mirror** the gate (PLAN Step 48). Every workflow job has a
  local equivalent, and actions are pinned by SHA — never `@main`.
- One aggregate `gate` check is what a branch ruleset requires, so renaming or
  adding a job cannot leave a ruleset naming a check that no longer exists
  (pattern: cluster-api-provider-nico's `merge-gate.yml`).

## 9. Docs and memory

- One `AGENTS.md` per vault. Claims must be verifiable —
  `tests/test_claims.py` guards counts and forbidden phrases, so a new live
  surface may not restate something the fabric has already disproved.
- `MEMORY.md` is standing state only, replaced rather than appended; session
  detail goes to `sessions/YYYY-MM-DD.md`; `log.md` is the append-only audit
  trail.
- Markdown: GitHub-flavoured, `[[wikilinks]]` inside the vault, frontmatter
  `title` + `updated` (provenance pages add `source`/`license`/`type`).

## 10. Versions and release

- `VERSION` is the single source of truth (SemVer); `pyproject.toml` follows
  it, and a test enforces the agreement.
- Regenerate the SBOM (`make sbom`) whenever dependencies or the skill suite
  change; `make drift-check` is the umbrella gate for derived artifacts.
- A released change updates the CHANGELOG (adopted with Step 47); unreleased
  work does not.

## Enforced by

| Rule | Gate |
|---|---|
| keys, secrets, `.gitignore` backstop | `make keys-check` |
| formatting | `make format-check` (full-tree from Step 49) |
| Python lint | `make lint` (whole-tree `E,F,I,UP,B,SIM,RUF,S`; `lint-strict` is an alias) |
| shell | `make shellcheck`, `tests/test_shell.py` |
| layout, claims, contracts | `make validate`, `make contract-test`, `tests/` |
| derived artifacts | `make drift-check` (manifest, SBOM, skills, contracts) |
| everything, locally | `make ci` + `make test-all` |
