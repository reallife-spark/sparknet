# 0012 — OpenShell as the peer execution sandbox

## Status

Proposed. Not deployed on the current peer. The status, platform blockers and
evidence live in `peer-node/PLAN.md` Steps 20–21 and `log.md`; this ADR records
only the design decision.

## Context

The peer already runs one OpenCode container per user through
`peer-node/services/sparknet-opencode-engine.py`: one `<vault>:/work` bind,
a per-user internal Docker network whose only reachable peer is the host model
proxy, a read-only rootfs, `--cap-drop ALL`, `no-new-privileges`, and pids,
memory and CPU limits. It runs the workload as a synthetic `10001:10001` and
recursively chowns the user vault to that identity.

That supervisor is hand-rolled. NVIDIA OpenShell supplies the same shape with a
policy engine, a supervisor that mediates egress, Landlock filesystem rules,
seccomp, and signed policy updates. The open question was which identity the
sandbox runs as, because the answer decides file ownership on the mounted vault
and whether the sandbox can write what the user can write.

OpenShell v0.1.7 facts that bound the decision:

- `process.run_as_user` / `run_as_group` accept `sandbox` or a numeric UID/GID
  from 1 through 4294967294; UID 0 is refused.
- Docker and Podman take the identity from the creation policy. Docker rootful
  maps container UID N to host UID N; rootless Podman maps through an unpinned
  subuid range and does not idmap its bind mounts.
- Numeric selectors skip `initgroups`; the workload receives only the primary
  GID. The VM driver exposes a symbolic `sandbox` account reconciled to the
  configured `sandbox_uid`/`sandbox_gid`.
- Bind mounts bypass workspace isolation and `filesystem_policy`; the mount's
  own read-only flag is the boundary.
- The image `WORKDIR` is the workspace root and cannot be replaced by a mount;
  the VM workspace is `/sandbox`.
- The Docker driver requires Docker 28+ and Landlock ABI 3; the microVM driver
  requires KVM and a libkrun-compatible glibc.

## Decision

- **Identity: the node owner's real numeric UID/GID.** Docker uses the numeric
  selectors; the VM reconciles its `sandbox` account to the same owner. The
  engine resolves the owner, refuses 0, reads the renderer's `owner.json`, and
  checks the sandbox's resolved `WorkloadIdentity` before accepting it.
- **Driver: implementation-defined, contract-neutral.** A peer may use Docker
  rootful or the microVM driver when the host meets that driver's prerequisites.
  Rootless Podman is excluded until it can pin a host-UID mapping. The signed
  sandbox request does not choose the driver; the peer's local policy does.
- **Mounts: one read-write vault bind.** A VM sandbox also has one read-only
  mount for its generated OpenCode config directory. The runtime image's
  `WORKDIR` is `/sandbox`; the vault is mounted at `/work`. No `$HOME`, `.state`,
  key material, sibling vault, role vault or Docker socket is mounted.
- **Isolation between users is mount-scoped, not UID-scoped.** All WebUI users
  share the node owner's Unix account; each sandbox sees only its own vault.
- **Approvals stay local.** OpenShell proposal auto-approval is off. A policy
  proposal is surfaced to the user; the Master cannot approve on the user's
  behalf. Filesystem, Landlock and process changes require recreation.
- **Master supervision is a reserved signed surface.** `sandbox-supervise`
  (holder: master, sensitive) and the `/sandbox/*` route name are contracted.
  The bridge route and executor are not implemented; the capability is inert
  until that work and a signed registry grant exist. The peer keeps the gateway
  credential; the Master never receives a token or a host socket.
- **The sandbox is not knowledge.** A sandbox request, policy or approval is
  authority, never an answer corpus; `contracts/knowledge-flow.md` records the
  row.

## Consequences

- Files written in `/work` are owned by the host user, not a synthetic sandbox
  UID. The engine's one-time re-own from `10001:10001` is symlink-safe,
  idempotent and fail-closed: a partial migration is not recorded as complete.
- The sandbox does not inherit `docker`, `sudo` or other supplementary groups.
  A mount that needs another group needs an ACL for the owner UID/GID.
- Bind-mounted paths are not Landlock-enforced. The mount list is the security
  boundary and must stay as narrow as the vault; `hard_requirement` protects
  only container-internal paths.
- The workload has no network interface. The model proxy must be reachable as
  `host.openshell.internal:<port>` under an explicit network policy. The
  policy must name the actual model-proxy port, not the guest's OpenCode port.
- The gateway is a user service with linger, not a root unit. The engine uses
  `openshell forward service` for the guest's OpenCode port because the
  service-URL default strips Basic auth. Bind sources must live outside the
  gateway unit's `PrivateTmp` namespace.
- The Docker driver and the VM driver have different host prerequisites. A
  host that meets neither keeps the existing Docker supervisor; moving the
  execution sandbox is a new host-placement decision.
- OpenShell and its images are pinned in `peer-node/manifests/openshell.json`.
  A version bump is a new decision with a fresh review of the identity and
  bind-mount behaviour.
- The `/sandbox/*` route is spec-only until 20E. No contract or README may
  claim it is reachable before then.
