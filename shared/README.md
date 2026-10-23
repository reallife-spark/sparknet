# shared/

Executable implementations that **both roles** depend on. Deliberately
sparse, and deliberately not duplicated per role.

## `sparknet-authz.py`

The reference implementation of the signed authorization scheme:
canonical identity projection, SHA-256 fingerprinting, Ed25519 signing and
verification, registry evaluation.

**Why there is exactly one copy.** The Master calls `sign`; a peer calls
`verify`. Those two must agree byte-for-byte on the canonical form, or the
Master signs something the peer rejects. If each role carried its own copy,
they could drift — a changed separator, a sorted list, a different set of
identity fields — and the failure would be silent and intermittent: signatures
that verify on the node that produced them and fail everywhere else.

That is a security bug, not a duplication nit. So the algorithm lives here once,
and each role wraps it:

- `master-node/` — signs entries, manages the registry, revokes
- `peer-node/` — verifies entries, evaluates its own authorization posture

Neither role re-implements the algorithm. Neither role may edit this file to
serve a local need; a change belongs in `contracts/` first, with both roles
updated in the same commit.

### The guard-approval projection

`guard_approval_message()` is a second canonical form in the same module: the
bytes a Master signature over a guard approval covers. It is here for exactly
the reason the rest of the module is — the Master **signs** the approval and
the peer **verifies** it, so the two must agree on the projection byte for
byte.

It is strict in both directions: a missing field is refused, and so is an
*extra* one. The signature covers exactly the projection, so anything outside
it is unsigned, and an unsigned field in an envelope that carries authority is
how a second, unchecked channel into the guard would appear later.

This projection was **not** here before Master build-plan Step 5, and its
absence was the defect: the Master's issuer, the isolated signer and the
peer's guard each carried their own idea of an approval's shape — three
different field sets, each internally consistent, each passing its own tests.
No approval the Master could mint was one a peer would accept, and nothing
failed loudly, because every side agreed with itself.

The contract is `contracts/guard-approval.json` (machine-readable) and
`contracts/guard-protocol.md` (narrative). `tests/test_contracts.py` fails the
build if a second copy of the field list appears in either role.

## `sparknet-consensus.py`

How the cluster agrees on who holds the signing key: master election, the
n-of-n unanimity rule (2 of 2 in a pair, 3 of 3 in the full cluster), canonical
cluster trust roots, and re-formation when the Master changes. The narrative
contract is `contracts/consensus-protocol.md`.

**Why it is here and not in the Master.** Every member runs this, including
those that are only peers. The Master does not decide who the Master is — the
members do. Putting the decision in `master-node/services/` would hand the
decision to the party the decision is about, which is the thing the election
exists to prevent.

**Why there is exactly one copy.** Two nodes computing different canonical bytes
for the same agreement would each conclude the other had not agreed, and the
cluster would deadlock with no visible cause. The bytes must not depend on dict
ordering or member listing order, so `root_bytes` sorts both.

**It does not reimplement Ed25519.** Every signing and verification operation
calls into `sparknet-authz.py`, loaded by path from this directory. Two crypto
implementations that must agree byte-for-byte would be a second trust boundary;
`tests/test_consensus.py::test_consensus_does_not_reimplement_ed25519` fails the
build if this module starts doing its own. When the shared file cannot be found,
this module raises rather than falling back to a local implementation.

**Every deadline is injected.** No code path here reads the wall clock, so the
agreement rules are testable in seconds instead of hours, and a missed window
cannot hide behind a test nobody waits for.

## `sparknet-http.py`

The signed JSON transport both roles dial: stdlib HTTP client + server where
every request carries an Ed25519 signature over method+path+body-sha256+
timestamp (see the module docstring for the exact envelope). The first real
consumer is the peer's dispatch bridge (`peer-node/services/
sparknet-dispatch-bridge.py --serve`, port 4096, `tests/test_http_transport.py`).

**Why it is here and not in a role.** A client that signs and a server that
verifies must agree byte-for-byte on what the signature covers; two copies
would drift the way authz copies would, and requests would verify on the node
that made them and fail everywhere else.

**It does not reimplement Ed25519.** Every signing and verification operation
calls into `sparknet-authz.py`, loaded by path from this directory — the same
loader pattern and the same refusal to fall back that `sparknet-consensus.py`
uses.

**Replay defence is the freshness window.** A signature is only good within
`max_age_seconds` of the timestamp it names, and the clock is injectable so the
window is testable without sleeping.

## `sparknet-registry-schema.py`

The checker for the **shape** of a node-authorization registry: it reads
`contracts/registry-schema.json` — the one statement of what a registry looks
like — and reports every way a document departs from it. Fields present and
absent, types, the fingerprint that must match the identity it carries, the
closed capability vocabulary, and each entry's signature under the
`master_public_key_b64` the document names.

**Why it is here and not in a role.** The Master signs a registry and a peer
verifies it. If the two checked against different expectations, a registry the
Master considered good would be rejected by the peer — and the failure would
look like a signature problem, not a shape problem, which is the worst place to
debug it. One checker, one contract, both roles.

**Why it reads the standard library only.** The fabric's runtime dependency
allow-list is `cryptography` alone, and the CI gate installs exactly that plus
pytest and ruff. A validator that needed `jsonschema` would pass here and fail
on a node, so this one interprets the small schema vocabulary the contract
declares — and **refuses** a keyword it does not implement rather than ignoring
it. A rule nobody enforces is a rule that quietly stops being true.

**It never re-implements the scheme.** The canonical form, the fingerprint and
the signature check all come from `sparknet-authz.py`, loaded by path from this
directory — the same loader pattern the other modules use, and the same refusal
to fall back to a local copy.

## Adding to this directory

Only if **both** roles need the same code and any divergence would be a
correctness or security problem. Role-specific logic does not belong here — it
belongs in the role's own `services/`. The test is: if only one role would ever
call it, it is not shared.
## Never copy this into a role

`sparknet-authz.py` stays here, at exactly one path, for both roles. A copy in
`peer-node/services/` or a future `master-node/services/` is how the two roles
silently stop agreeing: each verifies against its own version, and the day they
differ — a changed canonical form, a reordered field — every signature
verification fails at once, on every node, with no obvious cause.

So it is a rule, not a preference, and `tests/test_contracts.py`
(`test_only_one_authz_implementation_exists`) fails the build if a second copy
appears anywhere in the tree. A role that needs different behaviour wants a
contract change in `contracts/`, not a patched local variant.

This also means a role subvault on its own is **not** a working deployment: it
cannot verify anything, because it does not have this file. `make bundle`
assembles the role together with `shared/` and `contracts/`.
