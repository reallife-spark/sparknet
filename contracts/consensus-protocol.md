# Consensus protocol — how three nodes agree on who holds the key

All three nodes implement this conversation. The state of the implementation is
worth stating precisely, because a reader who takes this page for a description
of working code will be wrong about a security boundary:

| Piece | State |
|---|---|
| Root formation and verification (`shared/sparknet-consensus.py`) | built, unit-tested |
| Key separation (cluster / operational / identity) | built, unit-tested |
| **The election itself** — who votes, and how a result becomes a root | **not built.** `verify_root` checks a root; it does not produce one. Step 14's implementation, and it needs a trust root to vote on. |
| Re-formation when a member is dropped | **not built**, and unspecified — see below |

The signer that consumes a root is built (`master-node/services/sparknet-signer.py`),
but it deliberately has no way to make one. A signer pointed at a root that is not
valid, does not name it, or is not the root it was started with, refuses to sign.

The normative machine-readable policy is
`contracts/identity-schema.json` (`cluster_trust_root`),
`contracts/capabilities.json` (`cluster-vote`) and `contracts/ports.json`. This
page is the narrative contract.

## The problem this solves

The fabric previously assumed a Master that existed independently of its peers
and held the signing key. That is not a fabric; it is a server with clients, and
it has the weakness every such arrangement has — the key sits on whatever machine
was named, and nothing about that machine's legitimacy was ever agreed.

So the Master is **elected**. Three nodes join, and of those three one is chosen.
The choice is unanimous. The chosen node is a peer that additionally holds an
operational signing key.

## The asymmetry is a role state, not a structure

`guard-protocol.md` once stated as a timeless fact that a peer can verify an
approval but never produce one. Under this protocol that is no longer structural.
A peer's code contains the signing path; what separates a peer from a Master is
which state the node is in.

This matters for anyone reading the code. "The peer cannot sign" is not a
property of the peer's implementation — it never was, and now it certainly is
not. The property is that **only a node named by a valid cluster trust root may
use the operational key**, and that root required all three members to agree.

The authority asymmetry is preserved. It moved from "the code differs" to "the
state differs", which is a weaker guarantee and is stated as one.

## Membership

Membership is a set of node identities, each pairing an identity fingerprint
with a WireGuard public key. A node joins by exchanging its WireGuard public key
out-of-band with the two others — there is no authority to bootstrap from,
because the registry ships empty on purpose.

A member is not trusted merely for being a member. Each member holds a **cluster
key**: an Ed25519 keypair used only for agreeing on the trust root, never for
signing registry entries. Splitting the two keys is what makes a cluster key
useless to a node that is merely present.

## Election

```
three members present
        │
        ▼
election opens; each member casts exactly one signed vote for one candidate
        │
        ▼
three votes, three distinct members, all naming the same candidate?
        ├── no  → no trust root. No authority is issuable anywhere.
        │          Peers remain in peer-only mode, which is a working state.
        └── yes → candidate generates its operational keypair
                  root binds master_pubkey
                  all three members co-sign the root
        ▼
root distributed; peers verify it and accept the registry signed under master_pubkey
```

**One member, one vote.** Votes are deduplicated by member identity, so a node
that casts three votes for itself has cast one.

**Votes are signed and carry a nonce**, so a vote cannot be replayed into a later
election.

### Why unanimity, and what it costs

Unanimity is chosen over a 2-of-3 majority deliberately.

With a majority, one compromised node paired with any second node installs a
hostile master. With unanimity, a single bad node can **deny** an election — it
can refuse to vote, and the cluster stays without a root — but it can never
**win** one. That is the right trade for a fabric whose whole premise is that
nobody can grant themselves authority.

The price is liveness: one offline node blocks the election indefinitely. That is
accepted rather than worked around, because the alternative quietly reintroduces
the single-point-of-compromise the protocol exists to remove. The documented
escape is re-formation.

Every deadline in this protocol is evaluated against an **injected clock**. No
test waits for a real window.

## The cluster trust root

```
cluster_trust_root = {
  version, nonce, formed_at,
  members: [ { node_id, fingerprint, wireguard_pubkey, cluster_pubkey } × 3 ],
  master_node_id, master_pubkey
}
```

co-signed by all three member cluster keys, over the canonical bytes.

Peers accept a root only when:

1. it carries three valid signatures,
2. from three **distinct** members,
3. each matching the `cluster_pubkey` of a member the root itself names,
4. and the `master_pubkey` is the one the registry is signed under.

Points 3 and 4 matter more than they look. Without 3, a root could name members
and be signed by strangers. Without 4, a root could bind a master public key
that no authority ever recognised.

The root is self-describing: it carries its own membership, so a peer joining
later reads the membership from the root rather than from configuration that could
disagree with it.

### Replace versus revoke

This is the asymmetry that makes the protocol tolerable:

