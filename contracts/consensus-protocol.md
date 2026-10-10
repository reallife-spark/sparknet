# Consensus protocol — how the cluster agrees on who holds the key

Every node implements this conversation. The state of the implementation is
worth stating precisely, because a reader who takes this page for a description
of working code will be wrong about a security boundary:

| Piece | State |
|---|---|
| Root formation and verification (`shared/sparknet-consensus.py`) | built, unit-tested |
| Key separation (cluster / operational / identity) | built, unit-tested |
| **The election itself** — who votes, and how a result becomes a root | **built** (fabric `PLAN.md` Step 11). `shared/sparknet-election.py` is the exchange: `serve` collects bids, ballots and root co-signatures on port 4210 and holds no private key — every signature is made by a member process holding its own cluster key. `peer-node/scripts/sparknet-election-request.sh` and `master-node/scripts/sparknet-election-approve.sh` run the member ceremony for each role. The listener is code, not a deployment: `contracts/ports.json` records 4210 `implemented` with runtime `not-listening` until a host actually runs it. See **Exchange** below. |
| Re-formation when a member is dropped | **built** (fabric `PLAN.md` Step 21, schema 1.2) — policy B adopted: a chained root with a strict-subset membership, evidenced by a removal proof per dropped member — see below |

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
  master_node_id, master_pubkey,
  previous_root_id, epoch
}
```

co-signed by every member's cluster key, over the canonical bytes.
`previous_root_id` is the id (`root_id`) of the root this one supersedes:
the empty string for a cluster's first root, the held root's id for a
re-formation. It is one of the signed fields, so ordering travels inside the
very thing being ordered; the Re-formation section builds the chain on this.

`epoch` is the signed, clock-free height of the root in its lineage: `0` for a
genesis root, exactly `parent.epoch + 1` for a chained one. It entered the signed
fields in schema **1.2**, and `verify_root` checks it on the trust path, so a root
cannot claim a height it did not earn (a stale root replayed as fresh, or a forged
forward jump). Because a *reduced* root and its parent share a lineage but not a
membership, epoch—not `previous_root_id` alone—is what makes "the same lockstep
again" distinguishable from a genuine next generation.

**The signed-field set is version-aware.** `previous_root_id` entered the signed
fields in schema 1.1 and `epoch` in schema 1.2. A **1.0** root (the schema before
chained supersession) signed the block *without* `previous_root_id`; a **1.1** root
signed it *without* `epoch`. Both are still lawful: each is projected with its own
version's field set, so it keeps verifying against its original bytes and keeps its
id. A 1.1 root chains to a 1.0 parent by naming that parent's 1.0-computed
`root_id` as its `previous_root_id`; a 1.2 root chains to a 1.1 parent by naming
it and taking `epoch = 1` (the older parent is treated as height 0). The upgrade
path is a forward re-formation, not a fresh election, and it does not void the live
pair's existing co-signatures.

Peers accept a root only when:

1. it carries n valid signatures, exactly one per member,
2. from n **distinct** members,
3. each matching the `cluster_pubkey` of a member the root itself names,
4. and the `master_pubkey` is the one the registry is signed under,

and, on the trust path (a peer that already holds a root), additionally:

5. it names the held root as `previous_root_id` — it descends from the root in
   force. A well-signed root with a fresh nonce but no lineage is refused as
   `unchained_root`: supersession is a chain, not a free replacement.
6. its `epoch` is exactly the held root's `epoch + 1` (a 1.2+ root only; a root
   older than 1.2 predates the field and is treated as height 0). A root whose
   epoch is not the held root plus one is refused as `unchained_root`.
7. if its membership is a **strict subset** of the held root's — the reduced case
   — the dropped set is *exactly* the set its **removal proofs** evidence: one
   proof per dropped member, and no proof for a member that stays
   (`missing_removal_proof` / `unexpected_removal_proof`). Each proof is
   independently signed (see Re-formation), so it authenticates itself and is
   carried alongside the root, **not** among the signed fields — the signed root
   stays small and its co-signatures are unaffected by the evidence.

Points 3 and 4 matter more than they look. Without 3, a root could name members
and be signed by strangers. Without 4, a root could bind a master public key
that no authority ever recognised. Without 5, a re-formed cluster could be
replaced by a rival well-signed root that claims no descent, and the ordering
of two roots would depend entirely on where history happens to live. Without 6,
a stale root could be replayed as a fresh generation. Without 7, a colluding
survivor majority could silently vanish an honest node and a pure verifier could
not tell a lawful reduction from a forgery.

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

**The new root is chained, not free.** Every root carries `previous_root_id`,
the id of the root it supersedes, and (from schema 1.2) an `epoch` one above its
parent's. On the trust path — a peer that already holds a root — `verify_root`
refuses any candidate that does not name the held root as `previous_root_id`, or
whose epoch is not the held root's plus one, as `unchained_root`, however well it
is signed. This closes the old gap in which a pure verifier could not order two
different roots: ordering is now signed into the root itself, so it survives
offline and does not depend on where history lives. Membership under the chain may
only replace the master or *shrink* — a chained root that adds a member is the join
ceremony, which is a different contract — and may not fall below the cluster
minimum of two.

**Supersession is still enforced where history lives, as the last line of
defence.** The ledger records the `root_id` each signature was issued under.
`sparknet-signer.check_not_reverted` is monotonic: a root whose
`previous_root_id` names the ledger's root in force is a provably forward step and
is adopted without ceremony; anything else — the same lockstep again, a rollback,
or a stranger root with no lineage — is refused unless
`--accept-requalification` says so deliberately.

**A peer that missed a re-formation verifies the whole line.** It cannot use the
single-hop `verify_root(root, trust=held)` on a multi-generation-old held root;
`verify_chain(roots)`, newest first, walks each link with the same trust
discipline down to a genesis root. The news of a re-formation therefore reaches a
peer as a pull of successive roots, each chained to the one before — not as a
broadcast of the *latest* authority, which a rolled-back Master could suppress.
The pull path is the existing share/registry channel; no new port, no new
capability. *How far an offline peer may fall behind, and how the lineage is
fetched, is the mode of exposure to be specified separately.*

**A reduction must be evidenced.** A chained root whose membership is a strict
subset of its parent's carries one **removal proof** per dropped member,
alongside the root (the proofs are independently signed, so they authenticate
themselves and are not part of the signed root bytes). `verify_root` refuses a
reduced root unless its dropped set — parent membership minus child membership —
is *exactly* the set the proofs evidence: a dropped member with no proof is a
silent eviction (`missing_removal_proof`), and a proof for a member that stays is
a forged drop record (`unexpected_removal_proof`). Each proof names the parent
root it belongs to, and two kinds are accepted:

| Kind | Signed by | Meaning |
|---|---|---|
| `revocation` | the **parent** root's elected Master, with its **operational** key | the contract's existing one-signature revoke, made durable as evidence the chain can check. The operator who may already revoke a node unilaterally hands the survivors the proof of it. |
| `attested` | **every surviving** member, with its **cluster** key | majority-to-reduce (the n−1 survivors consent): a survivor-signed statement that the member is unreachable-and-departed. |

A lone survivor has no cluster to form (below the minimum of two); it holds only
the proof — a tombstone — and must re-witness a new member before a root can exist
again. The floor is not relaxed. This is **option B made concrete**: the threshold
drops to n−1 only to *reduce*, and only when every survivor signs (or the parent
Master revokes), while forming a root over a membership still requires unanimity
among the members of the *new* root. A Byzantine majority cannot silently remove
an honest node: the removal itself is the very thing every survivor signs.

**This is the escape from a blocked election.** If a member is unreachable —
powered off, disk failed, not hostile — the survivors form a new, chained root
with a strict-subset membership, dropping the missing node, each survivor
attesting the drop. The unsatisfiable case ("unanimity among survivors" where the
missing node's signature is required) is resolved by moving the unanimity *down*
to the survivors and proving the drop, rather than needing the absent node.

**Re-formation is not a bypass.** Whatever the threshold, it cannot install a
Master without unanimity among the members of the *new* root, and a node removed
by re-formation cannot re-form its way back in on its own — its cluster key is
not in the reduced root, and its removal is a signed fact in the chain.

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
