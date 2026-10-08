# Consensus protocol — how the cluster agrees on who holds the key

Every node implements this conversation. The state of the implementation is
worth stating precisely, because a reader who takes this page for a description
of working code will be wrong about a security boundary:

| Piece | State |
|---|---|
| Root formation and verification (`shared/sparknet-consensus.py`) | built, unit-tested |
| Key separation (cluster / operational / identity) | built, unit-tested |
| **The election itself** — who votes, and how a result becomes a root | **built** (fabric `PLAN.md` Step 11). `shared/sparknet-election.py` is the exchange: `serve` collects bids, ballots and root co-signatures on port 4210 and holds no private key — every signature is made by a member process holding its own cluster key. `peer-node/scripts/sparknet-election-request.sh` and `master-node/scripts/sparknet-election-approve.sh` run the member ceremony for each role. The listener is code, not a deployment: `contracts/ports.json` records 4210 `implemented` with runtime `not-listening` until a host actually runs it. See **Exchange** below. |
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

So the Master is **elected**. The members of a cluster — a pair of two, or the
full cluster of three — choose one of themselves. The choice is unanimous. The
chosen node is a peer that additionally holds an operational signing key.

## The asymmetry is a role state, not a structure

`guard-protocol.md` once stated as a timeless fact that a peer can verify an
approval but never produce one. Under this protocol that is no longer structural.
A peer's code contains the signing path; what separates a peer from a Master is
which state the node is in.

This matters for anyone reading the code. "The peer cannot sign" is not a
property of the peer's implementation — it never was, and now it certainly is
not. The property is that **only a node named by a valid cluster trust root may
use the operational key**, and that root required every member to agree.

The authority asymmetry is preserved. It moved from "the code differs" to "the
state differs", which is a weaker guarantee and is stated as one.

## Membership

Membership is a set of node identities, each pairing an identity fingerprint
with a WireGuard public key. A cluster is **two members (a pair) or three (the
full cluster)**; a fourth member changes the agreement threshold and needs its
own protocol, so the count is a bounded range, not a parameter. A node joins by
exchanging its WireGuard public key out-of-band with the other members — there
is no authority to bootstrap from, because the registry ships empty on purpose.

A member is not trusted merely for being a member. Each member holds a **cluster
key**: an Ed25519 keypair used only for agreeing on the trust root, never for
signing registry entries. Splitting the two keys is what makes a cluster key
useless to a node that is merely present.

## Election

```
the members present
        │
        ▼
election opens; each member casts exactly one signed vote for one candidate
        │
        ▼
every member's vote names the same candidate?
        ├── no  → no trust root. No authority is issuable anywhere.
        │          Peers remain in peer-only mode, which is a working state.
        └── yes → root binds the candidate's operational keypair
                  (generated when the candidate bid)
                  every member co-signs the root
        ▼
root distributed; peers verify it and accept the registry signed under master_pubkey
```

**One member, one vote.** Votes are deduplicated by member identity, so a node
that casts many votes for itself has cast one.

**Votes are signed and carry a nonce**, so a vote cannot be replayed into a later
election.

### Why unanimity, and what it costs

Unanimity is chosen over any n−1-of-n majority (2-of-3 in the full cluster, 1-of-2
in a pair) deliberately.

With a majority, one compromised node paired with any other installs a hostile
master. With unanimity, a single bad node can **deny** an election — it
can refuse to vote, and the cluster stays without a root — but it can never
**win** one. That is the right trade for a fabric whose whole premise is that
nobody can grant themselves authority. It is also why a pair is lawful: 2-of-2
means one member alone can never elevate itself, which is the same
no-self-elevation property the full cluster gets from 3-of-3.

The price is liveness: one offline node blocks the election indefinitely. That is
accepted rather than worked around, because the alternative quietly reintroduces
the single-point-of-compromise the protocol exists to remove. The documented
escape is re-formation.

Every deadline in this protocol is evaluated against an **injected clock**. No
test waits for a real window.

## Exchange

The election runs as one HTTP service: `shared/sparknet-election.py serve`, port
4210 (`contracts/ports.json`, `cluster-election`). This section is the contract
that file implements; the shapes below must not drift without both moving
together.

| Endpoint | Body | Rule |
|---|---|---|
| `POST /election/request` | `{node_id, operational_pubkey_b64, nonce, ts}` + `signature_b64` over the canonical form, signed with the member's **cluster** key | one bid per member. Re-filing the identical bid is idempotent; a different one is `bid_already_filed`. The bid exists to publish a usable operational key, so one that does not parse is refused here, not at co-signature time. |
| `POST /election/vote` | a signed vote from `sparknet-consensus.py` carrying `election_id` | one vote per member, verified before storage. A second vote for a *different* candidate is refused as equivocation (`already_signed`); the same choice again is idempotent. |
| `POST /election/root-signature` | `{node_id, signature_b64, election_id}` over the root's canonical bytes | one co-signature per member, each verified against that member's own cluster key **before** it is stored — a bad early signature must not hide behind "missing signatures" until every member arrived. The root forms at the last signature, and only when every member voted for the same candidate. |
| `GET /election/status`, `GET /election/root` | — | state machine: `collecting` → `awaiting_operational_key` (tally agreed, winner has not bid) → `awaiting_signatures` → `formed`; a tally that ran without agreement is `no_agreement`, terminal for this election, because filing a bid cannot rescue it. |

