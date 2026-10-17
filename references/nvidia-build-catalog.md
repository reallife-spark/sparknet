---
title: NVIDIA build catalog — verified endpoints
updated: 2026-10-17
source: live probes of build.nvidia.com, integrate.api.nvidia.com, api.ngc.nvidia.com
license: n/a — API notes, no vendor code
type: reference
---

# NVIDIA build catalog — verified endpoints

What `scripts/sparknet-nv-search.sh` queries, and what each surface *actually*
is. Every statement below was probed live on **2026-10-17**; the browser
surfaces were checked with `curl -w '%{http_code} %{content_type}'`. The rule
this feeds is `STYLE_GUIDE.md` §1 (resource-first).

## The endpoints

| Surface | Method | Auth | Result on 2026-10-17 |
|---|---|---|---|
| `https://integrate.api.nvidia.com/v1/models` | GET | none | `200 application/json`, OpenAI-shaped list — **81 model ids** (`vendor/model`) |
| `https://integrate.api.nvidia.com/v1/models/<id>` | GET | none | `200` for a live id; **`410` with the end-of-life date** for a retired one; `404 Model does not exist by the name of <id>` otherwise |
| `https://api.ngc.nvidia.com/v2/search/resources/ALL?q=<q>&pageSize=N` | GET | **key** | `401 {"statusDescription":"Not Authenticated"}` without a token; JSON with one |
| `https://build.nvidia.com/explore/discover` | GET | none | `200 text/html` — a **Next.js SPA** |
| `https://build.nvidia.com/api/search?q=<q>` | GET | none | `200 text/html` — same SPA. **There is no JSON search API on this host** |

The last row is the one worth remembering: `build.nvidia.com` was on the
original endpoint list as an API, and it is not one. Every path under it —
including `/api/...` — serves the same HTML shell unless the request carries
the headers the site's own fetch uses. Early research recorded "`build.nvidia.com/api/search` →
200", which was true and useless: 200 was the shell. Probe **content type**,
not just status.

## What the helper does

```sh
scripts/sparknet-nv-search.sh models [SUBSTRING]   # filter the 81 ids
scripts/sparknet-nv-search.sh show ID              # 200 = live, 410 = retired (date in the body)
scripts/sparknet-nv-search.sh ngc QUERY            # NGC search; refuses without a key
scripts/sparknet-nv-search.sh discover             # the browser surfaces, as pointers
make nv-search q="llama"                           # the make face of `models`
```

`show` doubles as a **lifecycle check**: `meta/llama-3.1-8b-instruct` answered
`410 … reached its end of life on 2026-08-26` during the probe, which is the
kind of thing a resource-first lookup is supposed to surface before you build
against a deprecated model.

## Auth

- `integrate.api.nvidia.com/v1/models` and `show` need **no** key.
- `ngc` and authenticated NGC calls read the key from exactly one place:
  `$SPARKNET_STATE_DIR/secrets/build-nvidia.env` (default
  `.state/secrets/build-nvidia.env`), mode **0600**, gitignored via `.state/`;
  `make keys-check` enforces the mode for the whole `secrets/` directory.
- The key is a `BUILD_NVIDIA_API_KEY=…` line. It is never printed, logged or
  written by the helper. `STYLE_GUIDE.md` §7 governs it, and any key pasted
  into a chat is treated as exposed and rotated.

## Known-open

- The NGC search response shape could not be verified here (no key on this
  host), so the helper passes it through unshaped. Verify before relying on
  the fields.
- The SPA can be scraped with a headless browser; that is deliberately not
  done — the browser surfaces are listed as pointers so a human can search
  them, and the machine-readable path stays the integrate list.

## Related

- [[nvidia-dsx-standard-practice]] — the repo inventory; adoption item 12
  (resource-first rule) comes from NVIDIA's published integration guidance.
- `STYLE_GUIDE.md` §1; `scripts/sparknet-nv-search.sh`; `make nv-search`.
