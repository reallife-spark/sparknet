# sparknet — Session Memory

> Standing state only. Read at session start; **replace, never append**.
> The plan and its cursor live in `PLAN.md` — this file mirrors it, it does not
> own it. Per-session detail belongs in `sessions/YYYY-MM-DD.md`.

Updated: 2026-10-10

## Standing State

- **Plan cursor**: root `PLAN.md` **`current: done`** (plan terminal, all steps
  1–27 `[x]`). Step 22 (KDE Connect notifications) closed 2026-10-10: both
  devices (raxxarMobile + Galaxy Tab A 2016) paired and pinged live rc=0 via the
  plugin's exact discovery+notify path.
  **Step 21 (F2 reduced-membership re-formation + F3 live cross-node root sync)
  closed 2026-10-10** as **option B full** (schema 1.2: signed `epoch`, removal
  proofs, exact-removal trust path; F3 delivered to a real peer `accept`
  subprocess; mutation-proven; docs reconciled) — only live deploy is
  `DoD: confirm: user`. **Steps 23–25 closed 2026-10-10**: Step 23 (node131/133
  proof pair) on the operator's direction to treat the host-visible checks as
  passed (not independently re-verified); Steps 24 (`compute-serve` design) and
  25 (cluster-inference design + reserved vocabulary) as their documentary DoD,
  verified (`compute-serve` still absent; `cluster-dispatch`/`cluster-serve`
  reserved in both places). New roadmap work gets a **new** step; this plan is
  not reused. Step 14 (claims + `--help`)
  closed 2026-10-08. **Hardening batch (2026-10-09) CLOSED as code and
  DEPLOYED**: Step 15 `f1b790c` (timeouts + guard fixes), Step 20 `bc518d6`
  (signer per-client read timeout + serialised key use, mutation-proven),
  Step 16 `b0126ce` (consensus chained supersession, policy B), Step 17
  `MCP_A2A_DESIGN.md` (fabric root, design-proposal status — MCP/A2A two
  layers, unchanged until adopted in its own commit). `49b715a` adds the
  version-aware 1.0/1.1 root canonical form (deploy precondition — else the
  live 1.0 root fails the signer's startup `verify_root`);   `7fa03b9` fixes the
  signer read deadline on Python 3.9 (see the live-signer bullet). **Step 21
  CLOSED 2026-10-10**: F2 reduced-membership re-formation + F3 live cross-node root
  sync — the two Step 16 halves that stayed spec-only — are now built as **option
  B full** (schema 1.2, signed `epoch`, removal proofs, exact-removal trust path),
  mutation-proven and doc-reconciled; only live deploy is `DoD: confirm: user`. R2 + R5 deferred by decision
  (one line in `log.md`). **Pushed** this session: `main` at `4e276df` on
  `origin/main` (`d901c8f..4e276df`), after the remote was corrected — it had
  drifted to `reallife-spark/SparkNet-Node`, renamed back to
  `reallife-spark/sparknet` by operator decision. `gh` lives at
  `~/.local/bin/gh` (authenticated); it is only missing from a non-interactive
  `PATH`.
- **A second, independent pair exists as a proof clone (2026-10-09, fabric
  PLAN Step 23; closed 2026-10-10 on operator direction — see the cursor
  bullet).** `node131` (.131) + `node133` (.133)
  were built from the dirty-worktree master bundle into `~/sparknet-cluster2`
  with an isolated state dir `~/.local/state/sparknet/cluster2`, on overlay
  `wg1` (userspace `wireguard-go`, `10.100.0.1/32`↔`10.100.0.2/32`, 51820).
  The 2/2 election formed root_id `29fbb13e…f676` (node131 Master, node133
  `not_elected`); a **distinct** unit `sparknet-master-signer-c2.service` runs
  on .131 (root-id match, caps `["sign"]`, restart-surviving) while the live
  agx64 signer and `/root/…/trust-root.json` are untouched. The isolated signer
  signed a registry entry for peer node133 (verified by root alone); three
  escalation refusals hold; node133 reaches the master over `wg1` with caps
  `[telemetry,p2p-sync,push-receive]` and no private Master key. Phase 9
  (destructive) left unexecuted. **Isolation caveat**: both clusters use
  `10.100.0.0/24`, so `wg1` must not run concurrently with the live cluster's
  `wg0` (and `/root/scripts/sparknet-wg-restore.sh` must not run while `wg1` is
  up). Lesson: the signer pins its socket to `SPARKNET_STATE_DIR` via
  `_default_state_dir()` — a second signer needs that env set explicitly.
  Transcript `/mnt/log/sparknet-cluster2-2026-10-09.md`. Not a promotion; no
  live state repointed. **Operator asked to confirm the host-visible checklist
  2026-10-10, could not confirm directly, then directed 2026-10-10 to treat the
  step as passed; Step 23 was closed on that direction (checks not
  independently re-verified).**
- **Signed delegated compute is spec'd, not built (fabric PLAN Step 24, design
  proposal 2026-10-09).** `COMPUTE_CAPABILITY_DESIGN.md` at the fabric root
  proposes a `compute-serve` capability (the second `sensitive: true` after
  `guard-apply`) so a peer can execute a **Master-signed** compute task over the
  overlay and return a node-attested result. The load-bearing honesty: a peer is
  already authoritative for its own compute, so local compute is **not** gated —
  only *delegated* work is. It binds nothing: no capability, port, contract or
  role changed. Adoption would need a two-place vocabulary edit
  (`contracts/capabilities.json` + the hard-coded `KNOWN_CAPABILITIES` in
  `shared/sparknet-authz.py`) plus a typed signer op `sign-compute-task`. Still
  **not adopted** — `compute-serve` is **not** in the vocabulary.
