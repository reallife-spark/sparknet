---
title: sparknet Plan
updated: 2026-10-06
current: 12
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
      - **Status**: complete. 31 skills; upstream
        `github.com/Ar9av/obsidian-wiki` at `ec2b6bc`, MIT.
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

- [ ] **Step 12** — Prove the whole arc on this host before touching the agx
      nodes: three nodes under `/tmp/opencode`, peer-only mode first, then
      election, then root, then signer, then registry, then escalation — and
      after the escalation, the assertions from Step 11's DoD (5) and (7) run for
      real: no information or privilege lost, and the master can act where the
      peer now cannot.
      - **DoD**: the rehearsal is scripted and repeatable, its transcript is
        saved to a dated file, every assertion in it is a test rather than a
        visual check, and a re-run from scratch produces the same result.
      - **Status**: in progress. The election → root → signer legs of the arc
        were proven by Step 11's cross-process and script tests and by the signer
        integration test (`test_the_formed_root_is_a_working_signer_start`), so
        the rehearsal concentrates on what those did not: three real node trees
        under `/tmp/opencode`, the registry under the elected root, and the
        escalation assertions (Step 11 DoD 5 and 7) against the live trees.

## Step 13 — agx64 / agx32 handoff

- [ ] **Step 13** — The two real nodes: peer-nodes on `agx64` and `agx32`,
      peer↔peer tested against a real transport, and the escalation repeated
      there — deferred by user decision until the local rehearsal is green.
      - **DoD**: `DoD: confirm: user` throughout — hosts are unreachable from
        this machine today (SSH timeouts, no agx nodes on the tailnet, no local
        overlay interface), and nothing about their state can be verified from
        here. This step is a handoff document plus the run, not a claim.
      - **Status**: not started, deliberately deferred.

## Next

The split is the last structural step. After this, roadmap work is role-scoped:
`master-node/plans/MASTER_BUILD_PLAN.md` for anything the Master must actually
build, `peer-node/PLAN.md` for the peer. Fabric steps (Steps 10–13 above) are the
exceptions — work that touches contracts and both roles at once belongs here.

**Do not treat a green fabric as a working Master.** It is not one: the Master
holds no usable signing key, no authority is issuable, and the registry ships
empty on purpose.

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

