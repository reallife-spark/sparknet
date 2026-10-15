---
title: sparknet Plan
updated: 2026-10-15
current: done
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

## Next

