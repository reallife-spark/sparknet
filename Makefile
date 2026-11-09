# sparknet — fabric-level entry points.
#
# This repository is three things at once:
#
#   contracts/ + shared/   the cross-role contract and its single implementation

#   peer-node/             a working node — the only role that is implemented
#   master-node/           the elected signing role — built (Steps 15–18); signer deployed on agx64, election proven live 2026-10-07; Steps 19+ remain as roadmapped roles.
#   .opencode/skills/      the wiki skill suite, vendored so a node needs no
#                          global skill farm
#
# So this Makefile is a router, not an implementation. Anything that touches a
# role lives in that role's Makefile; `make help-role` lists those.
#
# A role submodule alone is NOT a deployment. `make bundle` assembles what a node
# actually needs and can prove it runs.

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

VAULT_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
VENV_PY := $(VAULT_ROOT)/.venv/bin/python
PY := $(if $(wildcard $(VENV_PY)),$(VENV_PY),python3)
ROLE ?= peer
PROJECT ?=
TASK ?=
RUN ?=
TITLE ?=
OUT ?=
BUNDLE ?=
INBOX ?=

# format-check is whole-tree since Step 49: the fabric is pinned to one ruff
# and the sweep removed the pre-existing differences, so `ruff format --check .`
# is the gate, not a subset. ruff itself excludes .venv/.state/references and
# the vendored .opencode/skills tree (see pyproject.toml).
SCOPE ?= fabric

.PHONY: help help-role layout tui validate test test-all test-peer test-master \
        contract-test lint lint-strict format-check shellcheck test-report ci \
        shellcheck-install \
        container-test \
        render render-check sbom sbom-check nv-search drift-check context-pack context-check governance-check \
        goagx-publish goagx-drift-check \
        devtools webui-console model-catalog-check model-pull model-verify model-bench model-runtime-status model-runtime-start model-runtime-stop model-runtime-reap model-survey model-update-status model-set-candidate model-promote model-rollback \
        vector-dev vector-init vector-inspect \
        vector-index vector-stamp vector-query vector-parity kv-export reflex-eval reflex-live-check reflex-live-query \
        reflex-plan-eval verify-plans env-init wiki-sync wiki-verify \
        wiki-preflight bundle bundle-verify status-plan clean dist submodules \
        role-skills role-skills-check keys-check shims-check hooks self-improve package-install

submodules: ## Initialize/update all four pinned repositories
	@git submodule update --init --recursive
	@git submodule status

help: ## Show this help
	@echo "sparknet — fabric root"
	@echo
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Role subvaults have their own targets:"
	@echo "    make -C peer-node help"
	@echo "    make -C master-node help"

tui: ## Launch opencode with KDE Connect notifications (fabric-root sessions only)
	OPENCODE_CONFIG=$(VAULT_ROOT)/scripts/plugins/kde-notif.opencode.json opencode

help-role: ## What each role is, and whether it runs
	@printf '  %-14s %s\n' "peer-node"   "IMPLEMENTED — guard, anchor, dispatch, wiki vault"
	@printf '  %-14s %s\n' "master-node" "BUILT — runs the peer's services by path; plans/MASTER_BUILD_PLAN.md"
	@printf '  %-14s %s\n' "contracts/"  "the overlay, capability, identity, port and guard contracts"
	@printf '  %-14s %s\n' "shared/"     "the one canonical signed-authorization implementation"

layout: ## Show the repository layout
	@printf '%s\n' \
	  "sparknet/" \
	  "├── contracts/          cross-role contract (single source of truth)" \
	  "├── shared/              sparknet-authz.py — signed canonical form" \
	  "├── peer-node/           the working node role        [IMPLEMENTED]" \
	  "├── master-node/         the elected signing role    [BUILT]" \
	  "├── scripts/             fabric-level tooling (incl. the sparknet CLI)" \
	  "├── webui/               read-only Sparknet console, Caddyfile and Open WebUI patch" \
	  "├── tests/               fabric + vendored-skill tests" \
	  "├── sbom/                generated CycloneDX SBOM" \
	  "└── .opencode/skills/    vendored wiki suite (33 skills: 32 vendored + 1 local)"

