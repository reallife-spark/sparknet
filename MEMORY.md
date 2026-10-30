# sparknet — Session Memory

> Standing state only. Read at session start; **replace, never append**.
> The plan and its cursor live in `PLAN.md` — this file mirrors it, it does not
> own it. **All history lives in `log.md` and `sessions/YYYY-MM-DD.md`** — an
> entry here is a durable fact you still need, never a record of what happened.

Updated: 2026-10-29

## Plan cursors

- **root `PLAN.md` `current: done`.** Step 72 (plan selection: the LLM proposes, reflex ranks) is implemented and live-measured 2026-10-29: 12 golden cases on `sparknet-reflex:v1`, top-1 **0.833**, coverage **0.833**, abstain **0.167**, ECE **0.000**, false accepts **0**, p95 **3497 ms**, $0; the local 3B's explicit `none` option was removed after it acted as an attractor, and abstention is now the policy's decision plus a deterministic `forbid` list. No authority, port or capability was added. `make ci CI_QUICK=1` is green and `make test-all` is EXIT=0 (peer 545 passed/1 skipped; fabric/contract/master green). The two master-spec blockers were resolved on 2026-10-29: Master Steps 10–12 were reopened, then implemented (signed ratification, ledger-hashed evidence, signed trust events); their live legs remain `DoD: confirm: user`. The evidence-capture / review-agent CLIs are wired to `make -C master-node evidence-capture|review-agents`. Step 72 is complete. Step 70 closed 2026-10-25 (70A–70G); **Step 71 (inbox reviewer
  sanitisation + acceptance gate) closed 2026-10-25**. The peer `vault-curator` is a deterministic CLI,
  untrusted ingress needs an accepted `inbox_acceptance`, and reviewed bytes are `validity: sanitized` +
  user-key signed. **Master Steps 8–9 are built and tested** (Step 8 live containment verified 2026-10-28; Step 9 live arming is operator-confirmed). **Master Steps 10–12 are code-complete but live legs remain `DoD: confirm: user`**, so the Master cursor is 10. Step 64 (the reflex layer) opened
  **2026-10-23**: local-only default, Master broker (`4224`) for the unified
  massive-task workload, RAG relevance first on the fabric corpus,
  shadow → assist → enforce, Master-local before peer access. 64A is
  **design-only and delivered** (`REFLEX_DECISION_DESIGN.md`); 64B is delivered
  (`contracts/reflex-schema.json` + `shared/sparknet-reflex.py` + golden
  vectors); 64C is delivered (`master-node/services/sparknet-reflex-broker.py`,
  `4224` overlay-only, unit staged not enabled); 64D is delivered (loopback-only,
  grant-checked `/v1/reflex/*`; local RAG reranker pilot measured, assist on
  for fabric). **2026-10-23: the hosted cloud sensor was replaced by a
  local-only default; Step 65 (2026-10-24) removed it outright** — peers and
  Master use a local reranker/LLM, and there is no egress flag and no
  credential, because no backend in the vocabulary can leave the fabric.
  64F **executed 2026-10-23** on a loopback broker + LAN Ollama endpoint
  (`sparknet-reflex:v1`): live shadow precision 0.757 vs 0.771 baseline,
  agreement 0.817, abstain 0, p95 115.7 ms, $0; local-LLM Noul probe accept
  0.80 in 1.23 s. The broker sees one query+chunk, so its rerank is lexical and
  cannot reproduce the batch reranker's 0.786 — **keep broker/LLM shadow, keep
  the in-process chroma reranker on assist**. **64F confirmed by the operator
  2026-10-24**, which closes Step 64; 64G stays deferred and each of its legs
  becomes its own step. Step 57 (clean-slate peer pair on both
  AGXes + manual 2/2 Master escalation over the direct sparknet cable) delivered
  **2026-10-19**, Phases 0–11 executed and verified; live legs stay
  `DoD: confirm: user` (physical cable move done; human review of the ceremony
  transcript). It **supersedes Step 55's deployment** (archived
  `ARCHIVE-2026-10-19-escalation`). Step 58 (userspace-aware overlay anchors for
  both roles — **closes Step 57's parked reboot-survival leg**) delivered
  **2026-10-19**: both hosts restore `wg1` at boot via enabled anchor units,
  proven by a cold-path restart + cross-ping (a literal reboot stays
  `confirm: user`). **Both hosts were then rebooted for real (2026-10-19)** —
  overlay, firewall, guard, master units and the admin surface all returned
  unattended. Step 59 (deployment/contract consistency remediation A–E)
  delivered **2026-10-19**: peer authorization live (repo stays fail-closed),
  firewalls on both roles, ledger genesis + signature-issued blocks, protected
  paths → `wg1`. Step 60 (robustness / fail-safe hardening A–F) delivered
  **2026-10-20**: one strict base64 decoder, guard fail-closed on a chattr-less
  FS, firewall self-verify, anchor re-pin-on-failure + required interface.
  Step 61 (`CLUSTER_JOB_REALIZATION_DESIGN.md`, design-only, `4223`
  `spec-only`) delivered **2026-10-20**; its follow-up made `make shellcheck`
  self-provision the pinned 0.11.0, and the first GitHub CI run then caught the
  pin being defeated by the runner's 0.9.0 plus a twin `return $rc` in the
  master anchor — both fixed (resolver shared by both targets; version is
  *enforced*, not defaulted). **Step 62 (`reallife-spark/goagx` standalone
  distribution) delivered **2026-10-20: `reallife-spark/goagx` exists (private,
  generated, never hand-edited); fabric DoD legs 1–5 verified (fresh-clone
  `--verify`, repo CI 3× success, `make ci`/`test-all`/`drift-check` green) —
  its silicon legs are parked below with Step 56's.** Cursor `done`. Step 56 (`goagx/`) is delivered+reviewed; its hardware legs
  are `DoD: confirm: user` (below). **Step 63 (the vector substrate: bounded
  Chroma pin, stamped index, allow-listed `fabric` corpus) delivered
  2026-10-22** — the substrate half of Step 61's increment 2; the 4223 service
  itself is untouched and `4223` stays `spec-only`. **Step 65 (the naming purge)
  closed 2026-10-24**: the reflex cloud leg is *deleted*, not disabled, so the
  backend vocabulary has no member that can leave the fabric; the editor rebrand's
  boundary is a test rather than a comment; all five rolling image tags are pinned
  and swept tree-wide. Cursor `done` (64A–64F closed, 64F's measurements accepted
  2026-10-24, 64G deferred; 65A–65D closed). New roadmap work gets a **new** step
  — the approved six-phase arc continues as Phases 2–6, scoped in PLAN.md's
  `## Next`. **Step 66 (department as a signed privilege boundary) opened
  2026-10-24**: 66A done — `department` is in the signed registry envelope and
  `cross-department-share` is in the closed vocabulary, changed in *both* repos
  because the envelope is implemented twice (Python here, Go in goSpark) and
  `tests/test_registry_crossverify.py` is the only proof the two agree. 66B
  **66B enforcement done** — the boundary binds only when both sides carry an
  attested department and they differ, checked on both sides against their own
  registry view, wired into the bridge so it is not inert; 66B also found that
  `sign_authorization` could not emit the field at all, so no signer could
  attest one. **66C done** — `00_System/platform.md` (schema
  `sparknet-platform/1`), written by the same capture run as
  `manifests/user-env-manifest.json` so the two cannot disagree; declared in
  `tracking-schema.json` `platform_record`; the template ships uncaptured. The
  master role has no declaration yet (it carries no snapshot to agree with).
  **66D-i done** — the operator's OS identity (`operator_os`: uid, euid,
  username, groups, is_root) is inside the signed grant projection, because the
  ceiling must travel with the human rather than be whatever uid the daemon
  happens to run as. Single-repo: goSpark implements no grant handling at all.
  Also pinned `GRANT_FIELDS` against the contract, which nothing did.
  **66D complete** — operator decision: *the attestation authorises*. One rule,
  `authz.operator_os_authorises` (never reads the daemon's uid, fails closed on
  unattested, never infers root from `uid == 0`), declared in
  `security-policies.json` as `operator_os_ceiling` and reached two ways: from a
  grant's `operator_os`, and from the guard-apply envelope's, which carries it as
  a **canonical-JSON string** because `guard_approval_message` requires every
  projected field to be a string. The guard checks it at the apply path *before*
  the write and before the euid question — the attestation says whether the human
  may ask, the uid says whether the process can do, and both must hold. Only the
  live privilege leg stays `DoD: confirm: user`: this host has no root/non-root
  split to exercise. **Step 67 (intake) opened 2026-10-24: 67A done** —
  `build_inbox_acceptance` in `shared/sparknet-provenance.py`, dual-signed and
  *enforcing* the `inbox_dispatch` policy rather than merely recording it. It
  closes a gap both roles' agent charters had been asserting since 2026-10-10:
  they told agents acceptance *is* recorded as an `inbox_acceptance` block while
    no code could produce one. **67B, 67C and 67D are done — Step 67 is complete**
   (cursor `done`). **67C done** — `contracts/rfi-schema.json` plus
   `rfi_answer_message`/`sign_rfi_answer`/`verify_rfi_answer` in authz and
   `shared/sparknet-rfi-install.py` as the one acceptance rule; installing composes
   with 67A (writes the item, records the request id, appends an `inbox_acceptance`).
   No monotonic sequence: a registry *supersedes* so a lower sequence is a replay,
   while answers *accumulate*, so the idempotence key is the `request_id`.
   **67D done (2026-10-25) — the RFI *answer* transport is live over a wire:**
   `POST /api/v1/rfi` is a *third route on the guard's 9090* (not a new port),
   `handle_rfi` in `peer-node/services/sparknet-guard-d.py`, source-gated +
   installing through `shared/sparknet-rfi-install.py`; the Master composer is
   `master-node/scripts/sparknet-rfi-answer.sh` (`make -C master-node rfi-answer`),
   signing via the isolated signer's **new `sign-rfi-answer` op** (or `--offline`)
   and pushing like `sparknet-registry-deliver.sh`. `ports.json` names the route on
   9090 and `tracking-schema.json`'s `phase_boundary` now lists the answer leg as
   built — the two facts its rule requires before transport may be claimed. **The
   request direction is NOT built and is deferred to its own step**: a request is
   signed with the peer's node key, but nothing binds a peer *fingerprint* to a node
   *signing* public key (a registry entry carries the fingerprint + WireGuard key
   only), so the Master cannot attribute one and `verify_rfi_request` does not
   exist; the composer takes `request_id` + peer as inputs. The reason is recorded
   in `rfi-schema.json` `implementation_state.request_channel` (operator decision,
   Fork 1). The cross-node leg on a live pair stays `DoD: confirm: user`.
   **67B done (2026-10-25) — node-local notification on arrival.**
   `shared/sparknet-notify.py` is the one implementation (the Master admin console
   now *delegates* its `notify_kde` to it rather than keeping a second copy): a
   durable arrival spool (`<state-dir>/notifications/arrivals.jsonl`, 0600) plus a
   best-effort KDE Connect ping. The guard's `handle_rfi` calls
   `notify_inbox_arrival` *after* the install + `inbox_acceptance` append, so a
   notification failure can never undo or block a delivery. The spool is the
   *alert*; the ledger block is the *audit* — not redundant. Honest limit: a
   headless peer with no `kdeconnect-cli` no-ops the ping (still spools), and
   real-time push to a *remote* operator rides Phase 4 telemetry, not a local ping.
   **Step 67's deferred legs became new roadmap work:** the RFI *request* channel is
   now **Step 68** (below); reviewer-agent sanitisation (`agents/vault-curator` still
   a placeholder) and remote operator push stay in PLAN `## Next`.
   **Step 68 (the RFI request channel) opened 2026-10-25 — 68A + 68B done.**
   68A chose **Option B: attribute a request by the authenticated overlay, not a
   node-key signature.** The reason is blast radius, not merit — the contract's
   original "signed with the peer's node key" is *unverifiable* (nothing binds a
   fingerprint to a node signing pubkey; the identity carries only a Curve25519
   WireGuard key), and the fix that would make it verifiable (**Option C**: attest
   `node_pubkey_b64` in the signed envelope, as `department` was in 66A) is a
   **two-repo** change (the envelope is Python here *and* Go in goSpark;
   `tests/test_registry_crossverify.py` pins the agreement) that compounds the
   re-sign already pending from 66A. Option B is single-repo, reversible, no
   migration: WireGuard already authenticates each peer and the Master's registry
   maps `overlay_ipv4 → fingerprint`, so **on the overlay the tunnel is the
   identity**. Option C stays the recorded upgrade path if non-repudiation is ever
   needed. Design in `RFI_REQUEST_DESIGN.md`; `rfi-schema.json`'s `request` block
   rewritten (attribution/unsigned/verify/transport/upgrade_path) and
   `implementation_state.request_channel` moved `NOT BUILT → IN PROGRESS`. 68B built
   `build_rfi_request` + `verify_rfi_request` in authz — **no `sign_rfi_request`**
   (a test fails if one appears): `verify_rfi_request` is a validator +
   overlay-fingerprint match (`wrong_peer`) + expiry/`not_yet_valid`/`replayed_nonce`,
    never raises. **68C and 68D were later delivered as Step 70B/70C**: the Master
    listener re-scoped `8090` (closing Master Step 7) and the composer gained
    `--request`.
   **Step 69 (Phase 4, Master observability) opened 2026-10-25 — 69A + 69B + 69C done;
   the operator sequenced Phase 4 *before* 68C–68D on purpose.** The theme is
   *signed evidence pushed to the Master, never interception* (peers talk directly;
   the Master is authority-plane only at `10.100.0.1/32`), under two invariants the
   reflex layer also holds: **telemetry carries no authority** (inform/record/surface/
   flag, never grant/revoke/escalate/widen/approve) and **no interception, no new
   write path** (fabric vault maintenance rides `guard-apply` + `protected_paths`).
   `MASTER_OBSERVABILITY_DESIGN.md` is the architecture; the key structural decision
   is **one Master peer-intake listener** — re-scope the `spec-only`, superseded
   **8090** (resolving Master Step 7) to carry peer→Master families as *routes*
   (`POST /api/v1/telemetry` now; **68C's RFI request route joins the same 8090**),
   exactly as the peer's guard 9090 carries three routes. That is why Phase 4 goes
   first: 69C lays the listener once and 68C adds a route to it. Attribution reuses
   **68A's Option B** (the overlay is the identity; no node-key signature). 69B built
   `contracts/telemetry-schema.json` + `build_telemetry_report`/`verify_telemetry_report`
   in authz — a `kind`-tagged (`status|metrics|liveness|checkpoint_anchor|inbox_alert`),
   overlay-attributed, **unsigned** report (no `sign_telemetry_report`; a test fails if
   one appears), `verify` a validator + fingerprint match + nonce/expiry that never
   raises; `payload` is an opaque object so a new kind never reshapes the envelope.
   The existing **pull** path (admin console `feed()` → `list_events` over
   `admin-supervise`, bridge `/admin/*`) is complementary, not redundant: pull is
   Master-initiated/admin-supervise/auth-events, push is peer-initiated/`telemetry`-gated.
   **69C done (2026-10-25) — the Master peer-intake listener on a re-scoped 8090.**
   `master-node/services/sparknet-peer-intake.py` (renamed at 70B from
   `sparknet-telemetry-intake.py`) binds `10.100.0.1` only and its source gate is
   **registry-driven** (`PeerDirectory.attribute`: source address → the Master's signed
   registry entry), refusing `off_overlay`/`revoked`/`capability_missing` *before the
   body is read* — the last is what "wire the `telemetry` capability" means
   concretely. It verifies via `verify_telemetry_report(expected_fingerprint=<derived>)`,
   records to `/mnt/log/sparknet-telemetry.jsonl` (0600) with in-memory nonce replay
   protection, and carries **no authority** (a source-scan test fails on any signing
   primitive). The unit is staged (`make peer-intake-unit`), not enabled. **8090
   re-scoped** in `ports.json` (`master-instant-push`/`spec-only` → `master-peer-intake`/
   `implemented`), which **closed Master Step 7** (instant-push purpose retired as
   superseded by Step 6's 9090 push; Master cursor `7 -> 20`). The 7-line
   `sparknet-registry-listener.py` stub + its text-inspection `test_listener_8090.py`
   are **deleted**, replaced by `test_peer_intake.py` (a real `ThreadingHTTPServer`);
   six master docs reconciled. **70B joined the RFI request route to this one
   listener — one surface, two routes.**
   **Step 70 (opened 2026-10-25) consolidates the entire remaining fabric roadmap
   into one verbose plan** — Steps 68 and 69 are **closed** (their delivered legs
   68A/68B and 69A/69B/69C are done+gated; their unfinished legs *moved*, not done).
   Step 70's sub-steps, in dependency order: **70A** the peer telemetry pusher —
   **DONE 2026-10-25** (`peer-node/services/sparknet-telemetry-push.py`, `telemetry`-gated,
   10 tests against the real 69C intake; live push stays confirm:user), **70B DONE
   2026-10-25** — `POST /api/v1/rfi-request` joins the (renamed) `sparknet-peer-intake.py`
   with no capability requirement, verifying + queueing one content-addressed artifact
   per request; 24 tests over the real intake, gates green; **70C DONE 2026-10-25** — the
   composer's `--request` path consumes the queued artifact, re-verifies it, takes peer/id
   from it, and refuses any `--sources` category outside the request scope (3 new transport
   tests, incl. real request→intake→composer→inbox); **70D DONE 2026-10-25** — the
   peer liveness service (`peer-node/services/sparknet-liveness-monitor.py`) runs the
   shared `ContinuousMonitor` over a signature-checked registry roster, answers
   probes on the contracted non-serving **4211** (accept/close, no bytes), feeds
   inbound probes back as activity, and pushes `kind=liveness` via 70A; eviction is
   local, a republished registry re-admits; `ContinuousMonitor` gained `on_round`;
   `health-protocol.md` reconciled to Option B (unsigned, overlay-attributed);
   11 service tests + the real 8090 intake, both bundles green; **70E DONE 2026-10-25** —
   `sparknet-checkpoint-anchor.py` appends an idempotent signed checkpoint only when
   the head moved (a newest checkpoint that snapshots every prior block means no
   write), and pushes the full signed block as `checkpoint_anchor` over 8090; empty
   chain silent, tampered chain refused, 15-min oneshot timer; 8 tests + real intake,
   both bundles green; **70F DONE 2026-10-25** — the guard emits `inbox_alert` after
   an installed RFI answer via the 70A pusher (telemetry-gated, unsigned,
   overlay-attributed; payload item/request_id/digest/audit_block; failed push never
   affects install), local 67B spool/ping unchanged; `SPARKNET_TELEMETRY_ENDPOINT`
   added for daemon relocation/tests; 2 master tests + real intake, both bundles
   green; **70G DONE 2026-10-25** — `sparknet-share-regime.py::trust_summary` is the
   one reading of persisted share records (most-concerning belief wins; ratified
   shares stay `authenticated` with the `flagged` marker retained); the pusher adds
   it as `payload.trust` on the existing `status` report (no new kind), and the console
   reads the Master's telemetry spool (`SPARKNET_TELEMETRY_SPOOL`, newest status per
   fingerprint) to surface `trust.flagged` rows in `feed` and via a `trust` verb —
   read-only, no registry/trust mutation, no auto-remediation; 2 push + 2 console
   tests, both bundles green. **Step 70 is complete; fabric cursor `70 -> done`.**
   Locked operator decisions: execute sequentially gating each; 70D liveness → Option
   B; 70G flagged → `status` payload.
   **Reviewer-agent sanitisation is complete as Step 71** (2026-10-25): the
   `vault-curator` CLI refuses untrusted ingress until an accepted,
   `sanitized: true` block names it, sanitizes active content, sets
   `validity: sanitized` and signs with the user key. **Still honestly open**:
   Phase 5 (Open WebUI), Phase 6 (data lake), master plan Steps 8–12 (Step 8 is
   implemented but its live destructive run is unverified), and the live
   `DoD: confirm: user` items (Step 56's hardware legs, Step 57's cable follow-up,
   the Step 66 registry re-sign, Phase 9's destructive legs) — marking
   genuinely-undone work complete would be a false claim the conformance tests
   reject.
  **The pin hazard is closed** (`3d3bac9`): `goagx/GOSPARK_PIN` now names goSpark
  `0a6da00`, goSpark is pushed, and goagx was republished (`9898733`) since
  `tests/test_goagx_repo.py` binds the pin to the published manifest. **Still
  open, and not closable from this repo:** a live node must re-sign its registry
  and re-publish at a higher sequence, because the signed envelope changed shape.
  Steps 1–54 closed/parked: **Step 54 closed as fulfilled by Step 57** and
  **Step 55 marked superseded (not completed)** by Step 57 on 2026-10-25.
- **`peer-node/PLAN.md` `current: done`** — the peer arc is terminal; its last
  work (Steps 2–12: container, grants, bridge, Open WebUI surface, conversation
  passing, `MASTERSPIKE`, sharing regime, node admin agent) closed 2026-10-11/12.
  New peer work gets a **new** step.
- **`master-node/plans/MASTER_BUILD_PLAN.md` `current: 8`** — Phase 0 (13–18),
  honest verification (19), Steps 1–7 and Steps 20–21 are complete. **Step 2
  (registry schema + the spec/impl boundary) closed 2026-10-22**, **Step 5
  (guard approval issuer) closed the same day**, **Step 6 (registry distribution
  channel) closed 2026-10-23**, and **Step 7 closed by fabric Step 69C
  (2026-10-25)**. **Step 20 (signer liveness) was deployed live 2026-10-09** and
  **Step 21 (admin console) is complete**, with the surface bound on
  `10.100.0.1:8088` since 2026-10-19. **Steps 8–12 are open again** — their `[x]`
  boxes had never been updated after the 2026-10-06 reopening: KillSwitch,
  scheduler, share ratification, evidence repository and review agents. The
  registry's canonical shape is stated **once**, in
  `contracts/registry-schema.json`; the Master's path is a symlink to it and
  `shared/sparknet-registry-schema.py` checks documents against it (standard
  library only — the runtime allow-list is `cryptography` alone). The
  guard-approval envelope is likewise stated once, in
  `shared/sparknet-authz.py::guard_approval_message` and
  `contracts/guard-approval.json` — before Step 5 the issuer, the signer and the
  peer each had a different idea of its shape and **none was acceptable to the
  other**, with every side's own tests green. The registry now travels as a
  **publication** the Master pushes to each peer's guard on 9090
  (`contracts/registry-publication.json`, `shared/sparknet-registry-install.py`);
  its monotonic `sequence` is what makes replaying an older, un-revoked registry
  fail. The cursor sits at **8**; Steps 8–12 are the open set. Step 7 is closed:
  fabric Step 69C re-scoped 8090 from the 8090 pull listener to the peer→Master
  intake surface. Step 9's original pooled-memory premise predates the current
  two-node hardware and was re-decided on 2026-10-25:
  `master-node/plans/NOCTURNAL_BATCH_DESIGN.md` replaces literal pooled memory
  with a time-boxed batch lease over independent whole-node jobs. **9B is
  implemented**: `shared/sparknet-idle.py` feeds session/GPU/WireGuard evidence
  into telemetry `metrics.idle`, failing closed as `null` plus an error. The
  scheduler is still a 2-line scaffold; authoritative WireGuard counters remain
  Master-side work because the unprivileged peer service cannot read `wg show`
  and sysfs reports zero.

## What this repository is

- **A fabric, not a node.** Two roles, one contract. Most confusion comes from
  reading a page that belongs to one role as though it described both.
- **A role subvault alone is not a deployment.** A peer cannot verify a
  signature without `contracts/` + `shared/`; a bare copy fails validation by
  design. `make bundle` assembles a real deployment; `make bundle-verify` proves
  it (extract elsewhere and run).
- **Authority is key possession, not a capability grant.** A peer with the whole
  vocabulary but no private key can never grant, revoke or escalate. The
  capability vocabulary is closed:
  `telemetry, p2p-sync, push-receive, guard-apply, cluster-vote, cluster-dispatch,
  cluster-serve` (+ `admin-supervise`, held by the master).
- **Cross-role changes are atomic.** Edit `contracts/` and both roles in the
  same commit, then `make contract-test`. `tests/test_contracts.py` fails when a
  role's copy of the contract drifts.
- **The shipped registry is empty on purpose** — the fail-closed default. No
  node has privileges until the Master signs something.
- **`reallife-spark/goagx` is a generated distribution, never hand-edited.**
  It is the one-way export of this fabric's node surface (`make goagx-publish`;
  verify with `scripts/sparknet-goagx-publish.sh --verify <clone>`; drift via
  `make goagx-drift-check`, which self-skips unauthenticated). Every commit is
  a full-tree release; fixes go into the fabric and get republished. Its root
  README/manifest carry the pinned sparknet SHA, the goSpark pin
  (`goagx/GOSPARK_PIN`) and the image ARG pins.
- **The goSpark pin is `91a6ef9` (2026-10-29).** It carries the
  context-propagation fix: NATS handler contexts inherit the subscriber's
  context, the agent uses it for the post-adoption health re-publish and the
  signed result publish, and the control plane uses the signal context for both
  dispatch paths. The commit was pushed to `goSpark` (`0a6da00..91a6ef9`)
  before the pin bump; `VERSIONS.json` records it.
- **The local vector index is derived state, and it is stamped.** The corpus
  in the vault is the source of truth; the index under `.state/chroma/` is
  rebuilt from it, never patched. The collection carries
  `embedding_model`/`embedding_sha256`/`chroma_version`/`corpus_digest`, and the
  embedder is named explicitly (`ONNXMiniLM_L6_V2` = `all-MiniLM-L6-v2`) on
  every open — Chroma's default embedder cannot identify itself, so a stamp
  written from it is not a stamp. A mismatch in the model, its hash or the
  corpus digest **refuses** (exit 3 → 503 on the wire); a `chroma_version`
  difference is only *reported*. `make chroma-stamp` checks it.
- **One corpus policy, two allow-lists.** `scripts/sparknet-rag-corpus.py`
  holds the rule set once: `NODE_ROOTS` (a node's own Open WebUI) and
  `FABRIC_ROOTS` (the node's roots plus the fabric's design documents — a
  strict superset). The `fabric` scope uses the allow-list; the deny-list it
  replaced served 1,090 personal/runtime chunks (64% of 1,699).
- **Vaults: three, not one.** Fabric root plus `peer-node/` and `master-node/`,
  each with its own `.env`, category skeleton and `AGENTS.md`. Resolve which one
  you are in before writing. Both role vaults store content in `00_System`–
  `07_Archives`; legacy names are symlinks (`make shims-check`).
- **The node image surface is a platform pair.** `spark.docker` /
  `spark.compose.yml` (DGX Spark, r36) and `goagx/` (Xavier, r35 py3.8),
  selected by `sparknet-node-setup.sh --platform spark|agx`; goSpark enters the
  AGX build as a named BuildKit context, vLLM v0.2.7 compiles from source on
  the device. The AGX `Dockerfile` keeps every `ARG` a stage uses declared
  in-stage (BuildKit predefined values like `TARGETARCH` do **not** inherit
  from a global `ARG` — pinned by `test_agx_node.py` stage-scope check).
- **The Go control/service plane is checked out at `gospark/`.** It is a
  separate Git repository (own `.git`, gitignored, excluded from the fabric's
  layout/lint/format/compose sweeps) whose module path stays
  `github.com/reallife-spark/goSpark`. Build it in place
  (`make -C gospark build build-gpu`); node images consume `bin/` through the
  BuildKit named context `gospark`. Host defaults resolve to
  `<fabric-root>/gospark` (`GOSPARK_DIR` overrides).
- **`$SPARKNET_STATE_DIR` resolves outside the vault** (`$XDG_STATE_HOME/
  sparknet/<role>`, else `~/.local/state/...`) for the master; the peer keeps
  `<vault>/.state` on purpose (nothing mounts that vault). `keys-check` fails if
  it is pointed back inside.

## Live fabric (agx64 / agx32)

- **Live pair redeployed clean-slate by Step 57 (2026-10-19):**
  **`agx64` = peer = `sparknet-node-0001`** (wlan0 `192.168.178.21`, overlay
  `wg1 10.100.0.2/32`); **`agx32` = master = `sparknet-node-0002`** (wlan0
  `.22`, anchor `10.100.0.1`). Both on the **knowledge-base vault template**
  (owner `U-27689`). wlan0 (`h58`) carries the uplink/default route; the direct
  eth0 cable is the dedicated sparknet underlay **`10.99.0.0/30`** (agx32 `.1`,
  agx64 `.2`, static never-default) with `wg1` endpoints pinned to it. Trust
  root **`fa6f4fa5…`** (2/2, `0002` Master); signer `xjKK/Beuw…` (== root
  `master_pubkey`).   Running: guard `10.100.0.2:9090`, dispatch-bridge
  `127.0.0.1`+`10.100.0.2:4096`, master ledger/parity/signer units, both overlay
  anchors, the **firewalls** on both roles (`sparknet-firewall.service` /
  `sparknet-master-firewall.service`; ingress-only on 8181/11434/18000,
  master egress unrestricted; each `install` self-verifies and the unit runs
  `verify` via `ExecStartPost`), and the anchors place/pin
  `/etc/wireguard/wg1.conf` — cold-boot restore proven **by real reboots of both
  hosts 2026-10-19** (overlay back with no operator action; the master's admin
  container auto-starts and binds `10.100.0.1:8088`). Both anchors also pin the
  state-dir copy and re-pin on any non-zero exit (Step 60); they **require**
  `SPARKNET_WG_INTERFACE` (set to `wg1` in both env files) rather than defaulting. The ledger carries the
  genesis `trust_root_formed` block + a `signature_issued` block (chain intact);
  peer `authz-verify` is `allowed: true` (fp `84bd134e…`) while the **repo stays
  fail-closed** (empty registry, placeholder pubkey — live authorization is
  deployment-side only). State dirs:
  peer `~/sparknet/peer-node/.state`; master
  `~/.local/state/sparknet/master-node`. Both prior deployments (2026-10-07
  root, cluster2, **and the Step 55 role-swap**) are archived at
  `~/.local/state/sparknet/ARCHIVE-2026-10-19-escalation/` — rollback = mv back
  + re-enable. Python floor met with **uv CPython 3.12** at `~/sparknet/.venv`
  (system `python3` is 3.8/3.9).
- **Election/signer arc proven live 2026-10-07** (prior deployment, now
  archived): 2/2 root, signer as `sparknet-master-signer.service`, revoke→
  peer-inert→re-authorize cycle. The signer is the **only** process holding
  `operational.ed25519`.
- **Admin federation (Step 29) completed 2026-10-12**: design + Phases 0–4 as
  code + Phase 5 run live on the pair (procedure in
  `contracts/admin-federation-runbook.md`). `admin-supervise` held by master.
- **Overlay reboot resilience (2026-10-19)**: `wg-quick` is unusable on the
  tegra host (`CONFIG_WIREGUARD=n`), so both roles now restore `wg1` at boot
  through the peer's `scripts/sparknet-wg-bringup.sh` (userspace `wireguard-go`),
  driven by enabled anchor units — `sparknet-wireguard-anchor.service` on agx64,
  `sparknet-master-wireguard-anchor.service` on agx32 (in `make units`); peer
  secrets come from `/etc/sparknet/wireguard.env`, the master from
  `/etc/sparknet/master-wireguard.env` (both 0600). Both units carry
  `Before=docker.service` so a container binding the overlay address starts after
  it exists. The old `/root/scripts/sparknet-wg-restore.sh` is retired. Both
  clusters use `10.100.0.0/24`, so `wg0` (live) and `wg1` (cluster2 proof) must
  **not** run concurrently.
- **Networking (Step 54 → 57):** both nodes have **working Intel AX210 WiFi**
  (`iwlwifi` loaded — configuration only, no drivers needed); chosen uplink
  **h58** (user runs the PSK connect; PSK never enters chat) now carries the
  default route on wlan0 `.21`/`.22`. The **direct eth0 cable is the dedicated
  sparknet underlay `10.99.0.0/30`** (agx32 `.1`, agx64 `.2`, static
  never-default nmcli profiles) and `wg1` endpoints are pinned to it
  (`.1`/`.2:51820`, replacing the old LAN-IP endpoints). Tunnels are userspace
  `wireguard-go`. **wlan0 power save is disabled on both hosts** (`iw … set
  power_save off` + `nmcli … wifi.powersave 2`) — the Broadcom default caused
  intermittent `No route to host` / stale-ARP blips while the node was up.
- **Master admin page**: **running on agx32** — container `sparknet-admin-webui`
  is `Up (healthy)` on `10.100.0.1:8088`; a human browser check is still
  `DoD: confirm: user`. It bind-fails (`exit 128`, `cannot assign requested
  address`) if Docker starts it before `wg1` exists, so **both anchor units now
  carry `Before=docker.service`**. Port relocated `8080`→`8088` because the
  unrelated lab container `mitm` holds `0.0.0.0:8080` on agx32. Ports
  `4220`–`4223` are spec-only.
- **The goagx node stack runs live on both hosts (2026-10-21).** Both carry the
  same image facts: goagx `5cfe888`, goSpark `f547751`, vLLM 0.2.7, torch
  `2.0.0a0+ec3941ad.nv23.02`, transformers 4.37.2, xformers 0.0.20, jinja2
  3.1.6, whisper.cpp 1.9.5, llama.cpp 0.7.0. Measured ~5 tok/s for Mistral-7B
  fp16 (agx32 60.2 s / agx64 61.6 s per 300 completion tokens), 4 771 prompt
  tokens after the precontext cap. Durable facts worth keeping:
  - **`VLLM_GPU_MEM_UTIL` is a fraction of system RAM on Jetson** (unified
    memory; `mem_get_info` reports the system), and vLLM 0.2.7 subtracts a
    *system-wide* peak → 0.4 on the 64 GB peer, **0.8 on the 32 GB master**;
    lower values on the master mean no room for the cache blocks at all.
  - **The 32 GB master cannot host Mistral-7B and the aux profiles (embed /
    rerank / audio) together** — the engine dies with
    `torch.cuda.OutOfMemoryError`. The aux profiles are an **on-demand window**
    there; the 64 GB peer runs the full set concurrently.
  - **Ollama's keepalive cold-loads a ~9.6 GB model** → stays stopped on the
    master while the 7B model is resident (`ollama-keepalive.timer`).
  - **The control plane's admin surface must bind to loopback** — goSpark
    refuses `0.0.0.0:8899`; the composes set `GOSPARK_ADMIN_LISTEN:
    127.0.0.1:8899` and the host mapping is loopback-only.
  - **The chat precontext must be capped** (`SPARKNET_PRECONTEXT_MAX_BYTES=
    16000`) or the 8 192-token context overflows; **jinja2 must be in the
    image** (the chat template refuses to render without it) — it is installed
    in its own **late** layer so a jinja2 bump never invalidates the
    multi-hour vLLM compile.
  - `bootstrap-agx.sh` takes `--gospark <path>` (the goSpark repo is private;
    the on-host build enters the image as a named BuildKit context) and the
    overlay bind comes from `SPARKNET_BIND_API`, not a `--bind-api` flag.

## Security / secrets

- **The pasted `nvapi-…` build.nvidia.com key is treated as compromised —
  rotate it.** Its only home is `.state/secrets/build-nvidia.env` (0600, dir
  0700, gitignored); it is referenced by **path only**, never in a tracked file,
  and never printed (`make nv-search` refuses `ngc` without one). No
  `.env.example` knob for it (three-template key-set test).
- **Outstanding, unclaimed**: rotating/revoking the old broad OAuth token from
  the split-day leak.
- Never commit tokens/keys/`.env`; `make keys-check` is the gate.
- **One strict base64 decoder.** Every signature/key/body decode goes through
  `shared/sparknet-authz.py::decode_b64_strict` (or passes `validate=True`);
  `tests/test_hardening.py` scans the source and fails on a tolerant decode. This
  closes a real cross-CPython trap (a 43-char + stray-`=` body decodes on 3.12 but
  raises on 3.14 with `validate=True`).

## Open items (`DoD: confirm: user`)

- **Step 62 AGX legs**: the vLLM/xformers source build completing on a real
  Xavier from a clone of the published `reallife-spark/goagx` (bootstrap →
  setup), real tok/s inside 16 GB, and the full-node bring-up (overlay anchor +
  guard/bridge units) on that host — publishing and verifying the repo does not
  prove the silicon. **Partially answered 2026-10-21** (see "Live fabric"):
  the source build completed on both real Orin nodes and real tok/s were
  measured (~5 tok/s, 4 771-token prompts), the goSpark path was built
  on-host and the whole stack passed its battery — but from a **fabric tree,
  not a published-clone**, and on 32/64 GB Orins rather than a 16 GB Xavier.
  The clone-from-published-repo leg and the 16 GB budget leg stay open.
- **agx32 (master) text vLLM is stopped deliberately (contained 2026-10-29).**
  It had been crash-looping since 2026-10-26 (`Exited (255)`, 989 restarts):
  `torch.cuda.OutOfMemoryError` plus a stale `docker-proxy` on
  `10.100.0.1:8000`. Stopping the loop released the port and recovered memory
  (26 GiB used → 15 GiB used, 14 GiB available). It was **not** restarted:
  `ollama` (raxxar `infra` compose) holds `gemma4-4b-131k` at 131k context
  (9.2 GiB RSS, keepalive forever), and Mistral-7B cannot load beside it
  without risking the OOM killer taking raxxar services. `agx64`'s vLLM is the
  fabric inference path and answers `200` over the overlay from agx32.
  Restarting vLLM on agx32 requires unloading Ollama, shortening its context,
  or using a smaller model. The aux vLLM profiles stay stopped on this host.
- **Branch protection requiring the `gate` check** — unavailable on this plan
  (needs Pro or a public repo), so no check is enforced as required today;
  revisit if visibility or plan changes. **Live GitHub CI itself is proven**
  (see gotchas).
- Hardware/LLM legs of the adoption arc: a real GPU/driver host, a live BMC
  (Redfish inventory), a live eval endpoint (`EVAL_BASE_URL`), the Open WebUI
  handshake.
- **Step 56 AGX legs**: the source build (vLLM/xformers hours) completing on
  the Xavier, real tok/s inside 16 GB, NVML/tegra sidecar telemetry on Jetson,
  whisper `detect_language` through the audio shim. **Partially answered
  2026-10-21**: the source build and real tok/s are proven on both real Orin
  nodes, and the GPU sidecar's honest Jetson degradation is observed
  (`gpu_telemetry.available=false`, reason `libdcgm.so.4 not found` /
  `ERROR_LIBRARY_NOT_FOUND` — DCGM/NVML are absent on r35 by contract);
  whisper's route through the shim answers 200. Still open: the 16 GB budget
  and whisper's per-request `detect_language` behaviour.
- Full power-cycle reboot of a cluster2 node (peer Step 10 leg).
- Phase 9's destructive legs (rollback / replace-Master re-formation) are
  documented in `contracts/deployment-runbook.md` and deliberately unexecuted.

## Role-local skill catalogs (2026-10-29)

- Base suite: `.opencode/skills/` (33, MIT). Role-local additions:
  `peer-node/.opencode/skills/` (90 sellable) and
  `master-node/.opencode/skills/` (1,652 sellable role-local; 33 base + 1,652 =
  1,685 visible). Manifests: `.inventory.json`; gate: `make role-skills-check`.
- The twelve restricted names are removed from both roles. The master catalog
  excludes GPL/AGPL, CC BY-SA, modified-Apache and unclear licenses; the
  Apache-2.0 `claude-api` is present as `tier: optional` only, not in peer.
  `skill-template` is the only newly authored skill (dual MIT/Apache).
- The global opencode config no longer force-loads
  `/mnt/nvme/skills/raxxar-active`; project skills now win.
- `goagx` release `6663e44` was published from the dirty worktree on
  2026-10-29; `make goagx-drift-check` is green. It is not release-grade until
  the sparknet changes are committed and goagx is republished from that commit
  (the published `VERSIONS.json` currently names HEAD `47bbed4`).

## Command / environment gotchas

- **Local gates are authoritative**; the SHA-pinned GitHub Actions run the same
  `scripts/pre-merge-gate.sh` as a mirror. `make ci` (add `CI_QUICK=1` for the
  quick pass); `make test-all` for every suite. Bare `pytest` runs only `tests/`.
  **Both repos' `gate` + `secret-scan` pass on GitHub since 2026-10-18** (six
  bare-clone fixes; this host's system `python3` has `cryptography`, which is
  why the interpreter assumptions were invisible locally — CI measures the
  runner). `codeql` **self-skips with a `::notice`**: GitHub only scans public
  repos on the Free plan, so it analyses for real once public or Code
  Security-enabled.
- **A full `make ci` needs a long timeout** — the default 120 s shell cap
  truncates it (`Terminated` mid-run is not a gate failure).
- **`gh` lives at `~/.local/bin/gh`** (authenticated as `reallife-spark`), but a
  non-interactive `PATH` omits it. Push with
  `PATH="$HOME/.local/bin:$PATH" git push origin main`. Remote is
  **`reallife-spark/sparknet`** (private).
- **`make bundle-verify` only verifies the newest archive** — rebuild first.
- **Never read large tool output through a pipe** (e.g. `opencode agent list`,
  ~9 MB): a non-seekable stdout drops the tail. Redirect to a file.
- **`bash -n` is not a shell test**; every script must handle `--help` and do
  nothing (`tests/test_shell.py` runs all 33 shell scripts with `--help`).
- **The wiki suite is vendored** at `.opencode/skills/` (33 skills: 32 vendored
  + 1 local, MIT); `make wiki-sync` / `make wiki-verify`. Skills resolve the
  **nearest `.env`** — run `make wiki-preflight` first, never work around a
  failure (they would silently write to the wrong vault).
- **Relocate before declaring anything path-independent** — `make bundle-verify`
  does this; four bugs only appeared from a different directory.
- **`make shellcheck` provisions its own pinned binary.** `SHELLCHECK_VERSION`
  (0.11.0) is pinned in the Makefile like the Actions SHAs; the gate downloads
  into `.cache/tools/shellcheck-<ver>/<arch>/` when the binary is not on
  `PATH` and fails **closed** if it can neither find nor fetch one. It used to
  **skip silently**, which meant `make ci` passed on this host and every fresh
  clone without ever running the check — Step 60's green was that kind of
  green, and re-running with the binary surfaced two findings it had masked.
  A required gate must never pass by not running. `make shellcheck-install`
  provisions without running the gate. The workflows were deliberately left
  calling only `make ci` (`tests/test_ci.py` pins that invariant).
- **A gate that runs a *different* checker than CI is a gate that lies.** The
  pin must be *enforced*, not merely defaulted: `make shellcheck` accepts a
  `shellcheck` already on `PATH` **only if its version equals**
  `SHELLCHECK_VERSION`. The runner image ships 0.9.0; the first push let it
  through and CI enforced 0.9.0's opinion instead of 0.11.0's — that caught a
  real `return $rc` (SC2086) here, but only after a red CI run. When a pinned
  tool is the thing a gate's name promises, verify the version, not the
  presence. Both `shellcheck` targets share one resolver so they cannot drift.
- **Fix a bug where its twin lives.** The SC2086 quick-fix landed in the peer's
  `sparknet-wireguard-anchor.sh` and the *master's* `sparknet-master-*.sh` twin
  kept it, because only one was re-checked. These two files are deliberately
  near-duplicates; grep the sibling before closing a shellcheck finding.

## Local vs live

Everything `make test-all` / `lint` / `bundle-verify` checks is verifiable on
this host. Claims about the live pair were verified from those hosts per the
runbook; anything needing a second node or the Master carries
`DoD: confirm: user`, never a local pass. This host has no GPU and does not run
the overlay.
