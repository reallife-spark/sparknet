# Service health — one data-plane endpoint

A role listener answers one health route, `/healthz`. It is data-plane
information: it says whether the listener is serving, never whether a node may
sign, grant, revoke or be trusted. It carries no authority and no knowledge.

## Route

| Property | Value |
|---|---|
| Method | `GET` (also `HEAD`) |
| Path | `/healthz` |
| Auth | plain by default; the listener's source policy still applies |
| Payload | `{"ok": true, "service": "<name>"}` |
| Status | `200` when serving; a service may answer `503` when it cannot serve |
| Headers | `Content-Type: application/json`; no secrets, no key material, no paths outside the service's public state |

A service may add non-secret, non-authority fields to the payload (for example
a mode or a bound path). It must not include keys, tokens, capability grants,
registry contents or another node's state. Health is not a shortcut around a
listener's normal source policy.

## Legacy aliases

Existing listeners used `/health`, `/healthz` and `/v1/health` by accident of
history. They may keep their old path as a legacy alias during migration, but
new listeners use `/healthz`. The alias is the same data; it does not become an
authority route.

## Implementation

`shared/sparknet-http.py::listen` adds `/healthz` unless the caller already
declared that path. The listener owns the route, timeout and refusal envelope;
the service owns the payload. `tests/test_listener.py` pins the route and the
payload, and the role listener guardrail fails on a new bare HTTP handler.