share-rehearsal: ## Three-node loopback share rehearsal (offer, payload, 4203 queue, signed lift)
	@scripts/sparknet-share-rehearsal.sh $(if $(WORK),--work "$(WORK)")

recovery-rehearse: ## Snapshot a local role tree, delete one file, restore and verify
	@set -e; work="$${WORK:-/tmp/opencode/phase9-rehearsal}"; rm -rf "$$work"; mkdir -p "$$work"; scripts/sparknet-recovery.py snapshot --root peer-node --out "$$work/peer.tar.gz"; scripts/sparknet-recovery.py rehearse "$$work/peer.tar.gz" --work "$$work/restore";

validate: ## Validate every role that has an implementation
	@$(MAKE) --no-print-directory -C peer-node validate
	@$(MAKE) --no-print-directory -C master-node validate

test: test-all ## Alias for test-all

# Every suite in the repo, in the order a failure would matter: the contract
# first (both roles depend on it), then the peer implementation, then the
# master's parity and spec boundary, then the vendored skills.
test-all: ## Run every suite in the repository
	@echo "=== contract ==="
	@$(PY) -m pytest tests/test_contracts.py -q
	@echo
	@echo "=== memory ==="
	@$(MAKE) --no-print-directory memory-check
	@echo
	@echo "=== fabric + vendored wiki skills ==="
	@$(PY) -m pytest tests/ -q
	@echo
	@echo "=== peer-node ==="
	@$(MAKE) --no-print-directory -C peer-node test
	@echo
	@echo "=== master-node (parity + spec) ==="
	@$(MAKE) --no-print-directory -C master-node test

test-peer: ## Run only the peer suite
	@$(MAKE) --no-print-directory -C peer-node test

test-master: ## Run only the master's parity + spec suite
	@$(MAKE) --no-print-directory -C master-node test

memory-check: ## Prove the memory gateway, Go store, delegate broker and project lifecycle
	@$(PY) -m pytest tests/test_memory_gateway.py tests/test_memory_mcp.py tests/test_memory_bundle.py tests/test_memory_index.py tests/test_project_script.py -q
	@if [ -d gospark ]; then \
		$(MAKE) --no-print-directory -C gospark test ./internal/memory ./internal/delegates ./cmd/sparknet-memory; \
	else \
		echo "memory-check: gospark checkout absent — gateway contract only"; \
	fi

project-new: ## Create a signed project: PROJECT=slug ROLE=peer|master TITLE="..."
	@$(PY) scripts/sparknet-project.py --vault "$(VAULT_ROOT)/$(ROLE)-node" new "$(PROJECT)" --title "$(TITLE)"

project-list: ## List projects: ROLE=peer|master
	@$(PY) scripts/sparknet-project.py --vault "$(VAULT_ROOT)/$(ROLE)-node" list

project-run: ## Run a project delegate: PROJECT=slug TASK="..."
	@$(PY) scripts/sparknet-project.py --vault "$(VAULT_ROOT)/$(ROLE)-node" run "$(PROJECT)" --task "$(TASK)"

project-status: ## Show project runs: PROJECT=slug
	@$(PY) scripts/sparknet-project.py --vault "$(VAULT_ROOT)/$(ROLE)-node" status "$(PROJECT)"

project-report: ## File a signed report: PROJECT=slug RUN=<run-id> TITLE="..."
	@$(PY) scripts/sparknet-project.py --vault "$(VAULT_ROOT)/$(ROLE)-node" report "$(PROJECT)" --run-id "$(RUN)" --title "$(TITLE)"

memory-index: ## Index vault knowledge pages into semantic memory: ROLE=peer
	@$(PY) scripts/sparknet-memory-index.py --vault "$(VAULT_ROOT)/$(ROLE)-node"

memory-export: ## Export a vault memory bundle: ROLE=peer OUT=path
	@$(PY) scripts/sparknet-memory-bundle.py export --vault "$(VAULT_ROOT)/$(ROLE)-node" --out "$(OUT)"

memory-bundle-validate: ## Validate a memory bundle: BUNDLE=path
	@$(PY) scripts/sparknet-memory-bundle.py validate "$(BUNDLE)"

