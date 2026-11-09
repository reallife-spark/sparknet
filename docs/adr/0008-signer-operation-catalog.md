# 0008 — One signer operation catalog

## Status

Accepted (2026-11-09).

## Context

`master-node/services/sparknet-signer.py` answers ten signing operations. The
dispatch was a `_sign` if/elif chain and each operation carried its own copy of
the same sequence: validate the request object, derive the canonical projection,
check expiry or operation-specific policy, sign, append a ledger record and build
the response. Four operations use bespoke ledger events; six use
`signature_issued`. Adding an operation meant touching the operation tuple, the
dispatch chain, a new method, the docstring and the test file, and the module
docstring still claimed six payload types after the list had grown to ten.

The signer is the process that holds the operational key. The refactor must not
move canonical bytes, weaken root pinning or create a new signing path.

## Decision

Use one `SIGNER_OPERATIONS` catalog in the signer:

- `SignerOperation` names the operation, its request field and phrase, response
  key, ledger event and a named prepare callable.
- `SignerOutcome` carries the signed artifact or event payload, subject, ledger
  event/payload, response key and operation-specific response extras.
- The common `_sign` path owns root pinning, unknown-operation refusal,
  request-object validation, the ledger append and the response envelope.
- Named `_prepare_*` methods keep the security-sensitive projection and policy
  (registry fingerprint/capability checks, expiry, RFI decoding, share deadline,
  evidence digest, trust/distillation fields).
- `SIGN_OPERATIONS` and `describe()` derive from the catalog. The module
  docstring lists all ten operations.

The signer still has no raw-bytes operation, no second crypto implementation and
no new capability. `shared/sparknet-authz.py` remains the only canonical form.

## Consequences

- Adding an operation is one catalog row plus its named prepare method; the
  common sign/record/response path is not copied.
- Tests can assert the catalog, request fields, response keys and ledger events
  as one interface, while the existing per-operation refusal tests remain the
  behavior oracle.
- Response keys, ledger event names/payloads, error strings and the pinned-root
  order are unchanged.
- This is a master-role change: the signer commit lands first, then the
  superproject pins the master submodule. No peer or contract schema change.
