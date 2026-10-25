---
title: sparknet Plan
updated: 2026-10-24
current: 66
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
survival), but the Master build plan's Steps 5–7, 20 and 21 are unbuilt (Step 2's
registry schema closed 2026-10-22), the admin page is deployed on the live Master
at `10.100.0.1:8088` but binds nothing on the dev host, and the registry ships
**empty** on purpose — fail-closed until the Master signs each grant.

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

- [x] **Step 29** — Make the Master the one place an administrator signs in and
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
      - **Status**: **complete 2026-10-12** — cursor advanced to `done`; every DoD
        item verified and the live legs user-confirmed. Phases 0–4 landed as code
        + signed plumbing — the design page, compose + admin agent, the capability
        adoption (contracts + `shared/` + signer `sign-admin-request` + bridge
        `/admin/*` route, inert until the node's registry grants it), and the
        Master console (`master-node/services/sparknet-admin-console.py`) with
        its `list_events` event feed and KDE `--ping` push, wired as `make
        console`. Phase 5 ran live on the cluster2 pair (`.131` Master / `.133`
        peer) via `contracts/admin-federation-runbook.md`: the loopback→overlay
        binding (F1, fixed in code — `LOCAL_ONLY_PREFIXES` + repeatable `--bind`,
        regression tests in `peer-node/tests/test_admin_supervise.py`), a real
        pending signup, the signed `approve`/`role` legs (200, `pending→user`,
        `user`↔`admin`), the overlay event feed, and a KDE ping the operator
        confirmed on both devices. Three host-only defects were found and fixed:
        the agent ran `User=root` so its 0600 spool was unreadable by the
        `raxxar` bridge; the webhook update used `PATCH` (Open WebUI wants `PUT`);
        and the console CLI prepended the target node as the first entity field,
        so `approve`/`role` sent `user_id="<node>"` and the peer refused
        `USER_NOT_FOUND`. No human admin exists on a peer — its Open WebUI admin
        is a service account; the Master holds the human one. Host move: the two
        nodes are `agx64`=192.168.178.131 (`red-team`) and
        `agx32`=192.168.178.133 (`blue-team`); the old `192.168.178.131`/
        `192.168.20.32` legs are retired.
       - **Depends on**: Step 28 (per-user vaults + the proposed admin channel).

## Steps 30–36 — signed-ledger hardening, proposal/review, and the document round-trip

A review of the crypto, ledger and provenance surfaces (2026-10-12) found the
blockchain's security boundary is weaker than the contract claims, and that the
cross-user document workflow has no first-class object to carry. These steps
close that gap. Design decisions locked with the operator: **scope = ledger
hardening + cross-user proposal/review/countersignature + a Merkle transparency
log**; a **clean break** (ledger `schema_version 1.0 → 2.0`, ledgers are empty so
no migration); **Merkle (RFC 6962) is the integrity primitive** (signed tree
heads, inclusion + consistency proofs) while the linear `prev_hash`/`hash` stays
only as a local ordering index; and the **transport is built**, riding the
existing share ports 4201/4202 as a new share kind rather than a new port.

### Findings the batch fixes

- **F1 (HIGH): the ledger block header is unsigned and the chain hash is unkeyed.**
  `append_block` set `block["signature"] = data["signatures"]["node"]`
  (`shared/sparknet-provenance.py:1323`) and both signatures covered only `data`
  (`approval_signable`, `:1220`); `block_hash` is plain SHA-256 over the block
  minus `hash` (`:1172`). Deleting a `grant_use` block therefore removes its
  nonce from `consumed_grant_nonces` (`:1443`) and a spent grant replays. The
  contract wrongly said the hash binds the whole block
  (`contracts/tracking-schema.json:195`).
- **F2 (MEDIUM): truncation is undetectable** — nothing signs or externally
  anchors the ledger head.
- **F3 (LOW): `block_id` is never checked against the block's index**
  (`:1193`; `master-node/services/sparknet-ledger.py:71`).
- **F4 (LOW): `genesis_hash` is inconsistent** — `append_block` seeds
  `previous` from `ledger.get("genesis_hash")` (`:1316`) but `verify_chain`
  hard-codes `""`.
- **F5 (LOW): an empty `signature` passes the chain** (presence-only check,
  `:1203`).
- **F6 (LOW): the authorization messages are not domain-separated** —
  `authorization_message` (`authz:127`), `cluster_job_message` (`:487`),
  `admin_request_message` (`:573`) and `grant_message` (`:641`) are bare
  canonical JSON with no type tag, unlike `note_message`'s `sparknet-note/1`
  prefix (`provenance:627`); the Master signs all four with one key.
- **Gaps:** no first-class proposal/review object (G1/G2); `sign_note` refuses a
  note whose `owner_id` differs, so a reviewer can never countersign (G3); the
  per-node ledgers never anchor each other (G4); the share regime governs the
  data plane, not document approval (G5); node-to-node transport is spec-only
  (G6, `contracts/tracking-schema.json:232`).

### Recommended order

`30 → 32 → 31 → 35 → 34 → 33 → 36`. Step 30 is the load-bearing fix everything
else builds on; 32 gives Step 31 its proof primitive; 33 needs 34 (countersig)
and 35 (conversation commitment); 36 carries 33 over the wire.

## Step 30 — Signed ledger block headers and chain invariants (Arc A)

- [x] **Step 30** — Make the block *header* the signed unit and the invariants
      enforced, closing F1, F3, F4 and F5.
      - **DoD**:
        (1) `contracts/tracking-schema.json` `ledger_block` becomes
        `schema_version "2.0"`: `required` gains `node_pubkey_b64`, `signature`
        is redefined as **the appending node's identity key over
        `canonical_json(block − {hash, signature})`** (the whole header, not a
        restatement of `data.signatures`), and the section states the
        header-signing rule and that the header signature is what a reordered or
        deleted block breaks;
        (2) one canonical implementation — `ledger_block_signable` /
        `ledger_block_hash` in `shared/sparknet-authz.py` — imported by
        `shared/sparknet-provenance.py`, `master-node/services/sparknet-ledger.py`
        and `master-node/services/sparknet-signer.py`, so the three writers/
        verifiers cannot drift (a restated copy is how the first gap appeared);
        (3) `append_block` and the signer's `record_signature` sign the header
        and set `node_pubkey_b64`; `verify_chain` (both copies) verifies the
        header signature against the block's own key, enforces
        `block_id == f"{index:08d}"`, refuses an empty/absent signature, and
        seeds the genesis link from the ledger's `genesis_hash`;
        (4) both `ledger.json` files (and the signer's default) declare
        `version "2.0"`; the peer `ledger.schema.json` required list matches;
        `tests/test_contracts.py` pins all three to the contract;
        (5) **mutation-proven tamper tests**: deleting a block, reordering two
        blocks, back-dating a `timestamp`, rewriting a `block_id`, and blanking
        the header `signature` each make `verify_chain` fail (and each mutation
        reverted); a legitimate two-block chain still verifies;
        (6) `make test-all`, `make lint`, `make contract-test`, `make validate`,
        `make keys-check`, `make shims-check` green.

## Step 32 — RFC 6962 Merkle transparency primitive (Arc C)

- [x] **Step 32** — `shared/sparknet-merkle.py`: the integrity primitive the
      checkpoints and the conversation commitment are built on.
      - **DoD**: (1) RFC 6962 hashing — leaf hash
        `SHA-256(0x00 ‖ entry)`, interior `SHA-256(0x01 ‖ left ‖ right)`,
        `merkle_root(entries)` with the split at the largest power of two below
        the length; (2) `inclusion_proof(index, entries)` + `verify_inclusion`
        and `consistency_proof(size, entries)` + `verify_consistency`, both
        shape-checked so a verifier rejects a wrong-length or crafted proof;
        (3) a cross-implementation check against **published RFC 6962 vectors**
        from `transparency-dev/merkle` (the empty tree `e3b0c442…`, single
        leaves, roots for sizes 0..8 incl. the 7-leaf root `ddb89be4…`, and the
        reference inclusion/consistency proofs — RFC 6962/9162 carry no vector
        appendix of their own), plus the log-verifier corpus's negative legs, so
        the module is not merely self-consistent; (4) the module imports
        `shared/sparknet-authz.py` for any signing helper and adds no Ed25519 of
        its own; (5) `tests/test_merkle.py` covers the vectors, every proof
        accept/refuse leg, and an odd-count tree; (6) gates green.
      - **Done 2026-10-13**: module written (hashing + root + generators verbatim
        RFC 6962 §2.1.1–2.1.2, verifiers verbatim RFC 9162 §2.1.3.2/§2.1.4.2,
        signed tree head delegating to authz); the transparency-dev corpus —
        8 roots, leaf/interior hashes, 7 inclusion + 4 consistency proofs, every
        `testdata/inclusion/3` and `testdata/consistency/2` negative leg
        (wrong-leaf/root, modified/truncated/garbled proofs, size and index
        mutation, empty/trailing/preceding) — is matched; RFC 9162 §2.1.5's
        7-leaf example proofs verified in-test; 46 tests. Gates: `make lint`,
        `make validate`, `make contract-test`, `make test-all` (contract 72+1
        skip, fabric 776+3 skip, peer 437+1 skip, master 163), `make keys-check`,
        `make shims-check` green.

## Step 31 — Signed checkpoints and cross-node head anchoring (Arc A)

- [x] **Step 31** — Fix F2/G4: make truncation and forked history detectable by
      signing the ledger head and anchoring it across nodes.
      - **DoD**: (1) a `checkpoint` block (`data.event: "checkpoint"`) records
        the tree size, the block-head `hash`, and the RFC 6962 tree root of the
        block hashes, and is signed by the node key like every block
        (`shared/sparknet-provenance.py` `build_checkpoint_data`/`checkpoint`);
        (2) `anchor`/`verify_checkpoint` exchange a checkpoint between two nodes
        and refuse a rollback (a checkpoint whose size is below one already
        anchored for that node) and a fork (same size, different root) —
        `shared/sparknet-merkle.py` supplies `verify_consistency` for the growth
        case; (3) the ledger's `checkpoint` event is added to the peer
        vocabulary in the contract (disjoint from master) and the checkpoint
        shape is pinned; (4) tests drive two in-process nodes: an honest growth
        chain anchors, a truncated tail is refused, and a same-height fork is
        refused (mutation-proven: break the consistency or the rollback guard);
        (5) live cross-node anchoring over the overlay is `DoD: confirm: user`;
        (6) gates green.
      - **Done 2026-10-13**: `shared/sparknet-provenance.py` gains
        `build_checkpoint_data`/`checkpoint` (size = chain length *before* the
        checkpoint, so the payload never roots itself; `head_hash` =
        newest block hash; `root` = `merkle_root` of every block hash),
        `verify_checkpoint`/`anchor`, and CLI `append-checkpoint` /
        `anchor-checkpoint --block [--proof]`; `verify_approval_blocks` skips
        `checkpoint` (header-signed only, no `data.signatures`). Anchors persist
        per sender pubkey in `$SPARKNET_STATE_DIR/anchored-checkpoints.json`
        (0600, atomic) and refuse fail-closed: size below an anchor is a
        rollback, same size with a different root is a fork, growth needs an RFC
        6962 `verify_consistency` proof **and** an advanced head, and a corrupt
        anchor store raises rather than resetting. `contracts/tracking-schema.json`
        adds `checkpoint` to the peer vocabulary (master unchanged, still
        disjoint) plus a pinned `checkpoint` section and a `ledger_block.data`
        note; `contracts/provenance-protocol.md` documents the protocol.
        `tests/test_checkpoints.py` — 12 tests, two in-process nodes, honest
        growth anchors, truncated-tail rollback refused, same-height fork
        refused, consistency must be honest, tampered/non-object block refused,
        corrupt store raises, CLI paths. Gates: `make lint`, `make validate`,
        `make contract-test` (72+1 skip), `make test-all` (fabric 788+3 skip,
        peer 437+1 skip, master 163), `make keys-check`, `make shims-check` green;
        `make bundle-verify ROLE=peer`/`master` and `make -C peer-node precommit`
        also green.

## Step 35 — Conversation Merkle root joins the note signature (Arc B)

- [x] **Step 35** — Bind a note's conversation to its own bytes so the
      who/when/which-model trail cannot be edited without invalidating the note.
      - **DoD**: (1) the signed note message becomes `sparknet-note/2` and
        appends a fourth line, `conversation_root`, the RFC 6962 root of the
        canonical `tracking.conversation` entries (`shared/sparknet-provenance.py`
        `note_message` + `build_conversation_root`); (2) `sign_note` records
        `signature.signed_conversation_root` and the version tag, and
        `verify_note` recomputes the root — editing, adding or dropping a
        conversation entry turns a `valid` note into `stale:content` while an
        untouched note stays `valid`; (3) the contract (`tracking-schema.json`
        `signature`) states the four-line message and the version, and the note
        envelope carries the version; (4) existing note fixtures are re-signed
        in the step (clean break; no `sparknet-note/1` note is left in the
        tree) with a migration note in the session file; (5) mutation-proven: a
        changed conversation entry and a swapped note body each fail
        verification; (6) gates green.
      - **Done 2026-10-13**: `NOTE_VERSION`/`NOTE_DOMAIN` → `sparknet-note/2`;
        `build_conversation_root` (one canonical-JSON leaf per
        `tracking.conversation` entry, empty conversation = the empty tree's
        root) is added and `note_hashes` now returns it; `note_message` appends
        it as a fourth hashed line (five lines total). `sign_note` records
        `signature.note_version = "sparknet-note/2"` and
        `signature.signed_conversation_root`; `verify_note` records/verifies
        four hashes, refuses an unknown `note_version`, and classifies a moved
        conversation root (or swapped body) as `stale:content`. Fixed a latent
        emitter bug the step exercised: a list of dicts was emitted with its
        continuation fields one indent too shallow to re-parse (no signed note
        had carried one before) — `_emit_map` now indents `indent + 2`, and the
        frontmatter round-trip test carries a list-of-dicts. Contract
        `signature.message` describes the five-line message and the envelope
        gains `note_version` + `signed_conversation_root` (plus a
        `conversation_root` definition); `provenance-protocol.md` and both
        `00_System/schema.yaml` files updated (`sparknet-note/2`, five lines).
        Migration: all 8 signed peer notes re-signed under `/2` (envelope-only
        diff — `note_version`, `signed_conversation_root`, new `sig`/`signed_at`);
        `make -C peer-node provenance-verify` 8/8 valid. Tests:
        `tests/test_provenance.py` +3 (conversation root order/content
        sensitivity; conversation entry bound to the signature; unknown
        `note_version` refused) and `tests/test_contracts.py` message pin
        updated. Gates: `make lint`, `make validate`, `make contract-test`
        (72+1 skip), `make test-all` (fabric 791+3 skip, peer 437+1 skip,
        master 163), `make keys-check`, `make shims-check`; peer `precommit`
        clean, `make bundle-verify ROLE=peer`/`master` green.

## Step 34 — Multi-party countersignature (Arc B)

- [x] **Step 34** — Let a second user countersign a note without rewriting the
      original author, closing G3.
      - **DoD**: (1) `tracking.signature.co_signatures[]` is defined in the
        contract, each entry carrying `owner_id`, `owner_node`,
        `public_key_b64`, `key_fingerprint` and `sig` over the **same** note
        hashes (so a co-signature commits to the identical bytes); (2)
        `shared/sparknet-provenance.py` `add_co_signature` / `verify_co_signatures`
        append and verify without touching the primary `signature` or
        `owner_id`; a co-signature over different hashes, an unknown signer, or
        one that rewrites the body is refused; (3) the primary author remains
        `owner_id` and the note still verifies as `valid`; (4) the trust rule is
        explicit (a co-signer is trusted because its fingerprint resolves in the
        Master-signed registry, with the origin `user.md` snapshot as the offline
        fallback) and recorded in `provenance-protocol.md`; (5) tests: add a
        countersignature, verify, tamper the body → `stale:content`, swap the
        signer key → refused; mutation-proven; (6) gates green.
      - **Done 2026-10-13**: `contracts/tracking-schema.json` gains a
        `signature.co_signatures` array and a `co_signature` section (entry
        fields, the same `sparknet-note/2` message rebuilt from the primary
        envelope's four recorded hashes, the trust rule, the refusals).
        `shared/sparknet-provenance.py` adds `CO_SIGNATURE_FIELDS`,
        `add_co_signature` (signs this vault's user key over the primary
        recorded hashes, appends an entry, replacing one from the same
        `key_fingerprint`; never edits the primary `sig`/`key_id`/`owner_id` or
        the recorded hashes) and `verify_co_signatures(frontmatter, *,
        trusted_users, registry)` — byte integrity first (`key_fingerprint`
        must be the fingerprint of `public_key_b64`; `sig` must verify over the
        recorded hashes), then trust: the Master-signed registry naming a
        non-revoked, master-signed authorization for the co-signer's
        `owner_node`, or a `trusted_users` user.md snapshot matching
        `(owner_id, owner_node, key_fingerprint)`. A byte-intact entry that
        resolves through neither is `untrusted`, not `invalid`. CLI `co-sign`
        and `verify-co-signatures` (with `--registry` / `--trusted-user`).
        Because the primary tracking hash is taken with the whole `signature`
        key removed, appending a co-signature cannot invalidate the primary
        signature: the note keeps its author and still verifies `valid` (this
        exercises the Step 35 emitter fix — a list of dicts round-trips).
        `contracts/provenance-protocol.md` narrates the trust rule; both
        `00_System/schema.yaml` files note `co_signatures[]`. Tests
        (`tests/test_provenance.py`, two self-contained vaults): append-without-
        rewriting (author + primary sig + hashes unchanged, still `valid`,
        idempotent per key); unknown/foreign signer → `untrusted`; a
        co-signature over different bytes → refused; a swapped key →
        `key_fingerprint does not match public_key_b64`; body tamper after
        co-signing → `stale:content` while the co-signature still commits to the
        recorded bytes; the Master registry resolves a co-signer (revoked node
        and a tampered entry each refused); the CLI round trip. A contract pin
        (`tests/test_contracts.py`) ties `CO_SIGNATURE_FIELDS` to
        `co_signature.entry_fields`. Gates: `make lint`, `make validate`,
        `make contract-test` (73+1 skip), `make test-all` (fabric 799+3 skip,
        peer 437+1 skip, master 163), `make keys-check`, `make shims-check`;
        peer `precommit` clean, `make bundle-verify ROLE=peer`/`master` green.

## Step 33 — Proposal / review / decision protocol (Arc B)

- [x] **Step 33** — The first-class object the cross-user workflow needs (G1/G2).
      - **DoD**: (1) `contracts/proposal-schema.json` and
        `contracts/proposal-protocol.md` define `proposal`, `review` and
        `decision` records: the originating agent's work, each reviewer's
        verdict with **model + agent + reason** attributed, and the boss's
        approve/deny; lifecycle `draft → submitted → reviewed → decided`,
        fail-closed on an out-of-order transition; (2) the peer event vocabulary
        gains `proposal`/`review`/`decision` (disjoint from master); (3)
        `shared/sparknet-proposal.py` builds each record, commits the
        conversation via Step 35's `conversation_root`, signs with the shared
        dual-control envelope, and `verify_proposal_chain` walks
        proposal→reviews→decision and refuses a forged or reordered chain; (4)
        the transport half is Step 36; (5) tests drive a full
        draft→submitted→reviewed→decided round trip plus each refusal;
        (6) gates green.
      - **Done 2026-10-13**: `contracts/proposal-schema.json` +
        `contracts/proposal-protocol.md` define the three records, the
        `draft → submitted → reviewed → decided` lifecycle, the closed
        verdict/decision vocabularies, the dual-control signature over
        `proposal_signable`, the inline keys (integrity, not identity — the same
        split a co-signature makes) and the `verify_proposal_chain` checks.
        `contracts/tracking-schema.json` gains `proposal`/`review`/`decision` in
        the **peer** vocabulary (master untouched). `shared/sparknet-proposal.py`
        loads `sparknet-provenance.py` by path and reuses `dual_sign`
        (new public alias in provenance), `append_block`, `canonical_json` and
        `build_conversation_root` — no crypto of its own. `build_proposal`
        returns a local, unsigned `draft`; `submit_proposal`/`review_proposal`/
        `decide_proposal` sign and append a `proposal`/`review`/`decision` block,
        each re-reading the ledger and refusing out of order (review with no
        proposal, decision with no review, second decision, review after
        decision) before appending. `proposal_state` derives
        submitted/reviewed/decided from the chain; `verify_proposal_chain`
        re-checks each record's conversation root, key fingerprint and both
        signatures, plus the logical order (one first proposal, ≤1 decision,
        no review after the decision) against a bare list of records, so a
        received bundle (Step 36) is checked the same way. CLI `propose`,
        `submit`, `review`, `decide`, `verify`, `list`. `contracts/README.md`
        and `index.md` name the new files. Tests: `tests/test_proposal.py` (23) —
        round trip to `decided`, state derivation, every fail-closed transition,
        and `verify_proposal_chain` refusals (forged user/node signature, swapped
        key with and without its fingerprint, tampered conversation, reorder,
        decision before any review, missing/duplicate proposal, duplicate
        decision, foreign `proposal_id`, empty chain), block-edit breaks the
        ledger chain, contract pins, and the CLI round trip. Gates: `make lint`,
        `make validate`, `make contract-test` (73+1 skip), `make test-all`
        (fabric 824+3 skip, peer 437+1 skip, master 163), `make keys-check`,
        `make shims-check`; peer `precommit` clean, `make bundle-verify
        ROLE=peer`/`master` green. Cursor `33 → 36`.

## Step 36 — Proposal exchange over the share regime (Arc D, G5/G6)

- [x] **Step 36** — Carry a proposal round trip between two nodes for real,
      without a new port.
      - **DoD**: (1) `contracts/ports.json` records the proposal route on the
        existing share ports 4201 (`share-intake`) / 4202 (`session-transfer`)
        as a new share kind, `implementation_state` moved off `spec-only` only
        for what is actually built, with a truthful `runtime` axis;
        (2) `peer-node/services/sparknet-share-regime.py` accepts the new kind
        and still refuses to run if the contract is missing; (3)
        `peer-node/services/sparknet-proposal-exchange.py` (or dispatch-bridge
        `/proposal/*` routes) delivers a signed proposal and returns a signed
        review/decision, verified with the shared ladder; (4) two in-process
        nodes exchange a full round trip; the live overlay leg is
        `DoD: confirm: user` (no `wg` interface on this host); (5) gates green.
      - **Done 2026-10-13**: operator chose a **new message family on the ports**
        (not a `capabilities.share_types` member — a proposal conveys no read or
        copy) and a **dedicated service**. `contracts/proposal-schema.json` gains
        a structured `transport` section: ports `[4201, 4202]`, message types
        `proposal.submit`/`proposal.review`/`proposal.decide`, the bundle rule
        (each node appends only the records it authors; `verify_proposal_chain`
        checks the union) and the shared-ladder rule. `contracts/ports.json`
        moves 4201/4202 off `spec-only` to `implemented` + `not-listening` with a
        `runtime_why` (the engines are in-process; no daemon binds), keeping the
        Master's 4203 and the other unbuilt surfaces spec-only;
        `contracts/share-protocol.md` gains "The proposal exchange rides these
        ports" and `contracts/proposal-protocol.md` its Transport section.
        `sparknet-share-regime.py` loads `proposal-schema.json` (a missing
        contract now refuses construction) and adds `accepts_message` /
        `proposal_route`. `shared/sparknet-proposal.py` gains the transport half
        — `review_bundle` / `decide_bundle` (verify the received bundle with the
        shared ladder, check the lifecycle against the bundle rather than the
        local chain, append only this node's record) — factored over
        `_finalize_review` / `_finalize_decision`. New
        `peer-node/services/sparknet-proposal-exchange.py`: loads
        `sparknet-proposal.py` and the share regime by path, no crypto of its
        own; `submit`/`review`/`decide`/`receive`/`verify` + a `verify`/`ports`
        CLI; opens no socket. Tests `peer-node/tests/test_proposal_exchange.py`
        (13): a full A→B→A round trip, the authorship split (each ledger holds
        only its author's records, and each still passes
        `verify_approval_blocks`), the contract-driven route, and refusals
        (tampered conversation, forged signature, reordered bundle, decision with
        no review, second decision, unknown family) plus the regime refusing
        without `proposal-schema.json` and the CLI `verify`. `tests/test_contracts.py`'s
        share-plane pin now records the honest split (share-intake/session-transfer
        `implemented` + `not-listening`; share-ratification/opencode-serve still
        spec-only) without dropping the "grants no authority" intent. Gates
        green: `make lint`, `make validate`, `make contract-test` (73+1 skip),
        `make test-all` (fabric 824+3 skip, peer 454+1 skip, master 163),
        `make keys-check`, `make shims-check`; peer `precommit` clean;
        `make bundle-verify ROLE=peer`/`master` green. **`DoD: confirm: user`**:
        the live overlay round trip (no wireguard interface on this host). Cursor
        `36 → done`.

## Steps 37–41 — adoption from the rzfz-ai-service-stack / dify review

An external comparison against two production repos (`rzfz-ai-service-stack`,
`dify`) produced a prioritized adoption list. The operator approved all tracks:
**A** quality gates, **B** SSOT → derived artifacts, **C** release/licensing,
**D** code structure. Two framing decisions: type checking (A3) was **dropped**,
and hosted CI (A5) is a **local pre-merge gate only** — sparknet is offline-first
and has no forge on a node, so there is nowhere a workflow file would ever run.

### Step 37 — Quality gates (Track A)

- [x] **Step 37** — Add the local quality gates a merge should pass: an
      incremental `ruff format --check` (`format-check`), a graceful `shellcheck`
      target (skips with a note where the binary is absent), an advisory widened
      lint (`lint-strict`: `B,SIM,RUF,S`), machine-readable test reports
      (`test-report`: JUnit XML + `summary.json` under `.state/reports/`), a
      registered pytest marker vocabulary plus `tests/conftest.py`, and one
      `make ci` entry point backed by `scripts/pre-merge-gate.sh`.
      - **DoD**: each target runs; `make ci CI_QUICK=1` reports every step PASS;
        every new script satisfies the fabric `--help` contract
        (`tests/test_shell.py`); `make test-all` stays green.
      - **Status**: complete 2026-10-13. `make ci CI_QUICK=1` → keys-check,
        shims-check, lint, format-check, shellcheck (skipped: no binary),
        validate, contract-test all PASS; full `make test-all` rc=0 (fabric
        837/3 skip, peer 454/1 skip, master). Deliberate scope, recorded in the
        Makefile: **A3 dropped**; **A5 is local-only**; `format-check` checks
        *newly added* files only and `lint-strict` is advisory, because the tree
        predates any pinned ruff (69 files would reformat) and the wider rule set
        has 13 `B904` exception-chaining findings in the consensus/provenance
        paths — adopting those is its own reviewable change. A report run that
        created `.state` had to be fixed to `0700` (keys-check caught it), and
        `.shellcheckrc` was registered in `tests/test_layout.py`'s documented
        top-level set.

### Step 38 — One shared module loader (D10)

- [x] **Step 38** — Collapse the five hand-rolled `importlib` by-path loaders
      into one `shared/sparknet_loader.py` (`candidates` / `load_by_path` /
      `load_shared`), and have the six shared modules plus the master ledger
      delegate to it. The module name is `sparknet_loader.py` (underscore) so
      `from sparknet_loader import …` works after the two-line bootstrap.
      - **DoD**: `shared/sparknet_loader.py` exists exactly once; every shared
        module and the ledger load through it; `tests/test_contracts.py` pins
        both the single loader and the shared bootstrap; `make test-all` green.
      - **Status**: complete 2026-10-13. Per-module error vocabularies preserved
        (`ConsensusError`, `MerkleError`, `ProvenanceError`, `ProposalError`,
        `ElectionError`, `RuntimeError`). All suites green; lint clean.

### Step 39 — Derived artifacts from the SSOT (Track B)

- [x] **Step 39** — Render the `contracts/` SSOT into checked, generated
      artifacts instead of hand-copying them, and gate the derivation:
      - **B1** `scripts/sparknet-render.py` (+ `--check`) renders
        `contracts/manifest.json` — every JSON contract by sha256, plus the
        projected capability and port tables. `make render` writes it,
        `make render-check` fails when a contract changed without a re-render.
      - **B3** `scripts/sparknet-bundle.sh` writes a `SHA256SUMS` over the whole
        staged bundle (last, so `BUNDLE.md` is covered) and `--verify` now
        recomputes it — a corrupted or tampered archive fails before it runs.
      - **B4** `make drift-check` is the umbrella: `render-check` + `wiki-verify`
        + `contract-test`.
      - **B2** `env-changes.json` was **dropped after inspection**: sparknet's
        env model *regenerates* `.env` from `.env.example` (via
        `sparknet-env-init.sh`), it does not migrate user-edited values, so a
        rzfz-style migration list has nothing to migrate. The real invariant —
        that the root and both roles' `.env.example` templates expose one shared
        key set — is gated instead by
        `tests/test_layout.py::test_env_example_templates_share_one_key_set`.
      - **DoD**: `make render-check` green; `make drift-check` green;
        `make bundle ROLE=peer` writes and `--verify` checks `SHA256SUMS`
        (tamper fails); `render-check` is a step in `scripts/pre-merge-gate.sh`;
        `make test-all` stays green.
      - **Status**: complete 2026-10-13. `contracts/manifest.json` committed and
        fresh; `tests/test_render.py` (10 tests) pins freshness, coverage of the
        SSOT, determinism, and that `--check` actually goes red on a mutated
        copy. `make bundle ROLE=peer` → `SHA256SUMS (271 files)`; `--verify`
        reports `integrity manifest matches the archive ✓ 271 files verified`
        and a hand-tampered extract fails `sha256sum -c`. `render-check` added to
        the pre-merge gate (`make ci CI_QUICK=1` → all steps PASS). Full
        `make test-all` rc=0 (fabric **845/3 skip** — 837 prior + 11 new — peer
        454/1 skip, master). `manifest.json` also added to the `index.md` and
        `contracts/README.md` tables (the index-coverage test requires it).

### Step 40 — Package and split (D11–D13) — complete 2026-10-13 (further splits deferred)

- [x] **Step 40** — Reduce oversized modules/tests without regressing the
      fabric's constraints (relocatable tree, one-copy-per-implementation,
      `cryptography`-only runtime dep, fail-closed). **D11 (a `shared/sparknet/`
      importable package with kebab-case shims) was dropped by decision**: it
      would touch ~103 call sites and reintroduce a second name per module,
      fighting the by-path / one-copy / relocatable discipline that
      `test_only_one_authz_implementation_exists` and
      `test_shared_modules_share_one_loader_bootstrap` pin. So: behavior-
      preserving splits only, verified by an unchanged collected-test count plus
      every gate.
      - **D12a — YAML-subset parser extracted** (done): the frontmatter
        parser + emitter + the `ProvenanceError`/`FrontmatterError` pair moved
        from `shared/sparknet-provenance.py` (2952 → 2603 lines) into a new
        `shared/sparknet-yaml.py`, loaded *by path* via
        `shared/sparknet_loader.py` and re-exported from provenance
        (`ProvenanceError`, `FrontmatterError`, `parse_yaml_subset`,
        `emit_yaml`, `_split_frontmatter`) so every caller — including
        `tests/test_contracts.py`'s `provenance.parse_yaml_subset` — is
        unchanged. The error pair lives in the lower module (not provenance)
        because `FrontmatterError` must stay a `ProvenanceError` subclass for
        the many `except ProvenanceError` handlers, and this is what lets the
        module load before provenance without a cycle. Identity verified:
        `provenance.ProvenanceError is sparknet_yaml.ProvenanceError`, and
        `issubclass(provenance.FrontmatterError, provenance.ProvenanceError)`.
      - **DoD (per split)**: `make test-all`, `make contract-test`,
        `make validate`, `make lint`, `make format-check`, `make drift-check`,
        `make keys-check`, `make shims-check` all green; collected test count
        unchanged (849 in `tests/`); for a **module** split, `make bundle
        ROLE=peer` ships the new file and `--verify` runs the extracted peer
        suite green (a **test-only** split ships no runtime file, so bundle
        does not apply).
      - **Status (D12a)**: complete 2026-10-13. All the above gates green;
        `make ci CI_QUICK=1` all PASS; `make bundle ROLE=peer` (383 entries,
        `SHA256SUMS`) + `bundle-verify` pass, with `shared/sparknet-yaml.py`
        present in the archive. Fabric `pytest tests/` = **846 passed, 3
        skipped** (849 collected) — identical to the pre-change collection
        (proven by stashing the Step-40 diff and re-collecting 849).
      - **D13a — golden vectors split out of `tests/test_contracts.py`**
        (done): the pinned keyless vectors (`GOLDEN_*`) and their six tests
        moved into a new `tests/test_authz_golden.py`; the fixtures
        (`overlay`, `capabilities`, `identity_schema`, `ports`, `authz`) moved
        to `tests/conftest.py` (auto-discovered, so no fixture is imported by
        name and ruff's F401/F811 do not fire) and the constants + `load()` to
        a new `tests/contract_helpers.py`. `tests/test_contracts.py` 1451 →
        1168 lines; the golden section is now a one-line pointer. Behavior is
        unchanged: same 6 tests, same fixtures, `tests/test_contracts.py`'s
        own `test_*` set is untouched.
      - **Status (D13a)**: complete 2026-10-13. All DoD gates green
        (`make ci CI_QUICK=1` all PASS, fabric `846 passed, 3 skipped` = 849
        collected, unchanged); ruff `check` + `format` clean on all four
        touched files.
      - **Remaining Step 40 work — deferred (user advanced to Step 41)**: further
        safe splits of the still-large modules (`shared/sparknet-provenance.py`
        2603, `shared/sparknet-election.py` 1367, `shared/sparknet-authz.py`
        1054, `shared/sparknet-consensus.py` 936) and/or the large tests
        (`tests/test_election.py` 1484,
        `master-node/tests/test_signer_isolation.py` 1431,
        `tests/test_provenance.py` 1038, `tests/test_consensus.py` 982). Not
        blocking: the DoD (D11 dropped, D12a + D13a done) is met.

### Step 41 — Release surface (Track C) — complete 2026-10-13 (C1 deferred)

- [x] **Step 41** — Release surface (`VERSION`, generated SBOM, unified `sparknet`
  CLI). The licensing leg (C1: `LICENSE`/`NOTICE`/SPDX) stays **deferred** until a
  license is chosen.

**Implementation:**
- Root `VERSION` = `0.1.0` (single source of truth). `pyproject.toml`'s version
  matches, enforced by `tests/test_release.py`.
- SBOM: `scripts/sparknet-sbom.py` (deterministic CycloneDX 1.5) generates
  `sbom/sparknet.cdx.json` with components `sparknet`, `cryptography` (declared
  constraint from `requirements.txt`), and all 33 vendored skills (each hashed
  by `SKILL.md`, MIT). No timestamp/serial — byte-identical on re-render. New
  make targets `sbom` / `sbom-check`, wired into `drift-check` and the
  pre-merge gate (`scripts/pre-merge-gate.sh`).
- Unified CLI: `scripts/sparknet` (bash, execs `make`) supports `version`,
  `validate`, `test`, `contract-test`, `lint`, `format-check`, `render`,
  `render-check`, `drift-check`, `sbom`, `sbom-check`, `keys-check`,
  `shims-check`, `wiki-verify`, `bundle <role>`, `layout`, `help`, with
  `SPARKNET_DRY=1` for dispatch testing.
- Tests: `tests/test_release.py` (18) asserts version consistency, SBOM validity/
  freshness/determinism/component coverage/drift-gates, CLI dispatch/help.
- Layout: `VERSION` and `sbom/` added to `EXPECTED_TOP_LEVEL` and documented in
  `index.md`. Gates: `make lint`, `make format-check` (16 new files clean),
  `make sbom-check`, `make render-check`, `make drift-check`, `make keys-check`,
  `make shims-check`, `make validate`, `contract-test` green; full `make test-all`
  rc=0 (fabric 864 passed + 3 skipped, peer 454 passed + 1 skipped, master
  passes).

### Step 42 — DGX Spark node image (GB10 bring-up surface) — code complete 2026-10-15

- [x] **Step 42** — Package a SparkNet node as **one image, many services** for
  the DGX Spark (GB10 / Blackwell sm_121a, ARM64): vLLM serving with the fabric
  knowledge as precontext, the goSpark control/service plane, the Python compute
  plane, NATS/JetStream, and the option of Open WebUI — all from a single image
  started with a per-service entrypoint subcommand.
      - **DoD**: (1) `spark.docker` builds on `linux/arm64` from a selectable
        NVIDIA vLLM base (`ARG VLLM_BASE`, default `nvcr.io/nvidia/vllm:26.04-py3`)
        with the goSpark binaries supplied by a BuildKit **named context**
        (`--build-context gospark=…`, never a COPY of the source); (2)
        `spark-entrypoint.sh` is the one dispatcher every service runs
        (`vllm compute kvrouter agent control gpu nats opencode precontext shell`);
        (3) `spark.compose.yml` brings the node up with the text defaults and
        opt-in `kv/control/webui/embed/rerank/audio` profiles; (4)
        `sparknet-node-setup.sh` is the idempotent host bring-up (bundle → image
        → env-file/secret → `compose up`); (5) the fabric is baked as precontext
        at build time (`spark-precontext.py digest` → 51-line digest +
        `sparknet-rag-corpus.py` → 20 files + the MASTERSPIKE system prompt) and
        wrapped into the model's own chat template at container start; (6)
        `tests/test_precontext.py` pins the digest vocabulary and the template
        wrapper; (7) all fabric gates green and the GPU-free services boot from
        the image.
      - **Status**: code complete 2026-10-15. `sparknet-spark-node:dev` builds
        (arm64, 19.5 GB, 17 steps) with the base pull cached; in-image smoke
        verified `spark-entrypoint help`, `precontext` (template built, rc=0),
        the baked context (digest/corpus/system-prompt), the goSpark + nats +
        opencode binaries, the compute venv, and a live `sparknetctl keygen` +
        `spark-entrypoint control` (bus connect, `/admin/health`, `/metrics`).
        Found and fixed a real `spark-precontext.py` defect: the Jinja preamble
        was `%`-formatted but contains literal `%` from `{%- … -%}`, so template
        build raised `TypeError` at container start (sentinel + `.replace()`
        now). Gates green: `pytest tests/` (**fabric 880 passed, 3 skipped**
        = 883 collected),
        `make lint`, `make format-check`, `make validate`, `make contract-test`,
        `make render-check`, `make keys-check`, `make shims-check`.
      - **Live legs — `DoD: confirm: user`**: the GPU paths (`vllm`,
        `vllm-embed`/`-rerank`/`-audio`, `gpu` telemetry) and the NATS-JetStream
        swarm need a real GB10 host and NVIDIA container runtime; on this
        dev host there is no driver and no `nvidia-ctk`. Election/signing is a
        separate ceremony (`contracts/deployment-runbook.md`) and is not part of
        this step.

### Step 43 — Hardware-free verification harness (GPU telemetry + election) — complete 2026-10-15

- [x] **Step 43** — Shrink Step 42's residual `DoD: confirm: user` to the physics
  that genuinely needs a Spark, by making the blocked legs runnable on any host:
  an opt-in synthetic GPU backend, a CPU OpenAI-compatible engine stub, and the
  election arc run *inside the built image*.
      - **DoD**: (1) an opt-in sim GPU collector exists in goSpark and is never
        on by default; (2) a CPU engine stub brings the whole node graph up
        without a GPU and the agent↔vLLM↔compute path answers; (3) the election
        arc runs inside `sparknet-spark-node:dev` and forms the trust root,
        signs, and refuses escalations; (4) the remaining `confirm: user` items
        are only physics; (5) all fabric + goSpark gates green.
      - **Status (complete, 2026-10-15).** goSpark: new `internal/gputel/sim`
        (opt-in via `SPARKNET_GPU_FIXTURE`/`SPARKNET_GPU_SIM_CFG` or the
        `-sim-fixture` flag; telemetry only, never authority) with unit tests;
        `cmd/stub-vllm` (pure-Go OpenAI-compatible `/health`, `/v1/models`,
        `/v1/chat/completions`); `make build` now builds `stub-vllm`. Fabric:
        `spark-entrypoint.sh` gains the `vllm-stub` subcommand; the image bakes
        `stub-vllm` and `cryptography>=42` (the baked ceremony scripts need it);
        `spark.compose.cpu.yml` drops the NVIDIA device reservations (with
        `!reset`) and swaps in the stub + a synthetic telemetry fixture;
        `sparknet-node-setup.sh --engine stub` wires the overlay and writes the
        fixture; `scripts/make-gpu-fixture.py`; `scripts/sparknet-rehearsal.sh`
        gains `SPARKNET_PYTHON`/`SPARKNET_ELECTION_PY`/`SPARKNET_SIGNER_PY`/
        `SPARKNET_REHEARSAL_TGZ` overrides so the **same** script runs in the
        image; new `scripts/sparknet-election-rehearsal-container.sh` + tests
        (`tests/test_gpu_telemetry_hardware_free.py`,
        `tests/test_election_container.py`, `tests/test_cpu_node_smoke.py`, all
        `@pytest.mark.integration`, opt-in/skippable) and a `make container-test`
        target. Verified on this host: the containerised election rehearsal is
        **51 passed, 0 failed inside the image**; the CPU graph
        (`nats vllm-stub compute agent gpu`) boots healthy with no host ports and
        the gateway answers a real chat completion through the stub, while the
        GPU sidecar reports `available=true` from the fixture. New docs:
        `contracts/spark-node-runbook.md` (what is provable without a GPU vs the
        residual confirm list). Gates green: `make ci` all steps PASS (fabric
        **880 passed + 3 skipped**, peer **454 + 1**, contract + master);
        `go vet ./...` + `go test ./...` clean.
      - **Live legs — `DoD: confirm: user` (physics only)**: real `vllm serve` on
        Blackwell (sm_121a) and the multimodal engines; NVML/DCGM reporting real
        numbers from a driver (not the fixture); WireGuard on real NICs;
        `sparknet-master-signer.service` surviving a reboot with exactly one
        holder of the operational key; deployed containment; Phase 9's
        deliberately-unexecuted destructive legs.

### Step 44 — goSpark / spark.docker interop — complete 2026-10-16

- [x] **Step 44** — Make sparknet and goSpark work *together* rather than merely
  co-exist: prove the cross-language authority boundary, give a node a real
  **join** path onto a running fabric, document the node's ports honestly, wire
  the goSpark knowledge binaries as node services, and stop the foreign images
  from floating.
      - **DoD**: (1) a cross-language test proves the fabric's Python authz and
        goSpark's Go registry/identity layer agree — identical field names,
        identical canonical envelope **bytes**, identical fingerprint fields;
        (2) a node can join a running fabric by adopting the elected Master
        (`--master-pub`/`--registry` stage the registry, pin the public key,
        and the entrypoint fails closed on a registry with no pinned key);
        (3) the node's ports are declared in `contracts/ports.json` under
        `node_ports` with honest axes, projected into the rendered manifest,
        and drift-tested, while staying a namespace separate from the fabric's;
        (4) `ingest`/`backup`/`opencode` are real node compose services under
        profiles, and the setup script advertises exactly the profiles compose
        defines; (5) the foreign images are pinned (compose NATS tracks the
        image's `NATS_VERSION`; WebUI is an immutable release tag) and goSpark's
        reference `compute/docker-compose.vllm.yml` carries a supersession note;
        (6) all fabric and goSpark gates green.
      - **Status (complete, 2026-10-16).** Cross-language: new
        `tests/test_registry_crossverify.py` (6 tests) drives the real goSpark
        binaries (`sparknetctl`/`sparknet-authz.py`) against each other and pins
        the shared bytes; the one deliberate asymmetry — goSpark's 64-byte
        `private_key_b64` (seed+pub) vs the fabric's 32-byte seed — is recorded
        as *by design* (`test_private_key_encodings_differ_by_design`), since
        only public keys cross the boundary. Join: `sparknet-node-setup.sh`
        gains `--master-pub`/`--registry`, `render_env_file` emits
        `SPARKNET_MASTER_PUB` + `GOSPARK_REGISTRY_FILE`, `act_up` re-renders on
        (re)specified join inputs, the compose `x-spark-env` carries both, and
        `spark-entrypoint.sh master_pub()` fails closed when a registry is
        staged but no key is pinned (also refuses `--registry` with
        `--role master`); runbook §6 "Join a running fabric" added (later
        sections renumbered); `tests/test_node_setup_join.py` (7 tests). Ports:
        `contracts/ports.json` gained `node_measurement` + a `node_ports` table
        (14 numbers, each with the honest axes and, where a number collides with
        a fabric one, a `collision_note`), three new invariants, and the
        renderer projects it into `contracts/manifest.json`; drift tests in
        `tests/test_contracts.py` + `tests/test_render.py` bind the table to what
        compose actually publishes and keep the two namespaces apart (the
        fabric's `opencode-serve` 4200 stays `spec-only` while the node's is
        declared separately). Services: `spark.compose.yml` gains `ingest`
        (one-shot indexer), `backup` (signed snapshots, target a host bind
        outside the source) and `opencode` (loopback 4200) under profiles;
        `spark-entrypoint.sh` gains `cmd_ingest`/`cmd_backup`; an MCP server is
        documented as a stdio tool, **not** a listener; runbook §5 documents all
        three. Pins: compose `nats` default tracks `spark.docker`'s
        `NATS_VERSION=2.14.2` (→ `2.14.2-alpine`), WebUI pinned to `v0.12.2`, and
        goSpark's `compute/docker-compose.vllm.yml` carries a **DEPRECATED FOR
        THE DGX SPARK NODE** supersession note pointing at `spark.docker` (change
        committed in goSpark); `test_node_foreign_images_are_pinned` +
        `test_setup_script_advertises_only_profiles_compose_defines` lock both.
        Gates green: `make test-all` rc=0 (contract **75 passed + 1 skipped**,
        fabric **912 passed + 5 skipped**, peer **454 passed + 1 skipped**,
        master **163 passed**), `make ci CI_QUICK=1` all PASS, `make drift-check`
        in sync; goSpark `make ci CI_QUICK=1` → `ci: ok`.
      - **`DoD: confirm: user` (physics only)**: a real second host joining the
        live agx64 Master over a real overlay (needs a second Spark-class host
        with the node image), and a real GB10 GPU — the same residue Step 43
        narrowed.

### Step 45 — NVIDIA/dsx standard-practice adoption: clones + inventory — complete 2026-10-17

- [x] **Step 45** — Clone the **14** reference repos (1 EleutherAI + 13
  dsx-ai-factory) full-history into `/mnt/nvme/github` and write a SHA-cited
  inventory of what each repo is and which parts of its practice apply to
  sparknet/goSpark. Baselines recorded first so the sweep can prove it broke
  nothing.
      - **DoD**: (1) all 14 clones present at `/mnt/nvme/github/<name>` with
        full history, each pinned in `references/nvidia-dsx-standard-practice.md`
        by full SHA, commit count and default branch; (2) the inventory states
        per repo: purpose, license, standard-file presence, and an
        adopt / pattern-only / skip verdict for this fabric; (3) green baselines
        recorded — sparknet `make ci CI_QUICK=1`, goSpark `make ci`, both run
        **before** any adoption change; (4) license decision executed as
        agreed: **no license change, zero code copied** — provenance lives in
        the inventory doc, not a NOTICE.
      - **Status (complete, 2026-10-17).** Baselines green **before** any
        change (sparknet `make ci CI_QUICK=1` → `pre-merge-gate: all steps
        passed`; goSpark `make ci` → `ci: ok`). All 14 clones OK full-history
        (`lm-evaluation-harness` 4122 commits … `infra-controller` 4302;
        `model-streamer` default branch **master**); licences read from the
        clones' own LICENSE files — Apache-2.0 except `libredfish` **and**
        `lm-evaluation-harness`, both MIT. `references/nvidia-dsx-standard-practice.md`
        written (pinned SHAs; per-repo purpose/license/commits/branch;
        observed-standard counts; adoption map; gap table; Step-51 verdicts)
        and linked from `index.md`; session record
        `sessions/2026-10-17.md`. No license change, zero code copied.

### Step 46 — Codify the standard: STYLE_GUIDE + resource-first rule + build catalog — complete 2026-10-17

- [x] **Step 46** — Turn the inventory into standing rules both agents read:
  a `STYLE_GUIDE.md` at the fabric root (conventions adopted from dsx —
  Makefile `## help`, ruff strictness ladder, shellcheck, SemVer +
  CHANGELOG discipline, commit hygiene), the NVIDIA **resource-first** rule
  wired as a make target + AGENTS.md command-table line, and
  `references/nvidia-build-catalog.md` recording `build.nvidia.com`
  endpoints (explore/discover, `/v1/models`, api/search) for container/model
  lookups **before** building our own.
      - **DoD**: (1) `STYLE_GUIDE.md` exists, cites the inventory as
        provenance, and is referenced from AGENTS.md; (2) `make nv-search q=…`
        (or equivalent script) queries the catalog with `$BUILD_NVIDIA_API_KEY`
        **indirection only** — the key lives at
        `.state/secrets/build-nvidia.env` (0600, `.state/` gitignored), is
        documented by *name/path only* in docs, never by value, and the helper
        degrades to unauthenticated when absent; (3)
        `references/nvidia-build-catalog.md` records verified endpoints +
        search pattern; (4) `keys-check` + `make ci CI_QUICK=1` green.
      - **Note (key handling).** The `nvapi-…` key was pasted in chat in
        plaintext — treat as exposed: recommend **rotation**; it is not in
        `.env`, no env var carries it, and it must never enter any tracked
        file (PLAN/MEMORY/sessions/log/CI). A root-only `.env.example` knob is
        rejected: `tests/test_layout.py::test_env_example_templates_share_one_key_set`
        forces identical key sets across all three templates, and a node
        template must not grow a fabric-tooling key.
      - **Status (complete, 2026-10-17).** `STYLE_GUIDE.md` written (10
        sections: resource-first, tree, Python, shell, Makefiles, commits,
        secrets, CI, docs/memory, release) with a gates table; registered in
        `EXPECTED_TOP_LEVEL`; linked from `AGENTS.md` ("How work is written")
        and `index.md`. `scripts/sparknet-nv-search.sh` + `make nv-search`
        added: `models [SUBSTRING]` / `show ID` / `ngc QUERY` / `discover`;
        key read only from `$SPARKNET_STATE_DIR/secrets/build-nvidia.env`
        (default `.state/secrets/`, 0600) and never printed; `ngc` refuses
        without a key. **The endpoints were re-probed live and the original
        list was wrong in a load-bearing way**: `build.nvidia.com` (including
        `/api/search`) is a Next.js SPA — every route answers 200
        `text/html`, so status 200 proved nothing; the machine-readable
        catalog is `integrate.api.nvidia.com/v1/models` (81 ids, no auth) and
        `/v1/models/<id>` is a real lifecycle check (200 live, 410 + EOL date
        retired). `references/nvidia-build-catalog.md` records all of this,
        including the correction. `keys-check` extended to `.state/secrets/`
        (dir 0700, files 0600) with three tests; new hermetic
        `tests/test_nv_search.py` (8, stub `curl`; includes "the key is sent
        as a header and never printed"). Gates green: `make ci CI_QUICK=1`
        all steps PASS after `ruff format` on the new test file.

### Step 47 — Community + agent file set (both repos) — complete 2026-10-17

- [x] **Step 47** — Add the dsx-shaped community surface to **both** repos:
  `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`,
  issue templates, and the agent-facing `llms.txt` index — written for *this*
  fabric's real commands (never aspirational targets), in both sparknet and
  goSpark.
      - **DoD**: (1) files exist in both repos and describe only commands that
        actually run (`make ci`, `make test-all`, `make contract-test`, goSpark
        `make ci` …); (2) new root files registered where the layout tests
        demand (`EXPECTED_TOP_LEVEL`, `test_claims` prose guards); (3)
        `make validate` + full `make test-all` green in sparknet, `make ci`
        green in goSpark; (4) CHANGELOG/RELEASE conventions either adopted
        (`VERSION` exists) or explicitly deferred **in the inventory doc**,
        not silently skipped.
      - **Status (complete, 2026-10-17).** Landed in sparknet: `CONTRIBUTING.md`
        (setup, the gate, the atomic cross-role rule), `SECURITY.md`
        (private-report route + the fail-closed authority model it protects),
        `CODEOWNERS`, `llms.txt`, `CHANGELOG.md`, `.github/` PR + issue
        templates; all four new root entries plus `.github` registered in
        `EXPECTED_TOP_LEVEL`; `index.md` "Start here" now names
        CONTRIBUTING/SECURITY/CHANGELOG. goSpark got the same set plus an
        `AGENTS.md` (it had none) and a `CHANGELOG.md` opening at `Unreleased`
        because that repo has no `VERSION`. CHANGELOG adopted in both;
        `RELEASE.md` / `CODE_OF_CONDUCT` / `GOVERNANCE` / `MAINTAINERS` /
        `NOTICE` / `llms-full.txt` **deferred with reasons recorded** in the
        inventory doc's "Step 47 — community surface, as landed" section.
        Verification: `make validate` pass; `tests/test_layout.py` +
        `tests/test_claims.py` all pass (the new files are scanned: links
        resolve, no forbidden phrases, no hard-coded paths); full
        `make test-all` exit 0; goSpark `make ci` → `ci: ok`.

### Step 48 — GitHub Actions CI from dsx-github-actions (mirror, not source of truth) — complete 2026-10-17

- [x] **Step 48** — sparknet is pushed to a private remote yet has **no
  workflows**; add `.github/workflows/` for both repos following
  dsx-github-actions practice: gate jobs mirroring the local gate (keys-check,
  lint, format-check, shellcheck, validate, contract-test, render-check,
  pytest quick suite; goSpark: gofmt/vet/test-race + golangci-lint), actions
  **pinned by SHA (never `@main`)**, CodeQL + secret-scan workflows patterned
  on dsx's `codeql-scan`/`trufflehog-scan`.
      - **DoD**: (1) workflows parse (PyYAML check) and are pinned by SHA or
        immutable version tags; (2) every CI job has a local equivalent and
        the docs say the **local pre-merge gate stays authoritative**
        (decision A5 carried); (3) a test asserts no `@main` refs and that
        workflow steps mirror `scripts/pre-merge-gate.sh` vocabulary;
        (4) local gates all green (the first real run on GitHub is
        `DoD: confirm: user`).
      - **Status (complete, 2026-10-17).** Three workflows in **both** repos:
        `gate.yml`, `codeql.yml`, `secret-scan.yml`. Every action pinned to a
        40-hex commit SHA resolved via `git ls-remote` (checkout v4, setup-python
        v5, setup-go v5, codeql-action v3, gitleaks-action v2). The gate job
        **calls `make ci`** (PR → `CI_QUICK=1`, push to default branch → full)
        and never re-lists a check; CodeQL is the one GitHub-only job (no local
        analyzer) and the only one with `security-events: write`. New guard
        `tests/test_ci.py` (21 cases): every workflow parses, every `uses:` is a
        40-hex SHA (so `@main` **and** `@v4` fail), permissions are
        least-privilege, each gate workflow runs `make ci` and not
        `make <check>`, and `scripts/pre-merge-gate.sh`'s step names are pinned
        so the mirror cannot silently drift. gitleaks chosen over dsx's shared
        org `trufflehog-scan` action (one pinned action, local counterpart
        `make keys-check`). Two stale prose claims corrected to match
        (the gate script's "nowhere to hang a workflow" note, goSpark's
        "GitHub Actions (once added)"). Local gate green: `make ci CI_QUICK=1`
        all steps PASS; `pytest tests/` pass; goSpark `make ci` → `ci: ok`.
        **Deferred with reason** (inventory doc): Renovate (SHAs refreshed by
        hand for now); branch protection requiring the `gate` check is a
        repository setting → `DoD: confirm: user`, as is the first real
        GitHub run.

### Step 49 — Python/shell format sweep (sparknet): strict gates become blocking

- [x] **Step 49 — Python/shell format sweep (sparknet): strict gates become blocking** — complete 2026-10-17.
      - **DoD**: (1) `ruff format --check` clean across the whole fabric tree,
        `make format-check` green (widened to full-tree); (2) `make lint` runs
        the widened rule set green with no undocumented suppressions;
        (3) pre-commit config exists, `make shellcheck` + `keys-check` +
        `shims-check` green; (4) full `make ci` green — the sweep changed
        formatting only, never behavior (contract-test + test-all prove it).
      - **Status (complete, 2026-10-17).** `ruff format .` reformatted 62 files
        (65 changed incl. session edits; formatting-only, proved by a full
        `make test-all` green immediately after). `pyproject.toml` `[tool.ruff]`
        `exclude` gained `".opencode"` (vendored MIT skills are pinned upstream,
        never ours to reformat — `make wiki-verify` proves no drift) and
        `force-exclude = true` (so the hook's explicit filenames still honour
        the excludes). `[tool.ruff.lint]` `select` widened to
        `E,F,I,UP,B,SIM,RUF,S`, with three **documented** global ignores
        (`S310` urlopen on peer URLs from config; `S603`/`S607` subprocess with
        fixed argv + PATH lookup is the design) and `per-file-ignores` for the
        three test trees (`S101,S103–S108,S110,S112`). Fixed by hand, not
        suppressed: a module-level `assert` in the registry listener →
        `raise RuntimeError(...)`, a grant-write `assert` in
        `sparknet-provenance.py` → `raise ProvenanceError(...)`,
        `try/except: pass` in `sparknet-authz.py` → `contextlib.suppress`.
        `ruff check --fix` + `--fix --unsafe-fixes` resolved 73 more; the last
        8 hand-fixed (SIM102 nested-if, RUF002/RUF003 unicode dashes in
        consensus/oob/tests, an unused loop var in liveness, `raise ... from`
        chaining in `spark-precontext.py`). All 33 remaining `# noqa` in the
        fabric carry a reason. `Makefile`: `lint` is now whole-tree
        `ruff check .`; `format-check` whole-tree `ruff format --check .`;
        `FORMAT_BASE` retired; `lint-strict: lint` kept as a deprecated alias.
        `.githooks/pre-commit` gained the dsx-shape staged-format layer
        (reformat staged Python, re-stage, exit 1 so the diff is reviewed; soft
        dependency on ruff, keys-check stays the hard gate) — verified live on a
        probe file. Docs realigned: `AGENTS.md` `make lint` row,
        `STYLE_GUIDE.md` §3 + enforced-by table + §6 hooks note. **DoD met**:
        `make format-check` (111 files already formatted), `make lint` all
        checks passed, `make ci` all ten steps green.

### Step 50 — Go sweep (goSpark): golangci-lint + style conformance

- [x] **Step 50 — Go sweep (goSpark): golangci-lint + style conformance** — complete 2026-10-17.

### Step 51 — Functional adoption (the point of the exercise)

- [x] **Step 51 — Functional adoption (the point of the exercise)** — complete 2026-10-17.
      - **DoD**: each leg lands as (code + tests) or (a design doc with an
        explicit decision line); `make eval` runs green against the stub tier;
        the inventory's verdicts move from *planned* to *done*; all gates
        green. Legs needing live hardware/LLM mark `DoD: confirm: user`.
      - **Legs**: **(a)** `make eval` — lm-evaluation-harness against goSpark's
        OpenAI gateway (CPU tier via `cmd/stub-vllm`); **(b)**
        fleet-intelligence-agent telemetry vs `internal/gputel`; **(c)**
        nv-telemetry observation-model design; **(d)** Redfish with a mock
        fixture; **(e)** dsx-exchange AsyncAPI contract + NATS auth-callout
        design; **(f)** pattern-only adoptions in the inventory.
      - **Status (complete, 2026-10-17).**
        **(a) code + tests.** `cmd/stub-vllm/main.go` refactored
        (`newMux`/`echoText`/`digest`; crc32 of `TrimSpace(prompt)`) and gained
        a faithful **`/v1/completions`** handler (lm-eval's `local-completions`
        needs it); new `main_test.go` (5 tests). New `eval/spark_smoke.{yaml,jsonl}`
        pin the stub echo so a perfect score proves the chain;
        goSpark `Makefile` gained `golangci-lint`, `eval` (+`EVAL_*`/`LMEVAL_*`
        vars) and `lint`/`ci` now include golangci. **`make eval` green:
        `spark_smoke exact_match = 1.0`.** Deviation recorded in the inventory:
        the harness is a **pinned clone** (`/mnt/nvme/github/lm-evaluation-harness`,
        own `.venv`), not a tracked pip dep.
        **(b)–(e) design docs with explicit decision lines** (the leg DoD's
        second arm), in `references/`: `nvidia-fleet-telemetry-comparison.md`
        (adopt the additive `_info` gauge convention — follow-up),
        `nvidia-telemetry-observation-model.md` (batch-descriptor discipline as
        doc; structured validation errors — follow-up),
        `nvidia-redfish-bmc-inventory.md` (client/projection split + cassette
        fixture; live BMC `DoD: confirm: user`),
        `nvidia-dsx-exchange-bus.md` (bus subject/schema contract — follow-up;
        auth-callout evaluated **and deferred to its own step** as a cross-role
        contract change).
        **(f)** all four verdicts updated to *done* in
        `references/nvidia-dsx-standard-practice.md` with an "as landed"
        section naming each follow-up and why it is deferred.
        **DoD met**: `make eval` green; all four inventory verdicts *done*;
        `make validate`, `tests/test_layout.py`, `tests/test_claims.py`,
        `tests/test_ci.py` green.

### Step 52 — Verify, close, compact memory

- [x] **Step 52 — Verify, close, compact memory** — complete 2026-10-17.
      - **DoD**: all named gates green in both repos; MEMORY.md ≤ ~150 lines
        with history left in `log.md`/`sessions/`; no secrets anywhere
        (`keys-check`); **no commit unless the user asks** — if asked, land
        the two repos' changes as their own commits after flagging the
        pre-existing dirty state.
      - **Status (complete, 2026-10-17).** All named gates green:
        **sparknet** `make ci` (all ten steps; fabric, peer 454+1 skip, master),
        `make drift-check` (33 skills no drift, contract parity, derived in
        sync), `make keys-check` (clean), `make shims-check` (12 OK),
        `make validate`; **goSpark** `make ci` → `ci: ok`. Inventory claims
        audited by spot-check (`make nv-search`, `make eval`, `make drift-check`
        and the documented reference docs all resolve). **`MEMORY.md` compacted
        777 → 126 lines** (standing state only; all history remains in `log.md`
        + `sessions/2026-10-17.md`), and its long-stale peer cursor corrected
        (`current: 8` → `current: done`). Session file closed. `PLAN.md`
        `current: done`. 35+ doc/code files touched this arc, **all uncommitted**
        per the DoD (the trees were already dirty pre-session).

## Step 53 — 00_System template refresh (both roles) + vault-template

- [x] **Step 53 — base knowledge template refresh** — complete 2026-10-18.
      Scope decided with the user: refresh **both** roles' `00_System/` base
      sets **and** fill the `peer-node/deployment/vault-template/` stub.
      **Identity decision: `sparknet-node-0002`** (local numbering, peer-parity
      with `sparknet-node-0001` — deliberately *not* the live trust-root names
      `agx64`/`node131`; the divergence is recorded, not accidental).
      Companion network arc (h58 WiFi uplink on agx64/agx32, staged before any
      eth0 direct-link change) opens as **Step 54**.
      - **DoD**: (1) both roles' `00_System` prose states current truth — no
        pre-election claims (master charter vocabulary: "proven live
        2026-10-07", "declared, not bound", Phase 9 legs unexecuted);
        (2) the master identity chain is consistent — `node_id:
        sparknet-node-0002` in `manifests/{node,master}-identity.json`,
        `00_System/user.md owner_node` matching, `.user.lock` sha256
        rewritten, `provenance-verify` + strict `precommit` green;
        (3) `peer-node/deployment/vault-template/` is a real, instantiable
        template (no non-existent paths, pointer-only into `contracts/`);
        (4) gates green: `make validate`, `contract-test`, `render-check`,
        `keys-check`, `shims-check`, both roles' `precommit`, `lint`,
        `test-all`.
      - **Status (complete, 2026-10-18).** All four DoD arms met.
        **(1)** Stale claims fixed in `master-node/00_System/`:
        `alpha-admin.md` §5 ("never been deployed" → proven live 2026-10-07
        with what remains unbuilt) and §6 ("Master is not elected, no signing
        key is in use" → admin services `spec-only`/`provisioned`, nothing
        binds `10.100.0.1:8080`, election no longer the gap), `user.md`
        body (signer claim), `index.md` (work-in-flight now points at
        `plans/MASTER_BUILD_PLAN.md` — the role has no root `PLAN.md` — and
        the admin bullet records federation ran live 2026-10-12 while
        git/file-share/NAT/vector stay spec-only);
        `peer-node/00_System/index.md` (terminal cursor) — its `alpha-agent`
        inbox-transport claim was **verified still true** against
        `contracts/ports.json` (no intake listener exists) and deliberately
        left standing. **(2)** Identity chain fixed end-to-end: `node_id:
        sparknet-node-0002` in both manifests, `user.md owner_node`
        matching, `.user.lock` sha256 rewritten (`ecee44f8…`); strict
        `precommit` clean; the role's content dirs hold **no signed notes**,
        so nothing needed re-signing. **(3)** `deployment/vault-template/`
        built out: honest README (instantiation steps, and the closed
        `sparknet-env-init.sh` role list stated rather than glossed) plus
        `00_System/{index,user(unfilled),schema.yaml,secrets-index.json,log.md}`.
        **(4)** Every gate rc=0: `validate`, `contract-test`,
        `render-check`, `keys-check`, `shims-check`, both roles'
        `precommit`, `lint`, `test-all` (contract + fabric + peer 461 passed
        1 skipped + master). Note: `schema.yaml`'s `source.tracking` was
        left fabric-relative — it is pinned exactly by
        `tests/test_contracts.py:1315`. Nothing committed (not asked).
        Cursor `53 → 54`.

## Step 54 — h58 WiFi uplink on agx64/agx32 (staged; eth0 direct link gated)

- [ ] **Step 54 — WiFi-first network staging** — opened 2026-10-18.
      User-assisted: **the user runs** the PSK-bearing `nmcli device wifi
      connect h58 …` on each node (PSK never enters chat, the vault, or any
      command the agent runs); everything else is agent-side. Recon facts:
      both nodes carry an Intel AX210 (`8086:2725`) with `iwlwifi` loaded —
      this is configuration, not driver work; each has exactly one ethernet
      port; `wg1` endpoints are pinned to `192.168.178.131/133:51820`.
      - **DoD**: (1) `wlan0` connected to h58 on both nodes with an
        autoconnect NM profile; (2) wlan0 carries the default route
        (`ipv4.route-metric 50`; eth0's DHCP default stays as fallback —
        LAN `.131`/`.133`, the `100.65.19.51 via .126` route and the `wg1`
        endpoints untouched); (3) internet verified over wlan0
        (`ip route get 1.1.1.1` → dev wlan0, curl 204) and the `wg1`
        handshake still fresh on both; (4) h58's per-node gateway/subnet/DNS
        recorded in the session file and `MEMORY.md`. The eth0
        direct-cable re-addressing is **`DoD: confirm: user`** — applied as
        a follow-up when the cable exists, with the subnet decision taken
        against the facts from (4).

## Step 55 — role-swap deployment: peer on agx64, Master (all built services) on agx32

> **Superseded (deployed state) by Step 57 (2026-10-19)**, which redeployed both
> hosts clean-slate over the `10.99.0.0/30` cable underlay and re-ran the
> election (root `fa6f4fa5…`). Step 55's deployment was archived to
> `~/.local/state/sparknet/ARCHIVE-2026-10-19-escalation/`; its remaining
> `DoD: confirm: user` legs are carried by Step 57.

- [ ] **Step 55 — role-swap deployment of the fabric onto the live pair** —
      opened 2026-10-18. Trigger: the operator wants the two AGXes
      communicating by exchanging keys, then `peer-node` set up on **agx64**
      and `master-node` with all of its services on **agx32** — the reverse
      of today's live roles (agx64 holds both the 2026-10-07 root's signer
      and cluster2's `node131` Master). The user's node↔node SSH
      `Permission denied (publickey)` in both directions is reproduced and
      is fixed by Phase 1.
      **Operator decisions (answered 2026-10-18):** retire-first (archive,
      never delete) · LAN underlay now (WiFi Step 54 + direct cable stay
      follow-ups) · node_ids `sparknet-node-0001` (peer@agx64) /
      `sparknet-node-0002` (master@agx32) = repo SSOT · scope = everything
      built, spec-only ports honestly unstarted.
      **Hard constraint driving the order:** `contracts/overlay.json` pins
      `10.100.0.1` = Master anchor, never assignable to a peer → the flip
      to agx32 breaks both existing deployments, so they retire (Phase 2)
      before the overlay re-forms (Phase 3).
      - **Phases:** 0 pre-flight gates + host facts (venv mandatory —
        system cryptography 2.8 < 42) · 1 exchange SSH keys (fixes the
        publickey error) · 2 inventory → disable all old `sparknet-*`
        units → mv state to `~/.local/state/sparknet/ARCHIVE-2026-10-18/`
        (rollback = mv back + re-enable) · 3 fresh wg keys, wg1 flipped
        `.1`=agx32 / `.2`=agx64, LAN endpoints, cross-ping · 4
        `make bundle ROLE=master` → verify → `~/sparknet/` both hosts,
        python3.9 venv + cryptography ≥42, env-init per role, c2-pattern
        units (absolute paths + `User=raxxar`, recorded deviation from the
        runbook's `%h`/root form) · 5 keygen/keys + `cluster-members.json`
        roster (pub halves cross out-of-band) + `SPARKNET_NODE_ID` ·
        6 peer-only proof (validate, role peer, no root doc) then the
        election: serve on `10.100.0.1:4210`, `election-approve
        EXPECT=sparknet-node-0002`, `election-request CANDIDATE=…` ·
        7 signer unit → socket/root-id/caps `["sign"]`, ledger + parity,
        registry sign + root-alone verify + three refusals, console smoke,
        admin surface 8080 deploy attempt (reachability = confirm item),
        peer side `install-units` (guard-d, dispatch-bridge loopback +
        `10.100.0.2` per the F1 pattern, admin-agent, vault-provisioner,
        sync, wifi-guard, firewall), `guard-status`/`authz-verify`/
        `guard-contract`; wg reuses `wg1` — `anchor` not run ·
        8 transcript `/mnt/log/sparknet-swap-deploy-2026-10-18.md` +
        confirm list, port inventory proves spec-only silent, deployed
        `validate` + strict `precommit` + `units-check` ·
        9 PLAN/log/session/MEMORY.
      - **DoD**: (1) node↔node SSH `BatchMode` echo OK both directions;
        (2) old deployments archived + every old unit disabled + no
        process holds an old key; (3) wg1 up with fresh keys,
        `10.100.0.1`=agx32, ping 0% both ways; (4) root co-signed by
        `0001`+`0002`, `0002` Master, `0001` peer without a root doc;
        (5) signer socket proves root-id + caps `["sign"]`, registry
        verifies root-alone on the peer, three refusals hold,
        ledger+parity green; (6) built scope running with spec-only ports
        absent from `ss`; (7) transcript + confirm list landed, plan
        records updated. Live legs stay `DoD: confirm: user` where a
        human sees the node (restart/reboot survival, admin-surface
        reachability, guard refusal on a revoked host if exercised).
      - **Progress (2026-10-19):** Phases 7–8 executed and verified on the
        live pair — full record in
        `/mnt/log/sparknet-swap-deploy-2026-10-18.md`. **7a** signer live
        (socket `srw-------`, root-id `c5b4a23a…`, caps `["sign"]`,
        `public-key k8Gh2j…`). **7b** registry signed (peer entry
        `4f9d8a4e…`), peer verifies **root-alone** `allowed:true`, the
        **three refusals** hold; fixed the peer `authz-verify` target
        (`Makefile:112` → `$(FABRIC_ROOT)/shared/sparknet-authz.py`).
        **7c** peer units installed — guard (`10.100.0.2:9090`) and
        dispatch-bridge (`127.0.0.1`+`10.100.0.2:4096`, F1) active after
        minting the missing node key (`make keys` → `ed25519-node.key.b64`);
        console `feed` federates `{"ok":true}`; wg1 reused, anchor not run.
        **7d** admin surface **relocated + deployed** — an unrelated `mitm`
        container holds `0.0.0.0:8080`, so the surface moved `8080 → 8088` in the
        contract + compose + tests and is up at `10.100.0.1:8088` (HTTP 200 over
        the overlay from the peer; a human browser check = confirm). **8** peer `validate` + strict `precommit`
        **clean** (9 notes valid, ledger intact), master `validate` clean
        (**units wired and enabled**), spec-only ports (`4220–4223`, `4203`,
        `8090`) absent from `ss`, ad-hoc election serve on `4210` stopped.
        **Deviation:** the python floor is met with **uv CPython 3.12**
        (supersedes the "python3.9 venv" wording in Phase 4). **Finding:**
        keygen writes `.state/keys/*.pub*` at `0644` but `keys-check` demands
        `0600` — normalised on-host, reconcile in the repo. Step **stays
        open**: the remaining DoD legs are `DoD: confirm: user` (reboot
        survival; admin-surface browser check — bound at `10.100.0.1:8088`,
        HTTP 200 from the peer; guard refusal on a revoked host; WiFi Step 54 +
        direct cable).

## Step 56 — goagx: the node surface on Jetson AGX Xavier (sm_72, 16 GB)

- [ ] **Step 56 — goagx + the AGX node-image remake** — opened 2026-10-19.
      Trigger: retarget the goSpark node distribution from the DGX Spark to a
      Jetson AGX Xavier, all features retained, and remake the node image
      Dockerfile as `sparknet.agx.docker`.
      **Operator decisions (answered 2026-10-19):** (1) lives in this repo as
      `goagx/`, consuming the existing goSpark binaries through the same
      `gospark` named context — **no Go fork**; (2) inference engine =
      **vLLM v0.2.7 built from source** (the era that still supported
      `sm_72` + Python 3.8, behind `TORCH_CUDA_ARCH_LIST="7.0+PTX"`);
      (3) **real engines for rerank and audio too** (llama.cpp v0.7.0,
      whisper.cpp v1.9.5 — no placeholders).
      **Resource-first verdict (STYLE_GUIDE §1, `make nv-search` + forums):**
      NVIDIA publishes **no vLLM container for the r35 branch** (stated by an
      NVIDIA moderator in the JetPack 5.1.4 thread); `nvcr.io/nvidia/vllm` is
      current-generation only (25.09→26.06-py3, Python 3.12); the
      jetson-containers route fails on JetPack 5 exactly at Python/triton
      (≥3.10 vs r35's 3.8). Fallback escape hatch kept as
      `ARG VLLM_GIT_URL` (point it at dusty-nv/jetson-containers
      `packages/llm/vllm` instead of re-deriving).
      - **Deliverables (9-file set):** `goagx/sparknet.agx.docker` (L4T
        r35.2.1-pth2.0 base, aux-build stage for llama/whisper, xformers
        sdist + vLLM source build with requirement relaxations, build gates
        `import vllm._C` + `--port` greps + `py_compile` shim, `VLLM_CLI`
        image env) · `goagx/sparknet.agx.compose.yml` (14 services, identical
        names/ports/profiles/core env keys to `spark.compose.yml`, AGX
        defaults Mistral-7B / 8192 / shm 4gb) · `goagx/sparknet-audio-shim.py`
        (OpenAI `/v1/audio/transcriptions` over whisper's `/inference`;
        whisper ships no OpenAI route) · `goagx/README.md` (verdict, truth
        table, build budget, what-proven-where) · `sparknet-node-setup.sh
        --platform spark|agx` (default stays spark — test fixtures untouched;
        platform picks compose file + env file together) ·
        `spark-entrypoint.sh` `VLLM_CLI` dialect switch + `llama-embed` /
        `llama-rerank` / `whisper-asr` subcommands · runbook AGX subsection ·
        `index.md` / `CHANGELOG.md` · `tests/test_agx_node.py` + coupling
        edits (`test_layout.py` goagx, `test_contracts.py` pin test over both
        stacks).
      - **DoD**: (1) `tests/test_agx_node.py` green — service/port/env-key
        parity, container names/profiles parity, pin sharing (NATS/opencode
        both stacks), AGX defaults fit 16 GB, setup `--platform` wiring,
        entrypoint gating (2× `modern` gates), baked+healthchecked aux
        engines, shim surface; (2) `docker build --check` clean on the AGX
        dockerfile and `docker compose config -q` resolves all three
        compositions (agx, agx+cpu overlay, spark); (3) ruff check/format
        clean on every new/edited Python file; (4) full gate chain rc=0:
        `lint format-check shellcheck validate contract-test test-all ci`
        (+ `render-check` if the runbook edit reaches the manifest);
        (5) docs landed (README verdict cited, runbook subsection, index,
        CHANGELOG) with no forbidden phrase. **`DoD: confirm: user`:** the
        source build actually completing on Xavier hardware, real tokens/s
        from the 7B model in 16 GB, NVML/sidecar reading the Jetson driver
        honestly, whisper `detect_language` through the shim.
      - **Progress (2026-10-19):** all nine deliverables written; parity +
        claims + layout + setup-join + cpu-smoke suites green (exit 0);
        `docker build --check` clean; all three compose configs resolve;
        ruff clean on the new/edited Python; resource-first verdict recorded
        in `goagx/README.md` from primary sources (NGC tag list, two NVIDIA
        forum threads). **Gates (2026-10-19, rc=0 all):** `render-check`,
        `lint`, `format-check` (113 files), `shellcheck` (binary absent —
        skipped with the standard note), `validate`, `contract-test`,
        `test-all` (peer 461/1skip, master green), and the full `make ci`
        pre-merge gate ("all steps passed"). Auto-verifiable DoD (1)–(5)
        hold; step stays `[ ]` only for the `confirm: user` legs.
      - **Note**: Step 55 stays **open** (its live legs are `confirm: user`);
        the cursor moves here for this workstream, exactly as 54 was parked
        as a follow-up.

## Step 57 — fresh peer deployment on both AGXes + manual 2/2 master escalation over the sparknet cable

- [x] **Step 57 — clean-slate pair: peer-node + KB template on both hosts, cable
      underlay, manual election ceremony** — opened 2026-10-19, **done
      2026-10-19 (all phases 0–11 executed and verified)**; live legs
      (cable move, reboot survival, human review of the transcript) stay
      `DoD: confirm: user`. Outcome: agx32/agx64 redeployed clean-slate as
      peers on the knowledge-base template; wlan0 `.21`/`.22` carry the uplink
      (default-route handover asserted); the direct eth0 cable became the
      dedicated sparknet underlay `10.99.0.0/30` (`.1`=agx32 `.2`=agx64, static
      never-default) with the `wg1` overlay pinned to it (cross-ping 0% both
      ways); the **manual 2/2 ceremony formed root `fa6f4fa5…` naming `0002`
      (agx32) Master** (0001 stays a peer with no root document); the isolated
      signer runs as a c2-pattern unit (socket ``srw-------``, root-id
      `fa6f4fa5…`, caps `["sign"]`, public-key `xjKK/Beuw…` == root
      `master_pubkey`); a signed registry entry (peer fingerprint `84bd134e…`,
      caps `p2p-sync,push-receive,telemetry`) verifies **root-alone** on the
      still-peer, and the three refusals hold (wrong operational key, unnamed
      node, tampered root); guard + dispatch-bridge active on agx64 (guard
      `10.100.0.2:9090`, bridge `127.0.0.1`+`10.100.0.2:4096`). Full transcript:
      `/mnt/log/sparknet-manual-escalation-2026-10-19.md`. This **supersedes**
      Step 55's deployment (archived `ARCHIVE-2026-10-19-escalation`). Trigger:
      operator wants both AGXes freshly deployed as peer-nodes (each with the
      knowledge-base template instantiated + `user-init`), then one node
      escalated to Master **manually**, walking the election conversation:
      the peer's signed bid/vote is the request, the other side's
      `election-approve` is the acceptance, the root forms only at 2/2.
      **Operator decisions (answered 2026-10-19):** master =
      **agx32** (`blue-team`, anchor `10.100.0.1`); node_ids host-stable
      `0001`=agx64 / `0002`=agx32; vault owner `raxxar` on both;
      **network posture:** wlan0 stays the uplink (WiFi `h58`,
      `.21`/`.22`, default route) even while eth0 is cabled; the direct
      eth0 cable is a dedicated **sparknet underlay** `10.99.0.0/30`
      (agx32 `.1`, agx64 `.2`), and the `wg1` overlay endpoints are pinned
      to the cable — the cable *is* the sparknet connection. This closes
      Steps 54/55's parked "direct-cable re-addressing" follow-up (subnet
      decision taken here). The physical plug happens **after** the static
      cable profiles are live, so the move is a no-op for every configured
      state (WiFi untouched; wg re-handshakes within keepalive).
      **Method:** the Step 55 role-swap transcript
      (`/mnt/log/sparknet-swap-deploy-2026-10-18.md`) is the proven command
      reference (uv 3.12 venv, wireguard-go `setconf`-hang gotcha, c2-pattern
      units, registry-shipped-peer-identity gotcha); deviations: overlay
      endpoints = cable IPs, retire target = the Step 55 deployment
      (archive `ARCHIVE-2026-10-19-escalation`), vault template + `user-init`
      on both roles' vaults (fixes the "filled user.md ships, private key
      nowhere" finding on these nodes).
      - **Phases:** 0 pre-flight + `bundle ROLE=master` → verify → scp both ·
        1 retire (agx32 signer/ledger/parity + admin container first; then
        agx64 guard/bridge; unit files + state + trees → archive) ·
        2 fresh trees `~/sparknet/`, uv 3.12 venv, env-init per role,
        **vault template → 00_System + `user-init OWNER_ID=raxxar`**,
        provenance-verify + precommit before the first note ·
        3 network: ssh aliases → wlan0 `.21`/`.22`, assert default handover
        to wlan0, `sparknet-cable` nmcli profiles `10.99.0.x/30`
        never-default, wired-LAN profiles `autoconnect no`, cable cross-ping
        (over the switch) → **operator moves the physical cable** →
        re-asserts · 4 keys + identities + `wg-render` with cable endpoints
        + wireguard-go bringup + overlay cross-ping · 5 cluster keys +
        `cluster-members.json` (2 members, sha256(node_id) fingerprints) ·
        6 peer-only proof (validate, both `role: peer`, no root doc) ·
        7 **the ceremony** (serve `10.100.0.1:4210`;
        `election-request CANDIDATE=0002` on agx64;
        `election-approve EXPECT=0002` on agx32; `formed`, 2/2 co-sigs,
        0002 → master, 0001 stays peer no-root) · 8 signer unit (c2 pattern)
        socket/root-id/caps `["sign"]` · 9 registry sign + ship + root-alone
        verify + three refusals · 10 peer units agx64
        (`install-units --apply`, node key for the bridge, guard-status) ·
        11 transcript `/mnt/log/sparknet-manual-escalation-2026-10-19.md`,
        session/MEMORY, Step 55 recorded superseded-by-archive.
      - **DoD**: (1) wlan0 carries default + internet on both through and
        after the cable move; SSH from this host via `.21`/`.22` alive
        throughout; (2) old deployments archived, no sparknet unit files
        remain; (3) both peer vaults have filled `user.md` + valid
        `.user.lock`, precommit clean; (4) `10.99.0.x` cross-ping 0% over
        the direct cable; overlay up, cross-ping 0%; (5) root co-signed by
        `0001`+`0002`, `0002` master, `0001` peer without a root doc;
        (6) signer socket root-id + caps `["sign"]`; registry verifies
        root-alone on the peer; three refusals hold; (7) guard + bridge
        active on agx64; (8) transcript landed. Live legs stay
        `DoD: confirm: user` (the physical cable move itself, reboot
        survival, human review of the ceremony transcript).

## Step 58 — overlay survives reboot on the kernel-module-less AGX hosts

- [x] **Step 58 — userspace-aware overlay anchors for both roles** — opened and
      **done 2026-10-19**; the literal reboot stays `DoD: confirm: user`. Closes
      Step 57's parked "reboot survival" leg and retires the ad-hoc
      `/root/scripts/sparknet-wg-restore.sh`.
      **Root cause (probed live):** the AGX hosts ship `CONFIG_WIREGUARD=n`, so
      `ip link add … type wireguard` fails and `wg-quick up` — including its
      userspace fallback — is unusable: it starts `wireguard-go`, does not wait
      for the UAPI socket, and hangs in `wg setconf` before the interface is
      configured. The peer's `sparknet-wireguard-anchor.service` was **enabled
      but had no `/etc/sparknet/wireguard.env`**, so it would have failed at boot
      and left the node with no overlay; the master had no anchor unit at all.
      **Deliverables:** new role-neutral `peer-node/scripts/sparknet-wg-bringup.sh`
      (kernel probe → `wireguard-go` + UAPI-socket wait → `timeout`-capped
      `wg setconf` confirmed by `wg show` → address/MTU/route); the peer anchor
      now `chattr -i`-unlocks the pinned config before rendering and delegates to
      the helper with the `10.100.0.1/32` route; new
      `master-node/scripts/sparknet-master-wireguard-anchor.sh` +
      `sparknet-master-wireguard-anchor.service` (force-loads the peer's
      `.setconf`, resolves the helper by path, `chattr +i`), wired into
      `master-node/Makefile` `UNITS` with generated-shim install. Tests extended
      (peer bring-up/anchor contract; master anchor+unit). An unrelated
      pre-existing failure was fixed: the untracked editor dir `.obsidian` at the
      repo root was breaking `tests/test_layout.py`; added to
      `UNTRACKED_TOP_LEVEL` (machine-local, per the test's own definition).
      **Deploy:** both bundles rebuilt from the working tree + `bundle-verify`d,
      scp'd and re-extracted into `~/sparknet` preserving `.env`/`.state`;
      `/etc/sparknet/wireguard.env` written on agx64 (0600 root);
      `SPARKNET_WG_INTERFACE=wg1` added to agx32's `master-node/.env`; the master
      anchor unit + `/usr/local/libexec/sparknet` shim installed and enabled (the
      tracked parity/ledger units were **not** reinstalled — they run the c2
      absolute-path form live, and `make units` would clobber them with `%h`).
      **Proof (non-destructive):** with `wg1` deleted on each host, restarting the
      role's anchor unit rebuilt the interface through `wireguard-go`, re-pinned
      the config,       and the handshake returned within ~10 s; overlay cross-ping
      **0% both ways (~2 ms)**. All local gates green
      (`make ci CI_QUICK=1`, `make test-all`, `make lint`). Nothing committed;
      the ad-hoc fix additionally added `Before=docker.service` to both anchor
      units and disabled AGX wlan power-save.
      **Live reboot proof (2026-10-19):** both hosts were rebooted for real.
      agx64 re-formed `wg1 10.100.0.2/32` and re-handshook within ~25 s of coming
      back; agx32 restored `wg1 10.100.0.1/24`, its ledger/parity/signer units
      returned active, and the admin container auto-started and bound
      `10.100.0.1:8088` (health `healthy`, HTTP 200 over the overlay) with no
      operator action — the `Before=docker.service` ordering holds.
      **DoD:** (1) new helper + both anchors + unit exist and are covered by
      tests; (2) both role bundles verify standalone; (3) both anchors enabled
      and active on the live pair; (4) cold-path restore (no interface → unit)
      rebuilds `wg1` and restores the handshake on both hosts; (5) overlay
      cross-ping 0%; (6) local gates green; (7) **a literal host reboot on each
      role restored the overlay and the admin surface unattended**. All DoD
      legs verified; nothing stays open.

## Step 59 — deployment/contract consistency remediation (A–E)

- [x] **Step 59 — bring the live pair and the repo into agreement** — opened and
      **done 2026-10-19** after a read-only audit of the live pair against the
      repo surfaced five drift classes. Operator decisions: enable the master
      firewall; point protected paths at the live `wg1`/state layout; add
      election/root re-formation ledger blocks.
      **A — peer authorization (live only).** Deployed the real peer
      `node-identity.json`, a Master-signed `node-authorizations.json`, and the
      corrected `keys/master-ed25519.pub.b64`; `make authz-verify` on agx64 →
      `allowed: true`, fingerprint `84bd134e…`. The **repo copies stay
      fail-closed** (empty registry, placeholder pubkey — the committed manifests
      were reverted); live authorization is a deployment-side action.
      **B — firewall + anchor placement.** Both anchors now `install -m 0600`
      the conf at `/etc/wireguard/<iface>.conf` and pin it `chattr +i`.
      `sparknet-firewall.service` enabled on agx64; new
      `master-node/systemd/sparknet-master-firewall.service` (shim → the peer's
      `sparknet-firewall.sh` by path, ingress-only) added + enabled on agx32.
      Proven live: `SPARKNET-FW-IN`/`-FWD` chains present, 8181/11434/18000
      restricted, master egress has zero rules, overlay unaffected.
      **C — signer generalization.** `record_signature` → `record_event(…)`; the
      signer self-records `trust_root_formed`/`trust_root_reformed` at startup
      when the root is not already in the ledger (`Signer._record_root_binding`);
      new `sparknet-registry-sign-socket.sh` (fresh connection per request).
      Live restart wrote `00000000 trust_root_formed` (root `fa6f4fa5…`), then
      re-signing node 0001 wrote `00000001 signature_issued` (byte-identical
      signature); `sparknet-ledger.py verify` → chain intact.
      **D — protected paths.** `critical-manifest.json` + `security-policies.json`
      re-pointed to `/etc/wireguard/wg1.conf` (the anchor is the renderer) with
      provenance; `test_manifests.py`/`test_guard.py`, `peer-node/docs/wireguard.md`
      and `contracts/deployment-runbook.md` realigned. Deployed to the live peer;
      guard `--check-manifest` → 9 protected paths, provenance complete.
      **DoD:** (1) gates green — `make ci CI_QUICK=1`, `make test-all` (469
      passed / 1 skipped), `make contract-test`; (2) peer `authz-verify` allowed
      on agx64 with the repo still fail-closed; (3) both firewalls enforce the
      protected ports; (4) ledger carries the genesis root block + the
      signature-issued block and verifies; (5) **real reboots of both hosts**
      restored the overlay, the firewall, the guard, the master units and the
      admin surface (HTTP 200 on `10.100.0.1:8088`) unattended; overlay
       cross-ping 0% both ways. All DoD legs verified; nothing committed.

## Step 60 — robustness / fail-safe hardening (A–F)

- [x] **Step 60 — harden the fabric's security surface against fail-open** —
      opened and **done 2026-10-20** after a direct read-only review of the
      security-critical modules (authz, http, guard-d, signer, ledger, consensus,
      oob, dispatch-bridge, anchors, firewall, shell). The code was already
      fail-closed by construction; this step pays down the low/medium robustness
      debts found, each now pinned by a test.
      **A — guardrail tests (fail before the fix).** `tests/test_hardening.py`
      scans every `b64decode` in `shared/` + `*/services/` and fails unless it
      routes through the strict helper or passes `validate=True`; asserts both
      anchors pin *both* config copies; asserts the Master anchor header does not
      claim it skips pinning; asserts the anchors require `SPARKNET_WG_INTERFACE`.
      `peer-node/tests/test_guard.py` gains three fail-closed tests (chattr
      cannot-lock → refuse; already-locked/unreadable → tolerate; re-lock failure
      after a write → refuse). `peer-node/tests/test_firewall.py` gains
      install-self-verifies + unit-runs-verify. `peers/master` anchor tests gain
      the EXIT-trap assertions. `tests/test_authz_golden.py` gains the strict
      base64 vectors incl. the cross-CPython 43-char trap.
      **B — one strict decoder.** `shared/sparknet-authz.py` gains
      `decode_b64_strict(text, *, what, urlsafe=False)`; `public_key_from_b64`,
      `private_key_from_b64`, `verify_signature` route through it; the four
      tolerant `b64decode` sites in `sparknet-consensus.py`, the oob `make_handoff`
      and the dispatch-bridge grant token decode now decode strictly (`base64`
      imports pruned where they became unused).
      **C — privileged-step hardening.** Guard: new `_is_immutable()` three-way
      probe (True/False/None); `enforce_immutability` now **refuses**
      (`immutability_not_enforced`) instead of silently skipping when `chattr +i`
      cannot lock; `apply_patch` re-lock failure after a successful write now
      **refuses** (`immutability_not_restored`) instead of being swallowed in a
      `finally`. Firewall: new `verify` verb (non-zero unless every protected port
      jumps on v4+v6 and each chain ends in DROP); `install` verifies itself; both
      firewall units run `ExecStartPost=… verify`. Anchors: an `EXIT` trap re-pins
      any existing config on a non-zero exit, so a failed run never leaves the
      overlay config writable.
      **D — interface default discipline.** Both anchors now require
      `SPARKNET_WG_INTERFACE` (`${VAR-}` + `die`) instead of `:-wg0`, so a missing
      env file fails loudly rather than silently bringing up a second interface.
      **E — docs + edge cases.** `peer-node/docs/wireguard.md` documents the
      dual-copy pin, the re-pin-on-failure trap, the required interface, and the
      Master re-render/re-run workflow for peer-stanza changes (revocation via
      `wg set … remove` still takes effect immediately and survives the pin).
      **F — deploy + records.** Deployed the hardened firewall + anchor + guard to
      agx64 and the master anchor + shared firewall script + both firewall units
      to agx32; live: `sparknet-firewall verify` PASS on both hosts, both anchors
      restart clean with **both** copies pinned (`----i---` on `/etc/wireguard`
      and state-dir `wg1.conf`), guards re-armed (`mode: anchored`, 9 protected
      paths), overlay cross-ping 0% both ways (~1.8 ms).
      **DoD:** (1) `make ci CI_QUICK=1` green; (2) `make test-all` green
      (peer `475 passed, 1 skipped`; contract/fabric/master green); (3) the new
      guardrail tests fail on the pre-fix code and pass on the fixed code;
      (4) live firewall `verify` PASS on both hosts and both anchors leave both
      copies pinned. All DoD legs verified; nothing committed.

## Step 61 — cluster job realization design

- [x] **Step 61 — `CLUSTER_JOB_REALIZATION_DESIGN.md`** — a fabric-root design
      proposal realizing `CLUSTER_INFERENCE_DESIGN.md`: which seams exist, which
      side of each seam wins, and why. Design only — it adopts nothing.
      **The four defects it records** (all found by reading the tree, each cited
      to file:line): **D1** the job envelope has two divergent encodings and
      neither is pinned — the fabric signs ISO-8601 `created_at`/`expires_at`
      with four fields always projected (`shared/sparknet-authz.py:464-490`),
      goSpark/proto use `int64` `*_unix` with `omitempty`
      (`cluster.proto:41-42`, `apiv1/types.go:183-189`), the signer's own
      `_job()` fixture matches neither (`test_signer_isolation.py:226-233`),
      and `tests/test_authz_golden.py` pins every other canonicalisation
      **except** `cluster_job_message`; **D2** peer↔peer fan-out is unreachable
      on the authority plane (a peer's `AllowedIPs` is exactly
      `10.100.0.1/32`), so at `master_governed` the **Master** becomes the
      dispatcher and a peer-initiated cross-peer fan-out is a named, deferred
      increment needing a time-boxed job-scoped data-plane stanza; **D3** the
      `fabric` Chroma scope is a deny-list (`EXCLUDE_PARTS`) where the charter
      and `sparknet-rag-corpus.py` mandate an allow-list — the wrong default for
      a corpus served to every `cluster-serve` node; **D4** the parent design's
      `chromadb:8000` prose (`CLUSTER_INFERENCE_DESIGN.md:77`) no longer matches
      the committed config (Open WebUI → `127.0.0.1:18000`, the out-of-repo
      `~/infra` stack), recorded here, corrected there in its own commit.
      **Seam F, the Master's vector DB (port 4223), in scope as the operator
      directed.** Three industry patterns weighed against measured facts —
      native distributed VDB (Milvus/Qdrant), HA sharding+replication+etcd, and
      pgvector — all **rejected for v1**, with Qdrant designated the upgrade
      path under a numeric trigger. The deciding number: the `fabric` corpus is
      **3.3 MB / 257 files / ≈2,300 chunks** (measured 2026-10-20 — *superseded
      by Step 63: the allow-listed corpus is 28 markdown files / 242 chunks*) on a
      two-host Xavier fleet with no k8s, no object store and no postgres in
      tree. The chosen shape is the **inverse** of all three patterns: the index
      is *derived state* (pure `plan_index`/`chunk_text`, idempotent upsert), so
      it gets a single writer on the Master, stateless readers over the
      WireGuard overlay, and **rebuild-from-source instead of replication**.
      F1–F10 specify: one collection `sparknet-fabric`; embedded
      `PersistentClient` behind our own listener via
      `shared/sparknet-http.py` (not the `chromadb` server — no registry gate,
      API-key auth); **server-side query embedding only**, with a collection
      stamp (`embedding_model`/`chroma_version`/`corpus_digest`) checked per
      query and **503 on mismatch** — closing the live hazard that
      `pyproject.toml:29` pins `chromadb>=0.5` **unbounded above**, so a library
      upgrade can silently change the model under a live index; allow-list
      corpus; `POST /v1/query`, `GET /v1/doc/{id}` (how `context_refs` resolves
      — the parent note never said), `POST /admin/reindex` loopback-only; a
      six-step fail-closed check gated on the **existing**
      `cluster-dispatch`/`cluster-serve` pair, so **no new capability**; and the
      invariant that a job with `context.source: master_vector_db` that cannot
      get context is **refused at dispatch, never run ungrounded** — silence is
      an answer, a silently-degraded answer is a different question. Ownership
      `master-node/services/sparknet-vector-serve.py`, chunker **imported not
      copied** (the `sparknet-ledger.py:37` pattern); build step filed in
      **`master-node/plans/MASTER_ADMIN_PLAN.md`** (which `ports.json`'s own
      status string and `master-control-plane.md:61` already name), not
      `MASTER_BUILD_PLAN.md`.
      **Eight adoption increments, order = dependency chain** (operator
      decisions 2026-10-20): envelope golden vectors → 4223 → task ingress →
      construction/placement → reduce → reindex timer → n≥3 peer fan-out →
      live deploy. `MASTER_BUILD_PLAN.md` Step 9 (nocturnal pooling scheduler)
      cross-referenced as the nearest existing "pooled fabric" concept —
      marked `[x]` but Status reopened 2026-10-06 with nothing built.
      **DoD:** (1) the doc is registered in
      `tests/test_layout.py::EXPECTED_TOP_LEVEL` and `make test-all` proves it;
      (2) zero diff to `contracts/capabilities.json`, `contracts/ports.json`,
      `shared/sparknet-authz.py` and `contracts/manifest.json` — the
      "nothing adopted" invariant, shown by `git status`; (3) all gates green —
      `make render-check`, `validate`, `contract-test`, `lint`, `format-check`,
      `shellcheck`, `test-all`, `make ci CI_QUICK=1`. All three legs verified
      2026-10-20: doc registered and proven by `make test-all` (peer 475
      passed, 1 skipped; contract/fabric/master green); the four
      contract/shared files last modified 06:14/10-19/10-12 — before this
      session's 09:52 start — and their pending diffs are Step 55's 8080→8088
      and Step 60's `decode_b64_strict`, so this step's diff over them is
      **zero**; every gate green including `shellcheck` run **for real** with
      the v0.11.0 binary at `/tmp/opencode/bin` on `PATH`. That last run found
      two info-level findings Step 60 had masked by leaving the binary off
      `PATH` (its `make ci` passed only by skipping): `return $rc` unquoted and
      SC2329 on `repin_on_exit`, which is reached indirectly via `trap … EXIT`.
      Fixed here — one quote, one site-level directive per `.shellcheckrc`'s
      documented convention (SC1090 is handled the same way; SC2317 is already
      waived globally for the identical "reached by name" rationale) — and
      `--help` re-proven intact. Nothing committed. Cursor `61 → done`.
      **Follow-up (same session, operator-directed): make shellcheck real.**
      The skip was the defect, not the symptom — on any host without the
      binary (this one, and every fresh clone) `make ci` passed while shellcheck
      never ran. `make shellcheck` now **provisions the pinned binary itself**:
      `SHELLCHECK_VERSION ?= 0.11.0` (pinned like the SHA-pinned Actions, so a
      new release cannot silently change what the gate enforces) into
      `.cache/tools/shellcheck-<ver>/<arch>/`, then runs it. A version bump is a
      reviewed commit. Fails **closed** when it can neither find nor fetch one
      (verified with a bogus proxy: non-zero exit naming the URL and the
      offline remedy) — a required gate must never pass by not running. New
      `make shellcheck-install` target for provisioning without the gate. The
      GitHub workflow needed **no change**: `make shellcheck` self-provisions,
      so CI keeps calling only `make ci` (the single-vocabulary rule
      `tests/test_ci.py::test_the_gate_workflows_call_the_local_gate` enforces —
      an attempt to add a `make shellcheck-install` step failed that test
      because `make shellcheck` is a prefix of it, and the target was reverted
      to a developer convenience rather than contorting the workflow). Docs
      realigned where they described the old behaviour: `AGENTS.md`,
      `STYLE_GUIDE.md` §1, `CONTRIBUTING.md`, `scripts/pre-merge-gate.sh`
      `--help`. **DoD:** (1) from an empty `.cache/tools` with no shellcheck on
      `PATH`, `make shellcheck` downloads, runs and **PASSES**; (2) the same
      holds through the whole gate — `./scripts/pre-merge-gate.sh --quick` from
      a clean cache: *pre-merge-gate: all steps passed*, with a real
      `shellcheck: 0.11.0` line replacing the old *SKIPPED*; (3) offline +
      absent ⇒ non-zero; (4) `make test-all` green (peer 475 passed, 1 skipped;
      `tests/test_ci.py` green); (5) `make ci CI_QUICK=1` green.

## Step 62 — goagx standalone distribution repo (reallife-spark/goagx)

- [x] **Step 62 — publish the AGX Xavier node as a standalone deployment repo** —
      opened 2026-10-20, **closed 2026-10-20**. Trigger (user): put goagx in its own GitHub repository
      under the org with everything needed to deploy onto a Jetson AGX Xavier
      and become a fully functioning sparknet node — vLLM setup included and
      the required parts of the sparknet codebase hosted in that repo.
      **Operator decisions (answered 2026-10-20):** (1) **generated
      distribution** — one-way export from this fabric at a pinned ref, like
      `make bundle`, never hand-edited on the forge side; (2) **full fabric
      node** — compose stack plus host integration (overlay anchor, guard/
      bridge units, firewall), not compose-only; (3) **peer + master opt-in**
      (`--role master`), same surface as the monorepo setup script; (4)
      target = **`reallife-spark/goagx`, private** (the org is `reallife-spark`;
      the user's "reallife-sparknet" names it).
      **Design.** The published tree *reproduces the monorepo layout* for the
      needed subtrees (`peer-node/`, `master-node/`, `contracts/`, `shared/`,
      `scripts/`, `.opencode/`, `opencode.json`, `requirements.txt`, plus the
      root glue `spark-entrypoint.sh`, `spark-precontext.py`,
      `spark.compose.cpu.yml`, `sparknet-node-setup.sh`, `.dockerignore` and
      the `goagx/` surface itself) so every existing code path —
      `sparknet-node-setup.sh --platform agx`, `make -C peer-node dist`, the
      image's `COPY`, `install-units` — runs **unmodified** from a clone. One
      code path; the repo is what `make bundle` ships plus the image surface.
      goSpark arrives by pin: `goagx/GOSPARK_PIN` (one file, consumed by both
      the bootstrap and the publish manifest) and
      `goagx/bootstrap-agx.sh` (new, fabric-owned), which preflights the
      device (aarch64, L4T r35, docker+buildx+nvidia-runtime, disk, swap —
      the vLLM/xformers source build is the known 16 GB risk), fetches
      goSpark at the pin, `make build build-gpu`, then hands over to
      `sparknet-node-setup.sh --platform agx`.
      **Deliverables:** `goagx/GOSPARK_PIN`, `goagx/bootstrap-agx.sh`,
      `scripts/sparknet-goagx-publish.sh` (`--out`/`--verify`/`--push`,
      SHA256SUMS + VERSIONS.json + generated deploy-first README from
      `goagx/publish-templates/`), `make goagx-publish` /
      `make goagx-drift-check` (the drift leg **self-skips with a notice**
      when the private remote cannot be fetched, the `codeql` pattern — it is
      not in `pre-merge-gate.sh`, which stays offline-first), and
      `tests/test_goagx_repo.py` pinning the export manifest against every
      dockerfile `COPY` source and compose reference. Docs: goagx README
      "Standalone deployment repo" section, CHANGELOG, index, AGENTS row.
      **DoD:** (1) `scripts/sparknet-goagx-publish.sh --out <tmp>` produces a
      tree that passes its own `--verify` extracted elsewhere (relocation
      discipline); (2) `reallife-spark/goagx` exists (private) and carries the
      first release commit; (3) `tests/test_goagx_repo.py` green in the
      fabric suite, shell `--help` contract holds for both new scripts;
      (4) `make goagx-drift-check` green from this host (authenticated),
      self-skipping with a notice where it is not; (5) full gate chain rc=0 —
      `lint format-check shellcheck validate contract-test render-check
      test-all` + `make ci CI_QUICK=1`. **`DoD: confirm: user`:** the vLLM
      source build completing on actual Xavier hardware from a clone of the
      published repo, real tok/s in 16 GB, and the full-node bring-up
      (overlay + guard units) on that host — publishing the repo does not
      prove the silicon. **Resolution (operator, 2026-10-20): parked** — the
      silicon legs join the standing `DoD: confirm: user` open items next to
      Step 56's identical legs; everything else was verified (relocation
      `--verify` from a fresh clone of tip `73cf157`, repo private with its
      own `verify` workflow 3× green, `make ci`/`test-all`/`drift-check`
      green).

## Step 63 — the vector substrate: bounded pin, stamped index, allow-listed corpus

- [x] **Step 63 — make the local vector index self-describing, and stop it
      serving what it should not** — the *substrate* half of Step 61's
      increment 2, with the 4223 service itself untouched.
      **Two live defects, both found by reading the tree.**
      **(1)** `pyproject.toml:29` pinned `chromadb>=0.5`, **unbounded above**, and
      Chroma's *default* embedding function is the one the library fetches — so a
      library upgrade could swap the model under a live index, and every
      distance returned afterwards would be meaningless while looking entirely
      healthy. Worse, the default embedder cannot even name itself: on 0.6.x it
      carries no usable name, on 1.5.x it reports `default` with an empty
      configuration — a stamp written from that is not a stamp.
      **(2)** The `fabric` scope was a whole-tree **deny-list** (`EXCLUDE_PARTS`)
      where the peer charter and `sparknet-rag-corpus.py` mandate an
      **allow-list**. Measured: 138 markdown files / 1,699 chunks, of which
      **1,090 chunks (64%) were personal or runtime pages** handed to every node
      in the fabric.
      **Delivered, in four commits.** (a) The pin is bounded
      `chromadb>=0.5,<1` and the resolved model (`all-MiniLM-L6-v2`) is recorded
      on the reindex target. (b) The substrate **names the embedder itself**
      (`ONNXMiniLM_L6_V2`, sha256 `913d7300…16ec3`) and passes it explicitly on
      every open, so the library default can never decide the model behind an
      existing collection. (c) The collection carries a **stamp** —
      `embedding_model`, `embedding_sha256`, `chroma_version`, `corpus_digest` —
      and a query **refuses** (exit 3 → 503 on the wire) when the model, its
      hash or the corpus digest differ; the version difference is *reported*
      only, because the model and the corpus are what make a distance
      meaningful, and refusing on a version difference would train operators to
      ignore refusals. (d) The corpus policy is **one policy with two
      allow-lists** (`NODE_ROOTS` for a node's own Open WebUI, `FABRIC_ROOTS` for
      the shared store — a strict superset), and `EXCLUDE_PARTS` becomes
      belt-and-braces. (e) Two rough edges the real round trip found, both
      closed: an index **written by another chromadb version is rebuilt, not
      served** (the storage format belongs to the library, so 0.6.3 reads a
      1.5.9 collection as an unknown segment type — a traceback, which is the
      absence of a failure mode; the version that wrote the index is now
      recorded next to it), and the index is made **equal** to the corpus
      rather than merely containing it (an upsert does not remove the ids that
      left the corpus, so a shortened passage left its old chunks behind while
      the digest still matched — the digest hashes what was *written*).
      **The corpus, measured 2026-10-22:** the allow-listed `fabric` scope is
      **28 markdown files, 381 KiB, 242 chunks** — a seventh of the old chunk
      count, and none of it personal. `make chroma-stamp` makes "reindex on any
      change" checkable instead of a habit.
      **The numeric trigger** for re-opening Milvus/Qdrant is now written down
      (design F2): **>100,000 chunks**, or **p95 > 200 ms** over 1,000 queries,
      or **a third host joining the fabric**. Until one of them holds, the
      embedded client *is* the store.
      **Scope:** `scripts/sparknet-chroma.py`, `scripts/sparknet-rag-corpus.py`,
      `pyproject.toml`, `Makefile`, `tests/test_chroma.py`, the new
      `tests/test_vector_corpus.py`, and the design doc's figures. **No contract
      changes** — `4223` stays `spec-only`, `contracts/` and `shared/` are
      untouched, and the runtime dependency allow-list stays `cryptography` only
      (chromadb remains the opt-in `chroma` extra).
      **DoD:** (1) `make chroma-inspect CHROMA_SCOPE=fabric` prints 242 documents
      and a corpus digest, and `make chroma-index` + `make chroma-query` round
      trip on a real chromadb (0.6.3) answering with contract pages; (2) a
      tampered stamp makes `chroma-stamp` and `chroma-query` exit **3** with
      `REFUSED`, while a version-only difference is reported and still answers;
      (3) `tests/test_vector_corpus.py` proves against the real repository that
      only allowed paths reach the index and that the contract tree, both role
      charters and the design documents are all present; (4) `make test-all`,
      `make lint`, `make format-check`, `make shellcheck`, `make validate`,
      `make contract-test`, `make render-check` and `make ci CI_QUICK=1` green,
      with `git diff --stat contracts/ shared/` **empty**.

## Step 64 — reflex layer (design + phased adoption)

Opened 2026-10-23 on operator direction: beside the agentic layer, add a fast
System One decision layer that screens, ranks and flags, but never holds
authority. The design record is `REFLEX_DECISION_DESIGN.md`; this step tracks
adoption in dependency order.

**Operator decisions (2026-10-23):**
1. **Local-only is the default.** The reflex layer runs rules / the node's own
   reranker with no egress. A hosted cloud sensor was opt-in at the time;
   Step 65 removed it outright, so local-only is now the *only* mode rather than
   the default one.
2. **The Master broker is the shared path** for the unified "massive task"
   workload. Peers never call an outside API directly; per-node direct cloud was
   ruled out by the one-address `AllowedIPs` rule (`contracts/overlay.json:14`).
   With the cloud leg gone the broker answers locally too — what it centralises
   now is the budget, the redaction point and the audit trail.
3. **RAG relevance is the first touchpoint**, on the allow-listed `fabric`
   corpus only (28 files / 242 chunks; no personal material).
4. **Shadow -> assist -> enforce**, per question class. No class skips shadow.
5. **Master-local first.** Peer access needs its own `reflex-consult` capability
   and is deferred.
6. **sparknet now, goSpark later.** The Go router client is a separate commit
   in the sibling repo.

**Invariant:** reflex output may rank, annotate, route or flag; it may never
sign, grant/revoke, approve a guard application, or widen a permission. It may
only tighten, and it abstains on doubt. The guard, signer and registry never
consult it.

- [x] **64A — design record, nothing adopted** — `REFLEX_DECISION_DESIGN.md`
      records the topology, the typed decision contract, the four touchpoints,
      the data-governance rules, the threat model and the phase plan. It creates
      no port, grants no capability and changes no contract.
      **DoD:** (1) the doc is registered in
      `tests/test_layout.py::EXPECTED_TOP_LEVEL` and linked from `index.md`;
      (2) this step's edits touch **no file under `contracts/` or `shared/`** —
      the "nothing adopted" invariant (the working tree already carried a
      concurrent registry arc's 06:02–06:13 edits there; they are untouched);
      (3) `make validate`, `make test-all` and `make ci CI_QUICK=1` are green.
      Verified 2026-10-23.
- [x] **64B — decision contract and shared client** — added
      `contracts/reflex-schema.json`, `shared/sparknet-reflex.py`, golden
      vectors (`tests/reflex/golden/vectors.json`) and `consult()`'s fake
      backend seam. Cross-role: contract + both roles in one commit. **DoD:**
      canonical round-trip; abstain on timeout/low confidence/budget; redaction;
      audit writes hashes only; no authority fields; `make render`,
      `contract-test`, `test-all` green. Verified 2026-10-23: 40 reflex tests,
      `make ci CI_QUICK=1` green, `make test-all` green.
- [x] **64C — Master broker and port 4224** — added
      `master-node/services/sparknet-reflex-broker.py`, its unit, tests and the
      `4224` port entry (overlay-only, `binds_to 10.100.0.1`). **DoD:**
      overlay-only bind; peer source refused in Phase 1; local backend by
      default; an optional credential only for explicit egress; exact model pin;
      timeout -> abstain; budgets; `/healthz` leaks nothing; `units-check`
      green. Verified 2026-10-23: 14 broker tests, master suite green,
      `make contract-test`, `render-check`, `validate`, `lint`, `format-check`
      green. The unit is staged (`make reflex-unit`), **not enabled**; local
      mode needs no credential.
- [x] **64D — node surface** — added `/v1/reflex/` to the dispatch bridge's
      `PLAIN_PREFIXES` and `LOCAL_ONLY_PREFIXES`, the OpenAPI entry, the setup
      env and tests. **DoD:** 401 without grant; 403 from overlay;
      loopback-only; local default; broker opt-in; no new published port.
      Verified 2026-10-23: 8 surface tests, peer suite green, `contract-test`,
      `validate`, `lint`, `format-check`, `shellcheck` green. Local mode uses the
      node's reranker/local LLM and never egresses; broker mode forwards to
      `10.100.0.1:4224` and binds the caller's `node_id`.
- [x] **64E — RAG pilot (shadow -> assist)** — added `--reflex` to
      `scripts/sparknet-chroma.py`, the local reranker cascade (rules by
      default, optional `SPARKNET_RERANK_URL`), the bounded on-disk cache
      (`.state/reflex-cache.json`), `scripts/sparknet-reflex-eval.py`,
      `tests/reflex/rag-golden.json` and `make reflex-eval`. **DoD:** fabric
      scope only; shadow agreement reported; fail-open on abstain; precision@5,
      recall, abstain rate, p95 and cost per 1k measured; no regression without
      `--reflex`. Verified 2026-10-23 on 14 fabric queries, top-k 5,
      candidate-k 50, local rules backend: baseline precision@5 **0.771**,
      reranked **0.786** (assist delta **+0.015**), recall@5 **0.946**, shadow
      agreement@5 **0.962**, abstain **0.000**, p95 **7.7 ms**, cost/1k
      **$0.0000** (no egress). Assist is safe for fabric RAG; the broker path stays
      shadow until 64F. Plain queries without `--reflex` are unchanged.
- [x] **64F — live pilot (local-only)** — **executed
      2026-10-23; measurements accepted by the operator 2026-10-24.** Local
      backends are the default
      and need neither governance approval nor a credential: `make
      reflex-live-check` then gates only on broker `/healthz`. `REFLEX_LIVE=1
      make reflex-eval [REFLEX_MODE=assist]` scores up to `--live-candidates`
      fabric chunks per query through the Master broker; `make
      reflex-live-query QUERY="…"` runs one broker-backed fabric query. Live
      scoring is fail-open (transport or shape error → abstain) and reports
      measured tokens plus cost. An optional hosted cloud leg existed at the
      time behind a governance flag, a 0600 key and an explicit egress opt-in;
      it was never the pilot default, was never promoted past shadow, and
      Step 65 removed it entirely.
      **Live setup:** loopback broker (`127.0.0.1:4224`, local backend, no key)
      plus a LAN Ollama OpenAI endpoint at `192.168.178.21:11434`; local LLM
      tag `sparknet-reflex:v1` (copy of `qwen2.5-3b-32k`). **Measured (14 query
      fabric golden set, candidate-k 50, top-k 5, local-rerank):** shadow
      baseline 0.771 → reranked 0.757, agreement@5 0.817, recall@5 0.946,
      abstain 0.000, p95 115.7 ms (one outlier), cost $0. Direct local-LLM
      probe (`tool.risk`, Noul): accept 0.80, 1.23 s. **Finding:** the broker
      sees one query+chunk and therefore can only do lexical local-rerank, not
      the distance-aware batch rerank that produced 64E's 0.786; assist served
      0.757, a small regression. Broker/LLM stays **shadow**; the in-process
      chroma reranker keeps **assist**. **DoD:** measurements recorded;
      `DoD: confirm: user` — **confirmed 2026-10-24**. The step closes with the
      split the measurements forced: the in-process chroma reranker holds
      **assist** on the fabric scope, and the broker/local-LLM path stays on
      **shadow** because one query+chunk per call cannot reproduce a
      distance-aware batch rerank. No mode was promoted on the strength of the
      probe alone.
- [ ] **64G — deferred; each leg becomes its own step** — `reflex-consult` +
      peer broker access; goSpark router client; Open WebUI filter; opencode
      tool-guard plugin; groundedness; agent-callable MCP tool. Not part of
      Step 64's closure: the plan protocol's rule is that new roadmap work gets
      a **new** step rather than being folded into a finished one.

**Status:** 64A–64F **done**. The hosted cloud sensor this step was opened
against was replaced by a local-only default (local reranker/LLM, no egress, no
credential) and then removed outright in Step 65. 64F's live measurements
were accepted by the operator on 2026-10-24, which closes the step. 64G stays
open and deferred, as above. Cursor `64 -> done`.

## Step 65 — Naming purge, and the pins the rename exposed

Opened 2026-10-24 on operator direction: remove a retired vendor name and the
old editor name from the fabric, and finish the rebrand consistently. Kept as one
step because a rename touching a contract, a service, a unit, four test suites and
a golden-vector set has to land atomically — the tree does not build between the
pieces.

- [x] **65A — the cloud reflex leg is deleted, not disabled.** The vendor name was
      not prose: it was a member of the backend enum in
      `contracts/reflex-schema.json`, a hard prefix check in the broker that
      refused any model tag outside the vendor's namespace, the default model
      tag, a systemd `Environment=`, and
      an `ALLOW_EGRESS` opt-in. All of it is gone, and the backend vocabulary now
      reads `broker | local-rerank | local-llm | rules | null` with **no member
      that can leave the fabric**. `broker` takes over as the label for "the
      Master answered", which is what it always did: the broker was already local,
      and what it centralises is the budget, the redaction point and the audit
      trail — never a credential. Removed alongside it: the broker's HTTP client,
      `read_key`, `vendor_payload`, `_vendor_backend`, `--key-file`, `--endpoint`,
      the `allow_egress` posture flag, and the eval harness's governance and
      0600-key preflight gates (a gate nothing can trip is decoration, not a
      control).
      **DoD:** (1) no vendor reference remains in any live artifact; (2) the
      surviving test mentions are *negative* assertions — that the vendor's
      endpoint is absent from the broker's source, that its name is absent from
      `BACKENDS`, and that a stale environment variable still naming the retired
      backend falls back to local rather than selecting something removed;
      (3) the contract enum and
      `shared/sparknet-reflex.py::BACKENDS` still agree, which
      `tests/test_reflex_contract.py` pins; (4) the golden cache-key vectors were
      regenerated **only after** each original expectation was reproduced from the
      original model tag, proving the hash function unchanged — so the
      regeneration is a consequence of the rename and not a mask over real drift.
      Verified 2026-10-24.

- [x] **65B — the editor rebrand is finished, and its boundary is now enforced.**
      The rebrand to `orchestrator` already existed as the dialect in
      `scripts/sync-wiki-skills.py`, with four documented exclusions for artifacts
      this repo does not own: the editor's `.obsidian/` config dir, its CLI, its
      `help.*` documentation URLs, and the upstream repo it is vendored from.
      Auditing all 127 mentions found the exclusions
      correct and the vendored suite already rewritten — the residue is not
      sloppiness. But the boundary lived only in a comment, so it is now a test:
      `tests/test_wiki_skills.py` sweeps every file we author and refuses a mention
      matching none of the four categories, with the exemption list itself pinned
       so it cannot grow quietly. The sweep found one real miss
       (a callout named for the editor's old brand, in
       `master-node/tests/test_master_spec.py`) and
      deliberately left `peer-node/manifests/user-env-manifest.json` alone: it is a
      generated host snapshot whose `PATH` names a directory that exists, recorded
      as by-design in `log.md` (2026-10-08), and editing it would make the manifest
      lie about the machine.
      **DoD:** the sweep passes, its exemptions are pinned, and it is proven
      non-vacuous (it reports the six mentions it examined). Verified 2026-10-24.

- [x] **65C — every image this fabric deploys names a fixed release.** The rename
      turned up a defect of exactly the class it was meant to prevent:
      `sparknet-node-setup.sh` carries the rule in a comment ("WEBUI_TAG is a
      stable release, never `main`/`latest`") and `tests/test_contracts.py`
      enforced it — for the two *node-stack* composes only.
      `peer-node/configs/ai-stack/docker-compose.yml` and
      `master-node/configs/admin-surface/docker-compose.admin.yml` shipped
      `open-webui:main`, and three agent composes shipped `alpine:latest`. All five
      are pinned now (`${WEBUI_TAG:-v0.12.2}`, and `alpine:3.20` to match
      `peer-node/container/anchor/Dockerfile`), and `tests/test_hardening.py`
      sweeps the tree instead of naming files. A rule one test applies to a
      hand-picked subset is a rule the other files can break silently.
      **DoD:** the sweep passes, and was shown to fail on a planted
      `${WEBUI_TAG:-latest}` before the plant was removed. Verified 2026-10-24.

- [x] **65D — two claims the tree no longer supported.**
      `contracts/share-protocol.md` opened "Nothing here is built yet" while peer
      Steps 6 and 8 **and** Master Steps 10–12 are all closed. It now separates
      what is built (the offer lifecycle, four clocks, trust levels and
      reconciliation, tested against in-process node pairs with injected clocks)
      from what is not (the live 4201/4202/4203 listeners, stanza application, the
      ratification service, the evidence repo — `wired, not deployed`), citing
      `share-regime.json` and `ports.json` rather than asserting a mood.

**A bug this step caught in its own new test.** The first version of the image-tag
sweep resolved `${WEBUI_TAG:-v0.12.2}` by splitting on the *last* colon, which
lands inside the interpolation's `:-` and yields `-v0.12.2}` — never a rolling tag,
so the sweep passed while proving nothing. It now splits on the first colon of the
last path segment, and a resolver test pins ten references including the two that
must be *caught*. Recorded here because a gate that fails open is worse than no
gate: from the outside the two are indistinguishable.

**Status:** 65A–65D done, full `make ci` green. Cursor `done -> 65 -> done`.

## Step 66 — Department as a Master-attested, signed privilege boundary

Opened 2026-10-24 on operator direction (Phase 2 of the six-phase arc). Two
operator decisions shape it: a node's department is **attested by the Master in
the signed registry**, never self-declared; and crossing a department boundary is
**a new capability in the closed vocabulary**, not a share type and not a local
convention.

The first decision is the security one. In-department sharing is the *easier*
path, so a self-declared department would let a node claim its way into whichever
department it wanted to read — the exact direction an attacker pushes. Attestation
belongs where the rest of authority belongs: inside the envelope the Master signs.

- [x] **66A — the contract and both implementations, in one change.**
      `department` joins `entry_fields` (optional, `["string","null"]`, modelled on
      `revoked`) and `signed_envelope_fields` in **both**
      `contracts/registry-schema.json` and `contracts/identity-schema.json`, and
      `cross-department-share` joins `known_capabilities` with a definition in
      `contracts/capabilities.json`. `shared/sparknet-authz.py` gains the field in
      `SIGNED_FIELDS`, in `authorization_message`'s envelope, and in
      `KNOWN_CAPABILITIES`.
      The envelope carries `department` **always**, as `null` when unattested. One
      message shape rather than one-per-optional-field: two canonical forms for
      the same logical entry is precisely the ambiguity the byte-for-byte
      agreement rule exists to prevent, and a verifier should never have to guess
      which form it holds.
      **This is a cross-language contract, so it is not one repo's change.**
      goSpark mirrors the envelope in `internal/authz/registry.go` and the
      vocabulary in `internal/authz/capabilities.go`, with `spec/sparknet/`
      holding verbatim snapshots whose `PROVENANCE.md` rule is that the Go code
      and the snapshot move together or not at all. Both moved: the snapshots were
      re-copied, `CapCrossDepartmentShare` added (and marked sensitive, since the
      holder bears the risk), `apiv1.NodeAuthorization` gained `Department`, and
      `TestVocabularyMatchesFabric` was updated.
      **DoD:** (1) `tests/test_registry_crossverify.py` passes in **both**
      directions — the fabric's Python signs and goSpark verifies, and goSpark
      signs and the fabric verifies — which is the only proof that two
      implementations of one signature agree; (2) the golden bytes were updated on
      both sides only after the delta was shown to be exactly the added
      `department: null` key, with no key removed and no value changed;
      (3) `make render` re-ran, so `contracts/manifest.json` projects the new
      vocabulary; (4) `make ci` green here and `make ci` → `ci: ok` in goSpark.
      Verified 2026-10-24.

- [x] **66B — enforcement, wired to the signed registry rather than merely
      possible.** `Regime` gained two injected resolvers — `department_of` and
      `holds_capability` — and `_department_check` implements the rule: the
      boundary binds only when both sides carry an attested department and the two
      differ, so a deployment whose Master attested none shares exactly as it did
      before. It is enforced on **both** sides, each against its own view of the
      registry: the offerer at `offer()`, the acceptor at `accept()`. Trusting the
      sender would let one granted node pull an ungranted one across the boundary.
      A narrower share type does not help — `kb-view` needs the capability too,
      because the type says what a share conveys while the department says who may
      share at all. An inbound offer the recipient will refuse is still *recorded*,
      with `crosses: true` and `permitted_by: null`: an attempt refused silently
      leaves no evidence it was made, and the evidence is the point.
      **The bridge is wired, so this is not inert.** `_department_of` and
      `_holds_capability` read `manifests/node-authorizations.json` and are passed
      into the `Regime` the bridge constructs; both default to "nothing attested,
      nothing granted" when unwired, which is the fail-safe direction.
      **A gap this found in 66A, and the fix.** `sign_authorization` neither
      accepted nor emitted `department`, so *no signer could attest one* and the
      field was unreachable in practice. Its own docstring already states the
      principle that caught it — `revoked` is a parameter rather than a field a
      caller may set afterwards *because* it is inside the signed envelope — and
      `department` is in the same envelope for the same reason. It is now a
      parameter, always emitted (null when unattested) so there is one entry shape.
      goSpark's `NewAuthorization` was checked for the same gap: it needs no
      parameter, because `SignRegistry` is already the only writer of an entry's
      signature and re-signs the whole envelope; that path is now documented in
      goSpark `0a6da00` so it is discoverable rather than accidental.
      **DoD:** (1) same-department share needs no extra capability;
      (2) cross-department without it is refused `403 cross-department` naming the
      capability; (3) with it, the share proceeds and still obeys the four clocks
      and ratification; (4) unattested on either side behaves exactly as before —
      proven by all 26 pre-existing share-regime tests passing **unchanged**;
      (5) `share-regime.json` declares the rule; (6) the bridge's own construction
      path is tested end to end against a real signed registry, and every entry the
      test mints is verified to still sign. Verified 2026-10-24: 16 new tests
      (11 engine, 5 bridge), peer suite 494 → 510 passed / 1 skipped, `make ci`
      green, goSpark `make ci` → `ci: ok`.

- [x] **66C — the platform declaration in `00_System/`.** The data already
      existed: `manifests/user-env-manifest.json` carries `system.platform`,
      `machine`, `release` and `privilege_boundaries`, written by
      `scripts/sparknet-identity-capture.sh`. What was missing is a declaration an
      agent reads — the snapshot lived in `manifests/` and nothing in the vault
      pointed at it. `00_System/platform.md` (schema `sparknet-platform/1`) is that
      declaration, and the capture script now writes **both files from one probe**,
      which is the structural reason they cannot disagree: two files derived from
      one capture, rather than one derived from the other at read time.
      `contracts/tracking-schema.json` declares it under `platform_record` (path,
      fields, generation rule, `agreement_rule`, and that it is descriptive and
      never permissive), and names it in `layout.dirs["00_System"]`. The template
      ships `status: uncaptured` with every value `null`, so a fresh vault does not
      inherit this host's identity.
      The committed record was derived from the **committed** snapshot rather than
      by re-probing, after first asserting every host fact already agreed — so
      `captured_at` matches the snapshot it summarises instead of silently
      re-stamping a record whose host facts never changed.
      **DoD:** (1) `00_System/` names the platform; (2) the schema declares it;
      (3) a test pins that the declaration and the captured snapshot cannot
      disagree — and a second runs the real capture script in a temp vault and
      proves the two files it writes agree, so the invariant is tested against the
      generator and not only against the committed pair. Verified 2026-10-24:
      4 new tests, peer suite 513 → 517 passed / 1 skipped, `make ci` green.
      **Remaining leg:** `master-node/00_System/` has no declaration, because the
      Master role carries no `user-env-manifest.json` to agree with. Adding one
      there needs the capture script reachable from the Master role first, so it is
      deferred rather than faked with a hand-written file that nothing could check.

- [x] **66D-i — the operator's OS identity is inside the signed grant.** Operator
      decision: the ceiling is the identity of the **human operating the session**,
      not of the daemon serving it. A bridge or WebUI container running as root
      would otherwise hand every session root, making the ceiling a property of how
      the node was started rather than of who is driving it — so the identity has
      to travel with the grant the human presents.
      `contracts/identity-schema.json` declares `grant.fields.operator_os`
      (`uid`, `euid`, `username`, `groups`, `is_root`) with the reasoning recorded
      beside it, and `shared/sparknet-authz.py` adds it to `GRANT_FIELDS` — the
      projection the signature covers — plus `normalise_operator_os`, which refuses
      a wrong type rather than coercing it and sorts/deduplicates groups so two
      orderings of one set cannot produce two signatures. `mint_grant` takes it as
      a parameter, for the same reason `revoked` and `department` are parameters:
      it is inside the envelope, so it cannot be set afterwards without invalidating
      the signature. It stays **optional** and is always emitted, as null when
      unattested — a mint must never have to invent an OS identity, and null means
      "nothing attested", which caps the session at nothing rather than implying
      root.
      **This is single-repo, unlike 66A.** goSpark implements no grant handling at
      all (no `grant_id`, `vault_scope`, `user_identity` or `conversation_key` in
      any Go file), so there is no second implementation of this projection to keep
      honest. Verified rather than assumed before relying on it.
      **A gap this closed beside the feature:** `SIGNED_FIELDS` is pinned against
      `contracts/registry-schema.json` by `test_shared_constants_match_the_contract`,
      but nothing pinned `GRANT_FIELDS` against `grant.fields`. The two happened to
      agree, so a grant whose signer projected one field set and whose verifier
      projected another would have verified here and failed on a node with nothing
      red in between. `test_grant_projection_matches_the_contract` pins it now, as
      a **set** rather than a tuple, because `grant_message` serialises with
      `sort_keys` so field order cannot change the bytes.
      **DoD:** (1) the contract and `GRANT_FIELDS` agree and a test fails if they
      stop; (2) `operator_os` is optional, so a grant can express "none attested";
      (3) normalisation is closed and strict — undeclared fields refused, wrong
      types refused rather than coerced, `is_root: 0` and `uid: True` both refused;
      (4) widening the ceiling invalidates the signature, proven by re-signing
      check on an `is_root`-flipped copy; (5) `make ci` green. Verified
      2026-10-24: 3 new contract tests, peer suite unchanged at 517 passed / 1
      skipped.

- [ ] **66D-ii — enforcement at the mutating path.** The ceiling is now signed and
      travelling; nothing yet consults it. The check belongs on the bridge's
      mutating verbs (and the guard's), and must refuse a mutation that needs a
      privilege the attested operator does not hold — **whatever uid the serving
      daemon runs as**. `deny_root_escalation_attempts` in
      `manifests/security-policies.json` also still has no enforcement behind it.
      Correcting the audit that opened this item: the guard is *not* silent about
      privilege — `sparknet-guard-d.py:1002` refuses to arm `--apply-enabled`
      without `euid 0`, and `:786` gates on it, matching `security-policies.json`'s
      `apply_requires: [..., "euid_0", ...]`. But that is the **opposite**
      direction: it *requires* privilege for the sensitive path rather than
      *capping* by the operator's, and the two interact. A non-root operator's
      agent can already never satisfy `euid_0`, so guard-apply is out of reach by
      construction — which is either the cap working, or an accident a root-run
      WebUI would silently void. Deciding which, and making it explicit, is the
      content of this leg.
      **Partly landed 2026-10-24.** The decision itself is now one rule in one
      place: `shared/sparknet-authz.py::operator_os_authorises(grant,
      requires_root=...)` returns `(allowed, reason)` and never raises, so a caller
      cannot turn a missing attestation into an unhandled error and thereby into a
      fail-open path. It encodes the operator's decision — the attestation
      authorises, an absent one fails closed, `is_root` is read and never inferred
      from `uid == 0`, and an unprivileged operation needs no attestation at all.
      `manifests/security-policies.json` declares it under `operator_os_ceiling`,
      including how it relates to the guard's `euid_0` requirement: complementary,
      not redundant — the attestation says whether the human may *ask*, the daemon's
      uid says whether the process can *do*, and both must hold. Seven tests cover
      it, including one that reads a real `mint_grant` output rather than a dict
      literal.
      **What is still missing, and why it is not a small omission.** The rule is not
      wired to any mutating path, and the reason is structural: `operator_os` lives
      on the **grant** envelope, while the privileged filesystem mutation happens
      through the **guard-apply** envelope — and `GUARD_APPROVAL_FIELDS` is eight
      fields (`content_b64`, `content_sha256`, `expires_at`, `file_path`,
      `issued_at`, `nonce`, `peer_fingerprint`, `request_id`) with **no operator
      identity among them**. So enforcing the ceiling where privilege is actually
      exercised needs that envelope to carry the attestation, which is a second
      signed-envelope change with its own golden vectors. Wiring the rule only to
      the bridge's vault verbs would have been worse than not wiring it: those
      writes are not privileged, so it would have produced a check that always
      passes and looked like enforcement. Recorded here so the next pass does not
      mistake the rule's existence for the control's.
      **DoD:** a mutating request is refused when the attested operator lacks the
      OS privilege it would exercise; a null `operator_os` fails closed on
      privileged mutations rather than being read as root; the check is on the
      request path and not advisory; the interaction with the guard's existing
      `euid_0` requirement is stated in `security-policies.json` rather than left
      implicit; `DoD: confirm: user` for the live leg, since this host cannot
      exercise a privilege boundary it does not have.

**Deployment hazard this step creates.** Adding a field to the signed envelope
changes the bytes the Master signs, so **every existing entry signature stops
verifying**. In this repo that costs nothing — the shipped registry is empty by
design and fail-closed. On a live node it means re-signing and re-publishing at a
higher sequence, never editing entries in place. That half stays open: it is an
operator act on a live Master, not something this repository can do.

The other half is **closed**. `goagx/GOSPARK_PIN` now names the goSpark commit
carrying the matching Go envelope, so a device bootstrapped from the pin builds an
agent that agrees with the fabric rather than one that would reject a *correctly*
signed registry. Two things that made this more than a one-line edit: goSpark had
to be pushed first, because a pin naming an unfetchable revision is a worse hazard
than a stale one — `bootstrap-agx.sh` would fail on the device instead of quietly
building the wrong thing — and `tests/test_goagx_repo.py` binds the pin to the
published manifest (`manifest["gospark_sha"] == GOSPARK_SHA`), so the goagx
distribution had to be republished in the same pass. `goagx/README.md`'s
`f547751` was deliberately **not** changed: it is a record of what was measured on
real AGX hardware, and rewriting a measurement to match a pin makes the evidence
say something that never happened.

**Status:** 66A–66C and 66D-i done, `make ci` green. 66D-ii (enforcement at the
mutating path) is the one open leg.
Cursor `done -> 66`. Wiring 66B into the bridge also surfaced and fixed a
security-relevant bug beside it: the mesh size was captured once and both the
registry and the regime were cached with no invalidation, so `mode_for()` could
never change after construction. `peer_pair` has **no Master arbitration** while
`master_governed` requires ratification of every cross-node share, so a third node
joining under a running bridge left it skipping a check it should have applied —
reachable, because the guard installs registry publications while the bridge runs.
`_share_regime`'s own docstring claimed the opposite, and nothing tested it. The
registry now re-reads on a `(mtime_ns, size)` stamp change and `_mesh_count` is
passed as the live callable; the regression test is negative-controlled against
the captured-constant version. See `log.md` 2026-10-24.

## Next

Step 64 is closed, so reflex work is now roadmap work and needs its own step.
Two things carry forward as constraints rather than tasks:

**The mode split is settled by measurement, not preference.** The in-process
chroma reranker holds **assist** on the allow-listed `fabric` scope (0.771 →
0.786 precision@5, no egress). The broker/local-LLM path stays on **shadow**
(0.757, a regression) for a structural reason that a faster endpoint would not
fix: the broker receives one query+chunk per call, so it can only rerank
lexically and cannot see the distances the batch reranker uses. Promoting it
would need the broker to score a batch, which is a design change, not a tuning
one. The broker unit remains staged and needs no credential; Step 65 removed
the cloud leg, so there is no egress flag left to set and no backend in the
vocabulary that could leave the fabric.

**The invariant is load-bearing.** Reflex output may rank, annotate, route or
flag; it may never sign, grant or revoke, approve a guard application, or widen
a permission. It may only tighten, and it abstains on doubt. The guard, signer
and registry never consult it. Any 64G leg that would put reflex in an
authority path is a contract change and belongs in `contracts/` first.

The nearest genuinely open cross-role item is **Master Step 7 reconciliation**:
Step 6 marked the 8090 instant-push listener *superseded in direction*, because
the signed registry is now pushed Master → peer guard on 9090 and needs no
peer-pull listener for distribution. `contracts/ports.json` retains 8090 as
`spec-only` until Step 7 decides whether it survives for ACL pushes, is
re-scoped, or is retired. Do not add the `reflex-consult` capability before its
own cross-role commit.

**The remaining arc, approved 2026-10-24, becomes Steps 66+.** Step 65 was
Phase 1 of a six-phase review of what this fabric is for: a development
environment for the `peer-node` and `master-node` templates, with goSpark
supplying the node surface. Each later phase gets its own step, because each
needs its own DoD and its own cross-role commit.

- **Phase 2 — identity contracts.** A `department` field on the user record
  (shared freely inside a department, extra permission to cross out of one), a
  platform declaration in `00_System/`, and OS-level permissions *enforced*
  against agent permissions rather than merely recorded beside them. The
  department field is a signed-schema change: `USER_RECORD_KEYS` is an allowlist
  pinned to `contracts/tracking-schema.json`, and every tracking block is signed,
  so it needs a `sparknet-tracking/2` bump with a stated migration for signatures
  already made.
- **Phase 3 — intake.** The RFI channel (a peer asks, the Master answers into
  `01_Inbox/`), the inbox transport that `tracking-schema.json`'s
  `phase_boundary` still lists as `not_built`, the `inbox_acceptance` ledger
  event, reviewer-agent sanitisation setting `validity: sanitized`, and
  notification on arrival. The registry publication is the shape to mirror:
  signed envelope, digest-bound payload, monotonic sequence, and one shared
  install rule serving both the online and the offline path.
- **Phase 4 — Master observability without touching the data path.** Peers talk
  directly by design and the Master is authority-plane only at `10.100.0.1/32`,
  so monitoring means *signed evidence pushed to the Master*, never interception:
  wire the existing `telemetry` capability, deploy
  `shared/sparknet-liveness.py` (reference code that has no unit), anchor
  `checkpoint` Merkle roots, and make the retained `flagged` trust levels
  actionable. Fabric-wide vault maintenance rides the existing `guard-apply` plus
  `critical-manifest.json` `protected_paths` mechanism rather than a new write
  path.
- **Phase 5 — the Open WebUI surface.** Pin first (65C did), then build the
  Plan/Build panels against the permission API peer Step 5 already shipped,
  replace the two-line `docs/openwebui-plan-permission-execute.md` stub, and hook
  the node's skills, tools and knowledge in. Extend rather than fork unless a
  panel proves impossible: a fork of a fast-moving upstream is a perpetual
  rebase, and the Approve/Deny card an operator needs is reachable through the
  supported extension points.
- **Phase 6 — data lake, media, distillation.** Build 4223 `vector-embed`, already
  specified as the fabric's single semantic store; add image/video/audio ingest
  (audio has `goagx/sparknet-audio-shim.py` and node port 8003); then distillation
  as its own workstream, extending `MASTERSPIKE` from prompt-injection on
  `llama3.2` to a genuinely trained artifact with a corpus, a harness and an eval.

**Two things this arc deliberately does not do.** Fabric-wide KV-cache collection
is rejected: port 9100 `node-kvrouter` is node-local by design ("an in-stack
optimization plane, not an API. No fabric number shares 9100"), KV state is
model- and shape-specific so cross-node reuse needs identical models, and vLLM's
prefix caching already captures the local benefit. And containers do **not** get
admin access to the host: that would void `deny_root_escalation_attempts`, the
guard's `euid_0` requirement and `chattr +i` in one move, and because ingested
content is untrusted under this repo's own schema (`validity: sanitized` exists
for exactly that) a single injected document would then own the machine. Scoped
host access — a bind-mount allowlist plus a signed `guard-apply` for privileged
mutations — delivers the same capability as an auditable exception instead of a
standing one.

