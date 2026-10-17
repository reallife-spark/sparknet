# Security policy

## Reporting a vulnerability

These repositories are **private** and operated by a single maintainer. Do not
open a public issue for a security problem. Instead, either:

- open a **private vulnerability report** on the repository
  (*Security → Advisories → Report a vulnerability*), or
- contact the maintainer directly through the host.

Include the affected path or command, what you observed, and the smallest
reproduction you have. There is no bug-bounty programme.

## Supported versions

The current `master`/`main` branch is supported. Older states are provenance,
not releases; fixes land on the branch and are not backported.

## What matters most here

This fabric's security model is **fail-closed authority by key possession**:

- The **Master** signs; a peer verifies. A peer that holds the whole
  capability vocabulary but not the private key can never grant, revoke or
  escalate — and a registry entry that fails verification must be treated as
  absent, not as "unknown, so allow".
- The signing key is held by one process only (`services/sparknet-signer.py`,
  unix socket, mode 0600, typed payloads, never signs caller-supplied bytes)
  and never leaves the node that owns it.
- The shipped registry is **empty on purpose**: no node has privileges until
  the Master signs something.

A report that shows one of those invariants bending is the highest-priority
kind of report you can send.

## Secrets

- Nothing secret is ever tracked: no private keys, tokens, PEM blocks or
  `.env` contents — and no plausible-looking placeholders in docs. Reference
  the secret *path* only.
- `make keys-check` (and the `pre-commit` hook after `make hooks`) refuses a
  tracked key-shaped name, a tracked PEM private-key block, a loose
  `.state/keys/` or `.state/secrets/` mode, or a missing `.gitignore`
  backstop.
- If you find a secret committed: **rotate it first** (removing the file does
  not remove it from history), then report it as above. A key pasted into a
  chat is treated as exposed even if it was never committed.
- Non-key secrets (an API token) live at `.state/secrets/<name>.env`, mode
  0600, under the gitignored `.state/`.

## Scope

In scope: the fabric's own code and contracts (`contracts/`, `shared/`, both
roles, `scripts/`), the container image and compose surfaces, and the node
bring-up scripts. Out of scope: vulnerabilities in third-party images or
dependencies, which belong upstream — pin reports to the version we ship.
