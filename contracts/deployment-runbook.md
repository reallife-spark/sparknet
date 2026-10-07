# Deployment runbook — the real three-node handoff (Step 13: agx64 + agx32)

> Status: **handoff document written; run not started.** The two hosts are
> unreachable from this machine as of 2026-10-07 (no ping, no SSH; this host is
> on `192.168.178.0/24`, the agx hosts on `192.168.10.64` / `192.168.20.32`;
> no agx node is on the tailnet). Step 13's DoD is `DoD: confirm: user`
> throughout — every claim below about a deployed node must be confirmed by a
> human who can see that node. This runbook is the procedure, not the proof.

This document is the operational companion to the protocols that define the
behaviour: `consensus-protocol.md` (election, the cluster trust root,
re-formation), `share-protocol.md` (peer↔peer sharing regime, four clocks,
isolation), `guard-protocol.md` (Master↔peer approval), and the addressing in
`overlay.json` + `ports.json`. If a command here disagrees with those, the
contract wins — this runbook is a script the operator reads, not a norm.

It was written from the **Step 12 local rehearsal** (`scripts/sparknet-rehearsal.sh`,
51 checks green on this host), translated to the differences that only exist
when the nodes are real machines on one overlay. Those differences are in the
next section and must be read first, because they are why a copy-paste of the
rehearsal would silently fail.

## What changes when the nodes are real

| Rehearsal (one box) | Real nodes (Step 13) |
|---|---|
| three node trees under `/tmp/opencode` | three physical hosts, `agx64`, `agx32`, plus a third (`nuc`/primary) that wins the election |
| exchange binds `127.0.0.1:4210`, ceremonies loopback | one host runs `serve` bound to its **overlay** address; ceremonies on each node dial `http://<exchange-overlay-ip>:4210` over the WireGuard overlay (`ports.json` 4210: `overlay_only: true`) |
| cluster keys under `node-X/cluster-keys` in the scratch tree | cluster keys live in each node's **state dir** (`$SPARKNET_STATE_DIR/keys`), 0600, so they are not shipped with or backed up with the vault |
| signer started as a background process | signer starts via `sparknet-master-signer.service`; the unit's `%h` paths resolve to the system manager's home (`/root` when no `User=` is set — the unit deliberately has none), so the master tree is installed at `/root` with config in `/root/.env` |
| one machine's operator runs every ceremony | the three ceremonies are run **by each node's own operator** on that node, against the shared exchange |
| peers "connect" only to the signer socket | peers talk to each other over the overlay; the **share transport (ports 4201–4203) is `spec-only` and unbuilt** — peer↔peer in this step means real overlay reachability and signed registry distribution, and that boundary is stated, not straddled |
| everything supervised by the script | each phase below is asserted by the same check list; anything a script cannot observe is `confirm: user` |

## Preconditions on every host

- Python 3.11+ and `cryptography` (the one runtime dependency, `requirements.txt`).
  On a host without the repo `.venv`, the role scripts already fall back to
  `python3` when `$FABRIC_ROOT/.venv` is absent — but `cryptography` must be
  importable by that interpreter.
- `wg` + `wireguard-tools` for the overlay.
- A writable `$SPARKNET_STATE_DIR` outside the vault (default
  `~/.local/state/sparknet/master-node` on the master, peer equivalents on the
  peers).

## Phase 0 — build and transport the bundle

A bundle is the whole node (`make bundle ROLE=master` assembles
`peer-node/` + `master-node/` + `contracts/` + `shared/` + `scripts/` +
`.opencode/`). One full-node bundle serves all three hosts; `ROLE=master` is
the build profile, and the two peers prove themselves with the peer checks at
Phase 4.

```sh
make bundle ROLE=master                      # writes dist/sparknet-master-worktree-<ts>.tar.gz
# to each host — transport is OUT OF BAND and only ever the pubkey halves cross.
# e.g. scp the tarball, then on each host:
#   tar xzf sparknet-master-worktree-<ts>.tar.gz --strip-components=1 -C <role-root>
```

`make bundle-verify` only ever proves the newest archive — rebuild, then ship.
A stale archive is a silent false green (recorded in `MEMORY.md`).

## Phase 1 — install each node

**Master host** (the node that will win; layout matters for the systemd unit):

```sh
# tree at /root so %h/services, %h/blockchain, %h/manifests resolve (no User= line)
./scripts/sparknet-env-init.sh /root/master-node      # writes /root/master-node/.env… see below
```

The signer unit reads `EnvironmentFile=-%h/.env`. It needs two variables the
role `.env` does **not** set by default:

```
# /root/.env (or wherever the operator's home is)
SPARKNET_NODE_ID=<node-id>              # must name this node when the root forms
SPARKNET_STATE_DIR=/root/.local/state/sparknet/master-node
```

Then `make -C master-node keygen` (creates
`$SPARKNET_STATE_DIR/keys/{cluster,operational}.ed25519` + `.pub.b64`, 0600).

**Two peer hosts**:

```sh
./scripts/sparknet-env-init.sh <peer-role-root>
make -C peer-node keygen                # peer keys into its own state dir
```

## Phase 2 — the overlay is up before any election

