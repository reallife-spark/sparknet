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
# A role subvault alone is NOT a deployment. `make bundle` assembles what a node
# actually needs and can prove it runs.

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

VAULT_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
VENV_PY := $(VAULT_ROOT)/.venv/bin/python
PY := $(if $(wildcard $(VENV_PY)),$(VENV_PY),python3)
ROLE ?= peer

.PHONY: help help-role layout validate test test-all test-peer test-master \
        contract-test lint devtools chroma-dev chroma-init chroma-inspect \
        chroma-index chroma-query env-init wiki-sync wiki-verify \
        wiki-preflight bundle bundle-verify status-plan clean dist \
        keys-check shims-check hooks

help: ## Show this help
	@echo "sparknet — fabric root"
	@echo
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Role subvaults have their own targets:"
	@echo "    make -C peer-node help"
	@echo "    make -C master-node help"

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
	  "├── scripts/             fabric-level tooling" \
	  "├── tests/               fabric + vendored-skill tests" \
	  "└── .opencode/skills/    vendored wiki suite (33 skills: 32 vendored + 1 local)"

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

lint: ## Lint everything that is linted
	@$(PY) -m ruff check shared scripts tests
	@$(PY) -m ruff check peer-node/services peer-node/tests
	@$(PY) -m ruff check master-node/services master-node/tests

devtools: ## Create .venv with cryptography, pytest and ruff (opt-in)
	@if [ ! -x "$(VENV_PY)" ]; then python3 -m venv "$(VENV_PY)"; fi
	@"$(VENV_PY)" -m pip install --quiet --upgrade pip
	@"$(VENV_PY)" -m pip install --quiet -r "$(VAULT_ROOT)/requirements.txt"
	@"$(VENV_PY)" -m pip install --quiet -r "$(VAULT_ROOT)/requirements-dev.txt"
	@"$(VENV_PY)" -m pytest --version && "$(VENV_PY)" -m ruff --version
	@echo "Dev tools ready."

# --- optional local Chroma index (scripts/sparknet-chroma.py) ------------------

CHROMA_SCOPE ?= peer

chroma-dev: ## Install the OPTIONAL chromadb package (sparknet[chroma]); allow-list untouched
	@if [ ! -x "$(VENV_PY)" ]; then python3 -m venv "$(VENV_PY)"; fi
	@"$(VENV_PY)" -m pip install --quiet --upgrade pip
	@"$(VENV_PY)" -m pip install --quiet 'chromadb>=0.5'
	@echo "chromadb ready. Run: make chroma-init / chroma-index / chroma-query CHROMA_SCOPE=fabric"

chroma-init: ## Create the CHROMA_SCOPE collection (peer|master|fabric) in .state/chroma/
	@$(PY) scripts/sparknet-chroma.py "$(CHROMA_SCOPE)" init

chroma-inspect: ## Show what chroma-index WOULD index, without needing chromadb
	@$(PY) scripts/sparknet-chroma.py "$(CHROMA_SCOPE)" inspect

chroma-index: ## Build/upsert the CHROMA_SCOPE index (requires chroma-dev)
	@$(PY) scripts/sparknet-chroma.py "$(CHROMA_SCOPE)" index

chroma-query: ## Search the CHROMA_SCOPE index: make chroma-query CHROMA_SCOPE=fabric QUERY="..."
	@$(PY) scripts/sparknet-chroma.py "$(CHROMA_SCOPE)" query "$(QUERY)"

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

# --- standalone node bundles ---------------------------------------------------

bundle: ## Build a standalone bundle for ROLE=peer|master into dist/
	@./scripts/sparknet-bundle.sh "$(ROLE)"

bundle-verify: ## Extract the newest bundle and prove it runs standalone
	@./scripts/sparknet-bundle.sh --verify \
		$$(ls -t "$(VAULT_ROOT)"/dist/sparknet-$(ROLE)-*.tar.gz 2>/dev/null | head -1)

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