---
title: sparknet Plan
updated: 2026-10-12
current: 29
---

# sparknet — Active Plan

> Single source of truth for multi-step work at the **fabric** level. The `current:`
> cursor marks the step being worked. Write this file back **immediately** on every
> advance; append the matching transition line to `log.md`.
>
> Role-level work has its own plans: `peer-node/PLAN.md` and
> `master-node/plans/MASTER_BUILD_PLAN.md`. A step here that is really one role's
> work belongs in that role's plan.

## Status Legend

- `[ ]` not started / in progress
- `[x]` complete — DoD verified
- **DoD** — the check that proves the step is done; `DoD: confirm: user` when a human must confirm
- `current: N` — step being worked now; `current: done` — terminal

## Step 1 — Split the vault into the two-role fabric

- [x] **Step 1** — One `worker` vault became `contracts/` + `shared/` +
      `peer-node/` + `master-node/`.
      - **DoD**: (1) `contracts/` holds the overlay, capability, identity, port
        and guard-protocol contracts as the single source of truth;
        (2) `shared/sparknet-authz.py` exists exactly once;
        (3) `peer-node/` runs its suite green with `role: "peer"` everywhere the
        old `worker` vocabulary appeared; (4) `master-node/` is present and
        **asserts** it is unbuilt — no `scripts/`, `services/` or `systemd/`;
        (5) `make contract-test` passes.
      - **Status**: complete. `185 passed, 1 skipped` in `peer-node`; the
        `worker` vocabulary is gone from every live surface (provenance under
        `references/` and `plans/` may still record it, correctly).
      - **Note**: `master-node/manifests/` is deliberately absent — a Master
        manifest needs a real signing key, so it arrives with the Master's own
        Step 1. The charter says so rather than listing a phantom directory.

## Step 2 — Vendor the wiki skill suite into the repository

- [x] **Step 2** — The suite must run from a bare clone, with no global skill
      farm and no host-bound skills.
      - **DoD**: (1) all 31 portable skills vendored under `.opencode/skills/`
        with `LICENSE` and provenance; (2) host-bound skills deliberately
        excluded and the exclusion is explicit in the sync script;
        (3) `make wiki-verify` proves the vendored copy matches its pinned
        upstream; (4) the one absolute cluster path is patched, and the patch is
        a reviewable file rather than an in-place edit; (5) a test fails if a
        vendored skill contains a host path.
      - **Status**: complete. 31 skills at the time of this step; the suite is
        33 today (count asserted against disk by `tests/test_claims.py`);
        upstream `github.com/Ar9av/obsidian-wiki` at `ec2b6bc`, MIT.
      - **Note**: `skill-creator` is copied from git-tracked files because both
        source working trees contain a 40-deep symlink chain that a filesystem
        copy would follow forever.

## Step 3 — Make each role runnable on its own

- [x] **Step 3** — "Sparknet is self-contained" has to be provable, not asserted.
      - **DoD**: (1) `scripts/sparknet-env-init.sh` writes a role-scoped `.env`
        and vault skeleton; (2) `scripts/sparknet-wiki-env.sh` **fails loudly**
        when the nearest `.env` points at a different vault, so the skills can
        never silently resolve the wrong vault; (3) `make bundle ROLE=<role>`
        builds a deployment unit that includes the role, `contracts/`,
        `shared/`, `scripts/`, the vendored skills and `opencode.json`;
        (4) `make bundle-verify` extracts the archive somewhere else, runs
        `env-init`, the preflight, role validation and the role's own test
        suite from the extracted copy — for both roles.
      - **Status**: complete. Both bundles verify from an extracted, relocated
        copy. The master's verify asserts its spec boundary rather than doing
        nothing, because verifying an unbuilt role by skipping its checks would
        prove nothing.

## Step 4 — Commit and push the split

- [x] **Step 4** — The split only exists once it is committed and reachable.
      - **DoD**: (1) every new and moved file is staged, with no `.env`, key,
        `__pycache__` or `dist/` artifact included; (2) `make test-all` green
        immediately before the commit; (3) `make lint` green; (4) pushed to the
        private remote with a message that explains the split; (5) the
        pre-split history is still reachable from the pre-split tip.
      - **Status**: done, all five verified.
        (1) 229 files staged, and a pre-commit scan found no `.env`, key, cache
        or `dist/` path — `dist/` is gitignored and the only key present is the
        public `master-ed25519.pub.b64`; (2) `make test-all` green immediately
        before committing, and again after; (3) `make lint` green; (4) pushed to
        `origin/main`, remote tip confirmed by `git ls-remote` to match local
        exactly; (5) `ad1cc396f3ee23685816418a50d7e8fcbf75cd60` fetched back and
        confirmed an ancestor of the pushed tip.
      - **Note**: the push needed a credential that this machine did not have —
        no helper, no store, no token in the environment, and `gh` held an
        invalid one. It was deliberately not sourced from shell history or any
        other leftover, since the token that leaked in this session had to be
        revoked rather than reused. The credential that worked is a fine-grained
        `github_pat_`, so the broad exposed OAuth token is no longer in play.

## Step 5 — Add the node orchestrator, and prove every agent loads

- [x] **Step 5** — The node needs an agent that directs the others, and the
      repository needs a check that asks opencode what it can actually see.
      - **DoD**: (1) a node orchestrator agent exists with subagent delegation
        and conversation-passing verbs; (2) `opencode agent list`, read through a
        file rather than a pipe, resolves every vendored agent by name; (3) a
        test fails if a documented agent is not a listed agent, so an agent
        cannot go missing silently; (4) agents live at the documented
        `.opencode/agents/` path and the bundle ships that path; (5) `make bundle
        ROLE=peer` and `make bundle-verify ROLE=peer` are green and the extracted
        copy resolves the same agents.
      - **Status**: complete, all five verified. `sparknet-node.md` added;
      agents at `.opencode/agents/`; `tests/test_agents.py` (6 tests) green and
      confirmed to *fail* when the agent set is broken; `make test-all` green
      (185 peer tests); `make validate` green; a freshly built peer bundle
      verifies and its extracted copy resolves all 9 agents, both sparknet ones
      included.
      - **Note**: this step began as a bug fix and turned out not to be one. The
        `vault` agent was suspected dead because it sat in `.opencode/agent/`
        (singular) while the docs name `.opencode/agents/` — but asking the
        loader proved it loaded all along, and that opencode accepts either
        spelling. The suspicion was an artifact of reading `opencode agent list`
        through a **pipe**: the listing is ~9 MB of per-agent permission config
        and a non-seekable stdout silently loses the tail, so `title` and `vault`
        — the last two entries — vanished and looked like missing agents. Both
        spellings work; the rename to the documented plural path is retained for
        that reason alone, not as a repair. The pipe gotcha is now asserted in
        the test, because a short read would otherwise turn this check into one
        that only ever validates a prefix.

## Step 6 — Make reality and claims agree

- [x] **Step 6** — The contracts currently describe listeners that do not exist,
      and `implemented` as a boolean cannot tell "code exists" from "it listens".
      - **DoD**: (1) `contracts/ports.json` replaces the `implemented` boolean
        with two separate axes — `implementation_state` (`implemented` /
        `provisioned` / `spec-only`) for the code, which travels with the
        contract, and `runtime` (`running` / `not-listening` /
        `not-verifiable-here`) for what one host was observed to do, which does
        not — and requires non-empty `status` text whenever
        `implementation_state` is not `implemented`; (2) `4096`, `4097`, `4098`
        and `4100` are `provisioned` / `not-listening` with a status naming what
        is actually there and pointing at a plan step that verifies as a real
        file, and `51820` is `implemented` / `not-verifiable-here`; (3) a test
        asserts every port declared `running` genuinely accepts a loopback
        connection and fails otherwise, a second test fails if the conflated
        `implemented` boolean is ever reintroduced, and a third requires any
        `implemented` claim to carry either a running listener or a recorded
        reason it could not be observed; (4) a machine-checked inventory is
        committed recording the measured facts — which ports have listeners, the
        full `opencode agent list` read through a file, and which privileged
        tools this host actually has.
      - **Status**: complete, all four verified 2026-10-05.
      - **Measured, not inferred**: probed — nothing listens on 4096, 4097, 4098,
        4100 or 9090. `services/sparknet-dispatch-bridge.py` is 110 lines
        containing no bind, listen or serve code at all, and each
        `agents/*/agent.py` is a two-line `print`. `51820` has a render script,
        a systemd unit, a config template and tests, but no `wg` binary here.
      - **The distinction that changed the schema**: `9090` and `4096` both
        showed no listener, and for opposite reasons. The guard *does* bind —
        `sparknet-guard-d.py:709-711` binds the overlay address and refuses to
        listen at all without one, so its silence here is the code working
        correctly on a host with no `wg0`. `4096` has no bind code in any
        branch. One boolean cannot carry both, so the contract now records them
        on separate axes rather than forcing a choice between a wrong claim and
        no claim at all.
      - **Tests proven to have teeth**: three mutations, each reverted —
        flipping `4096` to `runtime: running` fails the reachability test,
        adding `implemented: true` back to `4097` fails the conflated-boolean
        test, and stripping `runtime_why` from `51820`/`9090` fails the
        bind-evidence test. A test that cannot fail is not a DoD.