- **Cluster inference is spec'd; the two names reserved; the `sign-cluster-job`
  signer op built; and the node's own AI stack declared as committed config
  (fabric PLAN Steps 25–27, 2026-10-09/10).** `CLUSTER_INFERENCE_DESIGN.md`
  at the fabric root specs the `sparknet-cluster` prompt: per-node Ollama + Open WebUI
  (Master included), a prompt sent to a chosen node or fanned out to the cluster, local
  vault for own prompts vs the Master's shared vector DB for cluster jobs, and jobs
  recorded in the initiator's + Master's + participants' sessions. **Adopted:** (a) the
  two capability names — `cluster-dispatch` (initiate, not sensitive) and `cluster-serve`
  (accept a subtask, **sensitive: true**, second after `guard-apply`, confidentiality
  direction) — added to `contracts/capabilities.json` and the hard-coded
  `KNOWN_CAPABILITIES` in `shared/sparknet-authz.py`; the closed vocabulary is now
  `telemetry, p2p-sync, push-receive, guard-apply, cluster-vote, cluster-dispatch,
  cluster-serve`; (b) the typed `sign-cluster-job` signer op (Step 26) over the
  **one** canonical job projection in `shared/sparknet-authz.py`
  (`CLUSTER_JOB_MODES`/`CLUSTER_JOB_FIELDS`/`cluster_job_message()`/`is_expired()`),
  so the signer and the future verifier cannot drift the way `sign-guard-approval`
  and the guard did — the op has **no caller yet** and grants nothing; and (c) the
  node's **own AI stack** as committed config (Step 27 / peer PLAN Step 9, slice A of
  adoption item 3, peer-side): `peer-node/configs/ai-stack/docker-compose.yml`
  (exactly `ollama` :11434 + `open-webui` :8080 → `http://ollama:11434`,
  `RAG_INGESTION_ENABLED=false`, both `127.0.0.1`-only, no GPU declared),
  `peer-node/manifests/ai-stack.json` (loopback-only, own-server-only, no
  key/signer/state-dir mount, `sign`/`cluster-dispatch`/`cluster-serve` explicitly
  not granted), `peer-node/tests/test_node_ai_stack.py` (11 wiring tests, PyYAML
  + docker-compose-config), `make ai-stack-config`. **Declared, not deployed** —
  no image pulled, nothing binds 11434/8080; running healthcheck
  `DoD: confirm: user`. Still
  **proposed, not adopted**: envelopes, the four modes (decompose/shard/best_of_n/
  mixture), the reduce/contribution-map, the mode-dependent authority (Master ratifies
  at n≥3, direct signed initiator at n=2), the `4223` top-K index (served, not
  replicated), the Open WebUI `local`/`node/<id>`/`cluster` interface, task ingress and
  the inference-auto-executes/actions-guarded boundary — each lands in its own
  commit; live deploy is `DoD: confirm: user`.
