---
title: sparknet Plan
updated: 2026-10-04
current: 4
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

- [ ] **Step 4** — The split only exists once it is committed and reachable.
      - **DoD**: (1) every new and moved file is staged, with no `.env`, key,
        `__pycache__` or `dist/` artifact included; (2) `make test-all` green
        immediately before the commit; (3) `make lint` green; (4) pushed to the
        private remote with a message that explains the split; (5) the
        pre-split history is still reachable from the pre-split tip.
      - **Status**: 4 of 5 DoD items met. Items 1–3 and 5 verified: nothing
        secret is staged, `make test-all` and `make lint` were green immediately
        before the commit, the work is committed on `main` and the pre-split
        tip `ad1cc396f3ee23685816418a50d7e8fcbf75cd60` is still an ancestor.
        Item 4 — the push — is **blocked on credentials**: there is no credential
        helper, no credential store and no token in the environment, so git
        cannot authenticate non-interactively. The earlier push of `ad1cc39`
        succeeded from a session that had one, and it is not present now.
      - **DoD: confirm: user** — the push needs a credential from you. It was
        deliberately not sourced from shell history or any other leftover, since
        the token that leaked in this session has to be revoked rather than
        reused.

## Next

The split is the last structural step. After this, roadmap work is role-scoped:
`master-node/plans/MASTER_BUILD_PLAN.md` for anything the Master must actually
build, `peer-node/PLAN.md` for the peer.

**Do not treat a green fabric as a working Master.** It is not one: the Master
holds no usable signing key, no authority is issuable, and the registry ships
empty on purpose.