# Deep-module audit — sparknet fabric

- **Date:** 2026-11-10
- **Baseline:** `e1b3417` (`docs: settle the sandbox domain vocabulary`)
- **Scope:** superproject plus the four pinned submodules: `peer-node/`,
  `master-node/`, `gospark/`, `goagx/`
- **Mode:** read-only architecture audit; no production code changed
- **Working tree note:** `master-node/CONTEXT.md` was already modified in the
  submodule before this audit. It was not touched or staged.

## Method

1. Read `AGENTS.md`, `CONTEXT.md`, `GLOSSARY.md` and every ADR before judging a
   seam, so a deliberate decision was not re-opened as a defect.
2. Walked the last 100 commits by changed path to find hot spots; the recent
   work concentrated on provenance, envelopes, listeners, the issue module,
   the understand core, the skill catalog and the sandbox contract.
3. Parsed top-level Python definitions and compared function bodies to find
   duplicated implementations; reviewed the role services by hand where the
   static scan cannot see cross-file policy (registry acceptance, loader
   bootstrap, Qdrant access).
4. Applied the deletion test to each candidate: would deleting the module
   concentrate complexity, or merely move it?
5. Measured implementation boundaries as `bytes / 4` for a rough token budget,
   with the target of **< 140k tokens per boundary**.

This report uses the deep-module vocabulary: **module**, **interface**,
**depth**, **seam**, **adapter**, **leverage**, **locality**.

## Setup findings

| Check | Result |
|---|---|
| Remote | `origin` → `github.com/reallife-spark/sparknet` (private) |
| Canonical tracker | Local markdown under `.scratch/issues/`, schema `sparknet-issue/1` |
| Tracker decision | ADR-0001, accepted; local remains canonical |
| Triage labels | Five canonical roles documented; created on GitHub as a mirror vocabulary |
| Domain docs | `GLOSSARY.md` and `docs/adr/` present; single-context layout is correct |
| Monorepo signals | None; submodules are role/distribution repos, not package workspaces |
| GitHub mirror | Labels created; issue creation blocked by the current PAT (`createIssue` not permitted). Local issues are complete and canonical. |

No `GLOSSARY-MAP.md` was added. The submodule glossaries are already mapped by
`AGENTS.md` and `docs/agents/domain.md`; a second map would duplicate the
authority instead of clarifying it.

## Candidate ranking

| # | Candidate | Strength | Boundary cost |
|---|---|---|---|
| 1 | Go capability vocabulary drift | Strong | Small |
| 2 | Registry-entry acceptance duplication | Strong | ~106k tokens before all tests |
| 3 | Shared-directory resolution duplication | Strong | ~207k tokens across all role services |
| 4 | Console bypasses the vector implementation | Worth exploring | ~40k tokens |
| 5 | `tests/test_contracts.py` monolith | Worth exploring | ~28k tokens alone; ~82k with authz |
| 6 | Package artifact selection in the CLI | Speculative | Small |
| 7 | `sparknet-authz.py` internal split decision | Speculative | ~82k tokens with tests |

### 1. Go capability vocabulary drift — Strong

`contracts/capabilities.json` and `shared/sparknet-authz.py:62-77` know 13
capabilities. `gospark/internal/authz/capabilities.go:17-48` knows 11:

- missing `issue-report`;
- missing `sandbox-supervise`;
- `sandbox-supervise` is also absent from the Go sensitive map at `:60-68`.

Go refuses an authorization entry whose capability is not known
(`gospark/internal/authz/registry.go:239-242`) and refuses to sign one
(`:422-426`). A valid Master-signed registry entry carrying either capability is
therefore refused by goSpark while Python accepts it. The existing
cross-verification tests (`tests/test_registry_crossverify.py`) only use
`telemetry` and `cluster-serve`, so the drift is invisible to CI.

**Deletion test:** deleting the Go constants and generating them from the
contract concentrates the vocabulary in one source. Keeping a hand-written copy
moves the same list into a second language with no gate.

**Proposed shape:** generate the Go known/sensitive sets from
`contracts/capabilities.json`, or keep the Go file and add a superproject drift
test that compares both sets. No runtime JSON dependency in Go.

### 2. Registry-entry acceptance duplication — Strong

Five surfaces decide whether a registry entry is usable, each with its own
sequence:

- `shared/sparknet-authz.py:459-520` — local-node `evaluate`: identity
  fingerprint, revocation, expiry, issued-at skew, signature, capability
  vocabulary.
- `master-node/services/sparknet-peer-intake.py:236-285` — signature,
  revocation, validity window, requested capability; no identity-fingerprint
  check.
- `master-node/services/sparknet-scheduler.py:190-245` — fingerprint, signature,
  capabilities, revocation, expiry, skew; custom error strings.
- `master-node/services/sparknet-rfi-responder.py:234-258` — signature,
  revocation, window; no identity-fingerprint or capability check.
- `master-node/services/sparknet-uplift-intake.py:196-215` — signature,
  revocation, window; no identity-fingerprint check.
- `peer-node/services/sparknet-liveness-monitor.py:178-205` — tolerant roster:
  revocation, expiry, signature; no identity check.

