# MCP / A2A design — how agents on the fabric talk to each other and to tools

Status: **design proposal, not a contract change.** Nothing in this note binds
`contracts/`, adds a port, or grants a capability. It answers a question the
contracts deliberately leave open — how the agents a node provisions
(`peer-node/agents/*`, the Master's admin surface, the vault skills) are supposed
to communicate — and it proposes, it does not adopt. Anything adopted from here
becomes a contract change in its own commit, with its own DoD.

## The gap this note addresses

The fabric already has the *authority* half of agent traffic:

- **The signed transport** (`shared/sparknet-http.py`) — requests carry the
  caller's signature; the registry carries grants and capabilities; `guard`
  decides what a granted request may mutate.
- **The dispatch-bridge** (`sparknet-dispatch-bridge.py`, loopback 4096) — an
  OpenAI-compatible proxy that routes *local client* calls toward domain agent
  ports and injects the node's user-environment profile. It is deliberately
  local-only: it carries the node's session authority.
- **Provisioned but silent agents** — `peer-node/agents/{engineering,cyber}/agent.py`
  are two-line placeholders; `vault-curator/agent.py` is now a deterministic
  inbox reviewer CLI (no listener), not a server. `opencode-serve` (8090) is the
  single opencode server. Open WebUI is the Master's declared admin surface
  (overlay 8088, provisioned; relocated from 8080 and deployed on the live
  Master, fabric Step 55).

What is *not* contracted is the part in between: how one agent reaches another
(or reaches a tool on a neighbouring node), and what an LLM-driven surface
(such as Open WebUI) is allowed to execute. Today the honest answers are "by
reaching the same loopback bridge" and "nothing — no tool is authorised for any
agent yet". This note designs both, without smuggling in a second trust boundary.

## Two protocols, two layers — do not merge them

| Layer | Question it answers | Candidate protocol | Decision in this design |
|---|---|---|---|
| **A2A** | how an agent or service talks to *another agent or service* | an agent-to-agent wire | the existing signed HTTP transport + grants, overlay-only; **not** MCP |
| **MCP** | how a *single agent* reaches its *local tools* (files, verifiers, the vault) | Model Context Protocol | acceptable **inside one agent process**, server-side; **not** as a cross-node or inter-agent wire |

MCP is a tool-calling protocol between one model and its tools. A2A is a
service-to-service wire. Using MCP for A2A would graft tool-call semantics onto
a boundary that already has a stronger primitive — the signed request. The
boundary is exactly where you want the *weaker* guarantee on the wire (signature
+ grant) and the *richest* semantics inside a process (tool calls), never the
reverse.

This mirrors what the repository already did once: the peer's proxy *explicitly
rejects* the client-executed MCP bridge ("no Node runtime enters the image",
`peer-node/PLAN.md` Step 4). This design keeps that rejection and generalises the
reason: the transport is shared and signed; tool-calling vocabulary does not hop
nodes.

## A2A: agents reach agents over the signed transport

### Message shape

An agent-to-agent request is an ordinary signed request on
`shared/sparknet-http.py`, with the same three properties every contract message
already has:

1. **signed by the caller's node key** — the recipient can tell who spoke before
   reading anything;
2. **carrying a grant the registry holds** — capability + scope, so the recipient
   applies its own verification rather than trusting the caller's claim;
3. **overlay-only** — a loopback service may face other loopback services; an
   overlay service binds `10.100.0.x`, never a wildcard (`ports.json`
   invariant).

There is no new endpoint vocabulary proposed here: the existing refusals
(`guard`'s 401/403 vocabulary, `ports.json`'s stable `reason`) are the A2A
error model. A2A does not get a second error language.

### Who reaches whom

- **Node-local agent → node-local agent**: via the shared loopback bridge
  (dispatch-bridge 4096 today), because both are the same node's sessions. No
  overlay path for this; crossing the node boundary is not free.
- **Node-local agent → tool on the same node**: also loopback. The tool is an
  agent or a script behind the guard; the request is signed like anything else.
- **Node-local agent → agent on a sibling**: by signed request over the overlay,
  terminating at the sibling's own guard, **not** at the sibling's loopback
  bridge. A peer's bridge injects *its* user profile; a stranger must never land
  inside that.

### What this deliberately does not mean

- No agent-to-agent *broadcast*. Every message has a named recipient and a
  grant that names the sender pair ("peer_pair" in the share vocabulary).
- No agent holds "re-formation" or "escalate" as a callable — convergence with
  `capabilities.json` is the closed vocabulary, not a superset of it.
- No new port, by construction: loopback-to-loopback goes through 4096, overlay
  goes through an existing overlay service. Adding a port for A2A would hand it
  a transport edge no other authority has (the same rule the re-formation
  invariant already states for `ports.json`).

## MCP: server-side, inside a process

Where MCP *is* useful is bounded: a single agent process offering its tools to
its own model through the standard tool-calling interface. The rules:

1. **Server-side only.** The MCP server is the agent; the client is the same
   process's model loop. No client-executed bridge (this preserves the peer's
   no-Node-runtime decision).
