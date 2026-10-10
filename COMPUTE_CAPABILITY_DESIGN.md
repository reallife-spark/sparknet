# Compute capability design — signed delegated compute, not a gate on arithmetic

Status: **design proposal, not a contract change.** Nothing in this note binds
`contracts/`, adds a port, grants a capability, or changes either role. It
answers a question the contracts deliberately leave open — *what would it take
for a peer to compute on the fabric's authority rather than only locally* — and
it proposes, it does not adopt. Anything adopted from here becomes a contract
change in its own commit, with its own DoD (`make contract-test` green, both
roles edited in the same commit).

## The tension this note has to resolve first

A naive "compute capability" is wrong. A peer is already **authoritative for its
own inference and compute** (`peer-node/AGENTS.md`): it reads, it thinks, it
runs its own vault without asking the Master. Gating that would be theatre — and
a capability that cannot be withheld without freezing the node is not a
capability, it is a tax.

So there are two different things, and only one of them is worth a contract
change:

| | Authority needed | Gate it? |
|---|---|---|
| **Local compute** — a node computes for itself | none | **No.** Already free, deliberately. |
| **Delegated compute** — a node executes work *another node supplies* | Master-signed task | **Yes.** This is remote execution. |

`2−2` is the first kind. It needs nothing from the Master; the honest answer
today is that a peer just computes `0`. This note therefore does **not** design a
`compute` capability. It designs **`compute-serve`**: the right to be handed a
signed task and run it.

## Scope and non-goals

- Non-goal: gating local arithmetic or a node's own inference.
- Non-goal: arbitrary code, `eval`, shell, or a "run this script" operation.
- Non-goal: a new authority. The task signer is the Master's operational key;
  the executor holds no signing authority at all.
- Non-goal: a transport edge other capabilities can borrow.

## The capability

One entry added to the closed vocabulary. It is the **second** `sensitive: true`
capability, and for the same reason as `guard-apply`: the holder is the node
that incurs the risk.

```json
"compute-serve": {
  "grants": "Accept a Master-signed compute task over the overlay, execute it within a closed operation whitelist, and return an attested result.",
  "holder": "peer",
  "sensitive": true,
  "note": "The second sensitive capability after guard-apply, and dangerous in the same direction: the holder is the node that gets made to run something. It gates DELEGATED compute only. A node computing for itself is already free and is not gated by this or any capability. A peer never executes a caller-supplied program; it executes one of a closed set of operations on Master-signed parameters."
}
```

**Two-place change — this is load-bearing.** The closed vocabulary is not a
single source of truth in code today:

1. `contracts/capabilities.json` — append `"compute-serve"` to
   `known_capabilities` and add the definition.
2. `shared/sparknet-authz.py` — add `"compute-serve"` to the hard-coded
   `KNOWN_CAPABILITIES` frozenset.

`tests/test_contracts.py` asserts the two sets are equal (`KNOWN_CAPABILITIES ==
known_capabilities`) and that `definitions` names exactly `known_capabilities`,
so a one-sided edit fails the build rather than half-working. The signer's
registry-entry path independently refuses unknown capabilities, so a stale copy
fails closed.

## Authority model

| Step | Who | Mechanism |
|---|---|---|
| Grant `compute-serve` to an executor | Master | the existing `sign-registry-entry` — **no new signer op** |
| Authorize one task | Master | **new** signer op `sign-compute-task`, typed payload |
| Execute | executor (a peer holding `compute-serve`) | closed whitelist; returns an attested result |
| Verify the result | requester | the executor's **node identity** signature |

The distinction that keeps this honest: the Master's **operational** key
authorizes (permission); the executor's own **node identity** key attests
(provenance). A result signature proves *who computed it*, never *that it was
permitted* — the same asymmetry `consensus-protocol.md` draws between a vote and
a grant.

### Signer change

`SIGN_OPERATIONS`/`OPERATIONS` gain `sign-compute-task`, modelled exactly on
`_sign_guard_approval` in `master-node/services/sparknet-signer.py`: build the
canonical bytes from a sorted field tuple, refuse unknown or blank fields,
refuse a task already expired against the injected clock, sign, and record a
ledger block. The signer still has **no "sign these bytes" operation** — it
grows one typed shape, not a general signer. Adding an operation is itself a
reviewed change with its own refusal tests (unknown op, unknown capability,
expired task, partial payload).

## Task envelope — what the Master signs