memory-bundle-stage: ## Stage a bundle for share review: BUNDLE=path INBOX=dir
	@$(PY) scripts/sparknet-memory-bundle.py stage --bundle "$(BUNDLE)" --inbox "$(INBOX)"

memory-import: ## Import an accepted bundle: ROLE=peer BUNDLE=path
	@$(PY) scripts/sparknet-memory-bundle.py import --vault "$(VAULT_ROOT)/$(ROLE)-node" --bundle "$(BUNDLE)"

# Opt-in, minutes-long, hardware-free: run the election arc and the CPU-only node
# graph inside the built node image. Not part of `make ci`; skips cleanly when
# docker or the image is absent.
container-test: ## Run the containerised election + CPU-node smoke (needs docker + image)
	@SPARKNET_CONTAINER_TESTS=1 $(PY) -m pytest tests/test_election_container.py tests/test_cpu_node_smoke.py -q

contract-test: ## Prove the peer role still matches contracts/
	@$(MAKE) --no-print-directory -C peer-node guard-contract

# --- provenance gates ---------------------------------------------------------

keys-check: ## No tracked key material; .state/ keys are 0600
	@./scripts/sparknet-keys-check.sh

shims-check: ## Every legacy name in peer-node/ and master-node/ is still a symlink
	@$(MAKE) --no-print-directory -C peer-node shims-check
	@$(MAKE) --no-print-directory -C master-node shims-check

hooks: ## Point this clone at .githooks/ so every commit runs keys-check
	@git config core.hooksPath .githooks
	@echo "core.hooksPath = .githooks"

lint: ## Lint the whole fabric (ruff E,F,I,UP,B,SIM,RUF,S — see pyproject.toml)
	@"$(PY)" -m ruff check . --extend-exclude peer-node/.opencode --extend-exclude master-node/.opencode

# The widened rule set (flake8-bugbear B, flake8-simplify SIM, Ruff-specific
# RUF, bandit S) became the blocking gate in Step 49, configured in
# pyproject.toml. `lint-strict` is kept as an alias so older notes keep working.
lint-strict: lint ## Deprecated alias for `lint` (the widened set is now the gate)

format-check: ## ruff format --check across the whole fabric (whole-tree since Step 49)
	@"$(PY)" -m ruff format --check . --extend-exclude peer-node/.opencode --extend-exclude master-node/.opencode

# Pinned like the SHA-pinned GitHub Actions: the gate must not silently change
# what it enforces when a new shellcheck release starts reporting something new.
# A version bump is a reviewed commit, not an ambient upgrade.
#
# The pin is *enforced*, not merely used-as-a-default: a shellcheck already on
# PATH is accepted ONLY if its version matches. A runner image shipping 0.9.0
# must not turn the gate into 0.9.0's opinion — that is exactly how a green
# local run and a red CI run happened once already.
SHELLCHECK_VERSION ?= 0.11.0
SHELLCHECK_CACHE ?= $(VAULT_ROOT)/.cache/tools

# Resolve the pinned shellcheck, provisioning it if needed. Sets `sc` via the
# caller's shell. Shared by `shellcheck` and `shellcheck-install` so the two can
# never disagree about what "the pinned binary" means.
define shellcheck-resolve
case "$$(uname -m)" in \
	x86_64|amd64) _sca=x86_64 ;; \
	aarch64|arm64) _sca=aarch64 ;; \
	*) echo "shellcheck: no pinned build for $$(uname -m); install shellcheck $(SHELLCHECK_VERSION) on PATH" >&2; exit 1 ;; \
