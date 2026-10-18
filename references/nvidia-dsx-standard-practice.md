---
title: NVIDIA / dsx standard-practice inventory
updated: 2026-10-17
source: https://github.com/dsx-ai-factory (13 repos) + https://github.com/EleutherAI/lm-evaluation-harness
license: mixed — Apache-2.0 (12) and MIT (2); pattern reference only, no code copied
type: reference
---

# NVIDIA / dsx standard-practice inventory

The provenance record behind PLAN Steps 45–52 (the NVIDIA/dsx
standard-practice adoption arc). All 14 repositories were cloned
**full-history** to `/mnt/nvme/github/<name>` on 2026-10-17 and are pinned at
the SHAs below; commit counts, default branches and licences were read from
the clones or the GitHub API that day.

## Rules of engagement (user decision, 2026-10-17)

1. **No license change.** sparknet and goSpark stay as they are; nothing here
   is vendored or copied. Every adoption is a *pattern* re-implemented against
   this fabric's own contracts.
2. **Provenance lives in this page** — not a NOTICE file. (`model-streamer`
   keeps a `third_party_notices/` tree for the same job; this page is our
   equivalent, one level up.)
3. **Our action pins are SHAs, never `@main`.** `dsx-github-actions` itself
   contains 88 `@main` self-references (it *is* the action source); that is
   the one pattern deliberately **not** copied.
4. Adopted files describe only commands that actually run here — no
   aspirational targets.

## The 14 repositories

| Repo | SHA | Commits | Branch | License | What it is |
|---|---|---|---|---|---|
| `EleutherAI/lm-evaluation-harness` | `d6de81643928d653435c431bae19945d41d32520` | 4122 | main | MIT | Model evaluation harness: task registry, `local-completions` backend |
| `dsx-ai-factory/run-ai` | `3c8f35ec0e77aa0d45283417cfcb3d8c6a215f09` | 1391 | main | Apache-2.0 | Run:ai monorepo: code + docs, Go/Python/Node |
| `dsx-ai-factory/nv-config-manager` | `6194825b9b0f18549a2c8b603e404acf526f9c9d` | 312 | main | Apache-2.0 | Datacenter network automation (Nautobot + Temporal), Python |
| `dsx-ai-factory/infra-controller` | `54d65377cfefa99ae0b5f50c9199fd929427ba86` | 4302 | main | Apache-2.0 | NICo: bare-metal/k8s lifecycle controller, Rust workspace |
| `dsx-ai-factory/dsx-exchange` | `484162a68b380f403458459ef9cad5a16758f3ff` | 100 | main | Apache-2.0 | Async bus + gateway bridge, NATS **auth-callout** |
| `dsx-ai-factory/cluster-api-provider-nico` | `a3bfe4ee100e52cc221ec96639a4938e8f4e1396` | 176 | main | Apache-2.0 | CAPI provider for NICo, Go |
| `dsx-ai-factory/topograph` | `091bca25f35354f10a4ce9c5d6328fd8c0c77357` | 528 | main | Apache-2.0 | Topology-aware scheduling (Slurm/k8s), Go |
| `dsx-ai-factory/model-streamer` | `f0a6915b4ad6b2a5289abef9f720bce30398d4a3` | 242 | **master** | Apache-2.0 | Streaming model loader SDK, C++ + Python |
| `dsx-ai-factory/workload-map` | `45e123747395d5fcac125a1d60a408c886fa5741` | 218 | main | Apache-2.0 | Workload mapping (formerly **Karta**), Go CLI + k8s |
| `dsx-ai-factory/fleet-intelligence-agent` | `6eace17c3c19adf1524ba71c9cbd0450266a61f1` | 251 | main | Apache-2.0 | Fleet telemetry agent (otelcol config), Go |
| `dsx-ai-factory/nv-telemetry` | `f947b61892694c4aafa48d0b2a045477dccaa150` | 25 | main | Apache-2.0 | Telemetry model + Prometheus/OTLP exporters + `bmc-mock`, Rust |
| `dsx-ai-factory/dsx-github-actions` | `26399d755ca30a486b80931fb50cc483a97a8582` | 155 | main | Apache-2.0 | Shared composite actions: docker-build, codeql, trufflehog, release |
| `dsx-ai-factory/libredfish` | `a51ffb1ffeae15d8f9471224cb799d54007098a2` | 266 | main | MIT | Minimal Redfish client, Rust |
| `dsx-ai-factory/nv-redfish` | `7c6a95762cc63cffbca459808b92f546c47aac25` | 451 | main | Apache-2.0 | Full Redfish crate + `bmc-mock` + CSDL compiler, Rust |