- **The deployable node container exists and is built (peer PLAN Step 2,
  complete 2026-10-10).** `peer-node/container/` + `configs/container/`: a
  multi-arch **CPU** opencode image (pinned `1.18.35` per TARGETARCH, no CUDA,
  the node bundle at `/srv/sparknet`, `.env` regenerated at boot — nothing
  path-baked) and a long-lived **anchor** sidecar (wireguard-go userspace, built
  from source off the official GitHub mirror pinned `0.0.20230223`/`21636207`
  — the vanity `golang.zx2c4.com` module domain 404s; inert mode without a
  rendered config). The app joins the anchor's netns
  (`network_mode: service:anchor`), `.state` is a host bind mount never a named
  volume, the healthcheck is GPU-agnostic, and `make container-preflight`
  proves `chattr +i` before anything relies on it. Make: `container-build`
  (`make dist` → staged bundle → buildx `linux/arm64,linux/amd64`,
  registry-ready) and `container-load` (host arch `--load`). Proven **on this
  build host**: amd64+arm64 cross-build (amd64 opencode ran under qemu →
  `1.18.35`), the compose stack came up with `sparknet-node` **healthy, no
  GPU**, anchor inert, bundle-verify green, peer 236 passed (new
  `test_node_container.py` wiring suite + the fabric `--help` contract). **Not
  claimed** (peer charter): a live WireGuard tunnel, deployed-node `chattr +i`,
  and the target-host healthcheck — all `DoD: confirm: user`. Cursor 2→3
  (signed grants next), then 3→4.
- **Signed session grants exist and are enforced on disk (peer PLAN Step 3,
  complete 2026-10-10) — the conversation-hash heuristic is gone, not built.**
  Every vault write is now authorised by one signed grant (two-tier trust: the
  Master-signed registry is the permanent ceiling, the signed grant is the
  conversation). `shared/sparknet-authz.py`: `grant_message`/`mint_grant`/
  `verify_grant` + `grant-mint`/`grant-verify` CLI, offline via `--master-key`
  with no Master running; the verification order restates
  `contracts/identity-schema.json grant.verification_order` = guard-protocol
  order unchanged (signature → registry fingerprint/revoked/entry-sig →
  capability subset → expiry+skew → nonce → presenter), all fail-closed, and
  provenance performs **no** cryptography of its own. The contract now carries
  the whole rule set: peer event vocabulary gained `grant_use`, the tracking
  block gained the optional `grant` field, provenance-protocol.md gained a
  "Signed session grants" section. `shared/sparknet-provenance.py`:
  `_dual_sign` (one dual-control signing path for every peer-written block),
  `build_grant_use_data`, `consumed_grant_nonces` (the ledger is the nonce
  retention store; a replayed grant dies at the nonce check),
  `grant_scope_allows` (containment = prefix-of-**path-parts**, so
  `05_Knowledge/con` never covers `05_Knowledge/configs`; empty scope allows
  nothing; `..` refused), `write_granted_note`, and a `grant-write` CLI.
  In-scope writes land with `tracking.grant` frontmatter + a signed note + a
  dual-signed hash-chained `grant_use` ledger block (`decision: granted`);
  out-of-scope writes are **quarantined** under `_raw/grant-quarantine/<grant_id>/`
  with the same accounting (`decision: quarantined`), so nothing is lost and
  authority is never widened. `tests/test_grants.py` (29 tests) covers every
  refusal plus DoD 5: a subagent's write is attributed in the ledger to the
  **acting child session** while authority traces to the parent grant — audit
  is finer than authority. Gates 2026-10-10: peer 265 passed/1 skipped, fabric
  687/3 skipped, contract-test, validate, ruff change-set clean, and
  `make bundle-verify ROLE=peer` green. Does **not** yet enforce over HTTP —
  Step 4 does (the bridge: grant-checked `/vault/*` endpoints, persistent
  grant-keyed sessions, no conversation identity derived from content hashing).
  **Not claimed**: live two-tier enforcement on a real node. Cursor 3→4.
- **The bridge is now a real server — grant-checked `/vault/*` tools,
  persistent grant-keyed sessions, one OpenAPI surface (peer PLAN Step 4,
  complete 2026-10-10).** `peer-node/services/sparknet-dispatch-bridge.py`
  listens loopback-only on 4096 with two personalities on one port: the
  **signed** envelope surface (`/v1/status` unchanged — fabric transport test
  green) and the **plain** Open WebUI surface (`/v1/models`, `/v1/chat/
  completions`, `/session/<grant_id>/message`, `/vault/list|cat|capture|
  promote|patch`) whose routes require `Authorization: Bearer <base64url signed
  grant>` verified in guard-protocol order (one stable refusal vocabulary:
  missing-grant/grant-refused/out-of-scope/bad-path). `/v1/models` lists agents
  declared on disk (`.opencode/agents/*.md` ∪ `agents/*/` pods — never
  fabricated models). Sessions: `$SPARKNET_STATE_DIR/sessions/<grant_id>.json`
  (0600, schema `sparknet-session/1`), grant-keyed, plain content turns — **no
  content-hash identity** — and restart survival is itself a test. Shared
  provenance grew `_verified_grant` (one fail-closed ladder for capture/promote/
  patch), `_target_within_scope`, `promote_granted_note` (pending raw/staged
  drafts only — a stranger's signed note moves for nobody) and
  `patch_granted_note` (exactly-once body replace → re-sign → stays `valid`);
  every mutation appends a dual-signed `grant_use` block. The bridge names **no
  ledger path** — the `test_services.py` invariant is now "cannot write what it
  cannot name" (`"blockchain" not in source`; the old `json.dump` check was
  dropped because Step 4 obliges session persistence). `manifests/vault-openapi.json`
  (6 operations, BearerAuth) is how Open WebUI consumes the vault tools as HTTP
  tools — no client-executed MCP bridge, no Node runtime (Step 4 DoD 5). Gates:
  peer 284 passed/1 skipped, fabric 687/3 skip, contract-test, validate, ruff
  lint on the change set, `make -C peer-node precommit` green (daily journal now
  signature-enveloped), bundle-verify ROLE=peer rc=0. **Not claimed**: the live
  Open WebUI handshake and routing `/v1/chat/completions` into a running agent
  are Steps 5–6; the bridge records and routes turns and never impersonates an
  assistant. Cursor 4→5 (Step 5 — Open WebUI surface).