The election rides the overlay (`ports.json` 4210 `overlay_only`). Bring `wg0`
up first, out of band: each host generates a WireGuard keypair
(`wg genkey | tee <state>/wg.key | wg pubkey > <state>/wg.pub`, 0600), the
three public halves and overlay addresses (`10.100.0.1` `10.100.0.2`
`10.100.0.3`) are exchanged, and each host's `[Peer]` stanzas are written from
`master-node/configs/wireguard/master-peer.template`. Assert: every pair pings
its `/32` before Phase 5. A node that cannot reach the exchange over the overlay
cannot vote — that is the liveness price unanimity documents, not a fault.

## Phase 3 — cluster keys and the roster

Each node runs `shared/sparknet-election.py keygen --key-dir
$SPARKNET_STATE_DIR/keys` (mints the cluster Ed25519 and the operational
keypair for bidding). The three `cluster.pub.b64` halves cross machines **out of
band** and are assembled into `cluster-members.json` exactly as the rehearsal
did: three distinct `{node_id, fingerprint, wireguard_pubkey, cluster_pubkey}`,
fingerprint = sha256 hex of the member identifier. `serve` reads only this file.

## Phase 4 — peer-only proof (before any authority)

On every node: role validation passes, `manifests/*-identity.json` still says
`"role": "peer"`, and no trust-root doc exists. That is the fail-closed default
the contract ships, and it is what a bare node must look like at this exact
point — not a moment later.

## Phase 5 — the election

1. One node hosts the exchange:
   `shared/sparknet-election.py serve --members cluster-members.json
   --bind 10.100.0.<exchange-host> --port 4210`.
2. The winner candidate's operator runs
   `make -C master-node election-approve EXPECT=<winner>
   URL=http://10.100.0.<exchange>:4210 KEY_DIR=$SPARKNET_STATE_DIR/keys`.
3. The two others run
   `make -C peer-node election-request CANDIDATE=<winner>
   URL=http://10.100.0.<exchange>:4210 KEY_DIR=$SPARKNET_STATE_DIR/keys`.

Assert (scriptable on the exchange host, via `GET /election/status` until
`formed`):

- `GET /election/root` carries three co-signatures from three distinct members;
- the winner's identity flips to `"role": "master"`, its operational key is
  `held`, its `master-node/manifests/cluster-trust-root.json` names it;
- the other two stay `"role": "peer"` with **no** trust_root block and **no**
  root document — same byte-level no-loss assertion as the rehearsal's
  before/after snapshot (DoD 5) applied over `wg0` delivery.

## Phase 6 — the signer, via the unit, not a shell

On the winner: place the *formed* root where the unit looks for it. The unit
refuses `manifests/cluster-trust-root.json` (it is a fail-closed template); it
wants `$SPARKNET_STATE_DIR/trust-root.json` — extract the root document's
`root` object (the rehearsal's one-liner, minus any environment it must not
carry). Then:

```sh
make -C master-node signer-unit          # stages, does NOT enable
systemctl daemon-reload
systemctl enable --now sparknet-master-signer.service
```

Assert: `sock` exists under `$SPARKNET_STATE_DIR/signer`, `--describe` output
matches, and a `root-id` exchange over the socket returns the formed root's id
with capability set exactly `["sign"]`.

## Phase 7 — registry and escalation (DoD 7, repeated on real nodes)

- Elected master signs a registry entry; a still-peer verifies it with
  `authz.verify_signature` against `root["master_pubkey"]` alone.
- The reference refusals must all hold on the deployed unit: the loser's own
  operational key (`is not the key this root authorises`), a node the root does
  not name (`refusing to sign`), a tampered trust-root copy (`not valid`).
- `sparknet-registry-sign.sh` (master script) writes
  `manifests/node-authorizations.json`; peers re-verify it by the root alone.
  **`confirm: user`**: that the unit survived a reboot (`systemctl restart`),
  and that no second process holds the operational key.

## Phase 8 — peer↔peer on a real transport, honestly bounded

With three registry entries the governance mode is `master_governed`
(`overlay.json`). What exists to test now is real overlay reachability and
signed registry distribution. The **share transport itself is unbuilt**
(`ports.json` 4201–4203 `spec-only`); a data-plane stanza open/close recording
in the ledger is the premise to check **when** the transport exists
(`overlay.json` `data_plane_stanza.unverified_on_dev_host`). Do not claim a
peer↔peer *share* happened. **`confirm: user`** for every overlay-observed
behaviour, since no suite on this machine can see it.

## Phase 9 — rollback and re-formation

- Rollback an election: `systemctl disable --now sparknet-master-signer.service`,
  remove the state trust root and the flipped identity fields, `wg-quick down`,
  rebuild from Phase 0.
- Replace the Master: never by revoking — a new root with a new nonce
  (3/3), per `consensus-protocol.md` §Re-formation.
- Revoke a node: one signature; the node becomes inert at the guard
  (cannot receive a valid approval). **`confirm: user`**: the guard's bind-and
  -apply refusal on the revoked host.

## Deliverables of the run

1. The dated transcript of every assertion above (mirror
   `scripts/sparknet-rehearsal.sh`'s check style; save under `/mnt/log/`).
2. The `confirm: user` list, answered by someone who can see the nodes:
   overlay up on real NICs, signer unit surviving restart, revoked peer inert,
   deployed signer containment (master build plan Step 17 DoD 3).
3. This step flipped to complete **only** when (1) and (2) land; nothing in it
   is claimed from this machine.