Notes: `infra-controller` and `workload-map` carry org/rename redirects (from
NVIDIA and from "Karta" respectively). `model-streamer` — the only non-`main`
default branch — is the repo whose SDK layout matter came closest to ours.
`/mnt/nvme` held 96 G free after cloning (63 % used).

## The standard, as observed

Presence across the 14 clones (counts are of the 14):

- **Agent + community files**: `AGENTS.md` 12, `CONTRIBUTING.md` 12,
  `SECURITY.md` 13, `RELEASE.md` 6, `CHANGELOG.md` 12, `CODE_OF_CONDUCT.md`
  ~8, `GOVERNANCE.md` ~6, `MAINTAINERS.md` ~4, `CODEOWNERS` 6, `NOTICE` 6.
  Four repos carry a **paired `CLAUDE.md`** next to `AGENTS.md` (run-ai,
  infra-controller, workload-map) — not adopted here: one `AGENTS.md` per
  vault is this fabric's rule.
- **Task-runner + help**: every Go/Python repo has a `Makefile` whose first
  meaningful target is `help` with `##` comments (nv-config-manager,
  infra-controller, cluster-api-provider-nico, topograph, workload-map,
  fleet-intelligence-agent, dsx-exchange). `lm-evaluation-harness`,
  `dsx-github-actions` and `libredfish` have none (all three are libraries).
  This is the one convention sparknet already meets.
- **Language gates**: `.golangci.yml` in all Go repos (`govet`,
  `staticcheck`, `unused`, `ineffassign`, errcheck excluded by policy in
  topograph); `ruff`-era Python config in nv-config-manager (`pyproject.toml`
  + `sort-check`/`sort-fix` targets); `clippy.toml` + `deny.toml` +
  `Cross.toml` for the Rust workspaces.
- **Repo-maintenance configs**: `renovate.json` 4 (run-ai's is deeply
  presets-based), `.pre-commit-config.yaml` 5 (lm-eval, infra-controller,
  model-streamer, dsx-github-actions, nv-config-manager), `mise.toml` +
  `mise.lock` (dsx-exchange), `commitlint.config.js` with
  `config-conventional` (dsx-exchange).
- **Agent-facing indexes**: `llms.txt` + `llms-full.txt` (nv-config-manager,
  dsx-exchange). nv-config-manager's is the house template: a title, a
  one-line blockquote summary, then a component-by-path map.
- **GitHub Actions**: every repo has workflows; refs are pinned by 40-hex SHA
  with a `# vN` comment (run-ai 93 SHA refs / 1 main; cluster-api 80/0;
  infra-controller 46/0; nv-config-manager 35/0; topograph 31/0; …;
  exceptions: `nv-telemetry` 3 `@main`, `nv-redfish` 3 `@main`,
  `libredfish`/`topograph` use version tags like `actions/checkout@v7.0.1`).
  Recurring jobs: CodeQL, secret scan (trufflehog), `govulncheck`, image scan,
  dependency review, OpenSSF scorecard, stale, DCO, CLA, license headers,
  semantic release/rc.
- **Aggregate merge gate** (the single most reusable CI idea):
  `cluster-api-provider-nico/.github/workflows/merge-gate.yml` — one `gate`
  check that every branch ruleset requires, so adding/renaming jobs never
  leaves a ruleset naming a check that no longer exists (a
  required-but-absent check blocks forever). Its header comment explains the
  two failure modes better than any doc.
- **Provenance/licensing discipline**: SPDX headers + `spdx-headers.yml`
  (model-streamer), `license.yml`/`add-license-headers` (cluster-api,
  dsx-exchange), `third-party-licenses` target + `third_party_notices/`
  (model-streamer, dsx-exchange), `NOTICE` files where required.
