# Sparknet WebUI console

Read-only Mesh, Vectors and Learning pages for the peer and Master Open WebUI
surfaces. The contract is `contracts/webui-surface.md`.

## Status

**Live 2026-11-05 on agx64 (peer) and agx32 (Master admin), Open WebUI v0.13.0.**

- The agent execution path is the loopback **Sparknet OpenCode engine** on
  `127.0.0.1:4204`; each user gets an OpenCode 1.19.5 sandbox that mounts only
  their `peer-<user_id>` vault.
- 16 bilingual prompts, four user-scoped native tools and two active/global
  functions are installed by `peer-node/scripts/sparknet-webui-workspace.py apply`.
- The static dispatch-bridge grant is no longer a WebUI model or tool server.
- The old cluster2 Master WebUI was retired; the Master is admin-only and the
  peer holds every human user.

Implemented and tested locally:

- `scripts/sparknet-console.py` — loopback service, Open WebUI token validation,
  Qdrant read-only view, deterministic 3D pilot cloud, distillation run view;
- `webui/console/` — dependency-free HTML/CSS/JS pages;
- `webui/patch-openwebui.py` — idempotent Open WebUI 0.12.x/0.13.x sidebar patch;
- `webui/nginx.conf.template` — same-origin proxy and HTML launcher injection template.

Live on 2026-11-04: nginx fronts Open WebUI on `agx64:8181` and
`agx32:10.100.0.1:8088`, routes `/sparknet-console/` to the loopback console
(`8099`/`8098`) and injects a native **SPARKNET** sidebar group directly below
Notes/Workspace. The peer shows Mesh/Vectors/Learning; the Master shows the same
for all authenticated users. Peer Learning is a signed 4221 read-only fetch of
the Master's sanitized snapshot. The 3D map has explicit zoom controls and a
wheel/keyboard binding. The Master's `/srv/sparknet/distill` is root-only, so the
snapshot service writes only sanitized metadata.

## Install the persistent user unit

```sh
python3 webui/install-console.py --role peer --apply
python3 webui/install-console.py --role master --apply
```

The installer writes `~/.local/bin/sparknet-console`, installs
`sparknet-console@.service` under the user manager and enables the role instance.
It refuses if the console token is missing.

## Run manually

Create the console token at `0600` under the role state directory:

```sh
install -d -m 0700 peer-node/.state/webui
head -c 32 /dev/urandom | base64 > peer-node/.state/webui/console.token
chmod 0600 peer-node/.state/webui/console.token
```

Peer:

```sh
scripts/sparknet-console.py --role peer
# http://127.0.0.1:8099/ (or through nginx at /sparknet-console/)
```

Master:

```sh
scripts/sparknet-console.py --role master
# http://127.0.0.1:8098/
```

The browser normally sends the Open WebUI token already stored at the same
origin. The deploy token is the service/automation fallback and is never sent to
the browser by this service.

## Patch Open WebUI

Against a v0.12.x/0.13.x checkout:

```sh
webui/patch-openwebui.py --root /path/to/open-webui --apply
webui/patch-openwebui.py --root /path/to/open-webui --check
```

The source patch adds the same links for a rebuilt image. The live prebuilt
image uses the injected `webui/console/sparknet-menu.js` sidebar group instead;
the source patch remains the build-time equivalent. Neither forks the backend,
adds an auth system or changes Open WebUI's data.

## Nginx

The compose stacks run `nginx:1.27-alpine` on the host network with
`webui/nginx.conf.template`:

- peer: `SPARKNET_BIND=8181`, `SPARKNET_CONSOLE_UPSTREAM=127.0.0.1:8099`,
  `SPARKNET_WEBUI_PORT=8080`;
- Master: `SPARKNET_BIND=10.100.0.1:8088`,
  `SPARKNET_CONSOLE_UPSTREAM=127.0.0.1:8098`, `SPARKNET_WEBUI_PORT=8080`.

Nginx injects `/sparknet-menu.js` into Open WebUI's HTML, so the launcher is
present without rebuilding the frontend. Caddy is not used because the standard
image has no response-body replace directive; Nginx `sub_filter` is built in.

## Master distill snapshot

The Master's distill state is root-only. `master-node/services/sparknet-distill-status.py`
writes a sanitized status snapshot, and `sparknet-distill-status.timer` runs it
every two minutes as root. The Learning page reads the snapshot; it never reads
datasets, prompts or traces.

## Limits

- The 3D cloud is a **deterministic random projection pilot**, not UMAP. It
  samples real Qdrant vectors and labels the projection honestly.
- The console is read-only. It cannot sign, approve, publish, train or change a
  setting.
- The Master's per-user vector inspection needs the separate `vector-inspect`
  capability; the read-only screen only exposes fabric/shared/distill-map.

## OpenCode engine

`peer-node/services/sparknet-opencode-engine.py` is the OpenAI-compatible adapter
behind the WebUI's `sparknet-chat`, `sparknet-plan` and `sparknet-build` models.
It is a **host systemd service** (`sparknet-opencode-engine@peer|master`), not a
compose service: it needs the Docker socket to supervise one sandbox per user.

- `peer-node/configs/opencode-engine/opencode.json.template` — chat/plan are
  read-only; build may edit and shell inside `/work` only.
- `peer-node/configs/opencode-runtime/` — the pinned 1.19.5 runtime image and
  its Unix-socket bridge. Build it with `make -C peer-node opencode-runtime`.
- The engine binds loopback only and requires the deploy-time engine token plus
  the WebUI-forwarded user header. It holds no key and mounts no role state.
- Master uses `--single-vault /srv/sparknet/knowledge/master-admin`; the master
  role vault (keys, ledger, registry) is never mounted.

## Workspace baseline

`make` / the deploy step runs:

```sh
python3 peer-node/scripts/sparknet-webui-workspace.py ... apply
```

It applies `webui/settings.peer.json` or `settings.master.json`, installs the
bilingual prompts, the four tools, the memory filter + capture action, migrates
per-user models to `sparknet-chat`, rebuilds the structure-only KB from the
RAG allow-list and requests a knowledge reindex.

## Memory filter

`functions/sparknet_memory_filter.py` is an Open WebUI Filter Function. It adds
scoped recall to `inlet` and captures the turn in `outlet` through the loopback
Python memory gateway; it never reads a vault or the Go store directly. Install
it with `install-memory-filter.py` using the node's WebUI admin token. The
filter's `Valves` read `SPARKNET_MEMORY_GATEWAY_URL` and
`SPARKNET_MEMORY_WEBUI_TOKEN` from the node env-file. If the gateway is down it
fails open so chat still answers.
