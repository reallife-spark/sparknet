# contracts/

The single source of truth for everything the Master and its peers must agree
on. Neither role hard-codes these values; both read them from here.

If a value appears in `master-node/` or `peer-node/` as well as here, that is a
bug — `tests/test_contracts.py` fails on it. Contracts change in one commit, and
the tests then prove both roles still agree.

| File | Governs |
|---|---|
| `overlay.json` | addressing, MTU, keepalive, AllowedIPs discipline |
| `capabilities.json` | the closed capability vocabulary and who may hold each |
| `identity-schema.json` | canonical identity, fingerprinting, signed envelope |
| `ports.json` | every listener and dial target, with implemented/spec-only status |
| `guard-protocol.md` | the Master↔peer approval conversation |

## Why this directory exists

The Master and a peer are separate programs with opposite security postures.
They stay correct as a pair only because they agree on the bytes they exchange.
Before the split that agreement was implicit in duplicated constants scattered
across scripts — `10.100.0.1` appeared in six places, and nothing detected a
mismatch.

Explicit contracts make the agreement checkable. A peer that drifts no longer
fails silently at handshake time; it fails `make contract-test`.

## Changing a contract

1. Edit the file here.
2. Run `make contract-test` — it tells you which role files now disagree.
3. Update the affected role's files in the same commit.
4. Bump `schema_version` in the file you changed.

Never edit a contract to make a test pass without asking whether the *other*
role should change too. That question is the entire value of this directory.

## What is deliberately *not* here

Nothing executable. The reference implementation of the signed canonical form is
`shared/sparknet-authz.py`, deliberately singular — two copies of signing or
canonicalisation code is a security bug waiting to happen, because they can
drift and then silently stop validating each other. Contracts state rules;
`shared/` binds them to code; each role wraps that code in its own CLI.