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
| `rfi-schema.json` | the request-for-information channel: the peer's overlay-attributed request, the Master's signed answer, the digest that binds its content, the `01_Inbox/` destination rule, the acceptance order and the refusal vocabulary. Both halves are built: the 8090 peer-intake request route and the Master's signed answer transport (fabric Steps 69C/70) |
| `ports.json` | every listener and dial target, with `implementation_state` (code) kept separate from `runtime` (observed on a given host) |
| `guard-protocol.md` | the Master↔peer approval conversation |
| `guard-approval.json` | the approval envelope itself: the eight signed fields, the canonicalisation rule, where the capability comes from, and the transport (route, port, envelope fields) |
| `health-protocol.md` | peer liveness and eviction: probe rhythm, activity-trumps-eviction, the full-dark rule, no-authority guarantee |
| `telemetry-schema.json` | peer→Master observability evidence (Phase 4): overlay-attributed, unsigned, `kind`-tagged reports the Master records and acts on nothing — no authority on the telemetry path. Envelope, the 8090 peer intake (telemetry + RFI request routes), the peer pusher and the per-kind consumers are built (Step 70) |
| `share-protocol.md` | the peer↔peer sharing regime: offers, share types, the four clocks, trust levels, isolation, evidence |
| `consensus-protocol.md` | how the members (a pair or a trio) agree on who holds the signing key: election, the cluster trust root, re-formation |
| `phase9-recovery-runbook.md` | the approved destructive recovery exercise: snapshot, off-host archive, peer restore proof, Master restore, verification and rollback |
| `deployment-runbook.md` | the operational procedure for bringing the real multi-node system (a pair or a trio) up on actual hosts (Step 13): overlay, election, signer unit, registry, rollback |
| `role-inversion-runbook.md` | the executed Step 88 procedure for inverting the live pair to `agx64` Master / `agx32` peer: freeze and backup, new identities, chained re-formation, overlay/firewall swap, data/service migration, registry/grants/secrets, model placement, verification and rollback. Executed 2026-11-06; cleanup/goSpark placement remain |
| `admin-federation-runbook.md` | the operational procedure for the Phase 5 live deploy of cross-node admin federation (fabric Step 29): hosts/addressing, the route-class binding change, the `admin-supervise` grant, the node agent, the console, the confirm checklist and rollback |
| `spark-node-runbook.md` | the operational procedure for the node image in both platform variants (`--platform spark` = DGX Spark, `agx` = AGX Xavier): what is provable without a GPU (CPU stub engine, simulated telemetry, the containerised election rehearsal) and the residual confirm-on-the-device lists |
| `tracking-schema.json` | the numbered vault layout, the per-note tracking block and its signature, the user record, the approval record, the secret index |
| `provenance-protocol.md` | the narrative behind that schema: the accountability chain, stale-vs-invalid, ledger-only approvals, inbox dispatch policy, secret custody |
| `proposal-schema.json` | the cross-user proposal workflow: the proposal/review/decision records, the draft→submitted→reviewed→decided lifecycle, and what a verified chain verifies |
| `proposal-protocol.md` | the narrative behind that schema: why a review is a first-class object, the fail-closed transitions, inline keys and integrity-vs-identity, and why a verified chain is not an authority to write |
| `vector-store.md` | Qdrant topology, collections, parity matrix, embedding stamp, uplift/distillation separation and retention |
| `uplift-schema.json` | peer→Master consented opener: inventory, Qdrant snapshots, teacher traces, raw-KV manifests, 8091 transport and retention |
| `inventory-schema.json` | the user/model/usage mirror Qdrant keeps, with Open WebUI as the authoritative source |
| `distillation-schema.json` | same-family teacher→student dataset, run record, evaluation and model card |
| `model-catalog.json` | the operator-owned model catalog: role placement (teacher on the 64 GB Master host, student on the 32 GB peer host), repo/revision, quant, runtime, license and fit |
| `model-store.md` | the model store, pull/verify rule, runtime leases, idle stop, memory guard, role-specific weights and the prohibition on teacher backup on agx32 |
| `webui-surface.md` | the peer/master Open WebUI menus, console scope, session/token rule, read-only boundary and the 3D-map pilot |
| `knowledge-flow.md` | the map of every Master→peer, peer→Master and peer↔peer channel: what it may carry, what it must never carry, how it is authenticated, and why authority and knowledge never share a channel |
| `memory-schema.json` | per-vault typed memory, retention, the Go store/Python gateway boundary, delegate runs and the memory-bundle payload profile |
| `abac-schema.json` | attribute-based narrowing for knowledge resources: verified subject sources, resource classes, classifications, refusal codes, and the rule that ABAC never grants a capability or widens a scope |
| `event-schema.json` | the canonical NATS/JetStream event envelope: topic namespace, bounded lifetime, payload as data, and the rule that a signature is provenance not authority |
| `graph-schema.json` | the derived document-link graph: vault-scoped nodes, wikilink/frontmatter/manual edges, deterministic ordering and reported unresolved links |
| `hybrid-schema.json` | the semantic + agentic retrieval bundle: both result sets, provenance, and the rule that they are never silently merged |
| `exec-schema.json` | the signed argv-only execution contract: vector argv, vault-relative cwd, environment allow-list, operator OS cap, timeout and output bounds |
| `collab-schema.json` | bounded collaboration rooms: participants, classification ceiling, department boundary, provenance and no authority |
| `package-schema.json` | signed package manifests and the closed dependency-first install plan; a package is data and never executes itself |
| `agent-schema.json` | event-driven agent descriptors: one role family, bounded runtime/concurrency, no authority, no vault write |
| `self-improvement-schema.json` | bounded mutation/benchmark runs, deterministic thresholds, promotion/rollback and the worktree fallback |
| `release-schema.json` | signed release manifests, immutable artifacts, package-index binding and the 4221 distribution/install rules |
| `data-lake-schema.json` | consented Master-side uplift/trace/artifact intake; training and backup evidence that is never served as knowledge |
| `container-registry-schema.json` | private loopback OCI distribution: token gate, content-addressed manifests/blobs, read-only and non-knowledge |
| `pipeline-schema.json` | O1→O2→O5 eligibility, daily-log append, staged O5 candidate and explicit human promotion |
| `step89-admin-schema.json` | signed Master-side lake, collaboration, distill-schedule and package-index envelopes; provenance, never authority |
| `step89-matrix.json` | the Step 89 channel matrix: contract, implementation, tests and live state per channel |
| `nocturnal-artifact-schema.json` | signed cluster-job results and manifests under `01_Inbox/nocturnal/`, coverage, local commit and the no-auto-promotion rule |
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