| Field | Purpose |
|---|---|
| `fingerprint` | sha256 of the executor's canonical identity (`contracts/identity-schema.json`) |
| `capabilities` | must include `compute-serve`, or the executor refuses |
| `task_id` | correlates task → result; the ledger and the result carry it |
| `operation` | must be in the closed whitelist |
| `params` | operation parameters, **inside** the signature |
| `content_in_signature` | `true` — params are signed, not referenced |
| `nonce` | single-use; replay refused |
| `issued_at` / `expires_at` | validity window, evaluated against the injected clock |

`params` is inside the signature for the same reason `guard-protocol.md`'s
`content` is: signing only a task id would let anyone replay it against
different inputs.

## Result envelope — what the executor returns

| Field | Purpose |
|---|---|
| `task_id` | echoes the task |
| `node_id` / `fingerprint` | who executed |
| `operation` | which whitelisted op ran |
| `result` | the scalar answer (bounded size), or omitted for large output |
| `result_digest` | sha256 of the full output when only a digest is returned |
| `completed_at` | injected clock |
| `signature_b64` | Ed25519 by the executor's **node identity** key over the canonical result |

## Verification order (executor — cheapest decisive check first, fail-closed)

1. **Source address** — the Master's overlay IP
   (`contracts/overlay.json → master_anchor_ipv4`). The executor binds its *own*
   overlay address, so a legitimate task arrives from `10.100.0.1`.
2. **Master signature** — Ed25519 over the canonical task bytes.
3. **Not revoked** — registry checked *before* signature validity, so a tampered
   registry fails closed.
4. **Not expired / not replayed** — nonce unused, within TTL.
5. **`compute-serve`** — present in the signed envelope.
6. **`operation` in the whitelist** and `params` schema-valid.
7. **`euid`** — the executor runs **unprivileged**; unlike `guard-apply` it needs
   no root, because it mutates nothing.
8. **`--execute-enabled`** — off by default, mirroring the guard's
   `--apply-enabled`. Arming a node to run delegated work is an operator
   decision, never a default.

## Execution sandbox

v1 exposes exactly two operations. Both are deterministic, with no I/O, no
network, no filesystem and no name binding:

- `arith` — evaluate an arithmetic expression over a **restricted AST**
  (`+ - * / // % **`, unary minus, parentheses, numeric literals). `Name`,
  `Call`, `Attribute`, `Subscript`, comprehensions, lambdas and string input to
  `eval` are rejected.
- `digest` — sha256 of a supplied byte string, hex-encoded.

The whitelist **is** the sandbox. There is deliberately no "run this script"
operation: it would make the executor a general remote-code endpoint and void
the fail-closed model the rest of the fabric is built on. Adding an operation is
a contract change with its own review.

## Port and transport — the one open decision

