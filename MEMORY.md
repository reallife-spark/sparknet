# sparknet — Session Memory

> Standing state only. Read at session start; **replace, never append**.
> The plan and its cursor live in `PLAN.md` — this file mirrors it, it does not
> own it. **All history lives in `log.md` and `sessions/YYYY-MM-DD.md`** — an
> entry here is a durable fact you still need, never a record of what happened.

Updated: 2026-10-17

## Plan cursors

- **root `PLAN.md` `current: done`.** Steps 1–52 closed. The last arc (45–52,
  2026-10-17) adopted NVIDIA/dsx standard practice across sparknet **and**
  goSpark: conventions, governance surface, CI mirror, and functional adoption.
  **Scope guard: no license change, zero code copied.** Provenance is
  `references/nvidia-dsx-standard-practice.md` (pins all **14** repos by SHA;
  clones at `/mnt/nvme/github`). The functional legs and their follow-ups are
  recorded there and in the four `references/nvidia-*.md` design docs. New
  roadmap work gets a **new** step.
- **`peer-node/PLAN.md` `current: done`** — the peer arc is terminal; its last
  work (Steps 2–12: container, grants, bridge, Open WebUI surface, conversation
  passing, `MASTERSPIKE`, sharing regime, node admin agent) closed 2026-10-11/12.
  New peer work gets a **new** step.
- **`master-node/plans/MASTER_BUILD_PLAN.md` `current: 2`** — Phase 0 (13–18),
  honest verification (19), keypair/registry substrate (1), and Steps 3–4
  complete; Steps 2 and 5–12 unbuilt. Step 2's DoD is *contradicted*, not merely
  unimplemented (two registry shapes, neither matching the shipped schema).

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
- **Vaults: three, not one.** Fabric root plus `peer-node/` and `master-node/`,
  each with its own `.env`, category skeleton and `AGENTS.md`. Resolve which one
  you are in before writing. Both role vaults store content in `00_System`–
  `07_Archives`; legacy names are symlinks (`make shims-check`).
- **`$SPARKNET_STATE_DIR` resolves outside the vault** (`$XDG_STATE_HOME/
  sparknet/<role>`, else `~/.local/state/...`) for the master; the peer keeps
  `<vault>/.state` on purpose (nothing mounts that vault). `keys-check` fails if
  it is pointed back inside.

## Live fabric (agx64 / agx32)

- **`agx64` = master = `192.168.178.131`** (overlay `wg1 10.100.0.1/32`);
  **`agx32` = peer = `192.168.178.133`** (`10.100.0.2/32`). Flat
  `192.168.178.0/24` LAN; the pre-move `192.168.178.131`/`192.168.20.32` legs
  are retired. `~/.ssh/config` points the aliases at the current IPs.
- **Election/signer arc proven live 2026-10-07**: 2/2 root, signer as
  `sparknet-master-signer.service` on agx64 (socket 0600, root-id
  `65d9ce25…`, caps `["sign"]`, single key-holder, survives reboot), signed
  registry, revoke→peer-inert→re-authorize cycle. The signer is the **only**
  process holding `operational.ed25519`.
- **Admin federation (Step 29) completed 2026-10-12**: design + Phases 0–4 as
  code + Phase 5 run live on the pair (procedure in
  `contracts/admin-federation-runbook.md`). `admin-supervise` held by master.
- **Ops caveats that cost time before**: `wg0`/`wg1` do **not** survive reboot on
  the tegra host (`CONFIG_WIREGUARD=n`, userspace `wireguard-go`) — restore via
  `/root/scripts/sparknet-wg-restore.sh`. Both clusters use `10.100.0.0/24`, so
  `wg0` (live) and `wg1` (cluster2 proof) must **not** run concurrently.
- **Master admin page**: declared, **not bound** (nothing listens on
  `10.100.0.1:8080`) — `DoD: confirm: user`. Ports `4220`–`4223` are spec-only.

## Security / secrets

- **The pasted `nvapi-…` build.nvidia.com key is treated as compromised —
  rotate it.** Its only home is `.state/secrets/build-nvidia.env` (0600, dir
  0700, gitignored); it is referenced by **path only**, never in a tracked file,
  and never printed (`make nv-search` refuses `ngc` without one). No
  `.env.example` knob for it (three-template key-set test).
- **Outstanding, unclaimed**: rotating/revoking the old broad OAuth token from
  the split-day leak.
- Never commit tokens/keys/`.env`; `make keys-check` is the gate.

## Open items (`DoD: confirm: user`)

- Live GitHub CI (workflows are shaped + SHA-pinned; only GitHub proves a run)
  and branch protection requiring the `gate` check.
- Hardware/LLM legs of the adoption arc: a real GPU/driver host, a live BMC
  (Redfish inventory), a live eval endpoint (`EVAL_BASE_URL`), the Open WebUI
  handshake.
- Full power-cycle reboot of a cluster2 node (peer Step 10 leg).
- Phase 9's destructive legs (rollback / replace-Master re-formation) are
  documented in `contracts/deployment-runbook.md` and deliberately unexecuted.

## Command / environment gotchas

- **Local gates are authoritative**; the SHA-pinned GitHub Actions run the same
  `scripts/pre-merge-gate.sh` as a mirror. `make ci` (add `CI_QUICK=1` for the
  quick pass); `make test-all` for every suite. Bare `pytest` runs only `tests/`.
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

## Local vs live

Everything `make test-all` / `lint` / `bundle-verify` checks is verifiable on
this host. Claims about the live pair were verified from those hosts per the
runbook; anything needing a second node or the Master carries
`DoD: confirm: user`, never a local pass. This host has no GPU and does not run
the overlay.
