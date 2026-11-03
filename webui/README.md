# Sparknet WebUI console

Read-only Mesh, Vectors and Learning pages for the peer and Master Open WebUI
surfaces. The contract is `contracts/webui-surface.md`.

## Status

Implemented and tested locally:

- `scripts/sparknet-console.py` — loopback service, Open WebUI token validation,
  Qdrant read-only view, deterministic 3D pilot cloud, distillation run view;
- `webui/console/` — dependency-free HTML/CSS/JS pages;
- `webui/patch-openwebui.py` — idempotent Open WebUI 0.12.x sidebar patch;
- `webui/nginx.conf.template` — same-origin proxy and HTML launcher injection template.

Live on 2026-11-01: nginx fronts Open WebUI on `agx64:8181` and
`agx32:10.100.0.1:8088`, injects the Sparknet launcher, and routes
`/sparknet-console/` to the loopback console (`8099`/`8098`). The peer console
session test accepted an Open WebUI admin token and returned a 500-point map;
the Master returned 153 points. Persistent systemd units and the source-level
sidebar patch/image build remain target-node actions. The Master's
`/srv/sparknet/distill` is root-only, so the Learning page currently reports a
scoped permission note instead of reading runs directly.

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

Against a v0.12.x checkout:

```sh
webui/patch-openwebui.py --root /path/to/open-webui --apply
webui/patch-openwebui.py --root /path/to/open-webui --check
```

The patch adds **Mesh**, **Vectors** and **Learning** links to the sidebar. It
does not fork the backend, add an auth system or change Open WebUI's data.

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

## Memory filter

`functions/sparknet_memory_filter.py` is an Open WebUI Filter Function. It adds
scoped recall to `inlet` and captures the turn in `outlet` through the loopback
Python memory gateway; it never reads a vault or the Go store directly. Install
it with `install-memory-filter.py` using the node's WebUI admin token. The
filter's `Valves` read `SPARKNET_MEMORY_GATEWAY_URL` and
`SPARKNET_MEMORY_WEBUI_TOKEN` from the node env-file. If the gateway is down it
fails open so chat still answers.
