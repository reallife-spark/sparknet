# 0014 — Keep `sparknet-authz.py` as one deep module, split only behind its facade

## Status

Accepted (2026-11-10). This is a decision record, not a refactor.

## Context

`shared/sparknet-authz.py` is 2,655 lines and about 109 KB. It owns identity
projection and fingerprinting, key loading, Ed25519 signing and verification,
the closed capability vocabulary, local registry evaluation, the guard-approval
ceiling, the envelope catalog and every named envelope builder/verifier.

The module is **deep**, not shallow: callers cross a relatively small,
purpose-named interface and the implementation hides the canonical-byte rule
that both roles must agree on. The cost is context, not interface complexity.
A change to one envelope, plus its contract tests and golden vectors, is about
82k tokens; the registry-acceptance boundary is about 106k before the role tests
are added.

ADR-0002 keeps one by-path loader and one implementation. ADR-0004 keeps one
envelope catalog in this module. Any split must preserve both decisions, the
golden vectors, the refusal vocabulary and `AuthzError` identity.

## Decision

Keep `shared/sparknet-authz.py` as one path-stable module for this release.
Do not start a multi-file split from an audit finding.

The mitigations are narrower test surfaces and a documented internal map:

- `tests/contracts/` is split by contract boundary, so a change loads only the
  contract tests it touches.
- The envelope catalog (`SPECS`, `envelope_message`, `sign_envelope`,
  `verify_envelope`) is already the one internal seam for signed artifacts.
- New acceptance policy for a registry entry lives in `accept_entry`; callers
  do not grow a second registry verifier.
- The module docstring and this ADR name the internal regions (identity and
  keys, registry policy, envelope catalog, named envelope policy) so a reader
  can navigate without holding the whole file.

A future split is allowed only if it is staged behind the unchanged facade:
identity/crypto primitives and the envelope catalog are the first candidates.
It must preserve every public name, canonical bytes, golden vectors and error
identity, and it needs its own accepted ADR.

## Consequences

- No canonical-byte risk is introduced by an audit-driven refactor.
- The context cost remains real. The mitigation is test locality and the
  envelope catalog, not a claim that 109 KB is free.
- `accept_entry` is now the seam for remote registry entries; the local
  `evaluate` delegates to it, so the next acceptance hardening has one place to
  land.
- A future split has a clear starting point and a clear set of invariants
  instead of an open-ended licence to reorganize the trust boundary.

## Revisit when

- The authz-plus-tests boundary exceeds the 140k-token implementation target
  even after the contract-test split.
- A second real adapter appears for identity, envelope or policy (one adapter
  is a hypothetical seam).
- A change routinely touches identity, envelope and policy code together and
  the shared context is the measured bottleneck.