- **The Open WebUI surface exists as committed config, with the bridge's
  Approve/Deny path in server code (peer PLAN Step 5, complete 2026-10-10).**
  `manifests/agent-models.json` (schema `sparknet-agent-models/1`) declares
  **plan/build/vault/node-orchestrator selectable as models**, each bound to
  the agent that owns it (`node-orchestrator` → `sparknet-node`); the bridge
  serves declared-first, discovered pods after, no manifest → no declared
  surface (fail-closed). **Permission requests resolve through the bridge**:
  `POST /session/<grant>/permissions` raises (perm-N, pending) and
  `POST /session/<grant>/permissions/<id>` decides allow/deny — grant-checked,
  session-scoped, persisted in the grant-keyed session, restart-surviving;
  refusals stable (404 no-session/unknown-permission, 409 already-resolved,
  400 malformed). The ai-stack compose declares the whole surface:
  `OPENAI_API_BASE_URLS: http://host.docker.internal:4096/v1`
  (`extra_hosts host.docker.internal:host-gateway`), `MODEL_FILTER_ENABLED/LIST`,
  `DEFAULT_MODELS`, RAG still off, and **`OPENAI_API_KEYS` expands a
  deploy-time `${SPARKNET_WEBUI_BRIDGE_GRANT:?...}` — no token committed, compose
  fails loudly while unset**; `manifests/ai-stack.json` gained `webui_surface`
  claims. Tests: `test_webui_surface.py` (11) + ai-stack surface assertions;
  peer 298 passed/1 skipped, fabric 687/3 skip, contract-test, validate, ruff
  lint, bundle-verify rc=0, precommit green. **Not claimed**: the **live** Open
  WebUI handshake (webui container → surface → card → resolve past the bridge's
  loopback gate) is `DoD: confirm: user`; routing a conversation into a running
  agent is Step 6. Cursor 5→6.
- **Conversations pass between the node's own agents (peer PLAN Step 6,
  complete 2026-10-10).** Native verbs only, on the grant-owned
  `/session/:id` surface: `message` accepts `agent` (hand-off keeps the
  session and its history, each turn tagged with the agent that handled it),
  `fork` at a message writes a sibling `sessions/<id>-f<n>.json` carrying the
  shared prefix (the original stays whole; pending permission cards don't
  branch), `children` lists the branch, and the `share` verbs declare
  `session-view`/`session-handoff` in `open` (kb-*/full are 400 → Step 8 owns
  the clocked cross-node regime). The ownership gate is now load-then-check
  `owner_grant_id` (404 no-session / 403 not-your-session) instead of
  `parts[0]==grant_id`, so fork siblings are reachable by the same grant only;
  initial session keeps id==owner==grant, so prior session tests pass
  unchanged. SESSION_SCHEMA `sparknet-session/2`; `do_DELETE` added; new
  `conversation_passing` claims in `manifests/ai-stack.json`. DoD 4 ran
  against a real `ThreadingHTTPServer` (`test_conversation_passing.py`, 13
  tests); peer 311 passed/1 skipped, all gates green. **Not claimed**:
  executing a turn inside a live plan/build/vault process (routing ≠ running)
  and Step 8's sharing regime. Cursor 6→7 (Step 7 — MASTERSPIKE).