esac; \
_scd="$(SHELLCHECK_CACHE)/shellcheck-$(SHELLCHECK_VERSION)/$$_sca"; \
_scb="$$_scd/shellcheck"; \
if [ ! -x "$$_scb" ]; then \
	_scr="$$(command -v shellcheck 2>/dev/null || true)"; \
	if [ -n "$$_scr" ] && [ "$$("$$_scr" --version 2>/dev/null | awk 'NR==2 {print $$2}')" = "$(SHELLCHECK_VERSION)" ]; then \
		_scb="$$_scr"; \
	else \
		_scu="https://github.com/koalaman/shellcheck/releases/download/v$(SHELLCHECK_VERSION)/shellcheck-v$(SHELLCHECK_VERSION).linux.$$_sca.tar.xz"; \
		echo "shellcheck: provisioning pinned v$(SHELLCHECK_VERSION) ($$_sca) into $$_scd" >&2; \
		mkdir -p "$$_scd"; \
		if ! curl -fsSL "$$_scu" | tar -xJ -C "$$_scd" --strip-components=1; then \
			echo "shellcheck: could not download $$_scu — this gate is REQUIRED (see CONTRIBUTING.md); install shellcheck $(SHELLCHECK_VERSION) on PATH to run it offline" >&2; \
			exit 1; \
		fi; \
	fi; \
fi; \
sc="$$_scb"
endef

shellcheck: ## shellcheck tracked scripts (provisions the pinned binary, then runs it)
	@set -e; \
	$(shellcheck-resolve); \
	echo "shellcheck: $$("$$sc" --version | awk 'NR==2 {print $$2}') ($$sc)"; \
	files="$$( { git -C "$(VAULT_ROOT)" ls-files '*.sh' | grep -v '/\.opencode/skills/' || true; \
		if [ -f "$(VAULT_ROOT)/scripts/sparknet" ]; then echo scripts/sparknet; fi; } | sort -u )"; \
	if [ -z "$$files" ]; then echo "shellcheck: no tracked shell scripts"; exit 0; fi; \
	printf '%s\n' "$$files" | xargs "$$sc"

test-report: ## Write JUnit XML + summary.json (SCOPE=fabric|peer|master|all)
	@./scripts/sparknet-test-report.sh "$(SCOPE)"

shellcheck-install: ## Provision the pinned shellcheck binary without running the gate
	@set -e; \
	$(shellcheck-resolve); \
	echo "shellcheck-install: $$sc"

ci: ## Run the local pre-merge gate (CI_QUICK=1 to skip the full suite)
	@./scripts/pre-merge-gate.sh $(if $(filter 1,$(CI_QUICK)),--quick,)

context-pack: ## Regenerate CONTEXT.md for the fabric and both roles
	@$(PY) scripts/sparknet-context-pack.py --root "$(VAULT_ROOT)" --role fabric
	@$(PY) scripts/sparknet-context-pack.py --root "$(VAULT_ROOT)/peer-node" --role peer
	@$(PY) scripts/sparknet-context-pack.py --root "$(VAULT_ROOT)/master-node" --role master

governance-check: ## Enforce the five-file shape, budgets and template parity
	@$(PY) scripts/sparknet-governance-check.py

phase8-sync: ## Seed/refresh the 416-file Phase 8 inventory without losing verdicts
	@$(PY) scripts/sparknet-phase8-inventory.py sync

phase8-check: ## Check the Phase 8 inventory covers every file and is well formed
	@$(PY) scripts/sparknet-phase8-inventory.py check

phase8-closure-check: ## Fail unless every Phase 8 row has a terminal verdict and evidence
	@$(PY) scripts/sparknet-phase8-inventory.py closure

context-check: ## Fail if any CONTEXT.md is stale vs its source pages
	@$(PY) scripts/sparknet-context-pack.py --root "$(VAULT_ROOT)" --role fabric --check
	@$(PY) scripts/sparknet-context-pack.py --root "$(VAULT_ROOT)/peer-node" --role peer --check
	@$(PY) scripts/sparknet-context-pack.py --root "$(VAULT_ROOT)/master-node" --role master --check

render: ## Regenerate contracts/manifest.json from the contract SSOT
	@"$(PY)" scripts/sparknet-render.py

render-check: ## Fail if contracts/manifest.json is stale vs contracts/*.json
	@"$(PY)" scripts/sparknet-render.py --check

sbom: ## Regenerate sbom/sparknet.cdx.json (CycloneDX) from VERSION/deps/skills
	@"$(PY)" scripts/sparknet-sbom.py

sbom-check: ## Fail if the SBOM is stale vs VERSION, requirements.txt or the skills
	@"$(PY)" scripts/sparknet-sbom.py --check

