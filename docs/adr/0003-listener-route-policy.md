# 0003 — One listener interface with explicit route policy

## Status

Accepted (2026-11-09).

## Context

Role services each built their own HTTP surface: body parsing, `_send`, error
envelopes, health spellings and lifecycle. The shared signed transport existed,
but plain and custom listeners did not use it, so only some inherited the
socket timeout and every service carried a slightly different refusal shape.
The signer is a Unix-socket line protocol, the console is a root tool, and the
container registry and OpenCode proxy speak non-fabric protocols; they are not
part of this seam.

## Decision

`shared/sparknet-http.py` owns one route-table listener:

- `listen(routes, ...)` with explicit route auth (`plain`, `signed`, `custom`)
  and source policy (`any`, `loopback`, `overlay`, allowlist);
- the signed verifier and canonical request message stay the one shared
  implementation;
- the listener owns `TimeoutHandler`, body limits, health (`/healthz`), refusal
  shape and bind/start/stop/multi-bind lifecycle;
- `serve(router, ...)` remains the signed-only compatibility adapter;
- health is data-plane only; `contracts/service-health.md` is the contract;
- guard, bridge, intakes, reflex, admin agent and the signed routers are the
  in-scope listeners; signer, election, console, container registry and
  `opencode-engine` stay out.

## Consequences

- One timeout and one health contract instead of per-service copies.
- A new route must declare its auth and source policy; the default is not a
  permissive one.
- The guard and bridge keep their authority checks; the listener never gains a
  signing or granting path.
- A future new listener adopts the route table rather than growing a bare
  `BaseHTTPRequestHandler`.
