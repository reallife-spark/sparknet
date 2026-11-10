# sparknet glossary

The vocabulary of the two-role fabric. Entries name concepts; `contracts/` owns
rules and `docs/adr/` owns decisions. An unqualified term is safe only when the
layer or collision does not matter.

## Language

### Roles and authority

**fabric**:
The two-role system in this repository: the contract, the shared
implementation, a peer role and a Master role.

_Avoid_: platform, mesh

**peer**:
The user's local node. It runs chat, agentic work, a private vault and
self-healing. It holds an identity key, not the operational key.

_Avoid_: client, worker

**Master**:
The elected signing role. It holds the operational key and supplies authority
and scoped fabric knowledge.

_Avoid_: controller, admin node

**authority**:
The right to make a privileged decision. In the fabric it comes only from
possession of the operational key; a capability, a registry entry, a role name
or a prompt cannot create it.

_Avoid_: permission, privilege, control

**identity key**:
The peer's Ed25519 key. It proves the peer's identity and signs its requests;
it cannot grant, revoke or escalate.

_Avoid_: node key, signing key

**operational key**:
The Master's Ed25519 key. It signs registry entries, approvals and scoped
answers; it never leaves the Master.

_Avoid_: master key, root key

**capability**:
A named permission in the closed fabric vocabulary. It is inert until the
Master grants it to a node.

_Avoid_: permission, role

**capability grant**:
The Master's signed inclusion of a capability in one node's registry entry.
The entry's node carries the grant; the holder is the role that may exercise
it.

_Avoid_: capability (as a verb), permission

**capability holder**:
The role that may exercise a capability. A supervision capability is
master-held: the Master issues, the peer executes.

_Avoid_: grantee, owner

**supervision capability**:
A master-held capability whose signed request makes a peer act against its own
service. `admin-supervise`, `sandbox-supervise` and `memory-supervise` are the
supervision capabilities; the peer carries the grant.

_Avoid_: admin capability, control capability

**registry**:
The Master-signed list of node identities, capabilities and revocations.

_Avoid_: directory, roster

**guard**:
The peer service that verifies Master-signed requests before a protected file
is changed.

_Avoid_: firewall, sentinel

**guard approval**:
A Master-signed authorization to change one protected file on one peer. It is
not a policy approval.

_Avoid_: approval (unqualified), patch

**signed surface**:
An endpoint that accepts only signed authority requests. It is not a console
surface and not a knowledge channel.

_Avoid_: surface (unqualified), API

**inert capability**:
A capability that is contracted but cannot act because its route, executor or
signed grant is absent. It is not a disabled permission a user can turn on.

_Avoid_: unused capability, disabled capability

### Knowledge and work

**vault**:
A role's or user's knowledge tree. Knowledge lives here; secrets live in a
state directory.

_Avoid_: store, knowledge base

**user vault**:
The `peer-<id>` vault belonging to one sandbox user. It is the only vault a
session sandbox may mount.

_Avoid_: vault (unqualified), user KB

**role vault**:
The peer role's own vault. No execution sandbox may mount it.

_Avoid_: vault (unqualified)

**knowledge**:
Content a peer's AI may answer from within its scope: its vault, the user's
vault or KB, an accepted RFI answer, an accepted share, or the build-time
context pack. Authority artifacts are never knowledge.

_Avoid_: data, information, context

**scope**:
An allow-list that bounds what a request may read or receive. A scope narrows
on receipt and never widens.

_Avoid_: permission, range

**protected file**:
A file whose change requires a Master-signed guard approval. It is not
knowledge.

_Avoid_: system file, immutable file

**RFI**:
A request for information: a peer asks the Master a scoped question, and the
signed answer is installed in the peer's inbox and accepted before it is
knowledge.

_Avoid_: query, ticket

**issue**:
An operational work item tracked outside the vault. It is not knowledge and
not authority.

_Avoid_: ticket, bug

**issue module**:
The shared model that owns issue parsing, redaction, validation, state
transitions and the read projection. It is not authority and never signs a
report.

_Avoid_: issue service, tracker

**issue projection**:
The canonical read view of recorded issues and their triage state. It carries
no authority and is not a knowledge corpus.

_Avoid_: issue view, dashboard

**triage ledger**:
The append-only record of issue triage transitions; the latest triage view is
derived from it.