# Resource-first (STYLE_GUIDE §1): check NVIDIA's catalog before building our
# own container or model. `q` is a substring of a model id; no `q` prints the
# browser surfaces instead. Endpoints + provenance:
# references/nvidia-build-catalog.md.
# --- model store and on-demand runtimes ---------------------------------------

MODEL_NODE ?= agx64
MODEL_ROLE ?= peer
PROFILE ?= teacher

model-catalog-check: ## Validate the model catalog and role placement
	@$(PY) scripts/sparknet-model-pull.py --check

model-pull: ## Pull eligible models for MODEL_NODE (optional MODEL=id)
	@$(PY) scripts/sparknet-model-pull.py --node "$(MODEL_NODE)" $(if $(MODEL),--model "$(MODEL)",)

model-verify: ## Verify the pinned model manifests for MODEL_NODE
	@$(PY) scripts/sparknet-model-pull.py --node "$(MODEL_NODE)" --verify

model-bench: ## Benchmark MODEL_ROLE candidates (BENCH_ARGS="--dry-run" or --candidate <id>)
	@$(PY) scripts/sparknet-model-bench.py --role "$(MODEL_ROLE)" $(BENCH_ARGS)

model-runtime-status: ## Show model runtime leases (MODEL_ROLE=peer|master)
	@$(PY) scripts/sparknet-model-runtime.py status --role "$(MODEL_ROLE)" $(if $(PROBE),--probe,)

model-runtime-start: ## Start a model runtime lease (PROFILE=teacher|student; MODEL_ROLE=peer|master)
	@$(PY) scripts/sparknet-model-runtime.py start "$(PROFILE)" --role "$(MODEL_ROLE)" $(if $(REPLACE),--replace,)

model-runtime-stop: ## Stop a model runtime lease (PROFILE=teacher|student; MODEL_ROLE=peer|master)
	@$(PY) scripts/sparknet-model-runtime.py stop "$(PROFILE)" --role "$(MODEL_ROLE)"

model-survey: ## Inventory/plan/run the open-weight model survey (SURVEY_CMD=inventory|plan|run, SURVEY_NODE=agx64|agx32)
	@$(PY) scripts/sparknet-model-survey.py "$(or $(SURVEY_CMD),inventory)" --node "$(or $(SURVEY_NODE),agx32)" $(if $(SURVEY_INCLUDE_UNTRACKED),--include-untracked) $(if $(SURVEY_DRY_RUN),--dry-run) $(if $(SURVEY_MODEL),--model "$(SURVEY_MODEL)") $(if $(SURVEY_OUT),--out "$(SURVEY_OUT)")

model-update-status: ## Show the active/candidate/previous model state (MODEL_NODE=agx64|agx32)
	@$(PY) scripts/sparknet-model-update.py status --node "$(or $(MODEL_NODE),agx32)" $(if $(MODEL_STORE),--store "$(MODEL_STORE)")

model-set-candidate: ## Record a verified manifest as a candidate (MODEL_NODE, MODEL, MANIFEST)
	@test -n "$(MODEL)" -a -n "$(MANIFEST)" || { echo "MODEL and MANIFEST required" >&2; exit 2; }
	@$(PY) scripts/sparknet-model-update.py set-candidate --node "$(or $(MODEL_NODE),agx32)" --model "$(MODEL)" --manifest "$(MANIFEST)" $(if $(MODEL_STORE),--store "$(MODEL_STORE)")

model-promote: ## Promote a candidate after a passing benchmark (MODEL_NODE, MODEL, BENCH, OPERATOR)
	@test -n "$(MODEL)" -a -n "$(BENCH)" -a -n "$(OPERATOR)" || { echo "MODEL, BENCH and OPERATOR required" >&2; exit 2; }
	@$(PY) scripts/sparknet-model-update.py promote --node "$(or $(MODEL_NODE),agx32)" --model "$(MODEL)" --bench "$(BENCH)" --operator "$(OPERATOR)" $(if $(MODEL_STORE),--store "$(MODEL_STORE)")

