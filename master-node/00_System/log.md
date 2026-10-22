# master-node log — append-only transition trail

One line per plan transition, newest at the bottom. History before the numbered
layout lives in git history; this is the running record from `00_System/log.md`
forward. The root `log.md` is a symlink to this file.

- [2026-10-06] LAYOUT master vault moved to the numbered PARA layout: legacy
  category dirs became symlinks into `00_System`–`07_Archives`;
  `02_Daily/2026-10-05.md` holds the session note that used to live at
  `sessions/`.
- [2026-10-08] MEMORY master `02_Daily/` cleared by operator decision — this
  development's sessions live exclusively in the fabric root's `sessions/` (the
  master build timeline was folded into `../sessions/2026-10-05.md` before
  removal). Role `02_Daily/` stays empty until the master's own main is opened
  and used. The role also gains its own `.opencode/agents/chat.md` (read-only
  chat over this vault), mirroring the fabric root's config.
- [2026-10-22] Plan cursor 2 -> 5 — **Step 2 closed** (registry schema and the
  spec/impl boundary). The canonical registry shape was decided from the
  implementation (`../shared/sparknet-authz.py`), not guessed: it is stated once
  in `../contracts/registry-schema.json`, and
  `master-node/manifests/registry.schema.json` is a symlink to it. The checker
  `../shared/sparknet-registry-schema.py` is standard-library only (the runtime
  allow-list is `cryptography` alone) and refuses a schema keyword it does not
  implement. DoD (2) is asserted in its honest direction: the role *declares*
  its build state (`MISSION.md`) and the declaration must agree with the tree
  and the plan's open steps. Every `docs/` page now declares a `status:` from a
  closed vocabulary, and two pages carrying stale claims in both directions were
  corrected. Cross-role: `contracts/` + both roles in one commit.
