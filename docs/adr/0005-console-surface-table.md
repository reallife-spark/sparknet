# 0005 — One console surface table

## Status

Accepted (2026-11-09).

## Context

`scripts/sparknet-console.py` exposed about twenty read-only views through a
long `do_GET` if/elif chain, a separate admin path set, `api_surface` menus from
role config, a hard-coded HTML tab list and a hard-coded sidebar array. Adding
a view meant editing four places, and a missing admin-set entry could expose a
view to a user session.

The console is not a fabric listener: it is a root read-only tool behind the
Open WebUI same-origin proxy, with its own console-token/Open WebUI session
auth. The candidate 3 listener interface therefore stays for role services;
moving the console onto it is a separate decision.

## Decision

Use one ordered `SURFACES` table in the console module:

- `Surface` groups one or more `Endpoint` rows and optional `MenuSpec`.
- Every API path is an endpoint row with an explicit `session` or `admin` auth
  class. Handler-specific checks (for example, peer Issues refusing) remain in
  the handler.
- `API_BY_PATH` is the dispatch index; `do_GET` has no `/api/` branch chain.
- `MENU_SURFACES` is the menu source. `api_surface` returns both `menus` names
  (compatibility) and `menu_items` (id, label, href, icon).
- Role config `menus` is an allowlist; an unknown name is refused.
- The SPA sidebar and tabs read `menu_items`; no hard-coded menu list remains.

Static pages and per-view panels stay explicit. The table is the dispatch,
auth and menu seam, not a generic renderer.

## Consequences

- Adding an API view is one endpoint row; adding a rendered view also needs the
  panel and loader, documented rather than hidden.
- Auth is visible per row and exhaustive tests can iterate the table.
- Menu labels, hrefs and icons cannot drift between backend and SPA.
- A config typo fails loudly instead of removing a menu silently.
- The read-only boundary is unchanged: no row signs, grants, revokes or writes.