_Avoid_: triage log, history

### Execution sandbox

**sandbox**:
The umbrella term for the peer's execution environment. Qualify it as
`execution sandbox`, `sandbox record`, `sandbox backend` or `OpenShell driver`
when the layer matters.

_Avoid_: container, workspace, runtime

**execution sandbox**:
The per-user, vault-scoped environment in which the peer runs agentic work. It
is an execution surface, not a knowledge channel.

_Avoid_: container, workspace, runtime

**sandbox backend**:
The peer engine's choice of who supervises the execution sandbox: the legacy
Docker backend (`docker`) or OpenShell (`openshell`). It is not the OpenShell
driver.

_Avoid_: driver, runtime, engine

**OpenShell driver**:
The mechanism OpenShell uses to realise a sandbox: rootful Docker or a
microVM. Rootless Podman is excluded. The gateway selects it from local
configuration; a sandbox request never does.

_Avoid_: backend, runtime

**sandbox record**:
The gateway's object for one sandbox: its name, phase, stored policy, mounts
and resolved workload identity. It is not the sandbox's contents or its vault.

_Avoid_: sandbox (unqualified), container

**sandbox image**:
The image a sandbox record is created from. The peer refuses an image outside
its local execution whitelist.

_Avoid_: container image, runtime

**sandbox gateway**:
The loopback OpenShell service that owns sandbox records and is the only peer
process that talks to the container or VM runtime. It is not the model proxy
and not the Master.

_Avoid_: gateway (unqualified), supervisor

**gateway credential**:
The peer-local mTLS bundle and token the engine uses to reach its sandbox
gateway. It never leaves the peer or enters a sandbox.

_Avoid_: gateway token, API key

**sandbox workload**:
The process an execution sandbox runs. In an OpenShell sandbox it has no
network interface; its egress is the sandbox policy's network rules.

_Avoid_: agent, container, app

**workload identity**:
The Unix UID/GID a sandbox workload runs as, reconciled to the node owner. It
is not the sandbox user's WebUI identity.

_Avoid_: sandbox user, owner (unqualified)

**node owner**:
The Unix account that owns the peer node and every `peer-<id>` vault on it. All
sandbox users share it; isolation between them is mount-scoped, not
UID-scoped.

_Avoid_: owner (unqualified), admin

**sandbox user**:
The WebUI principal whose `peer-<id>` vault is mounted into a session sandbox.
All sandbox users share the node owner's Unix identity.

_Avoid_: owner, Unix user

**node operator**:
The human responsible for a peer node's configuration and service manifest.

_Avoid_: admin, root

**vault mount**:
The one read-write bind of a user vault into a session sandbox. It is the
sandbox's data boundary and is never deleted with the sandbox record.

_Avoid_: data mount, workspace mount, mount (unqualified)

**config mount**:
The one read-only bind of generated OpenCode configuration into a VM sandbox.
It carries runtime configuration, not user knowledge.

_Avoid_: second mount, config volume

**mount list**:
The set of binds a sandbox is created with. It is the security boundary for
bind-mounted paths; a sandbox request cannot add a mount outside it.

_Avoid_: mount set, volumes

**sandbox policy**:
The declared filesystem, Landlock, process and network rules for a sandbox. It
states intent; for bind-mounted paths the mount list is the boundary.

_Avoid_: policy (unqualified), profile

**local execution whitelist**:
The peer's own closed list of images, mounts, actions and ports it will execute
for a sandbox request. It is narrower than the signed contract and is checked
before the gateway is called.

_Avoid_: whitelist (unqualified), policy

**policy proposal**:
A workload-generated request to change its own sandbox policy. It is inert
until the local approver accepts it; for a session sandbox that is the sandbox
user. The Master cannot approve it.

_Avoid_: proposal (unqualified), request

**policy approval**:
The local decision that accepts or rejects a policy proposal. For a session
sandbox the approver is the sandbox user; a service sandbox's approver is not
yet contracted. It is not a guard approval and carries no Master signature.

_Avoid_: approval (unqualified), consent

**execution request**:
A user-only, signed request to run one argv-only action on the peer inside the
local execution whitelist. It is not a sandbox request and not a shell.

_Avoid_: exec, shell request

**sandbox request**:
A Master-signed envelope asking a peer to inspect or change one sandbox record,
its policy or its service exposure. It carries authority, never knowledge.