## Step 7 — Contract the grants and the sharing regime

- [x] **Step 7** — Trust, governance and conversation passing are specified
      before any of it is built, because two of them amend existing guarantees.
      - **DoD**: (1) `contracts/share-protocol.md` states the sharing regime —
        invite, acceptance, share types, the four clocks, trust levels,
        isolation and evidence — in the same normative voice as
        `guard-protocol.md`; (2) `contracts/overlay.json` gains
        `governance_mode` and time-boxed data-plane stanzas while the
        authority-plane invariant remains provable; (3) `contracts/capabilities.json`
        gains share types and trust levels; (4) `contracts/identity-schema.json`
        carries the grant fields; (5) the new ports are declared, including
        `opencode-serve` on 4200 and the share endpoints; (6) `make contract-test`
        and `make validate` are green with both roles updated in the same commit.
      - **Status**: complete, all six verified 2026-10-05.
      - **Assumption to record in the contract, not to leave implicit**:
        isolation severs the **fabric data plane** — KB sync, peer mesh, other
        nodes — while the authority and evidence channel to the Master stays open.
        A severed Master link would leave the required review unsatisfiable: the
        Master agents could never see the flagged evidence. The alternative
        reading, full severance, is recorded in `share-protocol.md` under
        *Isolation* so the choice is visible if the first one proves wrong, and a
        test asserts that alternative is still present.
      - **The authority plane is not widened for this.** Peer-to-peer transport is
        a time-boxed data-plane stanza, because `overlay.json`'s
        `peer_allowed_ips_rule` admits exactly one address and
        `security-policies.json:51` restricts egress to the Master. A sibling on
        the authority plane could present itself as the Master, which is the exact
        confusion the single-address rule exists to prevent. Every governance mode
        is therefore an arbitration of shares and nothing more, which
        `test_authority_plane_invariant_survives_the_governance_modes` enforces by
        failing if the rule is ever reworded to admit more.
      - **The four clocks are machine-readable, not just prose.** They govern
        expiry, so prose alone would drift from the code enforcing them; they live
        in `capabilities.json` as `share_clocks`, and
        `test_share_protocol_durations_match_the_machine_readable_clocks` fails if
        either side moves without the other. Every clock must also state whose
        clock binds it and what expiry does, because a deadline with no specified
        expiry behaviour is not a deadline. `silence_is_an_answer` is recorded as a
        property: there is no "awaiting ratification" state, so an unreachable
        Master causes shares to expire and never to persist.
      - **New tests, each proven by mutation.** Changing `idle_close` to `45m` in
        JSON alone fails the drift test; giving `session-view` an `includes` fails
        the closed-set test (a future type must not silently join a broad grant);
        rewording `peer_allowed_ips_rule` to admit sibling /32s fails the
        authority-plane test; marking `4201` implemented fails the spec-only test.


## Step 8 — Numbered layout for the peer vault, with signed provenance

- [x] **Step 8** — The peer vault becomes a numbered PARA layout with signed
      provenance, ledger-only approvals, key custody rules and an inbox intake
      policy. The transport that would move signed notes between nodes is
      **specified, not built**.
      - **Scope boundary**: execution is `peer-node/` first. `master-node/` is
        read-only until the user decides what to do with it.
      - **Sub-steps**:
        1. [x] contracts: `tracking-schema.json` message/envelope/append/phase
           boundary corrected; `provenance-protocol.md` agrees.
        2. [x] dispatch bridge stops writing the ledger; approvals go through
           the shared tool only.
        3. [x] `shared/sparknet-provenance.py` — keygen, user-init, sign,
           verify, append-approval, verify-vault, secret scan; stale vs invalid
           decided by the contract allowlist, never a delta threshold.
        4. [x] peer skeleton: `00_System`–`07_Archives`, `_staging` stays real;
           `env-init` creates the numbered dirs and the 12 shims.
        5. [x] content moved, shims in place, `PROVENANCE_DIRS` and the charter
           tables updated.
        6. [ ] `00_System/`: `alpha-agent.md`, `user.md`, `schema.yaml`,
           `index.md`, `log.md`, `secrets-index.json`.
        7. [x] `01_Inbox/` intake: `sparknet-provenance.py ingest` lands
           stdin/a file as an unsigned (pending) note, email source failing
           closed against `authorised_senders`. The containerised reviewer
           `peer-node/agents/vault-curator/` stays a placeholder — it is
           peer PLAN Step 5's work and the transport does not exist yet.
        8. [x] peer Makefile: `provenance-verify`, `user-init`, `precommit`,
           `provenance-append`, `ingest`, `shims-check`, `keys-check`.
        9. [x] `secrets-index.json` (empty, schema-pinned) + its tests.
        10. [x] `.gitignore` key patterns (root + peer), fabric-level
            `keys-check`, `.githooks/pre-commit` (`make hooks` activates it
            per clone).
        11. [x] `make user-init` run (U-27689, private key at
            `.state/keys/user.ed25519` 0600); all 7 notes in `03_Sources` and
            `05_Knowledge` got envelopes and now verify `valid`; `shims-check`
            + `keys-check` tests pass (incl. a planted-key refusal end to end).
        12. [x] bookkeeping done (this file, `log.md`, today's session file);
            final gate green: `make test-all`, `contract-test`, `lint`
            (fabric + peer; `master-node` lint stays its 42 pre-existing
            findings, out of scope), `wiki-preflight` (both roles),
            `wiki-verify`, `shims-check`, `keys-check`, `provenance-verify`,
            `bundle ROLE=peer` + `bundle-verify ROLE=peer` all passed.
      - **DoD**: every sub-step's check is observed green in the final gate;
        `peer-node/AGENTS.md` documents the numbered layout and the shim
        mapping; no private key material is committable (`keys-check`);
        `provenance verify` distinguishes `stale` from `invalid` with exit
        codes 0/1/2 as specified.
      - **Status**: complete 2026-10-06. Sub-steps 1–7 by midday; 8–11 (Make
        targets, secrets index, key backstop, signature backfill) plus the
        final gate green in the afternoon. The elected Master is still unbuilt
        and `master-node/` keeps the legacy category layout until the user
        decides what to do with it.



## Step 9 — Master role vault to numbered layout, signed, with an admin surface

- [x] **Step 9** — Mirror the peer migration into `master-node/` (numbered PARA
      layout, shims, signed provenance), and prepare the Master as the
      administrator of the fabric's git, file sharing, NAT and the vector
      embeddings database. The admin services are designed and contracted here,
      **not built** — the Master is not elected, has no signing key in use and
      nothing on this host may claim a listener that does not exist.
      - **Sub-steps**:
        1. [x] move `master-node/sessions/2026-10-05.md` and the `.gitkeep`-
           only legacy dirs into numbered homes; `env-init` creates
           `00_System`–`07_Archives` and the 10 category shims.
        2. [x] `00_System/`: `user.md` template, `alpha-admin.md`, `schema.yaml`
           (pointer-only), `index.md`, `log.md`, `secrets-index.json`; root
           `index.md`/`log.md` shims.
        3. [x] master Makefile: `provenance-verify`, `user-init`, `precommit`,
           `shims-check`, `keys-check`, `provenance-append`, `ingest`.
        4. [x] fabric `make shims-check` runs both roles; the master-legacy pin
           in `tests/test_shims.py` flips to a passing master shims check.
        5. [x] `make -C master-node user-init` + backfill signatures; `make -C
           master-node provenance-verify` exits 0.
        6. [x] admin surface: `contracts/ports.json` gains four `spec-only`
           ports (git, file-share, nat, vector-db), all `bound_by: master`;
           `master-node/docs/master-control-plane.md`, the master charter's role
           paragraph, `MISSION.md` and `MEMORY.md` state the administrator role;
           a `MASTER_ADMIN_PLAN.md` scopes each service as specified-not-built.
        7. [x] bookkeeping + final gate: `make test-all`, `contract-test`,
           `wiki-preflight` (both roles), `wiki-verify`, `shims-check`,
           `keys-check`, `provenance-verify` both roles,
           `bundle ROLE=master` + `bundle-verify ROLE=master`.
      - **DoD**: master's vault verifies signed (exit 0) and its shims match the
        contract; every admin port is `spec-only` with nothing claiming to run;
        fabric gates green.
      - **Status**: complete 2026-10-06. Migration + signed provenance (owner
        `U-97443`, key outside the vault under `$SPARKNET_STATE_DIR` per the
        master charter), admin-second docs, and the four `spec-only` admin port
        contracts all landed; bundle-verify of the master required a fix to the
        master scripts' `PY` default (fall back to `python3` when the excluded
        `.venv` is absent — a pre-existing gap, not caused by the migration).

