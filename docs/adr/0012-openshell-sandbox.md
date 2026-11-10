# 0012 — OpenShell as the peer execution sandbox

## Status

Proposed. The peer does not run it; deployment status, platform blockers and
evidence live in `peer-node/PLAN.md` Steps 20–21. This ADR records the design
decision only.

## Context

The peer already runs one OpenCode execution sandbox per user through
`peer-node/services/sparknet-opencode-engine.py`: one `<vault>:/work` bind, a
per-user internal Docker network whose only reachable peer is the host model
proxy, a read-only rootfs, `--cap-drop ALL`, `no-new-privileges`, and pids,
memory and CPU limits. It runs the workload as a synthetic `10001:10001` and
recursively chowns the user vault to that identity.

That backend is hand-rolled. NVIDIA OpenShell supplies the same shape with a
policy engine, an OpenShell supervisor that mediates egress, Landlock filesystem
rules, seccomp, and signed policy updates. The open question was which identity the
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
  checks the sandbox's resolved `WorkloadIdentity` before accepting it. The
  workload identity is the node owner; it is not a WebUI user identity.
- **Sandbox backend and OpenShell driver are peer-local.** The engine selects
  the sandbox backend, `docker` or `openshell`. The gateway selects the
  OpenShell driver, `docker-rootful` or `vm`, from its local configuration. A
  signed sandbox request chooses neither. Rootless Podman is excluded until it
  can pin a host-UID mapping.
- **Mounts: one read-write vault mount, plus one read-only config mount on the
  VM driver.** The vault mount binds the user's `peer-<id>` vault at `/work`.
  The config mount is the generated OpenCode configuration at
  `/sandbox/.sparknet`; it carries no user knowledge. The runtime image's
  `WORKDIR` is `/sandbox`. No `$HOME`, `.state`, key material, sibling vault,
  role vault or Docker socket is mounted.
- **Isolation between users is mount-scoped, not UID-scoped.** All WebUI users
  share the node owner's Unix account; each execution sandbox sees only its own
  user vault.
- **Policy authority is split.** A workload-generated policy proposal needs the
  local approver's approval; for a session sandbox that is the sandbox user. The
  Master cannot approve it on the user's behalf. A Master-signed `policy-update`
  is authority, not a proposal: the peer executes it within its local execution
  whitelist. The two paths are independent. ADR-0013 records the boundary and
  the recreation rule.
- **Master supervision is a reserved signed surface.** `sandbox-supervise`
  (holder: master, sensitive) and the `/sandbox/*` route name are contracted.
  The bridge route and executor are not implemented; the capability is inert
  until that work and a signed registry grant exist. The peer keeps the gateway
  credential; the Master never receives a token or a host socket.
- **The execution sandbox is not knowledge.** A sandbox request, policy or
  approval is authority, never an answer corpus. The mounted user vault remains
  knowledge under its own scope; the sandbox itself is an execution surface,
  not a knowledge channel. `contracts/knowledge-flow.md` records the row.

## Consequences

- Files written in `/work` are owned by the host user, not a synthetic sandbox
  UID. The engine's one-time re-own from `10001:10001` is symlink-safe,
  idempotent and fail-closed: a partial migration is not recorded as complete.
- The sandbox does not inherit `docker`, `sudo` or other supplementary groups.
  A mount that needs another group needs an ACL for the owner UID/GID.
- Bind-mounted paths are not Landlock-enforced. The mount list is the security
  boundary and must stay as narrow as the user vault; `hard_requirement`
  protects only container-internal paths.
- The workload has no network interface. The model proxy must be reachable as
  `host.openshell.internal:<port>` under an explicit network policy. The policy
  must name the actual model-proxy port, not the guest's OpenCode port.
- The gateway is a user service with linger, not a root unit. The engine uses
  `openshell forward service` for the guest's OpenCode port because the
  service-URL default strips Basic auth. Bind sources must live outside the
  gateway unit's `PrivateTmp` namespace.
- A policy change to filesystem, Landlock or process settings cannot be applied
  live. The peer refuses it with `policy-refused`; recreation is a separate
  stop/delete/create sequence, not a `recreate` action. Deleting a sandbox
  record never deletes the vault mount. ADR-0013 records this.
- A service sandbox's mount and approver are not defined by this decision. Its
  contract belongs to peer PLAN 20F and must not be inferred from a session
  sandbox.
- The Docker driver and the VM driver have different host prerequisites. A host
  that meets neither keeps the existing Docker backend; moving the execution
  sandbox is a new host-placement decision.
- OpenShell and its images are pinned in `peer-node/manifests/openshell.json`.
  A version bump is a new decision with a fresh review of the identity and
  bind-mount behaviour.
- The `/sandbox/*` route is spec-only until 20E. No contract or README may
  claim it is reachable before then.
