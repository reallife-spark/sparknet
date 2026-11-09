# Glossary

- **fabric** — the two-role system in this repository: contracts, shared code,
  a peer role and a Master role.
- **peer** — the user's local node. It runs chat, agentic work, a private vault
  and self-healing. It holds an identity key, not the operational key.
- **Master** — the elected signing role. It holds the operational key and
  supplies authority and scoped fabric knowledge.
- **vault** — a role's or user's knowledge tree. Knowledge lives here; secrets
  live in a state directory.
- **guard** — the peer service that verifies Master-signed requests before a
  protected file is changed.
- **registry** — the Master-signed list of node identities, capabilities and
  revocations.
- **RFI** — request for information: a peer asks the Master a scoped question
  and receives a signed answer into `01_Inbox/`.
- **issue** — an operational work item under `.scratch/issues/`. It is not
  knowledge and not authority.
- **understand graph** — the derived `.ua/knowledge-graph.json` built by the
  `/understand` tool. It is a build artifact, not an answer corpus.
- **opencode workspace** — one of the three editing contexts: the fabric root,
  `peer-node/` and `master-node/`.
- **release export** — the build-time module
  `scripts/sparknet-release-export.py`. It stages a distribution surface (a
  role bundle or the goagx distribution) from the working tree or a git ref,
  writes its `SHA256SUMS`, and verifies those checksums and the detached
  signature. It is not a runtime module and not a knowledge channel.
- **listener** — the shared HTTP surface in `shared/sparknet-http.py` that
  owns request parsing, route auth and source policy, refusals, health and
  lifecycle for a role module. A route handler owns the service behaviour; the
  listener owns the transport.
- **envelope** — a signed artifact whose canonical bytes are defined by an
  `EnvelopeSpec` in `shared/sparknet-authz.py`.
- **envelope catalog** — the `SPECS` table mapping every envelope kind to its
  fields, signed projection, signer and verifier. Named `*_message`/`sign_*`/
  `verify_*` functions are adapters over it.
- **console surface** — one read-only view exposed by
  `scripts/sparknet-console.py`: its endpoints, `session`/`admin` auth class
  and optional menu metadata in the one `SURFACES` table.
- **provenance facade** — the path-stable `shared/sparknet-provenance.py`
  that re-exports the provenance lifecycle modules and holds the CLI. Callers
  and role code load this path, never a lifecycle module directly.
- **provenance primitives** — the loader, YAML error re-exports, canonical
  form, crypto loaders, contract reader, time/key-path helpers and shared
  key-shaped patterns in `shared/sparknet-provenance-base.py`.
- **provenance lifecycle** — the note, ledger, grant and scan concerns behind
  the provenance facade. ADR-0007 completes the split: each lifecycle has its
  own module, while `shared/sparknet-provenance.py` is the path-stable facade
  and CLI.
- **signer operation catalog** — the `SIGNER_OPERATIONS` table in
  `master-node/services/sparknet-signer.py`. One row names an operation's
  request field, response key, ledger event and named prepare method; the
  common signer path owns root pinning, validation, ledger append and response.
