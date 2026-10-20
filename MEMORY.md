# sparknet — Session Memory

> Standing state only. Read at session start; **replace, never append**.
> The plan and its cursor live in `PLAN.md` — this file mirrors it, it does not
> own it. **All history lives in `log.md` and `sessions/YYYY-MM-DD.md`** — an
> entry here is a durable fact you still need, never a record of what happened.

Updated: 2026-10-20

## Plan cursors

- **root `PLAN.md` `current: done`.** Step 57 (clean-slate peer pair on both
  AGXes + manual 2/2 Master escalation over the direct sparknet cable) delivered
  **2026-10-19**, Phases 0–11 executed and verified; live legs stay
  `DoD: confirm: user` (physical cable move done; human review of the ceremony
  transcript). It **supersedes Step 55's deployment** (archived
  `ARCHIVE-2026-10-19-escalation`). Step 58 (userspace-aware overlay anchors for
  both roles — **closes Step 57's parked reboot-survival leg**) delivered
  **2026-10-19**: both hosts restore `wg1` at boot via enabled anchor units, proven
  by a cold-path restart + cross-ping (a literal reboot stays `confirm: user`).
  **Both hosts were then rebooted for real (2026-10-19)** — overlay, firewall,
  guard, master units and the admin surface all returned unattended. Step 59
  (deployment/contract consistency remediation A–E) delivered **2026-10-19**:
  peer authorization live (repo stays fail-closed), firewalls on both roles,
  ledger genesis + signature-issued blocks, protected paths → `wg1`. Step 60
  (robustness / fail-safe hardening A–F) delivered **2026-10-20**: one strict
  base64 decoder, guard fail-closed on a chattr-less FS, firewall self-verify,
  anchor re-pin-on-failure + required interface. Step 61 (fabric-root design
  `CLUSTER_JOB_REALIZATION_DESIGN.md`) delivered **2026-10-20**: records four
  cited defects — divergent
  envelope encodings with nothing pinning `cluster_job_message`; peer↔peer
  fan-out blocked by a peer's single `AllowedIPs` (Master dispatches at
  n≥3, cross-peer fan-out deferred); the `fabric` index is a deny-list where the
  charter mandates an allow-list; the parent note's `chromadb:8000` prose is
  stale vs the committed `127.0.0.1:18000`/`~/infra`. It puts the Master vector
  DB (**port 4223**) in scope: Milvus/Qdrant, HA sharding+replication+etcd and
  pgvector all rejected for v1 (corpus ≈2,300 chunks; no k8s/object-store/
  postgres in tree), **Qdrant designated the upgrade path**, and the index
  treated as derived state — single writer, rebuild-from-source instead of
  replication, collection-stamp 503-on-mismatch. Eight hand-forwarded
  increments, order = dependency chain; the 4223 build step belongs in
  `MASTER_ADMIN_PLAN.md`. Design only — `4223` still `spec-only`. Cursor
  `done`. Step 60's `make ci` had passed with **shellcheck silently skipped**
  (binary absent from PATH); re-running it with v0.11.0 surfaced two info
  findings Step 60 introduced (`return $rc` unquoted; SC2329 on the
  trap-invoked `repin_on_exit`) — fixed here, and now gated for real. Step 56 (`goagx/`) is delivered+reviewed;
  its hardware legs are `DoD: confirm: user` (below). New roadmap work gets a
  **new** step. Steps 1–54 closed/parked.
  Steps 45–52
  (2026-10-17) adopted NVIDIA/dsx standard practice across sparknet **and**
  goSpark (**Scope guard: no license change, zero code copied.** Provenance
  is `references/nvidia-dsx-standard-practice.md`, 14 repos pinned by SHA,
  clones at `/mnt/nvme/github`). Step 53 (2026-10-18) refreshed both roles'
  `00_System` base sets (stale pre-election claims) and built
  `deployment/vault-template/`; the master identity chain is now
  `sparknet-node-0002` end-to-end — a deliberate divergence from the live
  trust root's `agx64`, recorded not accidental. Step 54 = h58 WiFi uplink
  (in progress). New roadmap work gets a **new** step.
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
- **The node image surface is a platform pair.** `spark.docker` /
  `spark.compose.yml` (DGX Spark, r36) and `goagx/` (Xavier, r35 py3.8),
  selected by `sparknet-node-setup.sh --platform spark|agx`; goSpark enters the
  AGX build as a named BuildKit context, vLLM v0.2.7 compiles from source on
  the device. The AGX `Dockerfile` keeps every `ARG` a stage uses declared
  in-stage (BuildKit predefined values like `TARGETARCH` do **not** inherit
  from a global `ARG` — pinned by `test_agx_node.py` stage-scope check).
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

- **Branch protection requiring the `gate` check** — unavailable on this plan
  (needs Pro or a public repo), so no check is enforced as required today;
  revisit if visibility or plan changes. **Live GitHub CI itself is proven**
  (see gotchas).
- Hardware/LLM legs of the adoption arc: a real GPU/driver host, a live BMC
  (Redfish inventory), a live eval endpoint (`EVAL_BASE_URL`), the Open WebUI
  handshake.
- **Step 56 AGX legs**: the source build (vLLM/xformers hours) completing on
  the Xavier, real tok/s inside 16 GB, NVML/tegra sidecar telemetry on Jetson,
  whisper `detect_language` through the audio shim.
- Full power-cycle reboot of a cluster2 node (peer Step 10 leg).
- Phase 9's destructive legs (rollback / replace-Master re-formation) are
  documented in `contracts/deployment-runbook.md` and deliberately unexecuted.

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