- **MASTERSPIKE is a format carrier, never a signer (peer PLAN Step 7, complete
  2026-10-10).** One source, two backends: `peer-node/scripts/sparknet-masterspike.py`
  generates `manifests/masterspike/Modelfile` (base `llama3.2`,
  `temperature 0.1`, llm-wiki format body in `SYSTEM """`) and
  `vllm-system-prompt.md` (byte-identical body) from `.opencode/skills/llm-wiki/SKILL.md`,
  each with `source-sha256` provenance headers. `make model-generate` /
  `model-verify` (fails on divergence/moved/removed source) / `model-build` /
  `model-serve`. `masterspike` is selectable in `agent-models.json` and the webui
  `MODEL_FILTER_LIST`; `manifests/masterspike.json` declares `signing_boundary`
  (`capability: null`, `sign` explicitly not granted — authority is Ed25519 in
  the Master, never a prompt). Fabric `tests/test_layout.py` gained
  `EXCLUDED_GENERATED` for the verbatim-copy artifact. `test_masterspike.py` (10
  tests); peer 322 passed/1 skipped, all gates green, bundle-verify rc=0.
  **Not claimed**: the model is declared, not built — this host's `ollama` has
  no daemon; pull + `ollama create` + serve + live selection are
  `DoD: confirm: user`. Cursor 7→8 (Step 8 — inter-node sharing and the
  governance regime).
- **Roots are now a signed, epoch-chained lineage, and a reduced root must carry
  its removal evidence (policy B, schema 1.2, Step 21).**
  `previous_root_id` is in `ROOT_SIGNED_FIELDS` (genesis = `""`); a signed
  `epoch` (genesis 0, chained = parent+1) distinguishes a genuine next
  generation from a lockstep re-issue, and the signed-field set is
  version-aware so 1.0/1.1/1.2 roots each keep verifying against their original
  bytes and ids (a live 1.1 root is epoch 0 and can parent the first 1.2
  re-formation). `verify_root`'s trust path refuses an unchained root
  (`unchained_root`), chained growth, a wrong epoch, a drop below
  `MIN_CLUSTER_SIZE`, and — the new discipline — a strict-subset child whose
  dropped set (parent − child) is not exactly the set its carried,
  independently-signed **removal proofs** evidence
  (`missing_removal_proof`/`unexpected_removal_proof`/`bad_removal_proof`); a
  survivor-unanimous reduced root names exactly the survivors and is signed by
  every survivor and none else. `verify_chain(roots)` verifies a pulled lineage
  newest-first; the signer's `check_not_reverted` is monotonic — a chained
  descendant is adopted without a flag, a stranger/rollback needs
  `--accept-requalification`. Live pair facts below are unchanged in kind; a
  re-formed root must chain to the held `65d9ce25…` root.
