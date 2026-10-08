---
name: wiki-audit
description: >
  Produce dedicated audit logs and reports for the wiki: a conflict log, a missing-content log, a
  duplicate-detection log, and a duplicate-detection report. Use this skill when the user says "run an
  audit", "/wiki-audit", "conflict log", "missing content log", "duplicate detection log", "duplicates
  report", "what pages contradict", "what's missing from the wiki", "find duplicate pages as a report",
  or wants persistent, file-format audit artifacts rather than a one-off console report. Distinct from
  wiki-lint (structure health) and wiki-dedup (page merges): this skill writes dated artifact files into
  the vault's audit/ directory so the state of the vault is reviewable over time.
---

# Wiki Audit — dedicated log and report artifacts

You produce four persistent artifacts recording the current state of the wiki,
so contradictions, missing content and duplicates are reviewable as files (and
over time), not just as a console report:

| Artifact | Purpose |
|---|---|
| `conflicts.log` | pages that state conflicting/contradictory things |
| `missing.log` | pages that are referenced but absent, or referenced-but-missing placements |
| `duplicates.log` | every duplicate candidate detected, with link evidence |
| `duplicates-report.md` | human-readable verdict of the duplicate scan |

## Before you start

Follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for
`.env`, then `~/.wiki/config`). This gives `VAULT_PATH`. Refuse to proceed
without it — writing audit artifacts into the wrong vault is worse than not
writing them.

Determine the audit directory:

- Fabric vault (has `concepts/`, `entities/`, … at its root): `<VAULT_PATH>/audit/`
- Role subvault (numbered layout): `<VAULT_PATH>/00_System/audit/`

Create it if it does not exist. Never write audit artifacts into `_raw/`,
`_staging/` or `_archives/` — they are diagnostics, not vault content.

## Scan and log

Run the vault scans in this order. For each, read pages via the Retrieval
Primitives in `llm-wiki/SKILL.md` (grep frontmatter, index.md inventory,
section-anchored reads) rather than full-page reads of every file.

### 1. Conflicts

A conflict is two pages (or two spots in one page) asserting incompatible
facts about the same subject without cross-referencing each other.

- Read `index.md` for the page inventory.
- Grep each page for life-cycle / status / placement assertions and for
  explicit negations ("never", "no longer", "deprecated", "currently X").
- Where two pages disagree, append one line each to `conflicts.log`:
  `YYYY-MM-DD pageA.extract <> pageB.extract — one, or both, stale?`
- Link every conflicting page to the log line so the reader can verify.

### 2. Missing content

Three distinct misses, all logged to `missing.log`:

- **Broken wikilinks** — a `[[target]]` whose target file does not exist.
- **Dangling category/placement references** — a page whose frontmatter or
  prose names a location that is absent.
- **Referenced-but-absent files** — a page, manifest or index that names a file
  path which is not on disk.

Every entry: `YYYY-MM-DD <source> references <missing target>`. Do not invent
the fix — the log records *what is missing*, not how to fix it.

### 3. Duplicates

Detect page-level identity collisions: different titles covering the same core
concept (title-similarity, identical frontmatter subjects, near-identical
bodies). Reuse the detection approach documented in `wiki-dedup/SKILL.md`.

For every candidate pair append a line to `duplicates.log`:
`YYYY-MM-DD <pageA> ~ <pageB> — <reason>: <evidence>`.

## Write the report

From `duplicates.log`, produce `duplicates-report.md` in the audit directory:

- **Header**: date, vault path, page count scanned, artifact paths.
- **Summary table**: every candidate pair, the similarity reason, and a verdict
  — `merge`, `distinct`, or `review`.
- **Verdict rationale**: one line per pair explaining why it was judged merge /
  distinct / review. Use the evidence lines, not guesses.
- **Recommendation**: whether to run `wiki-dedup` (merges) or `wiki-lint`
  (structure) next.

`duplicates-report.md` is prose for a human reviewer; `duplicates.log` is the
machine-readable evidence chain. They must agree — every verdict in the report
has its evidence line in the log.

## Conventions

- Date stamp every entry as `YYYY-MM-DD`.
- Append, never rewrite: audit artifacts accumulate so the vault's state over
  time is reconstructable. If a page is later fixed, the fix is recorded in the
  next audit as a new dated line, not by deleting the old one.
- Keep entries one line each; use the report for prose.
- Do not self-lint: these four files are artifacts, and `wiki-lint` may report
  them as noise — note their existence in the report header so a later lint
  pass knows they are intended.

## Cross-references

- `wiki-lint/SKILL.md` — structural health; run before/after for context
- `wiki-dedup/SKILL.md` — the merge workflow this report feeds into
- `wiki-status/SKILL.md` — ingestion delta context