## Step 10 — Verification audit and claim reconciliation

- [x] **Step 10** — Review every "working part" of both roles against the tree
      and make the plans, statuses and contract prose agree with what is
      actually there. Approval decisions recorded before starting: agx
      deployment deferred (local rehearsal first, hosts later); the election is
      **built** as a new step rather than left as a stub; peer↔peer is deployed
      against a real transport with honest reporting that the sharing regime
      itself is unbuilt.
      - **Sub-steps**:
        1. [x] gates run as a baseline: `validate`, `contract-test`,
           `shims-check`, `keys-check`, `lint`, `provenance-verify` (both roles),
           `test-all`, `bundle` + `bundle-verify` (both roles),
           `wiki-preflight` (all three roots), `wiki-verify`.
        2. [x] one red gate repaired: `make keys-check` failed on a clean tree
           because `tests/test_keys.py`'s own fixtures pasted the PEM literal the
           scanner searches for — the corpus was poisoning the scan. The marker is
           now assembled at runtime (`PEM_MARKER`), both usages rewritten, and the
           scanner itself is unchanged.
        3. [x] `make lint` taken from 42 pre-existing findings to zero, without
           touching behaviour: `ruff --fix` plus hand-edits in four master test
           files (dead header vars, unused imports), re-green after.
        4. [x] Step 4's untested DoD items get real tests — no mask wider than a
           `/32`, a tampered entry never rendered, an expired entry never
           rendered — each **proven by mutation** (remove the renderer's checks
           and watch each fail), then restored.
        5. [x] `master-node/plans/MASTER_BUILD_PLAN.md` reconciled: every
           checkbox in Steps 1–12 had been flipped in one commit while each
           `Status:` still read `pending`; statuses rewritten from evidence and
           boxes returned to `[ ]` where the DoD does not hold (2, 5–12),
           cursor `current: 2`.
        6. [x] stale prose corrected: `contracts/consensus-protocol.md` no longer
           credits Step 14 with the election it never built;
           `master-node/docs/registry-protocol.md` no longer claims the CLI does
           not exist.
      - **DoD**: all gates above green on a clean tree (with
        `peer-node/manifests/user-env-manifest.json` restored after `test-all`'s
        known churn); the reconciled plan's checkboxes are provable from evidence
        in the tree rather than from assertions; every defect found is either
        fixed or recorded in the plan with the reason it was not fixed.
      - **Status**: complete 2026-10-06. Final gate: `make test-all` (197 passed,
        1 skipped at peer level, master and fabric suites green), `make lint`
        ("All checks passed"), `contract-test`, `validate`, `keys-check`,
        `shims-check` all rc=0 with the manifest churn restored. Tree dirty in
        exactly the 14 files this step touched.

## Step 11 — Election and role transition: build it

- [x] **Step 11** — Nothing in the fabric can be Master today: `verify_root`
      checks a root nobody produces, `shared/sparknet-election.py` is a
      22-line request-types scaffold, both election scripts are 4-line stubs, and
      `contracts/ports.json` records 4210 as `spec-only`. Build the conversation
      that turns three votes into a root, a Master and a running signer.
      - **Scope**: this is cross-role by nature and lands as one atomic change —
        `contracts/`, `shared/`, `peer-node/`, `master-node/`, then
        `make contract-test`. Precedent: fabric Steps 8 and 9 spanned both roles.
      - **DoD**:
        (1) `shared/sparknet-election.py` implements vote exchange and root
        formation by **importing** `sparknet-consensus.py` (tally, verify_vote,
        attach_root_signatures) and `sparknet-authz.py` — a test fails if it
        reimplements any cryptography;
        (2) the election exchange has a real home on port 4210 with loopback
        binding and an injected clock, and `ports.json` moves 4210 from
        `spec-only` to `implemented` with a truthful `runtime` axis value;
        (3) unanimity is enforced end to end: three distinct members must sign,
        one member voting three times cannot elect itself, and a member absent
        from the vote means no election rather than a 2-of-3 winner;
        (4) a successful election forms the cluster trust root, starts the signer
        (`make signer-unit`), and the signer refuses to sign under anything but
        the root the election produced;
        (5) `master-node`'s role manifest flips from `peer`-until-elected to
        elected, with **no loss**: the same cluster keys, the same ledger chain,
        the same capabilities and the same signed notes survive the transition,
        asserted by a test rather than asserted in prose;
        (6) the peer's side (`election-request`) is what actually cast the votes
        in the test, so the exchange is proven between two real processes, not
        inside one function;
        (7) admin control after escalation is testable: the elected Master can
        sign and the still-peer cannot — the capability vocabulary did not grant
        either power;
        (8) `make test-all`, `make lint`, `make contract-test` green, and the
        `DoD: confirm: user` items (live ports on the overlay, deployed signer
        containment) are listed as such rather than claimed.
      - **Status**: complete. DoD (1)–(8) verified: `tests/test_election.py` (34
        tests) proves no crypto reimplementation (source + behavioural spies),
        loopback 4210 exchange with injected clock, unanimity refusals, root
        formation only at three signatures, the no-loss install, and the signer
        refusing anything but the elected key/root/node; cross-process and script
        tests (`election-request` + `election-approve`) run the ceremony between
        real processes; `bundle-verify ROLE=peer` runs the bundle including the
        election payloads. `make test-all`, `make lint`, `make contract-test`,
        `make validate`, `keys-check`, `shims-check` all rc=0. Remaining as
        `DoD: confirm: user`, not claims: 4210 bound on the live overlay (this
        host never runs the daemon; implemented + not-listening with `runtime_why`
        on record) and deployed signer containment (Step 18). Step 12 is next.

## Step 12 — Local three-node rehearsal