- **The live signer on agx64 runs the hardened transport as of 2026-10-09.**
  Steps 15/16/20 plus the version-aware compat (`49b715a`) and the py3.9
  read-deadline fix (`7fa03b9`) are deployed to both agx64 (Master, unit
  restarted, root-id `65d9ce…` unchanged, capabilities `["sign"]`, ledger
  intact) and agx32 (peer shared code; its own Python 3.9.5 verifies the same
  root). Live-proven: a silent client gets `{"ok":false,"error":"timeout"}` at
  the deadline while a second client is served in parallel. **The py3.9 defect
  is the lesson**: on the hosts' Python 3.9.5 `socket.timeout` is *not*
  `TimeoutError`, so Step 20's `except TimeoutError` killed the serving thread
  and closed with a bare EOF — the local test venv (3.14) could not reproduce
  it; always preflight on the **target** interpreter. Backups:
  `/root/sparknet-deploy-backup-20261009-0736/` (agx64),
  `~/sparknet-node/.deploy-backup-20261009-0736/` (agx32). **Step 12 (local
  three-node rehearsal) complete** — the whole arc runs live on three real node trees under
  `/tmp/opencode/rehearsal` (51 checks/0 failures, dated transcript, repeatable);
  `scripts/sparknet-rehearsal.sh` is the reproducible harness, and the rehearsal
  also exposed two real signer CLI str/Path defects now fixed with regression
  tests. **Step 13 (agx64/agx32 handoff) COMPLETE 2026-10-07** — the handoff
  document `contracts/deployment-runbook.md` is written and every confirm-user
  item was answered live on the real pair. **The election FORMED on the real
  pair (2026-10-07)** — both hosts co-signed a root naming agx64
  (2/2, root_id `65d9ce25cbb40566b6735b0624d9840dc69ff35d66b3a97543fe650ed09212f5`);
  agx64 master-identity flipped to master, agx32 stayed peer. Transport
  deviation: **UDP did not cross the 192.168.10/20 subnet boundary at this
  machine (the gateway)**, so the ceremony ran over SSH loopback tunnels
  (trustless relay; keys stayed on hosts; 4210 loopback-only). **Transport
  solved thereafter (Gateway Decision)** — the gateway has no kernel firewall
  tooling and no root here, so a **userspace UDP relay** (`/tmp/gateway_udp_relay.py`,
  binds 192.168.10.1:51820 + 192.168.20.1:51820, forwards between the hosts;
  no root needed) stands in for opening UDP 51820, and wg peers re-point at the
  gateway IPs. The overlay now **handshakes and pings on real NICs** (0% loss
  ~2 ms; peer /32 kernel routes had to be added — AllowedIPs create none).
  **Phase 6–8 are live**: master role root staged at `/root` (signer unit's `%h`),
  state dir + keys moved to `/root/.local/state/sparknet/master-node`,
  trust-root.json extracted, `/root/.env` sets SPARKNET_NODE_ID/STATE_DIR and a
  PATH preferring the 3.9.5+crypto50 venv over the host's unusable 3.8.10+
  crypto2.8 system python; signer runs via `sparknet-master-signer.service`
  (socket 0600, root-id `65d9ce…`, capabilities `["sign"]`, restart survives,
  single key-holder). Registry: signed entry for agx32 (verified by the root
  alone) + `manifests/node-authorizations.json`; three escalation refusals hold
  live; agx32 verified the distributed entry with its own authz and matched its
  fingerprint. No *share* claimed (4201–4203 spec-only). **C4 revoke-demo live
  (2026-10-07, pair restored after)** — surfaced + fixed two artifact defects:
  agx32's `manifests/keys/master-ed25519.pub.b64` was a placeholder key (would
  fail every signature check) and both hosts' `node-authorizations.json` were
  bare entries while the guard needs the wrapped `authorizations:[…]` registry.
  After fixes: one socket signature `revoked: true` (ledger block 64717431…)
  ⇒ peer `reason: revoked caps: []`, guard `capabilities: []`, a
  signature-VALID master packet refused `403 capability_missing`, and
  `wg-render-master` dropped the stanza; fresh `revoked: false` signature
  (b3200847…) restored the pair. **C2 reboot proven**: ran a real reboot on
  agx64; signer unit came back active (enabled), socket root-id == `65d9ce25…`,
  capabilities `["sign"]`, ledger intact, peer auth still verifies after reboot.
  **New ops caveat**: wg0 does NOT survive reboot on this tegra host
  (`CONFIG_WIREGUARD=n`; overlay is userspace `wireguard-go`, started ad hoc) —
  restore via `/root/scripts/sparknet-wg-restore.sh` (proven, idempotent); a
  wg0 unit or restore-inclusive "up" check is a Phase 9/ops item. Also noted:
  signer `_serve_one` single-threaded, no client timeout. **C1/C3/C5 answered
  with live probes**: overlay rides real NICs to the gateway relay (routes
  `dev wg0`, endpoints `dev eth0`, handshakes seconds old, ping ~2 ms 0% loss
  both ways; userspace wireguard-go since tegra `CONFIG_WIREGUARD=n`); exactly
  one process holds `operational.ed25519` (signer PID 5063, no other fd holder,
  key 0600); deployed signer containment confirmed (socket `srw-------` 0600
  unix-stream by the signer, no TCP listener, `--describe` caps `["sign"]`,
  `check_socket_path` refuses `tcp://` and outside-state paths, no peer service
  imports the signer, parity asserts `not_reachable_from_here`). **All six
  confirm-user items answered; operator acknowledged 2026-10-07 and closed
  Phase 9 by decision ("Close without exercising")** — the destructive
  rollback / replace-Master legs in `contracts/deployment-runbook.md` §Phase 9
  stay documented-but-unexecuted, so the live pair is left up. `PLAN.md` Steps
  1–13 closed 2026-10-07; Step 14 opened 2026-10-08.
  `peer-node/PLAN.md` `current: 8` (Steps 4–7 — bridge server, Open WebUI
  surface, intra-node conversation passing and MASTERSPIKE — complete
  2026-10-10; Step 8 — inter-node sharing and the governance regime — next);
  `master-node` `current: 2` — Phase 0 (13–18: consensus, parity, isolated signer,
  admin surface), honest verification (19), the **keypair/registry substrate (1)**
  and, as measured on 2026-10-06, **Steps 3 and 4** are complete; **Steps 2 and
  5–12 are unbuilt** and the cursor points at the first of them (Step 2, whose DoD
  is contradicted, not merely unimplemented). The peer build-out is `peer-node`
  Steps 2–8: container, grants, bridge, Open WebUI, conversation passing,
  `MASTERSPIKE`, sharing regime.
- **Both role vaults now store content in `00_System`–`07_Archives`.** Legacy
  category names in `peer-node/` and `master-node/` are symlinks (shims), so the
  wiki skills and old instructions still resolve; `make shims-check` proves no
  shim has become a real dir.
