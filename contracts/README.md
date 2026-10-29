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
| `registry-schema.json` | the shape of the registry document and its entries: required fields, types, the `signature_b64` field name, and the decided distribution channel (a pointer to `registry-publication.json`) |
| `registry-publication.json` | the channel that carries a registry: the five-field publication, the signed projection and digest, the monotonic sequence, the peer's acceptance order and refusal codes, and the documented re-delivery window |
| `reflex-schema.json` | the typed decision contract for the reflex layer — a local sensor, never authority; abstain first-class, and a backend vocabulary with no egress member |
| `rfi-schema.json` | the request-for-information channel: the peer's overlay-attributed request, the Master's signed answer, the digest that binds its content, the `01_Inbox/` destination rule, the acceptance order and the refusal vocabulary. The answer transport (listener + composer) is built; the request channel is Step 68 |
| `ports.json` | every listener and dial target, with `implementation_state` (code) kept separate from `runtime` (observed on a given host) |
| `guard-protocol.md` | the Master↔peer approval conversation |
| `guard-approval.json` | the approval envelope itself: the eight signed fields, the canonicalisation rule, where the capability comes from, and the transport (route, port, envelope fields) |
| `health-protocol.md` | peer liveness and eviction: probe rhythm, activity-trumps-eviction, the full-dark rule, no-authority guarantee |
| `telemetry-schema.json` | peer→Master observability evidence (Phase 4): overlay-attributed, unsigned, `kind`-tagged reports the Master records and acts on nothing — no authority on the telemetry path. Envelope, the 8090 peer intake (telemetry + RFI request routes) and the peer pusher are built; the per-kind consumers are Step 70 |
| `share-protocol.md` | the peer↔peer sharing regime: offers, share types, the four clocks, trust levels, isolation, evidence |
| `consensus-protocol.md` | how three nodes agree on who holds the signing key: election, the cluster trust root, re-formation |
| `deployment-runbook.md` | the operational procedure for bringing the real three-node system up on actual hosts (Step 13): overlay, election, signer unit, registry, rollback |
| `admin-federation-runbook.md` | the operational procedure for the Phase 5 live deploy of cross-node admin federation (fabric Step 29): hosts/addressing, the route-class binding change, the `admin-supervise` grant, the node agent, the console, the confirm checklist and rollback |
| `spark-node-runbook.md` | the operational procedure for the node image in both platform variants (`--platform spark` = DGX Spark, `agx` = AGX Xavier): what is provable without a GPU (CPU stub engine, simulated telemetry, the containerised election rehearsal) and the residual confirm-on-the-device lists |
| `tracking-schema.json` | the numbered vault layout, the per-note tracking block and its signature, the user record, the approval record, the secret index |
| `provenance-protocol.md` | the narrative behind that schema: the accountability chain, stale-vs-invalid, ledger-only approvals, inbox dispatch policy, secret custody |
| `proposal-schema.json` | the cross-user proposal workflow: the proposal/review/decision records, the draft→submitted→reviewed→decided lifecycle, and what a verified chain verifies |
| `proposal-protocol.md` | the narrative behind that schema: why a review is a first-class object, the fail-closed transitions, inline keys and integrity-vs-identity, and why a verified chain is not an authority to write |
| `manifest.json` | **generated** — the machine-readable inventory of this directory: each JSON contract by hash (so an edit without a re-render is caught) plus the projected capability and port tables. Rendered by `scripts/sparknet-render.py`; never hand-edited. |

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
drift and then silently stop validating each other. Note signing, ledger
appending and provenance verification are the same story one layer up:
`shared/sparknet-provenance.py` loads authz *by path* and adds no crypto of its
own. Contracts state rules; `shared/` binds them to code; each role wraps that
code in its own CLI.