_Avoid_: command, instruction, sandbox message

**sandbox supervision**:
The authority a `sandbox-supervise` grant confers: the Master may issue signed
sandbox requests, and the peer executes them against its own gateway within the
local execution whitelist. It does not include approving a workload policy
proposal.

_Avoid_: control, admin, supervision (unqualified)

**service exposure**:
In an OpenShell sandbox, one sandbox-local TCP port made reachable to the peer
through an authenticated gateway forward. It never exposes a host path or the
gateway credential.

_Avoid_: publish, port-forward, proxy (unqualified)

**model proxy**:
The host-side endpoint an OpenShell execution sandbox reaches as
`host.openshell.internal:<port>` for model traffic. It is not a service
exposure.

_Avoid_: model gateway, inference proxy

**session sandbox**:
An execution sandbox created for one sandbox user's session and stopped when
idle.

_Avoid_: user sandbox, temporary sandbox

**service sandbox**:
An execution sandbox declared in a peer's service manifest and never
idle-stopped. Its mount and approval rules are a separate contract decision,
not an extension of a session sandbox.

_Avoid_: persistent sandbox, system sandbox

**sandbox recreation**:
The separate stop/delete/create sequence required after a policy change that
cannot be applied live. It is not a sandbox action and not a restart.

_Avoid_: restart, reload, recreate (unqualified)

### Fabric components

**skill catalog**:
The build-time catalog that owns skill copy, digest, manifest and drift checks.
Family adapters supply sources, destinations, exclusions and transforms.

_Avoid_: skill sync, installer

**skill family adapter**:
The skill-catalog adapter for one vendored family or the role catalogs. It owns
that family's source policy and transformations.

_Avoid_: plugin, family

**understand graph**:
The derived code-structure graph built by `/understand`. It is a build
artifact, not an answer corpus.

_Avoid_: code graph, dependency map

**graph producer**:
The side of the understand graph that produces graph data and deltas; it owns
scan and diff semantics.

_Avoid_: scanner, builder

**graph consumer**:
The side that reads an existing understand graph and exposes query, export and
MCP; it does not produce graph data or deltas.

_Avoid_: viewer, server

**graph seam**:
The single stable entry point through which a graph consumer asks the producer
for graph data and deltas. It is not an installed package.

_Avoid_: API, bridge

**graph production**:
The producer's file-scanning and project-metadata work: what files exist, what
language they use and what project they form.

_Avoid_: scanning, parsing

**graph algebra**:
The producer's operations over graph data: normalize, merge, validate, diff,
layers and tour.

_Avoid_: analysis, processing

**opencode workspace**:
One of the three editing contexts: the fabric root, the peer role and the
Master role.

_Avoid_: project, workspace (unqualified)

**release export**:
The build-time process that stages a distribution surface, writes its checksum
manifest and verifies those checksums and the detached signature. It is not a
runtime module and not a knowledge channel.

_Avoid_: release, publish

**listener**:
The shared HTTP surface that owns request parsing, route auth and source
policy, refusals, health and lifecycle. A route handler owns the service
behaviour; the listener owns the transport.

_Avoid_: server, router

**envelope**:
A signed artifact whose canonical bytes are defined by an envelope
specification.

_Avoid_: message, payload

**envelope catalog**:
The single registry of envelope kinds and their fields, signed projection,
signer and verifier. Named message, signing and verification functions are
adapters over it.

_Avoid_: schema, message table

**console surface**:
One read-only view exposed by the node console: its endpoints, `session` or
`admin` auth class and optional menu metadata.

_Avoid_: dashboard, panel

**provenance facade**:
The single entry point through which callers use the provenance lifecycle and
its CLI.

_Avoid_: wrapper, API

**provenance primitives**:
The loader, YAML error re-exports, canonical form, crypto loaders, contract
reader, time and key-path helpers, and shared key-shaped patterns behind the
provenance facade.

_Avoid_: utilities, base

**provenance lifecycle**:
The note, ledger, grant and scan concerns behind the provenance facade. Each
lifecycle is separate, while callers use the one stable entry point.

_Avoid_: provenance, signing

**signer operation catalog**:
The one catalog that names each signer operation's request field, response key,
ledger event and prepare method. The common signer path owns root pinning,
validation, ledger append and response.

_Avoid_: signer API, operation list