- **Both role vaults are now signed.** `peer-node` owner `U-27689`, key at
  `.state/keys/user.ed25519` (0600), never committed (`keys-check` proves it).
  `master-node` owner `U-97443`, key outside the vault under
  `$SPARKNET_STATE_DIR` (per the master's outside-vault key rule). Notes carry a
  signed tracking envelope; each `make -C <role> provenance-verify` exits 0.
  New intake lands unsigned pending notes via `make -C <role> ingest SRC=…`;
  email fails closed against `authorised_senders` in `user.md`. The
  containerised vault-curator remains a peer PLAN Step 5 placeholder — transport
  is specified, not built.
- **The Master administers the fabric's git, file share, NAT and vector
  embeddings DB — as a role responsibility, not an existence claim.** Ports
  `4220`–`4223` in `contracts/ports.json` are `spec-only`, `bound_by: master`,
  `overlay_only`, bound to `10.100.0.1`; scoped in
  `master-node/plans/MASTER_ADMIN_PLAN.md`. No daemon, no code, no adjacency to
  the signer (same structural rule as the admin surface).
- **`$SPARKNET_STATE_DIR` resolves outside the vault.** `$XDG_STATE_HOME/
  sparknet/master-node`, else `~/.local/state/...`. Not gitignored-inside — out.
  The admin surface bind-mounts the vault read-only into an LLM container, so a
  key under it is readable from there; `.gitignore` was never the relevant
  defence and `make keys-check` fails if the variable is pointed back inwards.
  The peer keeps `<vault>/.state` on purpose: nothing mounts that vault.
- **Vault**: three, not one. Fabric root plus `peer-node/` and `master-node/`,
  each with its own `.env`, category skeleton and `AGENTS.md`. A session resolves
  which one it is in before writing anything — see the Memory Protocol note below.
- **Config**: `.env` per vault (`VAULT_PATH`, gitignored, regenerated by
  `make env-init`); staged writes: false.
- **Blockers**: none blocking. The admin page is declared but not bound (nothing
  listens on `10.100.0.1:8080`; `DoD: confirm: user`, master Step 18) and the
  overlay doesn't survive reboot on the tegra host (`CONFIG_WIREGUARD=n`;
  userspace `wireguard-go`) — restore via
  `/root/scripts/sparknet-wg-restore.sh`. The signer's client timeout /
  non-blocking accept (master build plan Step 20) is now built and deployed
  (2026-10-09, with the py3.9 read-deadline fix). Phase 9's destructive legs
  (rollback / replace-Master re-formation) are documented in
  `contracts/deployment-runbook.md` and deliberately not executed.
  **Outstanding, unclaimed:** rotating
  and revoking the old broad OAuth token from the split-day leak.
- **Local gates prove the tree; the pair proves the fabric.** Everything
  `make test-all` / `lint` / `bundle-verify` check is fully verifiable on this
  host. Claims about the live pair (agx64/agx32) were verified from those hosts
  themselves per the runbook; anything further needing a second node or the
  Master carries `DoD: confirm: user` rather than a local pass. This host has
  no GPU (`nvidia-smi`) and does not run the overlay itself.

## Key Standing Facts

- **This is a fabric, not a node.** Two roles, one contract. Most confusion comes
  from reading a page that belongs to one role as though it described both.
- **A role subvault alone is not a deployment.** A peer cannot verify a signature
  without `contracts/` and `shared/`, so a bare copy fails validation by design.
  `make bundle` assembles a real deployment; `make bundle-verify` proves it.
- **Authority is key possession, not a capability grant.** A peer with the whole
  capability vocabulary but no private key can never grant, revoke or escalate.
