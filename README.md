# Sparknet

Master template for NVIDIA DGX Spark node setup as part of the Sparknet architecture.

## What this provides
- EU AI Act Article 14 compliant (Plan → Permission → Execute) workflow
- Vault/path/venv-agnostic service design with explicit env and absolute paths
- User local system identity capture with privilege boundary enforcement
- Security scaffolding: KillSwitch, immutable guard, signed approvals, permissioned ledger
- Hardware-aware networking (ConnectX-7 RoCEv2, MTU 9000, WLAN emergency routing)
- User-space P2P sync, hidden vault (.sparknet) patterns
- Template for provisioning standalone or cluster DGX Spark nodes

## Quick Start
The vault root **is** the node template — it is self-contained and relocatable.
```bash
make validate      # env contract + manifest checks
make test          # pytest suite
make provision     # identity capture + validate
```

Optional, opt-in tooling:
```bash
make devtools      # create .venv with cryptography + pytest + ruff
make lint          # ruff if available, otherwise prints how to install it
```

## Master-anchored node

A node is either anchored to the Master over WireGuard or running standalone.
The vault works either way; the difference is that without the anchor the guard
refuses to bind and refuses to apply anything.

```bash
make keys           # WireGuard + Ed25519 keypairs into .state/keys (0700, never committed)
make wg-render      # preview wg0.conf (dry-run); APPLY=1 writes it at 0600
make anchor         # root: render + wg-quick up + chattr +i
make authz-verify   # check this node's identity against the signed registry
make guard-status   # manifest state and authorization posture
```

See [docs/wireguard.md](docs/wireguard.md) and
[docs/node-authorization.md](docs/node-authorization.md). The short version: the
Master signs what each node may do (`guard-apply` being the sensitive one), and
WireGuard itself has no SHA-256 — the SHA-256 is the authorization fingerprint.

Every path resolves from the script's own location, so the vault can be cloned
anywhere and still run.

Writing outside the vault is always explicit:

| Command | Writes outside the vault? |
|---|---|
| `make install-config` | **Never.** Permanently dry-run; prints diffs only. |
| `make install-units` | Only with `APPLY=1`. Default is a dry-run report. |
| `make provision` | No. Identity capture + validation only. |
| `make wg-render` | Only with `APPLY=1`, into the git-ignored state dir. |
| `make anchor` | Yes — root; renders, brings up `wg0`, applies `chattr +i`. |

## Development

```bash
make help          # list targets
make validate      # env contract + manifest checks
make test          # pytest suite
make lint          # ruff, or a note on how to install it
make devtools      # opt-in: create .venv with pytest + ruff
```

The services need exactly one third-party package: `cryptography>=42`, because
Ed25519 verification is not in the standard library
(`requirements.txt` / `pyproject.toml`, and `tests/test_services.py` enforces
that the allow-list does not silently grow). `ruff` is optional — `make lint`
degrades to a message rather than failing when it is absent.

Configuration in `/etc` is *derived* from this vault. `make install-config`
shows the diff and cannot write it — applying a malformed netplan on a remote
node can drop your SSH session, so that stays a human decision. See
`manifests/critical-manifest.json` for which vault file generates which
`/etc` path.

Run `make dist` to build a release tarball from the committed tree; it warns
first if your working tree is dirty.

## Documentation
See docs/ directory for architecture, compliance, user identity, scenarios/BOMs.

## GitHub
Repository target: https://github.com/realllife-spark/sparknet (private)
Note: Push currently blocked by GitHub auth requirements (see plans/GITHUB_PUSH_BLOCKER.md)