The existing `evaluate` interface takes the local identity, so it cannot serve a
remote entry. The five copies have already drifted on check order, skew,
malformed-timestamp handling and identity verification. A future hardening in
`evaluate` reaches only the local-node paths.

**Deletion test:** deleting the five copies and moving the rule into one
`accept_entry` seam concentrates the authority decision. It does not move it:
the callers keep their HTTP mapping and refusal vocabulary.

**Proposed shape:** `accept_entry(entry, master_key, now,
required_capability=None, mode="strict|roster")` returning a typed
`AcceptedEntry` or a typed refusal. Strict refuses identity mismatch; roster
skips it. Uses only the canonical authz functions.

### 3. Shared-directory resolution duplication — Strong

`shared/sparknet_loader.py:19-24` documents `SPARKNET_SHARED_DIR` as a root
containing `shared/`. Role services treat the same value as the shared
directory itself and then add their own candidates:

- `peer-node/services/sparknet-guard-d.py:461-476`
- `peer-node/services/sparknet-liveness-monitor.py:88-98`
- `peer-node/services/sparknet-checkpoint-anchor.py`
- `peer-node/services/sparknet-telemetry-push.py`
- `peer-node/services/sparknet-issue-push.py:46-49` (a shorter variant)
- `master-node/services/sparknet-signer.py:192-207`
- `master-node/services/sparknet-admin-console.py:171-181`
- `master-node/services/sparknet-share-ratify.py:367-378`
- `master-node/services/sparknet-vector-serve.py:52-60`

There are 39 references to `SPARKNET_SHARED_DIR` in the two role trees and at
least 17 distinct resolver bodies. Some add `/srv/sparknet/shared`, some do not;
some accept a role-local `shared/`, some do not. A bundle-layout or environment
change currently requires edits across both submodules.

**Deletion test:** deleting the per-service resolvers and extending the loader's
search policy concentrates resolution in the module that already owns loading
and caching. ADR-0002 deliberately keeps the loader and the two-line path shim;
this does not conflict with it.

### 4. Console bypasses the vector implementation — Worth exploring

`scripts/sparknet-vector.py` owns collection naming (`:955`), stamp comparison
(`:858-864`, `:1175-1204`), query projection (`:1205`) and the stale-index
refusal. The 4223 service loads it correctly
(`master-node/services/sparknet-vector-serve.py:68-120`).

`scripts/sparknet-console.py` implements a second Qdrant path:

- `allowed_collection()` at `:143-149` reimplements the allow-list;
- `qdrant_request()` at `:151-173` builds raw HTTP requests;
- `api_qdrant()` at `:590-639` reads collection config;
- `api_map()` at `:641-668` scrolls points with vectors;
- `project_points()` at `:175-230` owns a second projection.

The console never checks the index stamp, so it can present a stale or foreign
collection as current. It is stdlib-only by design (`requirements.txt` allows
only `cryptography`), so the fix is a dependency-free read view, not an import
of `qdrant-client`.

**Deletion test:** deleting the console's Qdrant code and replacing it with one
shared read view concentrates collection naming, allow-listing and stamp
semantics. It does not remove the console's read-only surface.

### 5. `tests/test_contracts.py` monolith — Worth exploring

`tests/test_contracts.py` is 2,326 lines, 113 KB and 131 tests. It already has
section markers for one-implementation checks, overlay, ports, roles, registry,
guard, share, compose, consensus, provenance, RFI and telemetry. The file alone
is about 28k tokens; the authz-plus-contracts boundary is about 82k, and the
registry-acceptance boundary is about 106k before role tests.

**Deletion test:** this is not a production module; the test suite is the
interface. Splitting by the existing section markers gives each contract a
narrow test surface without changing assertions. Keeping one file moves the
context cost into every contract change.

### 6. Package artifact selection in the CLI — Speculative

`scripts/sparknet-package.py:17-19` defines `SKIP_PARTS`/`SKIP_NAMES` and
`:80-105` walks the tree. `shared/sparknet-package.py:121-147` accepts an
already-built artifact list but does not own the exclusion policy. A second
packager would duplicate the list or accidentally include `.git`, `.state`,
keys, `__pycache__`, `.env` or a secrets index.

**Deletion test:** moving the walk into the shared package module concentrates
an integrity rule. This is lower priority because there is one caller today;
YAGNI applies until a second packager is real.

### 7. `sparknet-authz.py` internal split decision — Speculative

`shared/sparknet-authz.py` is 2,655 lines / about 109 KB. It is deep, not
shallow: it hides the canonical-byte rule behind a wide but necessary interface.
The problem is context cost. ADR-0004 deliberately put the envelope catalog
here; ADR-0002 deliberately keeps the by-path loader. A split must preserve both
or supersede one explicitly. This is a decision ticket, not an implementation
ticket.

## Healthy modules and decisions not to re-open

- Provenance is split along lifecycle seams behind a stable facade
  (ADR-0006/0007). A note change loads only base and note.
- The listener is one route-table interface with explicit auth and source policy
  (ADR-0003). Remaining bare handlers are signer, console, container registry
  and the OpenCode proxy, all explicitly out of scope.