| Act | Threshold | Why |
|---|---|---|
| **Replace** the master | 3 of 3 | changes who holds authority |
| **Revoke** a node | 1 signature | a revoked node is inert either way |

Unilateral revocation is safe because it is a denial: it removes reach and cannot
add any. Unilateral replacement would hand the key to whoever committed the
change. The same reasoning already appears in `capabilities.json` under
`escalation_note`, and this protocol does not contradict it.

## Re-formation

Changing the Master means forming a **new** root.

A new root has a new nonce, so it is not a replay of the old one: re-presenting the
root already in force is refused as `root_replayed`, and the new root's
`master_pubkey` is the only one the new root authorises.

**But a new nonce does not make the old root stop verifying, and it is worth being
blunt about that.** The old root remains internally valid forever — same three
signatures, same master, nothing in it says it was superseded. `verify_root` is a
pure function over one root plus, optionally, the root the caller already holds;
given two roots with different nonces it can say "you already have this one", and
it cannot say which is newer. Two roots are only ordered by something outside
themselves.

Supersession is therefore enforced where history lives, not in the pure verifier:

- every signature a node issues records the `root_id` it was issued under, so a
  ledger containing a different `root_id` means the process is being pointed at a
  root it has already moved past — `sparknet-signer.check_not_reverted` refuses
  that unless `--accept-requalification` says so deliberately;
- a peer must *learn* the new root before the old Master stops being recognised by
  it. Until it does, the old root's authority still verifies, because nothing local
  contradicts it.

That second bullet is a real gap and is recorded below rather than asserted away.

**Re-formation is also meant to be the escape from a blocked election.** If
unanimity cannot be reached, the members that remain form a new root with a new
membership — dropping the node that would not agree.

**That escape does not exist yet, and the contract currently contradicts itself
here.** With exactly three members and unanimity required, a root needs all three
signatures, so if one member is merely *unreachable* — powered off, disk failed,
not hostile — the two survivors cannot form a root either. "Reduce membership by
re-formation, with unanimity among the survivors" is unsatisfiable at n=3: the
case where re-formation is needed is precisely the case where it is impossible.

This is recorded rather than papered over, because the resolutions are policy
choices, not implementation details, and each trades something real:

| Option | Threshold after a member is lost | Cost |
|---|---|---|
| **A** — permanent triple | stays 3 of 3 | a single failed disk requires manual recovery from backup. Highest integrity, lowest availability. |
| **B** — 2 of 3 to reduce, 3 of 3 to grant | 2 signatures to form a reduced root, 3 to form a full one | a Byzantine pair could remove an honest node. Needs a rule preventing two colluding nodes from reaching authority. |
| **C** — 4th member joins before any drop | unchanged at 3 of 3 | requires a join ceremony, which is also unspecified |

A second open question sits alongside it, and is narrower but no less real:

| Question | Why it is open | Cost of guessing |
|---|---|---|
| **How does a re-formed root reach a peer?** A new root is served by the nodes that formed it, and the old one is locally indistinguishable from the new one. | no signed ordering exists in the root, and `verify_root` cannot invent one | announcing over a channel the superseded Master also controls means a rolled-back Master can suppress the news of its own replacement. That is the classic reason a leader needs a *lease*, not a broadcast. |

Until one is chosen, the correct statement is: **a three-node cluster cannot
survive the loss of a member, by design or by omission, and a peer that has not
learned of a re-formed root still honours the superseded Master.** Everything
downstream — the signer's `--accept-requalification`, root supersession in
`shared/sparknet-consensus.py` — is built for the general case, but a *reduced*
root is a document this contract does not yet define.

**Re-formation is not a bypass.** Whatever threshold is chosen, it cannot install a
Master without unanimity among the members of the *new* root, and a node removed by
re-formation cannot re-form its way back in on its own.

## Isolation of the operational key

The elected Master is also a peer, and peers run Open WebUI, a dispatch bridge and
agent ports. A key that authorizes the whole fabric must not be reachable from an
LLM-driven web surface, so the operational key lives in a signer process that does
nothing else, and the peer functionality cannot reach it.

This is structural, and deliberately not a permission rule: a deny rule is a policy
statement that the thing it governs may later ignore, and the governed surface here
is a multi-user LLM application.

The cluster keys are a different matter. They sign only the root, which all three
members must co-sign, so a single stolen cluster key cannot install a Master on its
own — it is one of three required signatures.

## What is not contracted here

- **Membership changes beyond re-formation.** Adding a fourth node is out of
  scope here and would need its own threshold; a 4-member cluster's unanimity
  requirement is a different protocol, not a parameter.
- **What a vote is worth economically.** Votes are signed and distinct, not
  stake-weighted and not Sybil-resistant. A cluster is three known nodes.
- **Transport.** How the vote reaches the other members is implementation.
- **Timing attacks.** Elections use an injected clock and no nonce reuse window is
  specified beyond the election's own nonce.
