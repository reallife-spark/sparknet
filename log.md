---
title: sparknet Log
---

# sparknet Log

Append-only audit trail. Newest entries at the bottom. One line per state
transition (plan advances, ingests, rebuilds) — detail belongs in the session
file, not here.

- [2026-10-03] INIT vault scaffolded at `/mnt/knowledge/sparknet` via `opencode.new` — categories: concepts, entities, skills, references, synthesis, journal; git initialised; staged_writes=false
- [2026-10-04] SPLIT fabric became two roles: `contracts/` + `shared/` + `peer-node/` (implemented) + `master-node/` (specified, not built)
- [2026-10-04] VENDOR 31 wiki skills into `.opencode/skills/` (MIT, upstream ec2b6bc); no global skill farm dependency
- [2026-10-04] BUNDLE `make bundle ROLE=<role>` + `bundle-verify` — both roles extract and run standalone
- [2026-10-04] PLAN root `PLAN.md` Steps 1–3 complete (split, vendoring, bundles); cursor → 4 (commit and push)
- [2026-10-04] TEST added `tests/test_contracts.py` (cross-role conformance), `tests/test_layout.py` (phantom dirs, dangling links, hard-coded paths), `tests/test_shell.py` (the `]]` bug `bash -n` cannot catch)
- [2026-10-04] FIX `worker` → `peer` in live surfaces; removed 8 phantom dirs and a stale `services/`; corrected pre-split absolute links
- [2026-10-04] COMMIT split the fabric (229 files) as `sparknet <sparknet@local>`; pre-split `ad1cc39` still an ancestor
- [2026-10-04] BLOCKED push — no git credential available (no helper, no store, no token in env); awaiting a credential
- [2026-10-04] REWROTE the three unpushed split commits to author `sparknet <sparknet@local>`, matching `ad1cc39`; tree hash unchanged
- [2026-10-04] PUSHED `78f1602..c6960f1` to `origin/main`; remote tip verified equal to local, `ad1cc39` still an ancestor
- [2026-10-04] DONE root PLAN Step 4 (all 5 DoD verified); cursor `current: done`