Refusals answer with a stable machine-readable `reason`
(`signer_not_a_member`, `bad_signature`, `wrong_election_id`,
`bid_already_filed`, `already_signed`, `unexpected_master`, `no_root_yet`,
`root_unusable`, …) — 400 for malformed input, 403 for identity failures, 409
for state conflicts — so a member can tell a refusal from an outage without
parsing prose.

Properties the shape exists to preserve:

- **The service holds no private key.** It validates, tallies and merges;
  bids, ballots and co-signatures arrive already signed. An HTTP listener with
  a signing key would be a worse trade than the round trip it saves.
- **A member will not co-sign what it did not vote for.** The client refuses a
  root naming anyone but the candidate its own ballot named
  (`unexpected_master`), so two honest votes plus a lying exchange produce two
  refusals, not a master. That check is the member's half of unanimity.
- **The port carries no authority.** Signed votes and root signatures only —
  never a registry entry, never an approval — so the election decides who may
  hold the operational key without ever carrying it.
- **Loopback by default.** `serve` binds `127.0.0.1` unless told otherwise;
  binding the overlay address is a deployment act on a host that has the
  overlay. Hence `ports.json`: `implemented`, runtime `not-listening`.

Membership for the exchange is the out-of-band `cluster-members.json` —
`node_id`, fingerprint, WireGuard public key, cluster public key, two or three
distinct members — read only by `serve`. Members identify themselves by the
keys in it; there is no login, because the signatures are the identity.

Role wiring: `make election-request` (peer) runs the whole ceremony — bid,
vote, wait, co-sign, install on the node identity; `make election-approve
EXPECT=<node>` (master) runs the same ceremony and additionally writes the
formed root into `master-node/manifests/cluster-trust-root.json`. Both are
wrappers around the shared `member` command, because both roles run the same
conversation — the roles differ in what they hold, not in how they agree.

## The cluster trust root

```
cluster_trust_root = {
  version, nonce, formed_at,
  members: [ { node_id, fingerprint, wireguard_pubkey, cluster_pubkey } × n ],
  master_node_id, master_pubkey
}
```

co-signed by every member's cluster key, over the canonical bytes.

Peers accept a root only when:

1. it carries n valid signatures, exactly one per member,
2. from n **distinct** members,
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
| **Replace** the master | n of n | changes who holds authority |
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
blunt about that.** The old root remains internally valid forever — same member
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
here.** With unanimity required, a root needs every member to sign, so if one
member is merely *unreachable* — powered off, disk failed, not hostile — the
survivors cannot form a root either. "Reduce membership by re-formation, with
unanimity among the survivors" is unsatisfiable: a full cluster losing one member
leaves two, a pair losing one leaves one, and a lone node is not a cluster. The
case where re-formation is needed is precisely the case where it is impossible.

This is recorded rather than papered over, because the resolutions are policy
choices, not implementation details, and each trades something real:

| Option | Threshold after a member is lost | Cost |
|---|---|---|
| **A** — keep the original count | stays n of n | a single failed disk requires manual recovery from backup. Highest integrity, lowest availability. |
| **B** — majority to reduce, unanimity to grant | n−1 signatures to form a reduced root, n to form a full one | a Byzantine majority could remove an honest node. Needs a rule preventing colluding nodes from reaching authority. |
| **C** — a member joins before any drop | unchanged at n of n | requires a join ceremony, which is also unspecified |

A second open question sits alongside it, and is narrower but no less real:

| Question | Why it is open | Cost of guessing |
|---|---|---|
| **How does a re-formed root reach a peer?** A new root is served by the nodes that formed it, and the old one is locally indistinguishable from the new one. | no signed ordering exists in the root, and `verify_root` cannot invent one | announcing over a channel the superseded Master also controls means a rolled-back Master can suppress the news of its own replacement. That is the classic reason a leader needs a *lease*, not a broadcast. |

Until one is chosen, the correct statement is: **a cluster cannot
survive the loss of a member below its minimum of two, by design or by omission,
and a peer that has not learned of a re-formed root still honours the superseded
Master.** Everything
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

The cluster keys are a different matter. They sign only the root, which every
member must co-sign, so a single stolen cluster key cannot install a Master on its
own — it is one of the required signatures.

## What is not contracted here

- **Membership changes beyond re-formation.** Adding a fourth node is out of
  scope here and would need its own threshold; a 4-member cluster's unanimity
  requirement is a different protocol, not a parameter.
- **What a vote is worth economically.** Votes are signed and distinct, not
  stake-weighted and not Sybil-resistant. A cluster is two or three known nodes.
- **Transport.** How the vote reaches the other members is implementation.
- **Timing attacks.** Elections use an injected clock and no nonce reuse window is
  specified beyond the election's own nonce.
