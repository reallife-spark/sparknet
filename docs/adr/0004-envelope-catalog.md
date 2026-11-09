# 0004 — One envelope catalog in the authz module

## Status

Accepted (2026-11-09).

## Context

`shared/sparknet-authz.py` defines the canonical bytes for every signed
artifact the fabric exchanges: registry entries and publications, guard
approvals, cluster jobs, admin requests, grants, share ratifications, trust
transitions, RFI answers, distillation runs and ledger blocks. Each artifact
had its own `*_message` function, its own sign/verify pair and its own copy of
the same dict/field/canonical-JSON skeleton. They were all correct, but adding
a field or a new artifact meant remembering which of ten near-identical
functions to change.

The canonical bytes are a security boundary: a changed separator, field order,
sorted list or extra field changes what both roles verify. The refactor must
therefore preserve bytes exactly, including the existing golden vectors.

## Decision

Keep one implementation and put the repeated envelope rules behind an internal
**envelope catalog**:

- `EnvelopeSpec` records the full field list, required fields, signed
  projection, allowed extras, optional prefix, projection hook and signedness.
- `SPECS` maps every `ENVELOPE_KINDS` entry to its spec.
- `envelope_message`, `sign_envelope` and `verify_envelope` are the public
  interface for new artifacts.
- Existing named functions (`guard_approval_message`, `sign_rfi_answer`,
  `verify_grant`, …) remain thin wrappers. Callers do not change.
- Ordered policy verifiers keep their checks and refusal vocabularies; the
  catalog owns shape, canonicalisation and signature placement, not authority.
- Validation-only artifacts (RFI request, telemetry, issue report) are in the
  catalog with `signed=False`; they share the field vocabulary but have no
  signature path.
- `tests/test_envelopes.py` pins per-kind bytes and proves the wrappers and the
  generic interface agree. Existing identity/authorization/admin golden vectors
  remain the outer contract.

## Consequences

- One canonical JSON encoder and one signature-placement rule.
- A new signed artifact is one `EnvelopeSpec` and one golden vector, not a
  copied message/sign/verify trio.
- The named functions stay readable and source-compatible.
- A byte change still fails the pinned vectors before it can reach either role.
- The catalog is not a contract generator: `contracts/*.json` remains the source
  of truth, and a test keeps the identity spec aligned with it.
