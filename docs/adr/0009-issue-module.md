# 0009 — Issue module: one local issue model

## Status

Accepted (fabric Step 92B).

## Context

The issue lifecycle crosses three Python callers. The peer parses local
markdown, redacts and builds a signed payload; the Master verifies that payload,
appends to a JSONL store and derives a latest view; the console re-reads the
same JSONL and derives the view again. Peer and Master each keep their own
secret-pattern table. The issue contract and docs also promise triage
transitions, but no writer for `triage.json` exists — the console only reads it.

Issues are operational work, not authority and not knowledge. The signed
`POST /api/v1/issues` route remains the authority seam.

## Decision

- **One issue module lives in `shared/`.** `shared/sparknet-issue.py` is the
  path-stable facade; `shared/sparknet_issue/` owns the implementation. Callers
  load it by path, never from an installed package.
- **The module owns local issue semantics:** markdown parse, redaction policy,
  issue validation, the Master issue ledger and latest view, triage transitions
  and the read projection.
- **`shared/sparknet-authz.py` remains the envelope and signature owner.** The
  issue module calls its builders and verifiers; it never signs, verifies a
  signature itself, grants authority or installs knowledge.
- **Peer, Master and console are adapters.** The peer adapter signs and sends;
  the Master adapter applies the signed route and configures the ledger path;
  the console adapter renders the module's projection and stays read-only.
- **Triage history is append-only.** A Master-local transition appends to
  `<state-dir>/issues/triage.jsonl`; `triage.json` is a derived latest view.
  A small Master-local CLI writes transitions; the console does not.
- **Redaction has one policy table.** The peer applies it before signing and the
  Master applies it again before storing. Both fail closed.
- **The wire contract is unchanged.** `/api/v1/issues` keeps its fields and
  signed envelope. The local-store section is corrected to name the triage
  ledger and the derived view.
- **Migration preserves history.** Existing `/mnt/log/sparknet-issues.jsonl` is
  read as-is; an existing `triage.json` seeds the derived view; no record is
  rewritten.

## Consequences

- One issue shape, one redaction policy, one latest-view rule and one read
  projection.
- The triage behavior promised by the contract becomes implementable instead of
  remaining a reader-only fiction.
- The peer, Master and console keep their roles but lose their private copies of
  issue policy.
- The issue module gains no authority: the signed route, registry and guard
  remain the only privileged paths.
- A future shared issue store for another role is a new decision, not a quiet
  extension of this module.
