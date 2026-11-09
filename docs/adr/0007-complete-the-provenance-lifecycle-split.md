# 0007 — Complete the provenance lifecycle split

## Status

Accepted (2026-11-09). Supersedes [0006](0006-stage-the-provenance-split.md).

## Context

ADR-0006 accepted Stage 1: primitives and secret scanning moved into their own
modules, while note, ledger and grant stayed in the facade. That proved the
loader, error-identity and re-export pattern, but the main locality problem
remained: a change to the note envelope or a grant still loaded the whole
2,500-line facade, and tests had no narrower surface.

The lifecycle seams are already named in the module by section comments. The
dependency graph is acyclic:

```
base ──> scan
  └────> note ──> ledger ──> grant
facade ──> all of the above
```

Moving the remaining code is behavior-preserving: the canonical note message,
ledger block bytes, grant verification order and every external name stay
unchanged.

## Decision

Complete the split behind the unchanged facade:

- `sparknet-provenance-note.py` — frontmatter wrappers, note envelope,
  signatures and verification, co-signatures, the user record, layout shims
  and inbox intake.
- `sparknet-provenance-ledger.py` — ledger loading and chain verification,
  approvals, dual-signing, append, checkpoints and anchoring, the
  `inbox_acceptance` builder and vault-wide verification.
- `sparknet-provenance-grant.py` — path/scope containment, nonce retention,
  `grant_use`, and the grant-scoped write/promote/patch paths.
- `sparknet-provenance.py` — loader bootstrap, explicit re-exports for the
  whole compatibility surface, and the CLI. It defines no lifecycle logic.

`build_inbox_acceptance` and `verify_vault` live in `ledger` because both
verify or extend the ledger/accountability trail; they do not belong in
`grant`. `note` depends on `base`; `ledger` depends on `base` and `note`;
`grant` depends on `base`, `note` and `ledger`. No lower module loads a higher
one.

Two existing tests change only their load point: the email-authorised-sender
test patches `ledger.parse_user_record`, and the proposal clock patches
`ledger._now`. The contract-rule source scan now searches the note and ledger
modules as well as the facade.

## Consequences

- A note change loads only base and note; a grant change additionally loads
  ledger and grant, but not the CLI or scanner.
- The facade remains wide for compatibility but holds no business logic beyond
  argparse. New callers should still use the facade, not a lifecycle module.
- `ProvenanceError` remains the single class from `sparknet-yaml.py`; all
  modules use the same canonical module names through the one loader.
- The scanner exempts the primitives and scanner sources because the pattern
  definitions otherwise match themselves.
- No canonical bytes, contract schema, role submodule, bundle layout or
  submodule pin changes. The one crypto rule is unchanged.
- The split is a move, not a redesign. A future package rename or interface
  change needs its own ADR.
