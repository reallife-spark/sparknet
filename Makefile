# sparknet developer entry points.
#
# The vault is the package. Run everything through `make` so the pytest
# interpreter and optional tooling are picked up consistently.

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help
VAULT_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

# Prefer the optional .venv when it exists, otherwise the system interpreter.
VENV_PY := $(VAULT_ROOT)/.venv/bin/python
PY := $(if $(wildcard $(VENV_PY)),$(VENV_PY),python3)

.PHONY: help validate test lint devtools provision dist install-units install-config \
        keys wg-render authz-verify anchor guard-status clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

validate: ## Env contract + manifest checks
	@./scripts/sparknet-validate.sh

test: ## Run the pytest suite
	@$(PY) -m pytest

devtools: ## Create .venv with cryptography + pytest + ruff (opt-in)
	@if [ -x "$(VENV_PY)" ]; then \
		echo "$(VENV_PY) already exists; refreshing deps"; \
	else \
		echo "Creating $(VAULT_ROOT)/.venv"; \
		python3 -m venv "$(VAULT_ROOT)/.venv"; \
	fi
	@"$(VENV_PY)" -m pip install --quiet --upgrade pip
	@# This vault is not a distributable package, so install dependencies by
	@# name instead of `pip install -e .` (which would need a build backend and
	@# would try to package the vault itself).
	@"$(VENV_PY)" -m pip install --quiet -r "$(VAULT_ROOT)/requirements.txt"
	@"$(VENV_PY)" -m pip install --quiet -r "$(VAULT_ROOT)/requirements-dev.txt"
	@"$(VENV_PY)" -m pytest --version
	@"$(VENV_PY)" -m ruff --version
	@echo "Dev tools ready. make lint and make test will now use .venv."

lint: ## Ruff if available; otherwise explains how to get it
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check . && ruff format --check . ; \
	elif [ -x "$(VAULT_ROOT)/.venv/bin/ruff" ]; then \
		"$(VAULT_ROOT)/.venv/bin/ruff" check . && "$(VAULT_ROOT)/.venv/bin/ruff" format --check . ; \
	else \
		echo "ruff not installed — skipping lint."; \
		echo "Run 'make devtools' to install it into .venv."; \
		echo "(ruff is optional; the suite runs without it.)"; \
	fi

provision: ## Identity capture, then validate
	@./scripts/sparknet-identity-capture.sh
	@./scripts/sparknet-validate.sh

# Archive the committed tree. A dirty working tree is reported, because
# `git archive` reads a commit and would silently omit uncommitted work.
# Override with: make dist DIST_TREE=<ref>
DIST_TREE ?= HEAD
dist: ## Build dist/sparknet-<tree>.tar.gz from the committed tree
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "WARNING: working tree is dirty. '$(DIST_TREE)' omits uncommitted changes."; \
		git status --short; \
		echo; \
	fi
	@mkdir -p "$(VAULT_ROOT)/dist"
	@git archive --format=tar --prefix=sparknet/ "$(DIST_TREE)" \
		| gzip > "$(VAULT_ROOT)/dist/sparknet-$(DIST_TREE).tar.gz"
	@echo "Wrote dist/sparknet-$(DIST_TREE).tar.gz"

install-units: ## Generate shims + install systemd units (dry-run; pass APPLY=1 to write)
	@./scripts/sparknet-install-units.sh $(if $(APPLY),--apply,)

install-config: ## Show the /etc config diff. Never writes, by design.
	@./scripts/sparknet-install-config.sh

# --- Master-anchored node operations ----------------------------------------

NODE_ROLE ?= node
KEY_OUT ?= $(VAULT_ROOT)/.state/keys

keys: ## Generate WireGuard + Ed25519 keypairs into $(KEY_OUT) (secrets, never committed)
	@./scripts/sparknet-keygen.sh --role "$(NODE_ROLE)" --out "$(KEY_OUT)"

wg-render: ## Render wg0.conf from the template. Dry-run; pass APPLY=1 to write at 0600
	@./scripts/sparknet-wireguard-render.sh $(if $(APPLY),--apply,)

authz-verify: ## Verify an identity against the registry. IDENTITY=<node-identity.json>
	@./scripts/sparknet-run python3 ./services/sparknet-authz.py verify \
		"$(if $(IDENTITY),$(IDENTITY),manifests/node-identity.json)" \
		--registry "$(if $(REGISTRY),$(REGISTRY),manifests/node-authorizations.json)" \
		--master-pubkey "$(if $(MASTER_PUBKEY),$(MASTER_PUBKEY),manifests/keys/master-ed25519.pub.b64)"

anchor: ## Bring up the WireGuard Master Anchor (root; render + wg-quick up + chattr +i)
	@./scripts/sparknet-wireguard-anchor.sh

guard-status: ## Report the guard's manifest state and authorization posture
	@./scripts/sparknet-run python3 ./services/sparknet-guard-d.py --check-manifest

clean: ## Remove caches and build output
	@find "$(VAULT_ROOT)" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf "$(VAULT_ROOT)/.pytest_cache" "$(VAULT_ROOT)/dist"
	@echo "Cleaned caches and dist/ (left .venv, .state and .cache alone)."