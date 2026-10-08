# sparknet — Session Memory

> Standing state only. Read at session start; **replace, never append**.
> The plan and its cursor live in `PLAN.md` — this file mirrors it, it does not
> own it. Per-session detail belongs in `sessions/YYYY-MM-DD.md`.

Updated: 2026-10-08

## Standing State

- **Plan cursors**: root `PLAN.md` `current: done` — **Step 14 (fabric claims
  conformance + the `--help` contract) complete 2026-10-08**; Steps 1–14 all
  closed (each DoD in `PLAN.md`). New fabric-level roadmap work opens a new
  step rather than reopening one. **Step 12 (local three-node rehearsal)
  complete** — the whole arc runs live on three real node trees under
  `/tmp/opencode/rehearsal` (51 checks/0 failures, dated transcript, repeatable);
  `scripts/sparknet-rehearsal.sh` is the reproducible harness, and the rehearsal
  also exposed two real signer CLI str/Path defects now fixed with regression
  tests. **Step 13 (agx64/agx32 handoff) COMPLETE 2026-10-07** — the handoff
  document `contracts/deployment-runbook.md` is written and every confirm-user
  item was answered live on the real pair. **The election FORMED on the real
  pair (2026-10-07)** — both hosts co-signed a root naming agx64
  (2/2, root_id `65d9ce25cbb40566b6735b0624d9840dc69ff35d66b3a97543fe650ed09212f5`);
  agx64 master-identity flipped to master, agx32 stayed peer. Transport
  deviation: **UDP did not cross the 192.168.10/20 subnet boundary at this
  machine (the gateway)**, so the ceremony ran over SSH loopback tunnels
  (trustless relay; keys stayed on hosts; 4210 loopback-only). **Transport
  solved thereafter (Gateway Decision)** — the gateway has no kernel firewall
  tooling and no root here, so a **userspace UDP relay** (`/tmp/gateway_udp_relay.py`,
  binds 192.168.10.1:51820 + 192.168.20.1:51820, forwards between the hosts;
  no root needed) stands in for opening UDP 51820, and wg peers re-point at the
  gateway IPs. The overlay now **handshakes and pings on real NICs** (0% loss
  ~2 ms; peer /32 kernel routes had to be added — AllowedIPs create none).
  **Phase 6–8 are live**: master role root staged at `/root` (signer unit's `%h`),
  state dir + keys moved to `/root/.local/state/sparknet/master-node`,
  trust-root.json extracted, `/root/.env` sets SPARKNET_NODE_ID/STATE_DIR and a
  PATH preferring the 3.9.5+crypto50 venv over the host's unusable 3.8.10+
  crypto2.8 system python; signer runs via `sparknet-master-signer.service`
  (socket 0600, root-id `65d9ce…`, capabilities `["sign"]`, restart survives,
  single key-holder). Registry: signed entry for agx32 (verified by the root
  alone) + `manifests/node-authorizations.json`; three escalation refusals hold
  live; agx32 verified the distributed entry with its own authz and matched its
  fingerprint. No *share* claimed (4201–4203 spec-only). **C4 revoke-demo live
  (2026-10-07, pair restored after)** — surfaced + fixed two artifact defects:
  agx32's `manifests/keys/master-ed25519.pub.b64` was a placeholder key (would
  fail every signature check) and both hosts' `node-authorizations.json` were
  bare entries while the guard needs the wrapped `authorizations:[…]` registry.
  After fixes: one socket signature `revoked: true` (ledger block 64717431…)
  ⇒ peer `reason: revoked caps: []`, guard `capabilities: []`, a
  signature-VALID master packet refused `403 capability_missing`, and
  `wg-render-master` dropped the stanza; fresh `revoked: false` signature
  (b3200847…) restored the pair. **C2 reboot proven**: ran a real reboot on
  agx64; signer unit came back active (enabled), socket root-id == `65d9ce25…`,
  capabilities `["sign"]`, ledger intact, peer auth still verifies after reboot.
  **New ops caveat**: wg0 does NOT survive reboot on this tegra host
  (`CONFIG_WIREGUARD=n`; overlay is userspace `wireguard-go`, started ad hoc) —
  restore via `/root/scripts/sparknet-wg-restore.sh` (proven, idempotent); a
  wg0 unit or restore-inclusive "up" check is a Phase 9/ops item. Also noted:
  signer `_serve_one` single-threaded, no client timeout. **C1/C3/C5 answered
  with live probes**: overlay rides real NICs to the gateway relay (routes
  `dev wg0`, endpoints `dev eth0`, handshakes seconds old, ping ~2 ms 0% loss
  both ways; userspace wireguard-go since tegra `CONFIG_WIREGUARD=n`); exactly
  one process holds `operational.ed25519` (signer PID 5063, no other fd holder,
  key 0600); deployed signer containment confirmed (socket `srw-------` 0600
  unix-stream by the signer, no TCP listener, `--describe` caps `["sign"]`,
  `check_socket_path` refuses `tcp://` and outside-state paths, no peer service
  imports the signer, parity asserts `not_reachable_from_here`). **All six
  confirm-user items answered; operator acknowledged 2026-10-07 and closed
  Phase 9 by decision ("Close without exercising")** — the destructive
  rollback / replace-Master legs in `contracts/deployment-runbook.md` §Phase 9
  stay documented-but-unexecuted, so the live pair is left up. `PLAN.md` Steps
  1–13 closed 2026-10-07; Step 14 opened 2026-10-08.
  `peer-node/PLAN.md` `current: 2` (container first);
  `master-node` `current: 2` — Phase 0 (13–18: consensus, parity, isolated signer,
  admin surface), honest verification (19), the **keypair/registry substrate (1)**
  and, as measured on 2026-10-06, **Steps 3 and 4** are complete; **Steps 2 and
  5–12 are unbuilt** and the cursor points at the first of them (Step 2, whose DoD
  is contradicted, not merely unimplemented). The peer build-out is `peer-node`
  Steps 2–8: container, grants, bridge, Open WebUI, conversation passing,
  `MASTERSPIKE`, sharing regime.