2. **The MCP server adds no authority.** Whatever tool the MCP server exposes
   still signs its own requests and is subject to the guard. MCP is a
   presentation layer of tools, not a bypass of grants: a tool call that would
   have been refused as a signed request is not made legal by being an MCP tool.
3. **MCP does not cross the overlay.** A sibling's MCP server is outside your
   process and is therefore reached as an A2A signed request, never by pointing
   an MCP client at it.
4. **The vault is a tool surface, not a filesystem.** `/vault/*`-shaped reads
   and writes, grant-checked and path-canonicalised (the peer plan's Step 4
   property), are the shape of a vault tool; raw filesystem access is not.

## Options considered and rejected

| Option | Verdict | Reason |
|---|---|---|
| MCP everywhere (including inter-node) | **rejected** | reintroduces a tool-call wire on the one boundary that already has signatures + grants; two vocabularies for one boundary |
| client-executed MCP bridge (vendored proxy pattern) | **rejected** | needs a Node runtime; already rejected in `peer-node/PLAN.md` Step 4 |
| A2A broadcast or rendezvous namespace | **rejected** | no anonymous recipient; signatures are the identity, and a reply needs a named signed grant |
| new A2A port | **rejected** | `ports.json` invariant: no new transport edge for a capability no other authority has |

## What is adopted only in its own commit

If the operator adopts any part of this, each adoption is a normal contract
change (both roles + `contracts/` in one commit, `make contract-test` green),
and most pieces already have homes:

- **MCP server-side inside an agent** → a peer-side Step (agent provisioning),
  tracked in `peer-node/PLAN.md`, not a contract change (it changes no other
  role).
- **Stable A2A endpoint vocabulary** (the named-recipient signed message
  shapes) → extends `contracts/ports.json` + the relevant identity/capability
  text, and *then* the agent placeholders get real bodies.
- **Cross-node conversation passing** → explicitly **out of scope here**. It is
  `peer-node/PLAN.md` Step 3/4 work (grant_keyed persistent sessions,
  `/vault/*` ledgered mutations) and it is `DoD: confirm: user` — this design
  exists to keep MCP/A2A from being mistaken for that work.

## Provenance and consistency

- Grounded in the repository's own decisions: `peer-node/PLAN.md` Step 4 (no
  Node MCP bridge, persistent sessions, grant-checked `/vault/*`), `contracts/
  ports.json` invariants (overlay-only, loopback-only routes refuse 403,
  no-new-edge), `contracts/capabilities.json` (closed vocabulary, escalation
  note reformation_note).
- Nothing here creates a port number, a capability name, a message vocabulary
  that *must* be recognised, or a role behaviour change. It is a map of where
  the existing primitives reach, not an extension of them.
- The one open question this note hands forward: *how a granted A2A request is
  scoped to a specific peer_pair conversation* — answered by the session-grant
  work already tracked, and recorded here so MCP does not accidentally invent a
  competing scope.