- [x] **Step 12** — Prove the whole arc on this host before touching the agx
      nodes: three nodes under `/tmp/opencode`, peer-only mode first, then
      election, then root, then signer, then registry, then escalation — and
      after the escalation, the assertions from Step 11's DoD (5) and (7) run for
      real: no information or privilege lost, and the master can act where the
      peer now cannot.
      - **DoD**: the rehearsal is scripted and repeatable, its transcript is
        saved to a dated file, every assertion in it is a test rather than a
        visual check, and a re-run from scratch produces the same result.
      - **Status**: complete 2026-10-07. `scripts/sparknet-rehearsal.sh` builds
        a fresh master bundle, extracts three node trees under
        `/tmp/opencode/rehearsal`, personalises identities (node-alpha/beta/
        gamma, distinct overlay + wireguard keys), mints cluster keys out of
        band, and runs every node in peer-only mode first (validate + identity
        stays `peer` + no trust root). A three-process election then runs against
        the loopback exchange and the formed root is asserted: the winner's
        identity flips to `master` with the operational key held, the losers stay
        peers and write no root doc; Step 11 DoD (5) is checked as a real
        before/after **no-loss** comparison (every unchanged tree file, ledger
        and identity field byte-identical); the isolated signer binds to that
        root and answers the `root-id` of the root alone with capability set
        exactly `["sign"]`; the elected master signs a registry entry (DoD 7)
        that a still-peer verifies by the root's public key alone; and the
        escalation refusals hold live — the loser's own operational key, a node
        the root does not name, and a tampered root are all refused. The
        master-side `sparknet-registry-sign.sh` publishes under the elected key
        and a still-peer verifies that entry by the root alone. 51 checks, 0
        failures each run; transcript
        `/tmp/opencode/rehearsal/rehearsal-2026-10-07.log`. The rehearsal also
        exposed and drove fixes for two real signer CLI defects (see below).
        DoD met: scripted and repeatable, dated transcript, every assertion a
        test, re-runs identical (root ids differ per run via the injected clock;
        assertions compare shapes, not fixed values).
        - **Signer CLI defects caught by the rehearsal, not by the suites**: the
          signer refused to start through its own command line. `--socket` is
          kept as an unconverted string so the `tcp://` scheme check can see it,
          but `check_socket_path` and `serve` then called `Path`-only methods
          (`str.resolve()` / `str.exists()`) on it. Both now normalise with
          `Path(...)` after the scheme check; `tests/test_signer_isolation.py`
          gained a regression test for each (string socket accepted by the
          checker, and the serve transport binding an argparse-shaped string).
          The rehearsal's socket-up gate also now waits for a *real connection*
          (`pong`) rather than a socket file, closing a bind→listen race where a
          client could connect between `bind()` and `listen()` and see
          ECONNREFUSED.

## Step 13 — agx64 / agx32 handoff

- [x] **Step 13** — The two real nodes: peer-nodes on `agx64` and `agx32`,
      peer↔peer tested against a real transport, and the escalation repeated
      there — deferred by user decision until the local rehearsal is green.
      - **DoD**: `DoD: confirm: user` throughout — hosts are unreachable from
        this machine today (SSH timeouts, no agx nodes on the tailnet, no local
        overlay interface), and nothing about their state can be verified from
        here. This step is a handoff document plus the run, not a claim.
      - **Status**: in progress (deferral lifted 2026-10-07). The handoff
        document — `contracts/deployment-runbook.md` — is written: it translates
        the Step 12 rehearsal to real-host mechanics (full-node bundle to all
        three hosts, state-dir cluster keys, overlay before the election, one
        exchange host bound to the overlay, each node's own ceremony, the signer
        via `sparknet-master-signer.service`, staged peer↔peer boundaries since
        ports 4201–4203 remain spec-only) and a confirm-user checklist for the
        run. Preparing the runbook exposed and fixed a real handoff-blocking
        defect: the signer unit's `ExecStart` called a `sparknet-signer.py
        serve` subcommand the CLI does not have (argparse rejected it, so the
        unit would have died on first start after the election) — the unit now
        matches the CLI and a mutation-proven regression test parses the unit's
        own ExecStart against argparse. Stale `master-node/docs/role-transition.
        md` (pre-election "current master approves" flow) rewritten to the built
        unanimous ceremony. **The election half of the run now FORMED
        (2026-10-07)**: the two hosts were installed from a fresh bundle and both
        co-signed the root naming `agx64` (root_id
        `65d9ce25cbb40566b6735b0624d9840dc69ff35d66b3a97543fe650ed09212f5`, 2/2
        signatures, `state: formed`); agx64's master-identity flipped to
        `role: master`, agx32 stayed `peer` (`not_elected`, exactly right). One
        marked deviation: the overlay could not carry the ceremony — UDP does not
        cross the 192.168.10/20 boundary at this machine (the gateway), only
        TCP/22 does, so the WireGuard handshake never completed and the exchange
        was reached by SSH loopback tunnels to a `serve` on the fabric root
        (trustless by design; keys stayed on the hosts; port 4210 never left
        loopback). **Transport now solved (2026-10-07, Gateway Decision)**:
        this gateway ships no kernel firewall tooling and this session has no
        root, so per the operator's choice a **userspace UDP relay** stands in
        for the UDP 51820 open (`/tmp/gateway_udp_relay.py`, binding
        192.168.10.1:51820 + 192.168.20.1:51820, forwarding between the hosts;
        no root needed) and both wg peers re-point at the gateway IPs. The
        overlay now **handshakes and pings through real NICs** (received bytes
        >0 both sides, 0% loss ~2 ms; required adding the peer /32 kernel
        routes wg-quick would have made — AllowedIPs create none). **Phase 6 —
        the signer is now LIVE via `sparknet-master-signer.service`**: the
        master role root was staged at `/root` (so the unit's `%h` resolves),
        state dir + keys moved to `/root/.local/state/sparknet/master-node`,
        the root object extracted to `trust-root.json`, and `/root/.env` sets
        `SPARKNET_NODE_ID`/`SPARKNET_STATE_DIR` plus a PATH preferring
        `/root/.venv` (host system python3 is 3.8.10 + cryptography 2.8 and
        would break `removesuffix` and the `>=42` pin; venv is 3.9.5 +
        50.0.2). Asserted live: socket 0600, root-id → `65d9ce…`,
        capabilities → `["sign"]`, restart survives, single key-holder.
        **Phase 7 — registry + escalation live**: the signer signed a registry
        entry for agx32 over the socket (verified by the root's master_pubkey
        alone), all three refusals hold on the deployed unit (wrong key /
        unnamed node / tampered root), and `sparknet-registry-sign.sh` wrote
        `manifests/node-authorizations.json` (verifiable by the root alone).
        **Phase 8 — peer↔peer, honestly bounded**: the signed registry + root
        were delivered to agx32, which verified the entry with its OWN
        `shared/sparknet-authz.py` and matched its fingerprint; no *share*
        claimed (4201–4203 remain spec-only). **C4 revoke-demo run live
        (2026-10-07, then restored)** — surfaced + fixed two artifact defects:
        agx32's `master-ed25519.pub.b64` was a placeholder key (would fail every
        signature check) and both hosts' `node-authorizations.json` were bare
        entries while the guard needs the wrapped `authorizations:[...]` registry;
        after fixing, one socket signature with `revoked: true` (ledger block
        `64717431…`) made the peer `allowed: false reason: revoked caps: []`, its
        guard `--status` show `capabilities: []`, reject a signature-VALID master
        packet with `403 capability_missing`, and `wg-render-master` drop the
        peer's stanza; a fresh `revoked: false` signature (`b3200847…`) restored
        the pair. **C2 reboot proven (2026-10-07)**: ran a real
        `shutdown -r +1` on agx64; host back in ~60 s; signer unit returned
        `active` (enabled, unit-spawned PID 1763), socket `root-id` == `65d9ce25…`,
        `capabilities ["sign"]`, `public-key` == the root's `master_pubkey`
        (`r+ZjGb…`), ledger `84f090a8→64717431→b3200847` intact, peer
        authorization still verifies (`allowed: True, caps: [guard-apply,
        telemetry]`), overlay ping 0% loss both ways once restored. **New ops
        caveat**: wg0 does NOT survive reboot on the tegra host
        (`CONFIG_WIREGUARD=n`; overlay runs on userspace `wireguard-go`, started
        ad hoc) — `/root/scripts/sparknet-wg-restore.sh` (idempotent) written and
        proven; making the overlay a unit, or including the restore step in the
        aggregate's "up" check, is now a Phase 9/ops item. Also caught: the
        signer's single-threaded `_serve_one` has no client timeout (a connection
        that never sends `\n` occupies the only accept slot) — worth a robustness
        fix if the surface grows. Still open before the step can complete: Phase 9
        (rollback/re-formation/revocation — not executed, destructive) and the
        runbook's **confirm-user list** (C1–C6 in
        `/mnt/log/sparknet-handoff-2026-10-07-confirm.md`). **C1/C3/C5 answered
        with live probes (2026-10-07)**: overlay rides real NICs to the gateway
        relay (routes `dev wg0`, endpoints `dev eth0`, handshakes seconds old,
        ping ~2 ms 0% loss both ways) on userspace wireguard-go (tegra
        `CONFIG_WIREGUARD=n`); exactly one process holds `operational.ed25519`
        (signer PID 5063, fuser confirms no other fd holder, key 0600); deployed
        signer containment confirmed (socket `srw-------` 0600 unix-stream owned
        by the signer, no TCP listener, `--describe` caps `["sign"]` + 10 refuses,
        `check_socket_path` exercised on the deployed module refuses `tcp://` and
        outside-state-dir paths, no peer service imports the signer or references
        signer.sock, parity unit asserts `not_reachable_from_here`). All six
        C-rows answered. The step cannot complete until the operator acknowledges
        the answers and decides on Phase 9. Transcript:
        `/mnt/log/sparknet-handoff-2026-10-07.md`.
      - **Status: COMPLETE 2026-10-07 — operator acknowledged and closed Phase 9
        by decision ("acknowledge / proceed" + "Close without exercising").**
        All six confirm-user items answered: C1/C3/C5 by live probe, C2 by a real
        reboot, C4 demoed (with two artifact defects found & fixed), C6
        acknowledged as understood-not-exercised by operator choice. Phase 9's
        destructive legs (rollback, replace-Master re-formation) remain
        documented-but-unexecuted, per operator decision, so the live pair stays
        up; the wg0-not-reboot-safe caveat (`/root/scripts/sparknet-wg-restore.sh`)
        is the noted ops input to any future teardown. Runbook deliverables: the
        dated transcript at `/mnt/log/sparknet-handoff-2026-10-07.md` (3 addenda)
        and the answered confirm-user list at
        `/mnt/log/sparknet-handoff-2026-10-07-confirm.md` — both landed. The
        roadmap work from Step 13 onward is role-scoped (see `## Next`);
        Step 14 below is the single fabric-level exception, opened 2026-10-08.