model-rollback: ## Roll back to the previous model (MODEL_NODE, OPERATOR)
	@test -n "$(OPERATOR)" || { echo "OPERATOR required" >&2; exit 2; }
	@$(PY) scripts/sparknet-model-update.py rollback --node "$(or $(MODEL_NODE),agx32)" --operator "$(OPERATOR)" $(if $(MODEL_STORE),--store "$(MODEL_STORE)")

model-runtime-reap: ## Stop expired model leases once (MODEL_ROLE=peer|master)
	@$(PY) scripts/sparknet-model-runtime.py reap --role "$(MODEL_ROLE)" --interval 0

webui-console: ## Run the read-only WebUI console (MODEL_ROLE=peer|master)
	@$(PY) scripts/sparknet-console.py --role "$(MODEL_ROLE)"

nv-search: ## Look in NVIDIA's catalog first (q="llama"; details: scripts/sparknet-nv-search.sh --help)
	@if [ -n "$(q)" ]; then \
		scripts/sparknet-nv-search.sh models "$(q)"; \
	else \
		scripts/sparknet-nv-search.sh discover; \
	fi

# The umbrella drift gate for everything *derived*: the rendered contract
# manifest, the generated SBOM, the vendored wiki suite, cross-role contract
# parity, and the published goagx distribution. Each of these compares a
# generated or copied artifact against the source it claims to come from;
# running them together is what "nothing has silently drifted" means.
#
# The goagx leg compares against a PRIVATE remote, so it self-skips with a
# notice when that remote cannot be fetched (the codeql pattern) — it is a
# convenience drift detector, not a required offline gate. Run
# `make goagx-drift-check` alone for the strict, authenticated form.
drift-check: ## Fail if derived artifacts drifted (manifest, SBOM, skills, contracts, goagx)
	@echo "drift-check: operating context"
	@$(MAKE) --no-print-directory context-check
	@echo "drift-check: governance set"
	@$(MAKE) --no-print-directory governance-check
	@echo "drift-check: contract manifest"
	@$(MAKE) --no-print-directory render-check
	@echo "drift-check: software bill of materials"
	@$(MAKE) --no-print-directory sbom-check
	@echo "drift-check: vendored wiki skills"
	@$(MAKE) --no-print-directory wiki-verify
	@echo "drift-check: role-local skill catalogs"
	@$(MAKE) --no-print-directory role-skills-check
	@echo "drift-check: cross-role contract parity"
	@$(MAKE) --no-print-directory contract-test
	@echo "drift-check: published goagx distribution"
	@$(MAKE) --no-print-directory goagx-drift-check
	@echo "drift-check: all derived artifacts are in sync"

# The goagx distribution (reallife-spark/goagx, generated — fabric PLAN Step
# 62). Publish is a full-tree release commit; verify also ships inside the
# published repo, where its generated workflow re-runs it on every push.
goagx-publish: ## Push a signed release commit of the goagx distribution
	@test -f "$(BUNDLE_SIGN_KEY)" && test -f "$(BUNDLE_PUBKEY)" || { echo "BUNDLE_SIGN_KEY and BUNDLE_PUBKEY are required" >&2; exit 1; }
	@scripts/sparknet-goagx-publish.sh --push --sign-key "$(BUNDLE_SIGN_KEY)" --pubkey "$(BUNDLE_PUBKEY)" $(if $(FROM_GIT),--from-git $(FROM_GIT),)

goagx-drift-check: ## Fail if reallife-spark/goagx drifted from this tree (self-skips offline)
	@scripts/sparknet-goagx-publish.sh --drift

devtools: ## Create .venv with cryptography, pytest and ruff (opt-in)
	@# venv's argument is the DIRECTORY to create, not the interpreter inside it.
	@# Passing $(VENV_PY) here (as this did until the first bare-clone CI run)
	@# built a venv inside .venv/bin/python/, after which every target that
	@# execs $(VENV_PY) failed with "Is a directory".
	@if [ ! -x "$(VENV_PY)" ]; then python3 -m venv "$(VAULT_ROOT)/.venv"; fi
	@"$(VENV_PY)" -m pip install --quiet --upgrade pip
	@"$(VENV_PY)" -m pip install --quiet -r "$(VAULT_ROOT)/requirements.txt"
	@"$(VENV_PY)" -m pip install --quiet -r "$(VAULT_ROOT)/requirements-dev.txt"
	@"$(VENV_PY)" -m pytest --version && "$(VENV_PY)" -m ruff --version
	@echo "Dev tools ready."