- **Both role vaults now store content in `00_System`–`07_Archives`.** Legacy
  category names in `peer-node/` and `master-node/` are symlinks (shims), so the
  wiki skills and old instructions still resolve; `make shims-check` proves no
  shim has become a real dir.
- **Both role vaults are now signed.** `peer-node` owner `U-27689`, key at
  `.state/keys/user.ed25519` (0600), never committed (`keys-check` proves it).
  `master-node` owner `U-97443`, key outside the vault under
  `$SPARKNET_STATE_DIR` (per the master's outside-vault key rule). Notes carry a
  signed tracking envelope; each `make -C <role> provenance-verify` exits 0.
  New intake lands unsigned pending notes via `make -C <role> ingest SRC=…`;
  email fails closed against `authorised_senders` in `user.md`. The
  containerised vault-curator remains a peer PLAN Step 5 placeholder — transport
  is specified, not built.
- **The Master administers the fabric's git, file share, NAT and vector
  embeddings DB — as a role responsibility, not an existence claim.** Ports
  `4220`–`4223` in `contracts/ports.json` are `spec-only`, `bound_by: master`,
  `overlay_only`, bound to `10.100.0.1`; scoped in
  `master-node/plans/MASTER_ADMIN_PLAN.md`. No daemon, no code, no adjacency to
  the signer (same structural rule as the admin surface).
- **`$SPARKNET_STATE_DIR` resolves outside the vault.** `$XDG_STATE_HOME/
  sparknet/master-node`, else `~/.local/state/...`. Not gitignored-inside — out.
  The admin surface bind-mounts the vault read-only into an LLM container, so a
  key under it is readable from there; `.gitignore` was never the relevant
  defence and `make keys-check` fails if the variable is pointed back inwards.
  The peer keeps `<vault>/.state` on purpose: nothing mounts that vault.
- **Vault**: three, not one. Fabric root plus `peer-node/` and `master-node/`,
  each with its own `.env`, category skeleton and `AGENTS.md`. A session resolves
  which one it is in before writing anything — see the Memory Protocol note below.
- **Config**: `.env` per vault (`VAULT_PATH`, gitignored, regenerated by
  `make env-init`); staged writes: false.
- **Blockers**: none blocking. The admin page is declared but not bound (nothing
  listens on `10.100.0.1:8080`; `DoD: confirm: user`, master Step 18) and the
  overlay doesn't survive reboot on the tegra host (`CONFIG_WIREGUARD=n`;
  userspace `wireguard-go`) — restore via
  `/root/scripts/sparknet-wg-restore.sh`. The signer's missing client timeout
  (`_serve_one` blocks with no read timeout) is recorded as **master build plan
  Step 20**, deliberately unbuilt. Phase 9's destructive legs
  (rollback / replace-Master re-formation) are documented in
  `contracts/deployment-runbook.md` and deliberately not executed.
  **Outstanding, unclaimed:** rotating
  and revoking the old broad OAuth token from the split-day leak.
