# Per-user knowledge vaults (`peer-<user_id>`) — design

Status: **adopted as code; live-verified on the current pair 2026-10-31; extended 2026-11-05.** The peer now gives each approved user a `peer-<user_id>` model based on the OpenCode engine (`sparknet-chat`) with their personal KB and the structure-only KB attached. The Master is admin-only; there is no second user surface. The
peer-side provisioner, vault slice materialiser, KB wiring, re-indexer, tests and
systemd unit are built (`peer-node/services/sparknet-vault-provisioner.py`,
`peer-node/tests/test_vault_provisioner.py`). A disposable account on agx64 was
approved, provisioned with 26 files and a KB, then deleted with its vault, KB,
model and state record; peer `PLAN.md` Step 11 is closed. The retired cluster2
pair remains historical evidence, not current state. This is the
fabric-root sibling of `CLUSTER_INFERENCE_DESIGN.md`: that note designs the
cluster *job*; this one designs what a human user of a node's Open WebUI owns.

## What was asked, in the operator's terms

On each node's Open WebUI (`.131` and `.133` in the cluster2 proof pair):

1. Every user gets a **private copy of the `sparknet/peer-node` knowledge
   vault** on that machine's knowledge disk, named `peer-<user_id>`.
2. The copy is created **after the user's signup request is accepted** by the
   node admin (the role change pending → user), and is connected to that
   user's Open WebUI as a knowledge base they own and grow.
3. A node admin controls that node's users and knowledge bases. The
   Master-node admin has administrative privileges over **all** admins, users
   and knowledge bases on **all** nodes.
4. The Master's Open WebUI admin gets a copy of the `sparknet/master-node`
   vault named `master-<id>` — but **only** on a node that has been elected
   to the Master role **and** whose WebUI admin is signed in there as an
   admin. In the cluster2 pair **`.131` does not get a `master-` copy**:
   users on the Master node are still ordinary users for the knowledge base,
   and an admin on a peer node is a user-plus-node-privileges and still gets
   a `peer-` copy.
5. The templated directories are never modified; a user's copy is a **new
   folder** carrying the naming convention, grown by whatever the user adds.

## The authority model, restated in fabric terms

The fabric already says **authority is key possession, not a capability grant**
and **a role subvault alone is not a deployment**. Both rules shape this
feature:

- A `peer-<user_id>` copy is **knowledge content, not a node**. It is a
  standalone vault: categories, `AGENTS.md`, `docs/`, `schema`, its own `.env`
  resolving `VAULT_PATH` to itself. It does not need `contracts/`, `shared/`
  or a signer — it is the *corpus a user's KB is built from*, not a fabric
  member. A user cannot grant, revoke, sign or escalate anything with it.
- **WebUI `admin` role on a peer node ≠ fabric Master possession.** The node
  admin's authority is over that node's *knowledge surfaces* (users, KBs),
  bounded by what WebUI itself enforces. The only requirement that crosses
  nodes — rule 3's "Master-node admin over all nodes" — runs over the
  fabric's own signed transport (the bridge), never by shared WebUI admin
  credentials.

## The three surfaces

| Surface | Lives on | Created | Controlled by |
|---|---|---|---|
| `peer-<user_id>` vault copy | `/srv/sparknet/knowledge/peer-<user_id>/` on the node whose Open WebUI holds the user | on approval (pending → user) | that user (grows it) + node admin (WebUI KB control) |
| user's KB in Open WebUI | node's own Qdrant server via WebUI | on approval, named `peer-<user_id>` | user (read/use), node admin (admin), Master admin (all nodes, via bridge) |
| `master-<id>` vault copy | `/srv/sparknet/knowledge/master-<id>/` on an **elected-Master** node | only when elected-Master + admin signed in | the Master's admin |

## What a `peer-` copy contains

A **knowledge-vault slice** of the peer-node template — never the machine
plumbing:

- the numbered categories `00_System`–`07_Archives` (empty skeleton, `.gitkeep`)
- the legacy-name shims so the wiki skills and category names resolve
- `AGENTS.md`, `docs/`, `MISSION.md`, the schema and templates the role vault
  carries as *knowledge*
- a freshly generated `.env` with `VAULT_PATH` pointed at the copy itself

Excluded by construction: `.state/` (node keys), `blockchain/` (signed ledger),
`services/`, `scripts/`, `container/`, `configs/`, `tests/`, `manifests/`
(deploy artifacts), `.git/`, and the template's own `.env`. The copy is a
*vault*, and copying a signer into a user folder would smuggle machine identity
into a KB. `make keys-check` on the nodes must stay clean.

The Master's `master-<id>` copy is the same slice taken from
`master-node/` — identical rule, different template.

## The provisioner service

A root-gated, per-node service (systemd unit) that owns
`/srv/sparknet/knowledge/`. It runs the loop:

```
watch users (GET /api/v1/users/, admin token) 
  └─ role transition pending → user (or first-seen already-approved user)
        ├─ materialise /srv/sparknet/knowledge/peer-<user_id>/
        ├─ generate .env (VAULT_PATH -> copy)
        ├─ create KB "peer-<user_id>" (admin; access_grants [user read])
        ├─ embed the vault markup into the KB (files -> knowledge/<id>/file/add)
        ├─ default-attach the KB to the user's own model
        └─ record provisioning state (state file under /srv/sparknet/knowledge/.state/)
  └─ content change on an existing copy
        └─ re-embed changed/added pages (re-index)
```

### Trigger: the approval

The provisioner keys off the user's **role field**, not WebUI events. A
signup arrives as `role: "pending"`; the node admin Accepts it in the WebUI
admin panel; the role flips to `"user"` (or `"admin"`). Polling `GET
/api/v1/users/` and comparing to recorded state is the honest trigger: it
observes the same thing the UI shows, fails toward "not yet provisioned", and
keeps working across WebUI restarts. The `user.role_updated` webhook
(`events.webhooks`) is a hint to wake sooner, never the source of truth.

Every `pending` user stays pending until a node admin acts — the same gate the
operator chose for signup (new users are `pending` until accepted), so no copy
and no KB exists for a account nobody approved.

### The KB is the user's, not the admin's

WebUI 0.12.0 grants are flat dicts
(`principal_type`/`principal_id`/`permission`). The provisioner creates the KB
with the **admin token** (only admins may set grants on resources they do not
own) and grants the user `read`. Result:

- the KB appears in the user's own knowledge list,
- the user can attach it to any chat,
- the node admin (WebUI admin) controls all KBs on that node, and
- the Master admin reaches it cross-node through the bridge admin channel.

### Default-attach

Each user gets a **per-user model** (`models/create`, admin) whose config
carries `meta.knowledge = [<their kb_id>]` and whose `access_grants` name that
user, so only they see it. Their Open WebUI starts with a chat model that is
*their* model, attached to *their* KB by default — "customized to the knowledge
they add" without them having to re-pick a KB each session. The base generator
model is the node's default; `MASTERSPIKE` stays a Master-surface model and is
not duplicated per user.

### Re-index

The provisioner records a content digest per copy. When the digest changes
(pages added/edited by the user), the changed files are re-embedded into the
KB (`files/` upload → `knowledge/<id>/file/add`, or `knowledge/<id>/reindex`
for a full resync). This is what makes the connection "customized to the
knowledge they add": what the user writes into their vault becomes the KB's
content.

## The bridge admin channel (Master over all nodes)

Rule 3's cross-node half runs on the **fabric's signed transport**, not shared
WebUI passwords:

- each node's `sparknet-dispatch-bridge` gains an **admin route** on its
  loopback surface, reachable only with a **signed operation** whose signature
  verifies against the fabric registry (guard-protocol order),
- the Master's admin signs those operations with the Master identity key, so a
  peer verifies *who* asked before any WebUI admin call is proxied,
- the bridge then proxies to *that node's own* WebUI admin API with that
  node's admin token — the token never leaves the node,
- permission is bounded by a **new capability** (e.g. `webui-admin` /
  `admin-supervise`) granted in the registry to the Master; a peer without it
  refuses before any WebUI call.

Because it needs a new capability, this half is **cross-role atomic work**:
`contracts/capabilities.json` + `shared/sparknet-authz.py` `KNOWN_CAPABILITIES`
+ the guards' verification paths, in one commit with `make contract-test`.
Until that capability is granted in the real registry, the route exists but
authorises nothing — same inert posture as `cluster-dispatch`.

## Design-in vs design-out (what NOT to copy, and why)

| Item | Kept out of copies | Why |
|---|---|---|
| `.state/`, `blockchain/` | yes | machine identity + signed ledger; a KB must not hold a user's keys |
| `services/`, `scripts/`, `container/`, `configs/`, `tests/`, `manifests/` | yes | node plumbing; the vault slice is the corpus, not the deployment |
| `contracts/`, `shared/` | yes | not needed by a vault, and a bare copy must fail validation rather than half-work |
| template `.env` | regenerated | absolute paths must point at the copy, not the template |

## Where this lands (proposed commits)

1. **Provisioner + KB wiring** (peer-side, mostly peer-plan scope): the vault
   materialiser, the KB create/embed/default-attach, the approval watcher, the
   re-indexer; state file; tests. `master-` rule encoded (inactive on `.131`).
2. **Bridge admin channel** (cross-role): new capability in both vocabulary
   homes, signed-operation verification on the bridge admin route, proxy to
   the local WebUI admin API, refusal tests.
3. **Live deploy** on the retired `.131`/`.133` pair: unit installed, a real
   signup + Accept cycle provisioned a real `peer-<id>` vault + KB (20 pages
   after two slow-embed timeouts); gates green. This is **historical proof**,
   not the current pair.

Slices 1 and 2 are separable commits; slice 3's current-pair equivalent remains
`DoD: confirm: user`. A `master-` copy is exercised only if/when a node is
genuinely elected Master with its admin signed in — not in the current pair.