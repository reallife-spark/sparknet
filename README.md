# Sparknet

A two-role WireGuard fabric for DGX Spark nodes, with one signed-authorization
scheme and a knowledge vault per node.

The Master holds the signing key and decides what each node may do. Every other
node is a peer: it verifies the Master's decisions and cannot authorise anything
for itself. Authority comes from **key possession**, not from a capability
grant — a peer holding the full capability vocabulary without that key can never
grant, revoke or escalate.

## What this repository is

Not one node — a fabric with two node roles and a shared contract:

| Path | Role | State |
|---|---|---|
| `contracts/` | both | overlay, capabilities, identity, ports, guard protocol — the single source of truth |
| `shared/` | both | `sparknet-authz.py`, the one canonical signing implementation |
| `peer-node/` | peer | **implemented** — guard, anchor, dispatch, its own vault |
| `master-node/` | master | **built** (Steps 15–18); runs the peer's services by path; isolated signer deployed on agx64, election/signer arc proven live 2026-10-07 |
| `scripts/` | both | fabric tooling: skill vendoring, env init, bundling |
| `.opencode/skills/` | both | the vendored wiki skill suite (33 skills: 32 vendored + 1 local, MIT) |

**A role subvault alone is not a deployment.** A peer cannot verify a signature
without `contracts/` and `shared/`, so a bare `peer-node/` copy deliberately
fails validation instead of pretending to work. `make bundle` assembles what a
node actually needs.

The two roles are not symmetric, and their charters differ in substance. Read the
role's own `AGENTS.md` before working inside it.

## Quick start

```bash
make help          # what the fabric can do
make layout        # what exists, and what is merely specified
make devtools      # optional: .venv with cryptography, pytest, ruff
make env-init      # write each vault's .env and category skeleton
make test-all      # every suite: contract, fabric, peer, master
make contract-test # the cross-role check alone: contracts/ vs both roles
make validate      # both roles' charters, plans and manifests
```

Then pick a role and work inside it:

```bash
make -C peer-node help
make -C master-node help
```

## Standalone node bundles

The real deliverable: a directory that can be extracted onto a fresh machine and
run there.

```bash
make bundle ROLE=peer           # -> dist/sparknet-peer-<tree>.tar.gz
make bundle-verify ROLE=peer    # extract elsewhere and prove it runs
make bundle ROLE=master         # vault + peer parity; ships peer-node/ because parity needs it
```

A bundle carries the role, `contracts/`, `shared/`, `scripts/`, the vendored
wiki suite and `opencode.json`. Verification runs `env-init`, the wiki preflight,
role validation and that role's test suite **from the extracted copy**, at a
different path — which is what makes "self-contained" a checked claim rather
than a description.

`.env` is never bundled: it records machine-local paths, so deployment runs
`scripts/sparknet-env-init.sh` as its first step.

## Security posture

- **EU AI Act Article 14** — Plan → Permission → Execute. The guard never sees an
  unapproved request; it verifies a signature or refuses.
- **Capability-gated mutation.** `guard-apply` is the only capability that turns
  a valid signature into a filesystem write, and applying additionally requires
  `euid 0`, a protected target path, and `--apply-enabled` (off by default).
- **Immutable config.** Protected files are pinned with `chattr +i`; the guard
  lifts the bit, writes atomically, re-pins, and hash-chains an audit entry.
- **Fail-closed by default.** The shipped registry is **empty**, so a fresh
  deployment grants nothing. Without the overlay the guard refuses to bind —
  losing authority, not the ability to read and serve knowledge.
- **Containment.** A revoked peer loses its anchor and has no remaining WAN path.
  Revocation is isolation, not a warning.

Details in `peer-node/docs/`, starting with `wireguard.md` and
`node-authorization.md`.

> **Verified live on agx64+agx32 (2026-10-07):** unanimous 2/2 election formed; `sparknet-master-signer.service` active and restart-stable; signed registry entry distributed to a peer and verified by the root alone; revoke→peer-inert→re-authorize cycle executed live one-peer-at-a-time; reboot survival on agx64 (signer unit comes back, ledger intact, peer auth still verifies); overlay handshakes + ICMP ping ~2 ms 0% loss over real NICs via the gateway UDP relay.
> **Designed but undemonstrated on a dev host:** kernel WireGuard path (`CONFIG_WIREGUARD=n` here, so userspace `wireguard-go` + `/root/scripts/sparknet-wg-restore.sh`); `nftables` containment rules; `chattr +i` enforcement of protected paths; `guard-apply` with euid 0 and `--apply-enabled` (required, off by default). Phase 9's destructive legs (rollback / replace-Master re-formation) remain documented-but-unexecuted at operator choice.

## Configuration in `/etc`

Derived from the vault, never the other way round. `make install-config` prints
the diff and cannot write it — applying a malformed netplan on a remote node can
drop your SSH session, so that stays a human decision. `make install-units` is a
dry-run report unless you pass `APPLY=1`.

## Wiki skill suite

Vendored at `.opencode/skills/`, so a bare clone or an extracted bundle can run
it with no global skill farm. Re-vendor with `make wiki-sync`, prove no drift
with `make wiki-verify`.

Skills resolve their vault from the **nearest** `.env`, which is what keeps a
role subvault honest. Run `make wiki-preflight` before using one, and never work
around a failure: the skills would silently resolve a different vault and every
page would land there instead, with nothing to tell you.

## Dependencies

Exactly one third-party package, `cryptography>=42`, because Ed25519 is not in
the standard library. `pytest` and `ruff` are optional development tools and the
suite runs without them. Some wiki skills shell out to optional external tools
(`defuddle`, the orchestrator CLI, Dataview); their absence degrades that skill, not
the suite.

## GitHub

Private remote: `https://github.com/realllife-spark/SparkNet-Node.git`

The pre-split history is reachable at `ad1cc39`. Note that GitHub's REST API
reports the repository as missing while git fetch/push/clone succeed against it —
use git, and treat the REST 404 as a client-side visibility problem rather than
evidence that the push did not land.