# --- optional local Qdrant index (scripts/sparknet-vector.py) ------------------

VECTOR_SCOPE ?= $(if $(CHROMA_SCOPE),$(CHROMA_SCOPE),peer)

vector-dev: ## Install the OPTIONAL Qdrant client + FastEmbed; runtime allow-list untouched
	@if [ ! -x "$(VENV_PY)" ]; then python3 -m venv "$(VAULT_ROOT)/.venv"; fi
	@"$(VENV_PY)" -m pip install --quiet --upgrade pip
	@./scripts/sparknet-safe-build.sh --pip -- "$(VENV_PY)" -m pip install 'qdrant-client[fastembed]>=1.12,<2'
	@echo "qdrant-client ready. Run: make vector-init / vector-index / vector-query VECTOR_SCOPE=fabric"

vector-init: ## Create the VECTOR_SCOPE collection (peer|master|fabric|shared)
	@$(PY) scripts/sparknet-vector.py "$(VECTOR_SCOPE)" init

vector-inspect: ## Show what vector-index WOULD index, without needing Qdrant
	@$(PY) scripts/sparknet-vector.py "$(VECTOR_SCOPE)" inspect

vector-index: ## Build/upsert the VECTOR_SCOPE index (all-MiniLM-L6-v2 by default)
	@$(PY) scripts/sparknet-vector.py "$(VECTOR_SCOPE)" index

vector-stamp: ## Compare the VECTOR_SCOPE index stamp with this build (exit 3 = mismatch)
	@$(PY) scripts/sparknet-vector.py "$(VECTOR_SCOPE)" stamp

vector-query: ## Search the VECTOR_SCOPE index: make vector-query VECTOR_SCOPE=fabric QUERY="..."
	@$(PY) scripts/sparknet-vector.py "$(VECTOR_SCOPE)" query "$(QUERY)"

vector-parity: ## Run the Qdrant function-parity suites (skips if the optional package is absent)
	@$(PY) -m pytest tests/test_vector.py tests/test_vector_corpus.py tests/test_reflex_rag.py tests/test_kv_export.py -q

KV_MODEL ?=
kv-export: ## Package a safetensors KV export: make kv-export KV_FILE=... KV_MODEL=...
	@test -n "$(KV_FILE)" || { echo "KV_FILE required" >&2; exit 2; }
	@test -n "$(KV_MODEL)" || { echo "KV_MODEL required" >&2; exit 2; }
	@$(PY) scripts/sparknet-kv-export.py --from-file "$(KV_FILE)" --model "$(KV_MODEL)" --out "$${KV_OUT:-.state/kv-spool}"

# Deprecated aliases retained for one migration window.
chroma-dev chroma-init chroma-inspect chroma-index chroma-stamp chroma-query:
	@echo "sparknet: the Chroma targets are deprecated; use make vector-* (Qdrant is the store)" >&2
	@$(MAKE) --no-print-directory $(patsubst chroma-%,vector-%,$@) VECTOR_SCOPE="$(VECTOR_SCOPE)"

REFLEX_SCOPE ?= fabric
REFLEX_MODE ?= shadow
REFLEX_TOP_K ?= 5
PLANS ?= -

reflex-eval: ## Offline RAG reflex pilot (fabric only): precision@5, recall, abstain, p95, cost
	@$(PY) scripts/sparknet-reflex-eval.py --scope "$(REFLEX_SCOPE)" --mode "$(REFLEX_MODE)" \
		$(if $(REFLEX_JSON),--json "$(REFLEX_JSON)",)

reflex-live-check: ## Live pilot preflight: broker health (governance+key only for egress)
	@$(PY) scripts/sparknet-reflex-eval.py --check

reflex-live-query: ## One broker-backed fabric query (operator-gated): QUERY="..."
	@REFLEX_LIVE=1 $(PY) scripts/sparknet-reflex-eval.py --query "$(QUERY)" --top-k "$(REFLEX_TOP_K)"