- **The Master role's Phase 0 and its own boundary work are built — and the
  election/signer arc is now proven live** (build plan Step 14; Steps 13–19 done;
  fabric PLAN Step 13 complete 2026-10-07). It has `scripts/`,
  `services/`, `systemd/`, `manifests/`, `blockchain/` and
  `security/`, and runs the peer's
  services **by path** — `make -C master-node parity` proves the resolution and
  the bundle check proves it landed inside the extracted bundle.
  `services/sparknet-signer.py` is the only process holding the operational key:
  unix socket, mode 0600, typed payloads, never signs caller-supplied bytes, and
  refuses to start against a root superseded in its own ledger. Unit-tested with
  36 tests and 12 mutations; **deployed and proven in production on agx64
  (2026-10-07)** — ran as `sparknet-master-signer.service`, formed the 2/2 trust
  root with agx32, signed a live registry entry, survived a real reboot, refused
  non-Master keys/unnamed nodes/tampered roots, and drove a live
  revoke→peer-inert→re-authorize cycle; its unit stays excluded from `make units`
  by design (enabling a key-holder is the election's decision). **Re-deployed
  2026-10-09** with Steps 15/16/20, the version-aware root compat and the py3.9
  read-deadline fix. The remaining
  honestly-unclaimed item is the admin page: declared, not bound (Step 18 DoD).
- **Claim defects the 2026-10-06 audit found (all recorded where they were found,
  not fixed silently).** (a) `master-node`'s Steps 1–12 all had `[x]` boxes
  against `Status: pending` lines — the boxes were bulk-flipped in one commit and
  the statuses never written; the plan now carries measured statuses per step.
  (b) `make keys-check` failed on a clean tree because the test corpus pasted the
  PEM literal the scanner searches for — the marker is assembled at runtime now.
  (c) `master-node/manifests/registry.schema.json` validates nothing: it demands
  `role`/`1.0.0`/`signature` where the shipped peer registry has no `role`,
  `schema_version: "1.0"` (pinned by a peer test) and the signer emits
  `signature_b64`. Two roles, two shapes, neither matching the schema — the
  canonical shape is an open contract decision (master build plan Step 2).
  (d) Steps 7–10 of the master plan were "verified" by tests that read the
  scaffold's source text instead of binding anything; 7–8 lines each.

- **The wiki suite is vendored** at `.opencode/skills/` (33 skills: 32 vendored +
  1 local, MIT). No global skill farm dependency. `make wiki-sync` re-vendors,
  `make wiki-verify` proves no drift.
- **Skills resolve the nearest `.env`.** That is what keeps a role subvault
  honest. Run `make wiki-preflight` first and never work around a failure: the
  skills would silently write into the wrong vault.
- **Cross-role changes are atomic.** Edit `contracts/` and both roles in the same
  commit, then `make contract-test`. `tests/test_contracts.py` exists to fail
  when one role's copy of the contract drifts.
- **The shipped registry is empty on purpose.** No node has privileges until the
  Master signs something. That is the fail-closed default, not an oversight.
- **`gh` lives at `~/.local/bin/gh` (authenticated as `reallife-spark`), but a
  non-interactive shell's `PATH` omits `~/.local/bin`**, so the repo-local helper
  `!gh auth git-credential` silently fails to resolve it and git looks
  unauthenticated. Push with `PATH="$HOME/.local/bin:$PATH" git push origin main`.
  The fabric's remote is **`reallife-spark/sparknet`** (private); a remote that
  drifted to `SparkNet-Node` is wrong.
- **`make bundle-verify` only verifies the newest archive.** Rebuild first
  (`make bundle ROLE=…`) or it will cheerfully re-prove a stale bundle.
- **Never read large tool output through a pipe.** `opencode agent list` is ~9 MB
  of per-agent permission config; a non-seekable stdout silently drops the tail,
  which once made a working agent look dead and cost a confidently wrong
  diagnosis. Redirect to a file. `tests/test_agents.py` asserts the read size for
  exactly this reason.
- **opencode reads agents from `.opencode/agents/` and also accepts the singular
  `agent/`.** Agents live at the plural, documented path; neither spelling was
  ever broken. Ask the loader (`opencode agent list`) rather than inferring from
  docs or from what is on disk.
- **Use `make test-all`.** Bare `pytest` at the root runs only `tests/`, which is
  the fabric level and not the peer implementation.
- **`bash -n` is not a shell test.** It accepts `if [ -n "$x" ]]; then` — bash
  reads `]]` as an argument — so the failure only appears at runtime, on a branch
  nothing exercises. `tests/test_shell.py` checks for it textually.
- **Every script must handle `--help` — and answering it must do nothing.**
  Fabric-wide since Step 14: `tests/test_shell.py::test_fabric_every_script_has_help`
  runs all 33 shell scripts with `--help` and asserts rc 0, non-empty usage, an
  unchanged repo porcelain and an uncreated rehearsal tree; peer's own
  `test_every_script_has_help` covers the peer vault. A script without arg
  handling *executes its full body* on `--help` — that was the old
  `user-env-manifest.json` timestamp churn (identity-capture and provision ran
  during the suite), and on the master role `--help` reached the killswitch and
  the key generator. `tests/test_claims.py` locks the prose side: documented
  skill count == disk count, forbidden stale phrases absent from live surfaces,
  index contract-table completeness. Any new script and any new claim must do
  the same.
- **Relocate before declaring anything path-independent.** Four bugs only appeared
  when the tree ran from a different directory: a `.env` recomputed against an
  empty variable, a fabric root detected by its directory name, and a stale
  `.env` preserved because it looked configured. `make bundle-verify` does this.
- **Provenance keeps old vocabulary.** `references/` and `plans/` may still say
  "worker" and may hard-code host paths, correctly — they record what was true.
  Current surfaces must not; `tests/test_layout.py` enforces the difference.