- **Secrets rule, stated in prose**: run-ai's `AGENTS.md` opens with a
  section that forbids committing secrets *and* placeholder-looking-real
  values in docs, and routes discovery to `SECURITY.md` rather than a public
  PR. That wording is the model for our own `AGENTS.md`/`CONTRIBUTING.md`
  secret lines.
- **Docs trees**: 8 repos have `fern/` + `docs.yml`/`fern-docs-*` workflows.
  Out of scope here (no hosted docs site).

## Adoption map — what this fabric takes, and from where

| # | Adopt | Source (path) | Lands in |
|---|---|---|---|
| 1 | Community file set + `llms.txt` shape | nv-config-manager `AGENTS.md`/`llms.txt`, run-ai `AGENTS.md` secret section | Step 47 |
| 2 | Workflows: pinned SHA refs, secret-scan, CodeQL, license/stale jobs | cluster-api-provider-nico `.github/workflows/*`, run-ai `pr-checks.yaml`, `dsx-github-actions` `docker-build.yml`/`codeql`/`trufflehog` patterns | Step 48 |
| 3 | Aggregate `gate` workflow pattern | cluster-api-provider-nico `.github/workflows/merge-gate.yml` | Step 48 |
| 4 | Conventional commits + staged-format pre-commit | dsx-exchange `commitlint.config.js`, infra-controller `.pre-commit-config.yaml` | Steps 46, 49 |
| 5 | `.golangci.yml` baseline (govet/staticcheck/unused/ineffassign) | topograph `.golangci.yml`, fleet-intelligence-agent, workload-map | Step 50 |
| 6 | `## help` Makefile + `fmt-check`/`lint` target vocabulary | cluster-api-provider-nico, workload-map, fleet-intelligence-agent | Steps 46, 50 (mostly already met) |
| 7 | `llms.txt` / `llms-full.txt` | nv-config-manager, dsx-exchange | Step 47 |
| 8 | Renovate for pinned images/actions | any of the 4 `renovate.json` repos (adopt a small local equivalent, not the presets chain) | Step 46/48 |
| 9 | Redfish inventory with an offline `bmc-mock` | nv-redfish `bmc-mock/`, nv-telemetry `make test-bmc-mock`, libredfish client | Step 51d |
| 10 | Telemetry observation model (Prometheus/OTLP exporters) | nv-telemetry `exporters/`, `model/`, `schema/`; fleet-intelligence-agent `otelcol/` | Steps 51b, 51c |
| 11 | NATS auth-callout + AsyncAPI contract style | dsx-exchange `auth-callout/`, `docs/` | Step 51e |
| 12 | Evaluation gate | lm-evaluation-harness `lm_eval --model local-completions` | Step 51a |

Deliberately **skipped**: fern docs sites; `CLAUDE.md` twins; Rust
`clippy/deny` configs (no Rust here); DCO/CLA bot workflows (single-operator
private repos — recorded, not adopted); `dsx-github-actions`' `@main`
self-refs; Go module layout imports (pattern only).

## Gap table for this fabric (as of 2026-10-17, before Steps 46–52)

**sparknet already has**: `Makefile ## help`; `AGENTS.md` charter per vault;
`ruff` (`E,F,I,UP`) + `format-check` (new files only) + `lint-strict`
(advisory `B,SIM,RUF,S`); `.shellcheckrc` + `shellcheck` target; pre-commit
(keys-check only); `VERSION` + deterministic CycloneDX `sbom/`;
contract tests, `render-check`/`drift-check`, `keys-check`/`shims-check`;
contract SSOT + manifest rendering.

**sparknet missing** (→ Steps 46–49): `CONTRIBUTING.md`, `SECURITY.md`,
`CODEOWNERS`, PR/issue templates, `llms.txt`; any `.github/workflows` at all
(the repo is pushed private but untested on GitHub); full-tree
`ruff format --check`; blocking widened lint; staged-format pre-commit;
commit hygiene config (conventional commits); renovate.

**goSpark has**: `cmd/` + `internal/` layout, `docs/adr/`, `make ci`
(`fmt-check vet test-race`); clean history, private remote.

