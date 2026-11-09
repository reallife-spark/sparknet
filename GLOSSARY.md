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
