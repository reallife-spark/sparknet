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
- [2026-10-22] Plan cursor 5 -> 6 — **Step 5 closed** (`guard-apply` grantable
  in practice). The step found a defect the plan did not anticipate: three
  "approval" shapes were live at once — the issuer signed `{target,
  content_digest}`, the signer signed `{peer_fingerprint,
  guard_protocol_version, target_path, action, expires_at}`, and the peer's
  guard verified `{file_path, content_b64, content_sha256, issued_at,
  expires_at, nonce, request_id}`. Each side passed its own tests; no approval
  the Master could mint was one a peer would accept. The projection now lives
  once, in `../shared/sparknet-authz.py::guard_approval_message` (eight fields,
  compact sorted JSON, extra fields refused), stated as a contract in
  `../contracts/guard-approval.json`, with `../tests/test_contracts.py` failing
  the build if a second copy appears in either role. Two holes closed while
  fixing the shape: the envelope names the peer (`peer_fingerprint`, so an
  approval for peer A is refused by peer B) and carries no capabilities (the
  peer reads `guard-apply` from its own signed registry entry). DoD (4) is a
  real integration test — the peer's own guard daemon, loaded by path, accepts
  a Master-signed approval and answers `PATCH_VERIFIED_DRY_RUN`, with
  `wrong_peer` and missing-capability negatives; the protected-file *write*
  needs euid 0 + `chattr` and is a target-node item, stated as such rather than
  claimed. Cross-role: `contracts/` + `shared/` + both roles in one commit.
- [2026-10-25] Plan cursor 7 -> 20 — **Step 7 closed by re-scope** (fabric Step
  69C). 8090's instant-push purpose was superseded in direction by Step 6 (the
  signed registry is pushed Master→peer on 9090, so a Master-side ACL-push
  listener was never needed) and is retired. Fabric Step 69C re-scoped 8090 into
  the Master's peer→Master **intake** listener: `services/sparknet-telemetry-intake.py`
  + `systemd/sparknet-telemetry-intake.service` (staged via `make
  telemetry-intake-unit`, not enabled — a peer-facing socket on the authority-plane
  node is an operator decision), overlay-only, binding `10.100.0.1` and refusing a
  wildcard, attributing each `POST /api/v1/telemetry` by the WireGuard-authenticated
  source via the signed registry (refusing unregistered / revoked / `telemetry`-ungranted
  before the body is read), verifying with `authz.verify_telemetry_report`, recording
  evidence to `/mnt/log/sparknet-telemetry.jsonl`, and carrying no authority. The
  7-line `sparknet-registry-listener.py` stub and `test_listener_8090.py` — the
  text-inspection test this step's own Status flagged as "cannot fail for the failure
  the DoD names" — are **deleted**; `test_telemetry_intake.py` (15 tests) binds a real
  `ThreadingHTTPServer`. `contracts/ports.json` now records 8090 as
  `master-peer-intake` / `implemented`. Cross-role: fabric Step 69C, with the master
  docs (`docs/master-control-plane.md`, `MISSION.md`, `docs/registry-protocol.md`,
  `USER_MANUAL.md`, this plan, `MEMORY.md`) reconciled in the same pass. Step 68C's
  RFI request route will join this same listener rather than found a second one.