**goSpark missing** (→ Steps 47, 48, 50): `AGENTS.md`/`CONTRIBUTING.md`/
`SECURITY.md`/`CODEOWNERS`/templates/`llms.txt`; workflows; `golangci-lint`
+ `.golangci.yml`; doc-comment/table-test conformance; approved-command
documentation.

## Step 47 — community surface, as landed (2026-10-17)

Adopted in **both** repositories (files describe only commands that exist and
were run):

- **sparknet**: `CONTRIBUTING.md` (setup, the gate, the atomic cross-role rule),
  `SECURITY.md` (private-report route; the fail-closed authority model it
  protects), `CODEOWNERS`, `llms.txt` (agent-facing index), `CHANGELOG.md`,
  and `.github/{PULL_REQUEST_TEMPLATE.md,ISSUE_TEMPLATE/…}`. New root entries
  registered in `tests/test_layout.py::EXPECTED_TOP_LEVEL`.
- **goSpark**: the same set, plus `AGENTS.md` (the repo had none) and
  `CHANGELOG.md`.

**CHANGELOG adopted in both**, with different starting points because their
release surfaces differ: sparknet's entries follow `VERSION` (0.1.0 today);
goSpark has **no `VERSION` file**, so its changelog opens at `Unreleased` and
states that versions begin at the first tag.

**Explicitly deferred** (recorded so the decision is not re-litigated):

- `RELEASE.md` — **both repos.** sparknet's release mechanics already exist as
  `make bundle`/`bundle-verify` + `VERSION` + the generated `sbom/`; goSpark has
  no tagged release yet. A `RELEASE.md` describing a process nobody runs is
  exactly the prose that rots (`tests/test_claims.py` exists because of that).
- `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`, `MAINTAINERS.md` — single-operator
  private repositories; there is no external contributor community to govern
  yet.
- `NOTICE` — no license change was taken (user decision), so there is no
  redistribution obligation to satisfy; provenance stays in this file.
- `llms-full.txt` — one `llms.txt` per repo is enough with no hosted docs site
  to mirror.

## Step 48 — GitHub Actions, as landed (2026-10-17)

Three workflows in each repository, every action pinned to a **full 40-hex
commit SHA** (resolved by `git ls-remote` from the tag on 2026-10-17, tag as a
trailing comment):

| Workflow | sparknet | goSpark |
|---|---|---|
| `gate.yml` | `make ci` — PRs get `CI_QUICK=1`, a push to the default branch runs the full suite | `make ci` |
| `codeql.yml` | CodeQL `python` (weekly + push/PR) | CodeQL `go` (weekly + push/PR) |
| `secret-scan.yml` | gitleaks (pinned action) | gitleaks (pinned action) |

Pinned refs: `actions/checkout@11d5960a…` (v4),
`actions/setup-python@a26af69b…` (v5), `actions/setup-go@40f1582b…` (v5),
`github/codeql-action/{init,analyze}@ce5e7eea…` (v3),
`gitleaks/gitleaks-action@ff98106e…` (v2).

Decisions and the guard:

- **The gate job calls `make ci` and does not re-list the checks** — the local
  pre-merge gate is authoritative (A5) and a second copy of its vocabulary is a
  second thing to keep true. `tests/test_ci.py` enforces this: workflows parse,
  every `uses:` is a 40-hex SHA (so `@main`/`@v4` both fail), permissions are
  least-privilege, each gate workflow runs `make ci` and never `make <check>`
  directly, and `scripts/pre-merge-gate.sh`'s step names are pinned so the
  mirror cannot silently lose a step.
- **gitleaks instead of dsx's shared `trufflehog-scan` action.** The dsx
  version is `dsx-ai-factory/dsx-github-actions/.github/actions/trufflehog-scan@…`
  — a *shared org action*, which would add a cross-repo dependency to pin and
  vend. gitleaks is a single pinned action with a local counterpart
  (`make keys-check`). The scan is content-level, which name-pattern checking
  cannot do.
