# Contributing to sparknet

Thanks for helping. This repository is the **fabric root** of sparknet: a
two-role system (`peer-node/` implements a node, `master-node/` is the elected
signing role) joined by one contract in `contracts/` and one implementation in
`shared/`. Read `AGENTS.md` first — it explains the charter and the Memory/Plan
Protocol — and `STYLE_GUIDE.md` for how work is written here.

## Before you start

```sh
git clone --recurse-submodules https://github.com/reallife-spark/sparknet.git
cd sparknet
make submodules      # update the four pinned repositories
make devtools        # create .venv with pytest + ruff (only needed once)
make hooks           # point this clone at .githooks/ (commits run keys-check)
make help            # every fabric target, with one-line descriptions
make -C peer-node help
make -C master-node help
```

If `make devtools` is not for you, a system `pytest` and `ruff` are enough;
`make` picks `.venv/bin/python` when it exists.

## The gate

The **local pre-merge gate is authoritative**; GitHub Actions only mirror it.

```sh
make ci CI_QUICK=1   # the fast pass: keys, shims, lint, format-check,
                     # shellcheck, validate, contract-test, render-check, sbom
make ci              # the same, plus the full suite
make test-all        # contract + fabric + peer + master suites
make drift-check     # derived artifacts still match their sources
```

A change is ready when the gates you ran pass and you can say *how* they were
run. `make shellcheck` is **required**, not advisory: it provisions the pinned
binary into `.cache/tools/` when shellcheck is not on `PATH` (see the Makefile
for the pin), and fails closed if it can neither find nor fetch one. If any other
step skips, say so in the pull request rather than leaving it implicit.

Every fabric test module declares a tier: `unit` (fast, no sockets or
subprocesses), `integration` (ports, processes or filesystem writes), `contract`
(cross-role conformance), `layout` (structure, claims, hygiene) and `slow`.

```sh
make test-unit          # pytest -m unit — the tight feedback loop
make test-integration   # pytest -m integration
```

A module without a module-level `pytestmark` fails
`tests/test_tier_markers.py`, so the fast loop cannot silently lose coverage.

## The one rule that is not style

**Cross-role changes are atomic across repositories.** `contracts/` and
`shared/` live in the superproject; `peer-node`, `master-node`, `gospark` and
`goagx` are submodules. Commit role changes in their submodule first, then commit
the updated pointers with the contract/shared change in the superproject, then
run `make contract-test`. A pointer-only change leaves the other side verifying
against a shape that no longer exists; `tests/test_contracts.py` exists to fail
in exactly that case.

## Style

`STYLE_GUIDE.md` is the standing convention page (Python, shell, Makefiles,
commits, secrets, CI, docs, release). Three rules worth repeating here:

- **Resource-first**: before building a container, model or service of our
  own, look in NVIDIA's catalog (`make nv-search q="…"`); record the verdict.
- **No secrets, ever**: not in code, not in docs — not even a plausible-looking
  placeholder. Secret material lives under `.state/` (0600 files, 0700 dirs)
  and `make keys-check` enforces it. See `SECURITY.md` if one slips through.
- **Every script answers `--help`, and answering it changes nothing.** All
  scripts are run with `--help` by the suite for this reason.

## Commits

Conventional commits — `feat|fix|docs|style|refactor|perf|test|build|ci|chore`
— one logical change per commit. A Developer Certificate of Origin is **not**
required today (this is a private, single-operator repository; the dsx repos'
DCO/CLA tooling is deliberately not adopted — see
`references/nvidia-dsx-standard-practice.md`).

## Knowledge pages

The vault around the code is a wiki: distilled pages go to `concepts/`,
`entities/`, `skills/`, `references/`, `synthesis/`; provenance to
`references/`; session detail to `sessions/YYYY-MM-DD.md`; `MEMORY.md` is
standing state only and `PLAN.md` carries the plan cursor. Never scatter
copies; one page per file.

## Pull requests

Fill in the checklist in the pull request template. The short version:

1. state what changed and **how it was verified** (which gates, what output);
2. say what you could not verify and why (a `DoD: confirm: user` item is a
   first-class answer, not a failure);
3. keep the diff to one logical change.