## Step 14 — fabric claims conformance and the `--help` contract

- [x] **Step 14** — Consume the drift class from this session: stale/false master-status claims on live surfaces *and* the unenforced `--help` contract at fabric level.
      - **DoD**: (1) `README.md`, `index.md`, `PLAN.md`, `Makefile`, `AGENTS.md`, `MASTER_BUILD_PLAN.md` preamble all state current truth (Steps 15–18, signer alive, skills=33); forbidden phrases absent (`signs nothing yet`, `holds no usable key`, etc.); (2) every `scripts/*.sh --help` → rc0 + usage + zero disk writes; rehearsal has an explicit guard **before** it ever touches `/tmp/opencode`; (3) new regression tests: `tests/test_shell.py::test_fabric_every_script_has_help` (rehearsal dir stays empty on --help) and `tests/test_claims.py` asserting skill-count == disk count, forbidden-phrase absence in live docs, and index.md contracts table completeness; (4) `make test-all`, `bundle-verify` both roles green.
      - **Status**: complete 2026-10-08. DoD (1) README/index/PLAN/Makefile/
        AGENTS + the MASTER_BUILD_PLAN preamble restate verified truth
        (Steps 15–18 built, signer live on agx64, 33 skills) and
        `tests/test_claims.py` proves the forbidden phrases stay absent,
        the documented skill count equals what ships, and index.md's
        contract table names every `contracts/` file. DoD (2) all 33 shell
        scripts plus the five `shared/` CLIs exit 0 with usage and write
        nothing — rehearsal now guards *before* `mkdir`/`tee`, the master's
        killswitch and keygen before their side effects (keygen --help used
        to generate keys). DoD (3) `test_fabric_every_script_has_help`
        (with a repo-porcelain and no-rehearsal-dir check per script),
        `test_every_shared_cli_has_help`, the two rehearsal-specific tests,
        and `tests/test_claims.py` (4 tests) all exist and pass. DoD (4)
        `make test-all` green — fabric 633 passed/3 skipped, peer 198/1,
        master 119, contract suite green — and `make bundle-verify` green
        for both roles, alongside lint/validate/keys-check/shims-check/
        wiki-verify(33)/wiki-preflight. Cursor `current: done`: no `[ ]`
        step remains at the fabric level.

## Hardening batch (2026-10-09, all committed locally, no push)

A four-finding batch raised out of the Step 14 audit and the live agx64/agx32
arc. Steps 15 and 20 were optioned `current: done` + recorded in the session
memory; 16 and 17 closed this session. All commits are local only
(`origin/main` still 0/0 ahead — `GITHUB_PUSH_BLOCKER` stands).

- [x] **Step 15 — harden service timeouts + guard fixes** (F4, F6, F7, F10, F12,
      F13). DoD: the service-timeout cluster (silent client wedges the signer
      slot — later superseded by Step 20's real fix), the guard's timeout and
      request-size floors, and the argument-ordering / lockstep guards landed as
      mutation-proven changes; full gates green. Commit `f1b790c`.
- [x] **Step 16 — chained supersession of a cluster trust root, policy B**
      (closes the F1 ordering gap). DoD: `previous_root_id` joins the signed
      root fields (genesis = `""`); the `verify_root` trust path refuses an
      unchained root (`REASON_UNCHAINED`), a chained root that adds a member,
      and a chained root below the minimum; `verify_chain(roots)` verifies a
      pulled lineage newest-first to genesis; the signer's `check_not_reverted`
      is monotonic (adopts a chained descendant without a flag, refuses a
      stranger or a rollback without `--accept-requalification`);
      `SCHEMA_VERSION` → 1.1; contracts (`consensus-protocol.md`,
      `identity-schema.json`, `capabilities.json`, `ports.json`) and
      `PAIR_REFORMATION_DESIGN.md` state policy B; gates green (fabric 649
      passed/3 skipped, master 125, peer 204/1); chain + member-subset guards
      mutation-proven. Commit `b0126ce`. **DoD: confirm: user** remains for the
      two items the batch did not build: the reduced-membership re-formation
      (F2) and live cross-node sync of re-formed roots (F3) — both stay spec-only.
- [x] **Step 17 — MCP/A2A design doc at the fabric root, design-only.**
      DoD: `MCP_A2A_DESIGN.md` at the fabric root (NOT in `contracts/`) states
      `status: "design proposal, not a contract change"`, maps MCP (tool-calling
      inside one agent, server-side) vs A2A (the existing signed transport +
      grants, overlay-only), and commits to adopting any part of it only in its
      own commit with `make contract-test` green. Uncommitted until batch commit.
- [x] **Step 20 — signer per-client read timeout + serialised key use.**
      DoD: a silent client is answered `{ok:False, error:"timeout"}` after the
      read deadline and the connection closed while a second client is served in
      parallel; exactly one signer lock keeps the single-key holder + chain
      ordering invariant; mutation-proven via a deterministic serialising
      transport fake. Commit `bc518d6`. **DoD: confirm: user** — redeploy of the
      changed signer to the live agx64 pair is not done (batch-end operator
      decision).

**Deploy record (2026-10-09, operator-authorized).** The Step 15/16/20 changes
are now **live on the agx64/agx32 pair**, not just local. agx64 (Master) runs the
hardened signer under the unchanged root `65d9ce25…` (socket `root-id` +
`capabilities ["sign"]` re-asserted after restart, ledger intact); a silent client
now gets `{"ok": false, "error": "timeout"}` and a second client is served in
parallel (Step 20 proven live). agx32 (peer) has the matching
`shared/sparknet-consensus.py` + `sparknet-election.py` and verifies the same root
id under its own Python. Originals are backed up on both hosts
(`/root/sparknet-deploy-backup-*` on agx64, `~/sparknet-node/.deploy-backup-*` on
agx32). The deploy exposed a **field-only defect the suites could not**: on the
hosts' Python 3.9.5, `socket.timeout` is *not* `TimeoutError` (they unified in
3.10), so Step 20's `except TimeoutError` let a silent client's timeout escape,
killed the serving thread and closed with a bare EOF. Fixed in `7fa03b9`
(`except (TimeoutError, socket.timeout)` + a regression test) and re-verified live.
The batch's build decisions (F2/F3) moved to **Step 21**; push status is recorded
in `GITHUB_PUSH_BLOCKER`.