- **CodeQL is the one GitHub-only job** (no local analyzer on a Spark node), so
  it is documented as an addition, not a replacement, and keeps
  `security-events: write` while every other workflow is `contents: read`
  (plus `actions: read`, which `analyze()` needs to read its own workflow run
  to classify the outcome). GitHub only scans **public** repositories on the
  Free plan, so a preflight now checks availability and, when the feature is
  absent, emits a `::notice` and skips — green and explained rather than red
  for a tool the plan cannot run, and a real analysis the moment the repo goes
  public or Code Security is enabled (user decision, 2026-10-18).
- **Deferred**: Renovate (the four dsx `renovate.json` repos) — pinned SHAs are
  refreshed by hand for now; recorded in the inventory's skip list intent, not
  silently dropped. Branch protection requiring the `gate` check is a
  `DoD: confirm: user` item (it is a repository setting, not a file) — and as
  of 2026-10-18 it is also **unavailable on this plan** (branch protection
  needs Pro or a public repo), so no check is enforced as required.
- **First real run is `DoD: confirm: user`** → **confirmed 2026-10-18**: both
  repos' `gate` and `secret-scan` pass on GitHub Actions, so the mirror is
  proven and `make ci` is authoritative. It took six fixes to get there, all of
  them assumptions this machine hid: system `python3` without `cryptography`,
  `python3 -m venv` handed a file path instead of a directory, missing
  per-vault `.env`, tests spawning bare interpreters, and codeql's
  `actions: read` (then the plan wall above). Recorded in
  `sessions/2026-10-18.md`.

## Functional verdicts (Step 51)

| Leg | Repo | Verdict | As landed |
|---|---|---|---|
| 51a eval gate | lm-evaluation-harness | **adopt as dependency** (MIT, pip) | **done** — `make eval` drives `lm_eval --model local-completions` (`tokenizer_backend=none`) against `cmd/stub-vllm`; `spark_smoke` `exact_match=1.0`. Deviation: the harness is a **pinned clone** (`.venv` at `/mnt/nvme/github/lm-evaluation-harness`), not a tracked pip dep — the repo vendors no Python dependency tree. The stub gained `/v1/completions` to be a faithful vLLM target. See `../AGENTS.md` (goSpark) `make eval`. |
| 51b fleet telemetry | fleet-intelligence-agent | **pattern comparison** | **done** — `nvidia-fleet-telemetry-comparison.md`. Adopted the `_info` gauge convention (additive; follow-up). |
| 51c observation model | nv-telemetry | **design adoption** | **done** — `nvidia-telemetry-observation-model.md`. Adopted batch-descriptor discipline (doc) + structured validation errors (follow-up). |
| 51d BMC inventory | nv-redfish + libredfish | **functional adoption w/ mock** | **done (design + fixture spec)** — `nvidia-redfish-bmc-inventory.md`. Client/projection split + cassette fixture; live BMC is `DoD: confirm: user`. |
| 51e bus contract | dsx-exchange | **design adoption** | **done** — `nvidia-dsx-exchange-bus.md`. Subject/schema contract (follow-up); auth-callout evaluated and deferred to its own step. |
| 51f the rest | all | **pattern-only** | **done** — recorded above; no further action. |

## Step 51 as landed — what changed and what is a follow-up

Legs (b)–(e) landed as design docs with explicit decision lines, which is
exactly the leg DoD ("code + tests **or** a design doc with an explicit
decision line"). Only (a) landed as code + tests. Each doc names its
follow-up and why it is deferred rather than bolted on here:

- **`_info` gauge convention** (b) — additive metric surface, own test.
- **structured validation errors** (c) — config parsing, own test.
- **bus subject/schema contract** (e) — would join `contracts/`.
- **NATS auth-callout** (e) — cross-role contract change; needs its own PLAN
  step (peer + master + `contracts/` atomically).

Live-hardware / live-LLM / real-GitHub halves of these legs remain
`DoD: confirm: user`.

## Related

- [[pair-architecture-review]] — the earlier NVIDIA reference review; same
  provenance discipline, different subject.
- `nvidia-fleet-telemetry-comparison.md` — Step 51(b).
- `nvidia-telemetry-observation-model.md` — Step 51(c).
- `nvidia-redfish-bmc-inventory.md` — Step 51(d).
- `nvidia-dsx-exchange-bus.md` — Step 51(e).
- `PLAN.md` Steps 45–52 — the arc this page feeds.