reflex-plan-eval: ## Live plan-selection calibration (local LLM advisory; top-1, coverage, ECE)
	@$(PY) scripts/sparknet-reflex-plan-eval.py --live $(if $(REFLEX_JSON),--json "$(REFLEX_JSON)",)

verify-plans: ## Rank candidate plans from JSON (advisory only; no authority)
	@$(PY) scripts/sparknet-verify-plans.py --input "$(PLANS)"

env-init: ## Write every vault's .env + wiki dirs from its .env.example
	@./scripts/sparknet-env-init.sh "$(VAULT_ROOT)"
	@./scripts/sparknet-env-init.sh "$(VAULT_ROOT)/peer-node"
	@./scripts/sparknet-env-init.sh "$(VAULT_ROOT)/master-node"

# --- vendored wiki skill suite -------------------------------------------------

wiki-sync: ## Re-vendor .opencode/skills from the farm, applying local patches
	@$(PY) scripts/sync-wiki-skills.py --apply
	@echo
	@$(MAKE) --no-print-directory wiki-verify

wiki-verify: ## Fail if the vendored suite drifted from its pinned source
	@$(PY) scripts/sync-wiki-skills.py --check

wiki-preflight: ## Prove the vendored skills resolve the vault you are standing in
	@source "$(VAULT_ROOT)/scripts/sparknet-wiki-env.sh"

# --- role-local skill catalogs -------------------------------------------------
role-skills: ## Rebuild peer-node and master-node role-local skill catalogs
	@$(PY) scripts/sync-role-skills.py --apply

role-skills-check: ## Verify role-local catalogs, licenses and removal list
	@$(PY) scripts/sync-role-skills.py --check

# --- standalone node bundles ---------------------------------------------------

BUNDLE_SIGN_KEY ?= $(HOME)/.local/state/sparknet/master-node/keys/operational.ed25519
BUNDLE_PUBKEY ?= $(HOME)/.local/state/sparknet/master-node/keys/operational.pub.b64

bundle: ## Build a standalone bundle for ROLE=peer|master into dist/
	@./scripts/sparknet-bundle.sh $(if $(BUNDLE_SIGN_KEY),--sign-key "$(BUNDLE_SIGN_KEY)") "$(ROLE)"

bundle-verify: ## Verify the newest bundle's signature and prove it runs standalone
	@test -n "$(BUNDLE_PUBKEY)" && test -f "$(BUNDLE_PUBKEY)" || { echo "BUNDLE_PUBKEY is required" >&2; exit 1; }
	@./scripts/sparknet-bundle.sh --verify \
		$$(ls -t "$(VAULT_ROOT)"/dist/sparknet-$(ROLE)-*.tar.gz 2>/dev/null | head -1) \
		--pubkey "$(BUNDLE_PUBKEY)"

self-improve: ## Run a bounded worktree benchmark candidate (ARGS=...)
	@$(PY) scripts/sparknet-self-improve.py $(ARGS)

gitflow-check: ## Check SOURCE -> TARGET against the GitFlow policy
	@$(PY) scripts/sparknet-gitflow.py "$(SOURCE)" "$(TARGET)"

package-install: ## Verify and install a signed package (ARGS=...)
	@$(PY) scripts/sparknet-package.py install $(ARGS)

status-plan: ## Show each role's plan cursor
	@printf 'peer-node:\n'
	@grep -m1 '^current:' "$(VAULT_ROOT)/peer-node/PLAN.md" || echo "  (no PLAN.md cursor)"
	@printf 'master-node:\n'
	@grep -m1 '^current:' "$(VAULT_ROOT)/master-node/plans/MASTER_BUILD_PLAN.md" \
	  || echo "  (no build plan cursor)"

clean: ## Remove caches and dist artifacts
	@find "$(VAULT_ROOT)" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf "$(VAULT_ROOT)/.pytest_cache" "$(VAULT_ROOT)/.ruff_cache" "$(VAULT_ROOT)/dist"
	@$(MAKE) --no-print-directory -C peer-node clean
	@$(MAKE) --no-print-directory -C master-node clean
	@echo "Cleaned caches and dist/ (left .venv, .state and .cache alone)."