## Step 21 — Reduced-membership re-formation (F2) and live cross-node root sync (F3)

- [x] **Step 21** — Step 16 built the chained-supersession *policy*, the signer's
      monotonic adoption and `verify_chain`, but two halves stayed spec-only and
      were recorded as `DoD: confirm: user` on Step 16. Build them here; they are
      cross-role and contract-touching, so they belong at the fabric level.
      - **F2 — reduced-membership re-formation**: re-form a trust root with a
        member removed. The new root is a chained descendant (`previous_root_id`
        = the parent) whose member set is a **strict subset** of its parent's;
        unanimity now means all *surviving* members, and the removed member's
        signature is neither required nor accepted.
      - **F3 — live cross-node root sync**: deliver a re-formed root to the
        peer(s) so each verifies it with **its own** `shared/sparknet-consensus.py`
        and adopts it monotonically (no rollback), rather than only in-process.
      - **DoD**:
        (1) F2 — a test drives a real N→N-1 re-formation through the election
        exchange: the new root chains to its parent by `previous_root_id`, names
        exactly the surviving members, is signed by every survivor and none else;
        `verify_root`/`verify_chain` accept it, while a root that still names the
        removed member, or omits a survivor's signature, is refused;
        (2) F3 — the re-formed root reaches a second real process (the peer) that
        verifies it with its own consensus copy and adopts it; the peer refuses a
        rollback to the parent and a stranger fork;
        (3) both legs mutation-proven — break the subset, chain or unanimity
        guard and watch a named test fail;
        (4) `contracts/consensus-protocol.md` and `PAIR_REFORMATION_DESIGN.md`
        agree with the built behaviour (and with the Step 16 policy-B text);
        (5) `make test-all`, `make lint`, `make contract-test`, `validate`,
        `keys-check`, `shims-check` green; live deploy to agx64/agx32 is
        `DoD: confirm: user` (operator authorizes it, as with the 2026-10-09
        deploy).
      - **Status**: complete 2026-10-10 (build + tests + docs), except live deploy.
        Chose **option B full** (design-doc shape). Schema bumped to **1.2**:
        `shared/sparknet-consensus.py` gains the signed `epoch` field, a
        version-aware signed-field set (1.0 / 1.1 / 1.2 all verify against their
        original bytes and ids), the removal-proof primitives
        (`canonical_removal_proof` / `sign_removal_proof` /
        `verify_removal_proof`, kinds `revocation` and `attested`), and the trust
        path checks epoch (parent+1) and exact-removal (dropped set ==
        evidenced set). `shared/sparknet-election.py` threads `previous_root_id`,
        `epoch` and `removal_proofs` through `build_root` / `ElectionExchange` /
        `serve` (new `--trust` / `--removal-proofs`), and a `_load_held_root`
        helper. F2 tests drive a real N→N-1 re-formation through the exchange and
        the accept path (both refusal directions: named-removed-member,
        omitted-survivor, missing/extra/wrong-parent/forged proof, wrong epoch,
        1.1→1.2 migration seam). F3 delivers the re-formed root to a **real peer
        process** — the shipped `accept` subcommand in its own interpreter with
        its own `shared/sparknet-consensus.py` — which adopts it and refuses both
        a rollback to the parent and a stranger fork. Mutation-proven: breaking
        the chain, subset, removal-proof-completeness or survivor-unanimity guard
        each makes a named test fail. Docs reconciled: `contracts/consensus-protocol.md`
        (§Re-formation rewritten to adopted policy B), `contracts/identity-schema.json`
        (1.2 fields, `epoch`, expanded acceptance rules, `on_blocked_election`),
        and `master-node/plans/PAIR_REFORMATION_DESIGN.md` (Q1 adopted and built).
        Gates green: `make test-all` (fabric 700 passed/3 skipped; master 135;
        peer 352/1; contract 70/1) EXIT=0, `make lint`, `make validate`,
        `make contract-test`, `make keys-check`, `make shims-check`.
        **`DoD: confirm: user`** — live deploy of a re-formation to agx64/agx32
        (operator authorizes it, as with the 2026-10-09 deploy).

## Step 22 — KDE Connect notifications

- [x] **Step 22** — Add a KDE Connect notification plugin that alerts on agent questions, permission prompts, and session idle. The notification surfaces to paired, reachable devices so operators stay aware of prompts without blocking the terminal.
      - **DoD**: (1) `scripts/plugins/kde-notify.ts` exists with hooks for `tool.execute.before`, `permission.ask`, and `session.idle`; it calls `kdeconnect-cli --ping-msg` via the BunShell API, uses dynamic device discovery via `kdeconnect-cli -a --id-only`, and supports optional env override `SPARKNET_KDE_DEVICES`; it is reachable only through `scripts/plugins/kde-notif.opencode.json` via `OPENCODE_CONFIG` (`make tui`) — **not** through `opencode.json` or `.opencode/plugin*/` auto-discovery, because opencode 1.18.35 hangs when it starts from a role worktree with any plugin in an inherited scope; (2) a guard test in `tests/test_plugin.py` verifies the plugin has all three handlers, uses kdeconnect-cli, hardcodes no secrets or vault paths, uses `.text()` on buffers, calls `.nothrow()`, passes, AND asserts the plugin stays out of every inherited scope plus an integration guard that `opencode agent list` returns from `peer-node/` and `master-node/` (no role-worktree hang); (3) `make lint`, `make validate`, `make keys-check`, `make shims-check`, `make wiki-preflight` and the fabric `tests/` suite green; `make test-all` to be re-run once per build gate (skipped on demand per operator instruction 2026-10-09); (4) manual verification: trigger a question and permission prompt while KDE Connect is running on raxxarMobile + Galaxy Tab A 2016, confirm both devices ping without session blocking.
      - **Status**: complete 2026-10-10. DoD 1–3 were already in place (plugin + `kde-notif.opencode.json` + `tests/test_plugin.py`, 12 tests); this session closed **DoD 4 live**: both devices — raxxarMobile and Galaxy Tab A 2016 — are now **paired and reachable**, and the plugin's exact path (`kdeconnect-cli -a --id-only` discovery → `kdeconnect-cli -d <id> --ping-msg "sparknet: …"` notify) returned **rc=0 for both** (the Tab's pairing was accepted this session after a host-side `--pair` request). Non-blocking is by construction (`.nothrow()` + a swallowed catch), unit-locked. Gates: `tests/test_plugin.py` 12 passed; `make lint`, `make validate`, `make keys-check`, `make shims-check`, `make wiki-preflight` all rc=0. Cursor 22→23.
      - **Notes**: notifications fire per-turn ("session complete" = turn yield), notify only when permission resolves to "ask", never block on failures. Root cause of the hang: opencode 1.18.35 busy-loops (~40% CPU, no output) activating a plugin for a nested location; content-independent (even a no-op plugin hangs). The handler paths are proven by the live device notification above (both IDs discovered, both pinged); the `question`/`permission.ask` trigger rides the same `notify()` call.

## Step 23 — Second parallel pair + fresh election (node131/node133)

