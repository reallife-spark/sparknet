# Deployment runbook — the real handoff (Step 13: agx64 + agx32)

> [!warning] **Historical Step 13 procedure; roles changed at Step 57.**
> This page names `agx64` as Master and `agx32` as peer, which was true for the
> Step 13 deployment. The current Step 57 pair is the reverse: **`agx64` peer
> (`sparknet-node-0001`, `10.100.0.2`) / `agx32` Master
> (`sparknet-node-0002`, `10.100.0.1`)**. Do not copy a role-bound command
> without re-mapping it. Use `MEMORY.md`'s live-fabric section for current
> addresses and state dirs.
>
> Status: **Phase 0–1 complete; handoff being executed.** The two nodes were
> moved onto the `192.168.178.0/24` LAN on 2026-10-12; the old
> `192.168.10.0/24` / `192.168.20.0/24` legs are retired. `agx64` (Master,
> hostname `red-team`) is now `192.168.178.131` and `agx32` (peer, hostname
> `blue-team`) is `192.168.178.133`, both with the `wg1` overlay up
> (`10.100.0.1/32` ↔ `10.100.0.2/32`). The
> bundle has shipped to both nodes and been extracted, Python 3.9 venv +
> `cryptography 50.0.2` are provisioned on both, cluster/operational keys are
> minted, and `wireguard-go` (userspace, no tegra kernel module) is installed on
> both for the overlay. Step 13's DoD is `DoD: confirm: user` throughout —
> every claim below about a deployed node must be confirmed by a human who can
> see that node. This runbook is the procedure, not the proof.

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
| three node trees under `/tmp/opencode` | **two** physical hosts, `agx64` (`red-team`, 192.168.178.131) and `agx32` (`blue-team`, 192.168.178.133), running as a 2-of-2 **pair** — one is elected Master, the other stays peer. (A three-node cluster stays lawful; Step 13 exercises the pair so that the elevate-to-master path is exactly the 2-of-2 unanimous vote, both peers deciding together.) |
| exchange binds `127.0.0.1:4210`, ceremonies loopback | one host runs `serve` bound to its **overlay** address; ceremonies on each node dial `http://<exchange-overlay-ip>:4210` over the WireGuard overlay (`ports.json` 4210: `overlay_only: true`) |
| cluster keys under `node-X/cluster-keys` in the scratch tree | cluster keys live in each node's **state dir** (`$SPARKNET_STATE_DIR/keys`), 0600, so they are not shipped with or backed up with the vault |
| signer started as a background process | signer starts via `sparknet-master-signer.service`; the unit's `%h` paths resolve to the system manager's home (`/root` when no `User=` is set — the unit deliberately has none), so the master tree is installed at `/root` with config in `/root/.env` |
| one machine's operator runs every ceremony | the ceremonies are run **by each node's own operator** on that node, against the shared exchange. A pair has exactly two seats at the table; only the winner's operator runs `election-approve`, the other runs `election-request` |
| peers "connect" only to the signer socket | peers talk to each other over the overlay; the **share transport (ports 4201–4203) is `spec-only` and unbuilt** — peer↔peer in this step means real overlay reachability and signed registry distribution, and that boundary is stated, not straddled |
| everything supervised by the script | each phase below is asserted by the same check list; anything a script cannot observe is `confirm: user` |

## Preconditions on every host

- Python 3.9+ and `cryptography` (the one runtime dependency, `requirements.txt`).
  The "3.11+" floor written when this book was drafted was stricter than the
  code needs: the only 3.9+-only runtime call is `str.removesuffix()`, every
  `X | None`/generic annotation is defused by `from __future__ import
  annotations`, and `tomllib` is confined to the test suite. Verified 2026-10-07
  on Ubuntu 20.04 hosts whose only candidate is **python3.9.5**: smoke tests for
  `removesuffix`, annotation-as-string, and the exact `cryptography` API surface
  the code imports (Ed25519 + PEM serialization) all pass. Note the hosts ship
  `cryptography 2.8` — old enough that the surface still works, but the pin is
  `>=42`, so **upgrade it to ≥42** or the peer guard refuses every approval.
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
`.opencode/`). The same bundle serves every host; `ROLE=master` is
the build profile, and the pair proves itself with the peer checks at
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
make -C peer-node keys                  # peer keys into its own state dir
                                        # (NB: the peer target is `keys`; there is no `make keygen`
                                        #  in peer-node — the runbook once said so, and the first
                                        #  real run proved that stale line wrong)
```

## Phase 2 — the overlay is up before any election

The election rides the overlay (`ports.json` 4210 `overlay_only`). Bring `wg1`
up first, out of band: each host generates a WireGuard keypair
(`wg genkey | tee <state>/wg.key | wg pubkey > <state>/wg.pub`, 0600), the
public halves and overlay addresses (`10.100.0.1` for the prospective Master,
`10.100.0.2` for the peer — allocate from `overlay.json`
`peer_host_range` for the rest) are exchanged, and each host's `[Peer]` stanzas
are written from `master-node/configs/wireguard/master-peer.template`. Assert:
both directions ping the `/32` before Phase 5. A node that cannot reach the
exchange over the overlay cannot vote — that is the liveness price unanimity
documents, not a fault.

## Phase 3 — cluster keys and the roster

Each node runs `shared/sparknet-election.py keygen --key-dir
$SPARKNET_STATE_DIR/keys` (mints the cluster Ed25519 and the operational
keypair for bidding). The `cluster.pub.b64` halves cross machines **out of
band** and are assembled into `cluster-members.json` exactly as the rehearsal
did: two or three distinct `{node_id, fingerprint, wireguard_pubkey, cluster_pubkey}`,
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
3. Every remaining member runs
   `make -C peer-node election-request CANDIDATE=<winner>
   URL=http://10.100.0.<exchange>:4210 KEY_DIR=$SPARKNET_STATE_DIR/keys`.

Assert (scriptable on the exchange host, via `GET /election/status` until
`formed`):

- `GET /election/root` carries one co-signature from every distinct member —
  two in the pair, three in the full cluster;
- the winner's identity flips to `"role": "master"`, its operational key is
  `held`, its `master-node/manifests/cluster-trust-root.json` names it;
- the other member(s) stay `"role": "peer"` with **no** trust_root block and
  **no** root document — same byte-level no-loss assertion as the rehearsal's
  before/after snapshot (DoD 5) applied over `wg1` delivery.

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

This step's registry has two entries (the pair), so the governance mode is
`peer_pair` (`overlay.json`): symmetric, no Master arbitration of shares. What
exists to test now is real overlay reachability and signed registry
distribution. The **share transport itself is unbuilt**
(`ports.json` 4201–4203 `spec-only`); a data-plane stanza open/close recording
in the ledger is the premise to check **when** the transport exists
(`overlay.json` `data_plane_stanza.unverified_on_dev_host`). Do not claim a
peer↔peer *share* happened. **`confirm: user`** for every overlay-observed
behaviour, since no suite on this machine can see it.

## Phase 9 — rollback and re-formation

> The approved 2026-11-08 destructive recovery exercise has its own procedure:
> [`phase9-recovery-runbook.md`](phase9-recovery-runbook.md). Do not substitute
> that restore proof for the election rollback below; they are different risks.

- Rollback an election: `systemctl disable --now sparknet-master-signer.service`,
  remove the state trust root and the flipped identity fields, `ip link del wg1`,
  rebuild from Phase 0.
- Replace the Master: never by revoking — a new root with a new nonce
  (n/n, i.e. 2/2 in the pair), per `consensus-protocol.md` §Re-formation.
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