- **Recommended: a new overlay-only port `compute-exec`** (`bound_by: peer`,
  `overlay_only: true`, `binds_to` the peer's own overlay address), served over
  `shared/sparknet-http.py` with peer-personality only and no local face —
  exactly like the guard.
- **Rejected: a `/compute` route on the guard's `9090`.** It reuses a port but
  welds the most privileged mutator (`chattr +i`, protected writes) to a compute
  endpoint, so a defect in the parse path would sit inside the guard's trust
  boundary.
- **Rejected: piggyback on `push-receive`.** That is a data-plane accept, not an
  execution request; conflating them makes "may push an artifact" silently mean
  "will run work".

Note on `MCP_A2A_DESIGN.md`'s "no new port" rule: that rule is about
*agent-to-agent traffic and re-formation reusing an existing authority edge*. A
capability whose entire point is that a node executes supplied work **is** a new
authority edge, and `ports.json` already accounts for that case (`9090` exists
for `guard-apply`, a peer-side listener). A new port is therefore consistent
with the contract — but it stays a deliberate operator decision, not a default.

## Lifecycle

- **Nonces** are retained at least as long as the longest task TTL, or a replay
  window opens silently (the same rule as grants in `identity-schema.json`).
- **Ledger**: the executor appends a hash-chained record per executed task; the
  Master retains the nonces it issued. Both halves are needed — one says what
  ran, the other says who authorized it.
- **Revocation**: `revoked: true` in the registry makes the executor inert — it
  refuses to bind and refuses to execute, exactly the guard's standalone
  degradation in `guard-protocol.md`.
- **Silence is a refusal**: with no reachable Master there is no task to run, so
  nothing persists waiting for approval (`capabilities.json` clock semantics).

## Worked example — the 2−2 round trip, once built

On the 2026-10-09 pair (`node131` Master, `node133` peer):

1. Master `node131` signs a registry entry adding `compute-serve` to `node133`
   (existing `sign-registry-entry`); `node133` adopts the wrapped registry.
2. Master `node131` calls its isolated signer: `sign-compute-task` with
   `fingerprint = sha256(identity(node133))`, `capabilities: ["compute-serve"]`,
   `operation: "arith"`, `params: {"expression": "2-2"}`, a fresh nonce and a TTL.
3. It POSTs the signed task to `node133`'s overlay address.
4. `node133` runs checks 1–8, evaluates `arith("2-2") → 0`, and returns
   `{task_id, node_id: "node133", operation: "arith", result: 0, …}` signed by
   `node133`'s node identity key.
5. The Master verifies `node133`'s signature; the ledger holds both blocks.

**Answer: `0`, on the record** — and, unlike today, attributable to a named
executor under a Master-signed task. Without this build, step 4 is just
`python3 -c 'print(2-2)'` on the executor and nothing crosses the boundary, which
is the *correct* behaviour for arithmetic, not a gap.

## Options considered and rejected

| Option | Verdict | Reason |
|---|---|---|
| `compute` capability gating local arithmetic | **rejected** | freezes a node's own inference; a capability that cannot be withheld is a tax |
| arbitrary code / `eval` / shell operation | **rejected** | makes the executor a remote-code endpoint and voids the fail-closed model |
| reuse guard `9090` with a `/compute` route | **rejected** | widens the guard's trust boundary |
| piggyback on `push-receive` | **rejected** | conflates "may push an artifact" with "will execute work" |
| requester-signed tasks (any authorized member), no Master op | **rejected for v1** | lets any registry member make any `compute-serve` peer execute. The Master-signed task preserves the "only the Master causes a sensitive act" rule that `guard-apply` already follows. Revisit only if peer-to-peer offload becomes a real requirement — as a decision, not a detail. |
| no capability; peers offload by SSH | **viable, rejected** | moves the trust boundary out of the fabric and leaves no signed audit trail |

## Adoption plan (each item its own commit)

1. `contracts/capabilities.json` + `shared/sparknet-authz.py` gain the
   capability; `make contract-test` proves both roles agree.
2. `shared/sparknet-authz.py` gains the task signed-field tuple and its
   canonicalisation, shared by signer and verifier — **one** projection rule,
   never two (the reason `authorization_message` exists).
3. `master-node/services/sparknet-signer.py` gains `sign-compute-task`, with
   typed-payload tests and mutation-proven refusals (unknown op, unknown
   capability, expired task, partial payload).
4. `peer-node/services/sparknet-compute-d.py` executor + tests; `ports.json`
   `compute-exec`; a peer systemd unit in the same inert-until-armed pattern as
   the guard.
5. A Master dispatcher (`master-node/scripts/`) that signs via the socket, POSTs
   and verifies the result; plan steps in `peer-node/PLAN.md` and
   `master-node/plans/MASTER_BUILD_PLAN.md`.
6. `make test-all`, `lint`, `contract-test`, `validate`, `keys-check`,
   `shims-check` green; live deploy is `DoD: confirm: user`.

## Provenance and consistency

- Grounded in `contracts/capabilities.json` (closed vocabulary; `guard-apply`
  sensitive note; escalation/reformation notes), `contracts/identity-schema.json`
  (canonicalisation, grant, signature split), `contracts/guard-protocol.md`
  (ordered checks, content-in-signature, standalone degradation),
  `contracts/ports.json` (overlay-only, no wildcard, no-new-edge invariant),
  `shared/sparknet-authz.py` (the single verifier; `KNOWN_CAPABILITIES` is
  hard-coded and must match the contract), and
  `master-node/services/sparknet-signer.py` (`_sign_guard_approval` pattern).
- Nothing here creates a port number, a capability name, or a role behaviour
  that **must** be recognised until it is adopted in its own commit. It is a
  proposal about where the existing primitives reach, plus the one new
  primitive a delegated-compute capability actually needs.
- Open questions handed forward: (a) *requester scope* — Master-only (v1) or any
  registry member? (b) *result size* — scalar/digest only (v1), or a blob path
  over `push-receive`? Neither is a detail; both are decisions for adoption.