- [x] **Step 23** — Stand up a second, fully independent sparknet pair from the current working tree and run the full deployment arc (overlay → roster → election → isolated signer → signed registry → bounded proof) on real hosts, without touching the existing live agx64/agx32 cluster.
      - **DoD**: (1) a `make bundle ROLE=master` archive of the dirty working tree is installed on both fresh hosts under a private install dir (`~/sparknet-cluster2`) with a distinct state dir (`~/.local/state/sparknet/cluster2`); (2) the contract overlay (`wg1`, `10.100.0.1/32`↔`10.100.0.2/32`, userspace `wireguard-go`, listen 51820) handshakes and pings bidirectionally on real NICs; (3) `cluster-members.json` with 2 members (node_id/fingerprint/wireguard_pubkey/cluster_pubkey) and `make -C peer-node validate` green on both; (4) the election forms a 2/2 root with `previous_root_id ""`, node131 as Master, node133 a peer (`not_elected`); (5) a **distinct** system unit `sparknet-master-signer-c2.service` runs against the isolated state dir (root-id == formed root, capabilities `["sign"]`, restart-surviving) while the old `sparknet-master-signer.service` and `/root/…/trust-root.json` (agx64) stay untouched; (6) the isolated signer signs a registry entry for still-peer node133 and the peer verifies it by the root alone, while three master-side escalation refusals hold (loser key, unnamed node, tampered root); (7) node133 reaches the master over `wg1` with granted caps `telemetry,p2p-sync,push-receive` and holds no private Master key; (8) a dated transcript lands in `/mnt/log/` with a confirm-user checklist; the destructive Phase 9 legs are left documented-but-unexecuted, and every host-visible claim is `DoD: confirm: user`.
      - **Status**: complete 2026-10-10. Executed live on 2026-10-09 (nodes 192.168.178.131/.133) — all phases 0–8 green; transcript `/mnt/log/sparknet-cluster2-2026-10-09.md`. The host-visible checklist (wg1 ping .1↔.2, `sparknet-master-signer-c2.service` active on .131, Phase 9 left unrun) was put to the operator, who could not confirm it directly but **directed 2026-10-10 to treat Step 23 as passed** ("assume all checks for step 23 passed"); the checks were **not independently re-verified** this session. Phase 9 deliberately not executed. This is a proof clone, not a promotion: no existing cluster state was repointed, and the temporary overlay must not run concurrently with the live cluster's `10.100.0.0/24`. Cursor 23→24.

## Step 24 — Signed delegated-compute capability (design proposal)