- **Local gates prove the tree; the pair proves the fabric.** Everything
  `make test-all` / `lint` / `bundle-verify` check is fully verifiable on this
  host. Claims about the live pair (agx64/agx32) were verified from those hosts
  themselves per the runbook; anything further needing a second node or the
  Master carries `DoD: confirm: user` rather than a local pass. This host has
  no GPU (`nvidia-smi`) and does not run the overlay itself.

## Key Standing Facts

- **This is a fabric, not a node.** Two roles, one contract. Most confusion comes
  from reading a page that belongs to one role as though it described both.
- **A role subvault alone is not a deployment.** A peer cannot verify a signature
  without `contracts/` and `shared/`, so a bare copy fails validation by design.
  `make bundle` assembles a real deployment; `make bundle-verify` proves it.
- **Authority is key possession, not a capability grant.** A peer with the whole
  capability vocabulary but no private key can never grant, revoke or escalate.
- **The Master role's Phase 0 and its own boundary work are built — and the
  election/signer arc is now proven live** (build plan Step 14; Steps 13–19 done;
  fabric PLAN Step 13 complete 2026-10-07). It has `scripts/`,
  `services/`, `systemd/`, `manifests/`, `blockchain/` and
  `security/`, and runs the peer's
  services **by path** — `make -C master-node parity` proves the resolution and
  the bundle check proves it landed inside the extracted bundle.
  `services/sparknet-signer.py` is the only process holding the operational key:
  unix socket, mode 0600, typed payloads, never signs caller-supplied bytes, and
  refuses to start against a root superseded in its own ledger. Unit-tested with
  36 tests and 12 mutations; **deployed and proven in production on agx64
  (2026-10-07)** — ran as `sparknet-master-signer.service`, formed the 2/2 trust
  root with agx32, signed a live registry entry, survived a real reboot, refused
  non-Master keys/unnamed nodes/tampered roots, and drove a live
  revoke→peer-inert→re-authorize cycle; its unit stays excluded from `make units`
  by design (enabling a key-holder is the election's decision). The remaining
  honestly-unclaimed item is the admin page: declared, not bound (Step 18 DoD).
- **Claim defects the 2026-10-06 audit found (all recorded where they were found,
  not fixed silently).** (a) `master-node`'s Steps 1–12 all had `[x]` boxes
  against `Status: pending` lines — the boxes were bulk-flipped in one commit and
  the statuses never written; the plan now carries measured statuses per step.
  (b) `make keys-check` failed on a clean tree because the test corpus pasted the
  PEM literal the scanner searches for — the marker is assembled at runtime now.
  (c) `master-node/manifests/registry.schema.json` validates nothing: it demands
  `role`/`1.0.0`/`signature` where the shipped peer registry has no `role`,
  `schema_version: "1.0"` (pinned by a peer test) and the signer emits
  `signature_b64`. Two roles, two shapes, neither matching the schema — the
  canonical shape is an open contract decision (master build plan Step 2).
  (d) Steps 7–10 of the master plan were "verified" by tests that read the
  scaffold's source text instead of binding anything; 7–8 lines each.

- **The wiki suite is vendored** at `.opencode/skills/` (33 skills: 32 vendored +
  1 local, MIT). No global skill farm dependency. `make wiki-sync` re-vendors,
  `make wiki-verify` proves no drift.
- **Skills resolve the nearest `.env`.** That is what keeps a role subvault
  honest. Run `make wiki-preflight` first and never work around a failure: the
  skills would silently write into the wrong vault.
- **Cross-role changes are atomic.** Edit `contracts/` and both roles in the same
  commit, then `make contract-test`. `tests/test_contracts.py` exists to fail
  when one role's copy of the contract drifts.
- **The shipped registry is empty on purpose.** No node has privileges until the
  Master signs something. That is the fail-closed default, not an oversight.
- **`gh` may hold a working token while git has no helper.** They are independent:
  `gh auth status` can be valid with git still unable to authenticate. Push with
  `git -c 'credential.helper=!gh auth git-credential' push` — scoped to the one
  command, so no git config is touched.
- **`make bundle-verify` only verifies the newest archive.** Rebuild first
  (`make bundle ROLE=…`) or it will cheerfully re-prove a stale bundle.
- **Never read large tool output through a pipe.** `opencode agent list` is ~9 MB
  of per-agent permission config; a non-seekable stdout silently drops the tail,
  which once made a working agent look dead and cost a confidently wrong
  diagnosis. Redirect to a file. `tests/test_agents.py` asserts the read size for
  exactly this reason.
- **opencode reads agents from `.opencode/agents/` and also accepts the singular
  `agent/`.** Agents live at the plural, documented path; neither spelling was
  ever broken. Ask the loader (`opencode agent list`) rather than inferring from
  docs or from what is on disk.
- **Use `make test-all`.** Bare `pytest` at the root runs only `tests/`, which is
  the fabric level and not the peer implementation.
- **`bash -n` is not a shell test.** It accepts `if [ -n "$x" ]]; then` — bash
  reads `]]` as an argument — so the failure only appears at runtime, on a branch
  nothing exercises. `tests/test_shell.py` checks for it textually.
- **Every script must handle `--help` — and answering it must do nothing.**
  Fabric-wide since Step 14: `tests/test_shell.py::test_fabric_every_script_has_help`
  runs all 33 shell scripts with `--help` and asserts rc 0, non-empty usage, an
  unchanged repo porcelain and an uncreated rehearsal tree; peer's own
  `test_every_script_has_help` covers the peer vault. A script without arg
  handling *executes its full body* on `--help` — that was the old
  `user-env-manifest.json` timestamp churn (identity-capture and provision ran
  during the suite), and on the master role `--help` reached the killswitch and
  the key generator. `tests/test_claims.py` locks the prose side: documented
  skill count == disk count, forbidden stale phrases absent from live surfaces,
  index contract-table completeness. Any new script and any new claim must do
  the same.
- **Relocate before declaring anything path-independent.** Four bugs only appeared
  when the tree ran from a different directory: a `.env` recomputed against an
  empty variable, a fabric root detected by its directory name, and a stale
  `.env` preserved because it looked configured. `make bundle-verify` does this.
- **Provenance keeps old vocabulary.** `references/` and `plans/` may still say
  "worker" and may hard-code host paths, correctly — they record what was true.
  Current surfaces must not; `tests/test_layout.py` enforces the difference.