- The console has one `SURFACES` table (ADR-0005); the remaining seam is its
  external Qdrant access, not its dispatch.
- The issue model is one shared module behind a facade (ADR-0009).
- The skill catalog already has one engine and four family adapters (ADR-0010);
  the scripts' apply/check loops are adapters, not a second engine.
- The understand core has schema/production/algebra behind a facade
  (ADR-0011).
- The Go registry cross-verification tests already prove signed entries cross
  the language boundary; the missing piece is vocabulary drift, not a second
  crypto implementation.

## Recommended order

1. **Go capability drift** — concrete, small, closes a real cross-repo gap.
2. **Registry acceptance** — security-adjacent; needs the human decision on
   strict/roster modes before code.
3. **Shared-dir resolution** — mechanical, reduces the largest boundary.
4. **Contract-test split** — makes every subsequent contract change cheaper.
5. **Console/vector seam** — read-only, testable with a fake HTTP server.
6. **Package artifact selection** — small, speculative until a second caller.
7. **Authz split decision** — ADR first; do not start a canonical-byte refactor
   from an audit ticket.

## Ticket index

Local canonical files live in `.scratch/issues/`:

| ID | Title | Label | Report section |
|---|---|---|---|
| `go-capability-vocabulary-drift` | Sync the goSpark capability vocabulary with `contracts/capabilities.json` | `ready-for-agent` | 1 |
| `unify-registry-entry-acceptance` | Unify registry-entry acceptance across peer and Master services | `ready-for-human` | 2 |
| `consolidate-shared-dir-resolution` | Make `shared/sparknet_loader.py` own shared-directory resolution | `ready-for-agent` | 3 |
| `console-vector-view-seam` | Give the console one read-only vector view over the shared store | `ready-for-agent` | 4 |
| `split-contract-test-suite` | Split `tests/test_contracts.py` by contract boundary | `ready-for-agent` | 5 |
| `harden-package-artifact-selection` | Move package artifact selection behind the shared package module | `ready-for-agent` | 6 |
| `authz-internal-split-decision` | Decide whether to split `shared/sparknet-authz.py` behind its facade | `ready-for-human` | 7 |

GitHub mirror status: the five labels exist. Issue creation was refused by the
current fine-grained token (`Resource not accessible by personal access token
(createIssue)`); the local files remain the source of truth. The mirror can be
published later with:

```bash
while IFS=$'\t' read -r id title label; do
  python3 -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); t=p.read_text(); b=t.split("\n---\n",1)[1].lstrip("\n").rstrip("\n"); print(b); print("\n---\nMirror of `.scratch/issues/%s.md`; local is canonical." % p.stem)' ".scratch/issues/$id.md" \
    | gh issue create --repo reallife-spark/sparknet --title "$title" --label "$label" --body-file -
done < /tmp/opencode/sparknet-audit/manifest.tsv
```

## Implementation status (2026-11-11)

All seven findings are closed locally:

| Issue | Change |
|---|---|
| `go-capability-vocabulary-drift` | Go catalog synced to 13 capabilities; drift and cross-language tests added. |
| `unify-registry-entry-acceptance` | `authz.accept_entry` is the one seam; five services call it. |
| `consolidate-shared-dir-resolution` | Loader owns the search policy; per-service resolvers removed. |
| `console-vector-view-seam` | `shared/sparknet-vector-view.py`; console calls it. |
| `split-contract-test-suite` | `tests/contracts/` by contract boundary; old path is a thin marker. |
| `harden-package-artifact-selection` | Shared directory-package builder; CLI is argument parsing only. |
| `authz-internal-split-decision` | ADR-0014 keeps the module and records the staged-split trigger. |

Verification after the changes: `make test-all`, `make lint`,
`make format-check`, `make shellcheck`, `make render-check` and
`make context-check` pass. The source commits are goSpark `cd2d72a`, peer
`24bee7d`, master `edc45eb` and fabric `503a2f7`; the goagx distribution was
republished as `dcb84b4` and the pointer is pinned.

## Verification performed

- All seven local issue files parse and validate against the shared issue model:
  `parse_issue_file()` accepted each one, labels are canonical, bodies are
  below the 65536-byte limit.
- The five GitHub labels exist; `wontfix` was updated rather than duplicated.
- At audit time no production code, contract, role submodule or generated
  artifact had changed; the implementation status above records the follow-up.
- `master-node/CONTEXT.md` remains the pre-existing local modification.

## Boundary measurements

| Boundary | Files | Size | Approx. tokens |
|---|---|---|---|
| Authz + contract tests | 8 | 319 KB | ~82k |
| Registry acceptance | 11 | 413 KB | ~106k |
| All role services | 37 | 808 KB | ~207k |
| Vector + console | 6 | 155 KB | ~40k |
| Skill sync | 7 | 100 KB | ~26k |
| Understand core | 7 | 80 KB | ~20k |

The registry-acceptance boundary is the closest to the 140k target before role
tests are added. The role-service total is over the target, which is why the
loader issue is ranked above the smaller refactors.