- [x] **Step 24** — Spec a `compute-serve` capability so a peer can execute a Master-signed compute task over the overlay and return an attested result, without gating a node's own (already-free) local compute.
      - **DoD**: (1) a design proposal `COMPUTE_CAPABILITY_DESIGN.md` sits at the fabric root (design-proposal status — binds nothing) and states the tension it must resolve: local compute is already free and must **not** be gated, so the capability is `compute-serve` (accept signed delegated work), not `compute`; (2) it specifies the capability's two-place addition (`contracts/capabilities.json` + the hard-coded `KNOWN_CAPABILITIES` in `shared/sparknet-authz.py`, which `tests/test_contracts.py` proves equal), the Master's typed signer op `sign-compute-task` (modelled on `_sign_guard_approval`, never "sign bytes"), the task/result envelopes, the ordered fail-closed verification, the closed operation whitelist, the port decision, lifecycle (nonce/expiry/ledger/revocation), and a worked 2−2 round trip; (3) options considered are recorded with reasons; (4) **nothing is adopted** — no capability added, no port bound, no role changed — and a follow-on adoption plan is named with live deploy `DoD: confirm: user`; (5) `make validate`, `lint`, `contract-test`, `test-all` and the claims/layout suites stay green.
      - **Status**: complete 2026-10-10 as a **design proposal** (spec written 2026-10-09, mirrors Step 17's status). `COMPUTE_CAPABILITY_DESIGN.md` at the fabric root carries all DoD sections (capability, `sign-compute-task` signer op, task/result envelopes, ordered fail-closed verification, closed operation whitelist, port decision, lifecycle, a worked 2−2 round trip, options considered, adoption plan). **Nothing is adopted**: `compute-serve` is absent from `contracts/capabilities.json` and `KNOWN_CAPABILITIES` (verified), the closed vocabulary is `telemetry, p2p-sync, push-receive, guard-apply, cluster-vote, cluster-dispatch, cluster-serve`, and no port or role changed. Adoption is a separate commit with live deploy `DoD: confirm: user`. Cursor 23→24.

## Step 25 — Cluster inference design + reserved vocabulary (design proposal)

- [x] **Step 25** — Spec the `sparknet-cluster` prompt: every node runs its own
      model + Open WebUI, a prompt can be sent to a chosen node or fanned out to
      the whole cluster, cluster jobs retrieve from the Master's shared vector DB
      while local prompts use the local vault, and jobs are recorded in the
      initiator's and Master's sessions.
      - **DoD**: (1) `CLUSTER_INFERENCE_DESIGN.md` sits at the fabric root
        (design-proposal status, precedent = `MCP_A2A_DESIGN.md` and
        `COMPUTE_CAPABILITY_DESIGN.md`) and specifies the `sparknet.cluster-job`
        / `cluster-result` envelopes, the four division modes
        (`decompose`/`shard`/`best_of_n`/`mixture`), the reduce/contribution-map
        re-forming rule, the mode-dependent authority (Master-ratified at n≥3,
        direct signed initiator at n=2), the local-vs-shared knowledge split, the
        Open WebUI cluster interface, session recording on initiator + Master +
        participants, Docker packaging, and the security boundary (inference
        auto-executes; actions stay guard/PPE-gated); (2) the two capability
        **names** `cluster-dispatch` / `cluster-serve` are reserved in both
        places (`contracts/capabilities.json` + the hard-coded
        `KNOWN_CAPABILITIES` in `shared/sparknet-authz.py`) with `cluster-serve`
        as the second `sensitive: true` capability after `guard-apply`; (3)
        options considered are recorded with reasons (no multicast bus, no
        Master-run remote execution, no tensor-parallel sharding in v1, no vector
        DB replication); (4) **nothing beyond the vocabulary names is adopted** —
        no port, service, signer op or role changed — and the adoption plan names
        each follow-on with live deploy `DoD: confirm: user`; (5) `make
        contract-test`, `make validate`, `tests/test_layout.py` and
        `tests/test_claims.py` stay green.
      - **Status**: complete 2026-10-10 as a **design proposal + reserved
        vocabulary** (spec written 2026-10-09). `CLUSTER_INFERENCE_DESIGN.md` at
        the fabric root carries all DoD sections (job/result envelopes, the four
        division modes, the re-forming rule, mode-dependent authority, the
        local-vs-shared knowledge split, the Open WebUI interface, session
        recording, Docker packaging, the inference-auto-executes/actions-guarded
        boundary, options, adoption plan). The two capability names are reserved
        in **both** places — `cluster-dispatch` and `cluster-serve` in
        `contracts/capabilities.json` (`cluster-serve` the second
        `sensitive: true` after `guard-apply`) and in the hard-coded
        `KNOWN_CAPABILITIES` in `shared/sparknet-authz.py` (verified) — inert
        until the Master signs a registry entry carrying them. The envelopes,
        services, ports and role behaviour are **not** adopted; the typed
        `sign-cluster-job` signer op and the node AI stack are the separately
        adopted increments (Steps 26 and 27). Adoption of the remainder rides the
        design's "Where this lands" list, each in its own commit with live deploy
        `DoD: confirm: user`. Cursor 24→25.

## Step 26 — Typed `sign-cluster-job` signer operation

- [x] **Step 26** — Build the typed signer operation a cluster job is ratified
      with, and its single canonical projection in `shared/`, so the signer and
      the future verifier cannot drift the way `sign-guard-approval` and the
      guard did.
      - **DoD**: (1) `shared/sparknet-authz.py` gains `CLUSTER_JOB_MODES`,
        `CLUSTER_JOB_FIELDS`, `CLUSTER_JOB_REQUIRED`, `cluster_job_message()`
        and `is_expired()` as the *one* canonicalisation of a job — a fixed
        field projection (sort_keys + tight separators), refusing a missing
        required field, an unknown mode and an empty partition, and
        fail-closing an unparseable expiry; (2) `master-node/services/sparknet-signer.py`
        answers the typed `sign-cluster-job` op (added to `SIGN_OPERATIONS`,
        modelled on `_sign_guard_approval`), rebuilds the canonical envelope
        itself and never signs caller-supplied bytes, refuses a missing job /
        missing fields / empty partition / unknown mode / expired-or-unparseable
        expiry, discards a caller-supplied signature, and records the signature
        to the ledger; (3) `master-node/tests/test_signer_isolation.py` proves
        the signature verifies over the canonical projection, that changing a
        `subtask` invalidates it, and each refusal; (4) `CLUSTER_INFERENCE_DESIGN.md`
        records the op + projection as the second adopted increment; (5) gates
        green: `make contract-test`, `make validate`, `make lint` and the master
        signer suite.
      - **Status**: complete 2026-10-09. Adopted increment of the Step 25 design.
        The op has **no caller yet** — it is the instrument the later cluster
        client/reducer (design step 5) will use; nothing is dispatched by it and
        no capability is granted by it. Cursor stays `22` (Step 22 still open).

## Step 27 — Node AI stack (design item 3, slice A: own inference, declared)

- [x] **Step 27** — The peer node's own AI stack as committed config, the
      peer-side slice of the cluster design: every node runs its own model
      server and its own chat surface, and the stack must not be able to reach
      authority.
      - **DoD**: (1) `peer-node/configs/ai-stack/docker-compose.yml` declares
        exactly `ollama` (`:11434`, OpenAI-compatible at `/v1`) and
        `open-webui` (`:8080`, `OLLAMA_BASE_URL` = the compose service
        `http://ollama:11434`, `RAG_INGESTION_ENABLED=false`, `WEBUI_AUTH=true`,
        signup disabled), both bound to `127.0.0.1` only, no GPU declared, the
        vault named as the only knowledge base; (2) `peer-node/manifests/ai-stack.json`
        declares the bound claims (loopback-only, own-server-only, no authority,
        no key/signer/`SPARKNET_STATE_DIR` mount) and
        `peer-node/tests/test_node_ai_stack.py` asserts them read off the files;
        (3) `make ai-stack-config` validates via `docker compose config
        --quiet` with no images pulled; (4) `make contract-test`, `validate`,
        `lint`, the peer suite (215 passed/1 skipped) and `make bundle-verify
        ROLE=peer` stay green with `configs/ai-stack/` and the test bundled; (5)
        task ingress is deferred to design item 5 (cluster client + reducer) and
        recorded, not silently dropped; (6) the running healthcheck (pull/run on
        a target node, both surfaces answer with no GPU) stays
        `DoD: confirm: user` and nothing is claimed as live.
      - **Status**: complete 2026-10-10 for the composed/declared slice,
        mirroring the admin-surface pattern (`master-node/configs/admin-surface`
        + `manifests/admin-surface.json`). Declared, not deployed — no image
        pulled, nothing binds 11434/8080. Tracks peer PLAN Step 9; cursor stays
        `22` (Step 22 still open).

## Next

The split is the last structural step. After this, roadmap work is role-scoped:
`master-node/plans/MASTER_BUILD_PLAN.md` for anything the Master must actually
build, `peer-node/PLAN.md` for the peer. Fabric steps (Steps 10–14 above) are the
exceptions — work that touches contracts and both roles at once belongs here.

**A green fabric is not a finished Master.** The election/signer arc is proven
live (agx64/agx32, 2026-10-07: signed registry entry, revoke/restore, reboot
survival), but the Master build plan's Steps 2 and 5–12 are unbuilt, the admin
page is declared and not bound, and the registry ships **empty** on purpose —
fail-closed until the Master signs each grant.

Container packaging, the bridge, session grants, conversation passing, the
sharing regime and `MASTERSPIKE` are peer-side work and are tracked in
`peer-node/PLAN.md` Steps 2–8. The Master's ratification, review and
evidence-repo work is tracked in `master-node/plans/MASTER_BUILD_PLAN.md`.

## Standing verification rules

These are not aspirational; each one exists because its absence already cost a
wrong conclusion or a false green.

1. **Read large tool output through a file, never a pipe.** `opencode agent list`
   is ~9 MB and a non-seekable stdout silently drops the tail, which once made a
   working agent look dead.
2. **No step's DoD may assert something not directly observed.** Step 5's DoD was
   written on a premise that turned out false, and would have "verified" it
   forever.
3. **A DoD names what it freshly built.** `make bundle-verify` once verified a
   stale archive from three days earlier and reported success.
4. **A judgement no machine can make is `DoD: confirm: user`**, never a silent
   pass.

## Step 28 — Per-user knowledge vaults (design) + cross-node admin channel

- [x] **Step 28** — Record the per-user vault design at the fabric root and
      reserve the cross-role surface it needs: each approved node user gets a
      private `peer-<user_id>` knowledge-vault copy and an owned KB; the
      Master's admin supervises all nodes' users/KBs over the fabric's signed
      transport.
      - **DoD**: (1) `PER_USER_VAULTS_DESIGN.md` exists at the fabric root and
        records the three surfaces (peer copy, user KB, `master-<id>`), the
        knowledge-vault slice rule, the approval trigger, the per-user KB grant
        shape, and the exclusion list; (2) the design notes the **new
        capability** the bridge admin channel needs (e.g. `admin-supervise`) as
        *proposed, not adopted* — nothing in `contracts/` or
        `shared/sparknet-authz.py` changes in this step; (3) the `master-<id>`
        rule is recorded as **inactive** (elected-Master + admin signed in; not
        met by `.131` in the cluster2 pair); (4) `make contract-test` and the
        fabric suite stay green with only this design doc + plan edits.
      - **Status**: in progress. Design doc written 2026-10-11; adoption of the
        capability and the bridge admin route lands in its own commit after the
        peer provisioner is live.

## Step 29 — Cross-node admin federation (design → build)

- [ ] **Step 29** — Make the Master the one place an administrator signs in and
      supervises every node's Open WebUI users, privileges and activity over the
      signed fabric transport, with admin login impossible on a peer.
      - **DoD**: (1) `ADMIN_FEDERATION_DESIGN.md` exists at the fabric root and
        records the signed-federation architecture, the operator decisions
        (signed federation; signup+pending; console feed + KDE push; successful
        logins only + full control), the `admin-supervise` capability as
        adopted-in-vocabulary, and admin-only-on-master enforcement;
        (2) Phase 1 lands: the node AI stack enables signup with
        `DEFAULT_USER_ROLE=pending` and a node-local admin agent
        (`peer-node/services/sparknet-admin-agent.py`) ingests the Open WebUI
        auth-event webhooks to a 0600 spool, registered through the node's own
        admin API; (3) `admin-supervise` adoption (contracts + `shared/` + bridge
        `/admin/*` + signer `sign-admin-request`) lands in exactly one place as
        the vocabulary rule requires; (4) the live legs (real pending signup,
        Master approval over the overlay, KDE push, no human admin on a peer)
        are `DoD: confirm: user`.
      - **Status**: in progress. Phases 0–4 landed 2026-10-12 as code + signed
        plumbing — the design page, compose + admin agent, the capability
        adoption (contracts + `shared/` + signer `sign-admin-request` + bridge
        `/admin/*` route, inert until the node's registry grants it), and the
        Master console (`master-node/services/sparknet-admin-console.py`) with
        its `list_events` event feed and KDE `--ping` push, wired as
        `make console`. Phase 5 (the live deploy on `.131`/`.133`, incl. the
        loopback→overlay binding change that turns the overlay-reachable
        `/admin/*` surface on) remains; every live leg is `DoD: confirm: user`.
        The Phase 5 procedure is `contracts/admin-federation-runbook.md`
        (2026-10-12); recon against the live cluster2 trees surfaced **F1** —
        the binding change is not code-free: the bridge declares no
        local-personality route class (`loopback_only_routes = ()`), so the
        overlay bind must land with a route-class change or it exposes the
        env-profile-injecting routes to the fabric. Host move: the two nodes
        are now `agx64`=192.168.178.131 (`red-team`) and
        `agx32`=192.168.178.133 (`blue-team`) on the `192.168.178.0/24` LAN;
        the old `192.168.10.64`/`192.168.20.32` legs are retired.
      - **Depends on**: Step 28 (per-user vaults + the proposed admin channel).

## Next

The split is the last structural step. After this, roadmap work is role-scoped:
`master-node/plans/MASTER_BUILD_PLAN.md` for anything the Master must actually
build, `peer-node/PLAN.md` for the peer. Fabric steps (Steps 10–14 above) are the
exceptions — work that touches contracts and both roles at once belongs here.

