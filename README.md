# Sparknet

Master template for NVIDIA DGX Spark node setup as part of the Sparknet architecture.

## What this provides
- EU AI Act Article 14 compliant (Plan → Permission → Execute) workflow
- Vault/path/venv-agnostic service design with explicit env and absolute paths
- User local system identity capture with privilege boundary enforcement
- Security scaffolding: KillSwitch, immutable guard, signed approvals, permissioned ledger
- Hardware-aware networking (ConnectX-7 RoCEv2, MTU 9000, WLAN emergency routing)
- User-space P2P sync, hidden vault (.sparknet) patterns
- Template for provisioning standalone or cluster DGX Spark nodes

## Quick Start
```bash
cd /mnt/knowledge/sparknet/template
./scripts/sparknet-identity-capture.sh
./scripts/sparknet-validate.sh
./scripts/sparknet-provision.sh
```

## Documentation
See docs/ directory for architecture, compliance, user identity, scenarios/BOMs.

## GitHub
Repository target: https://github.com/realllife-spark/sparknet (private)
Note: Push currently blocked by GitHub auth requirements (see plans/GITHUB_PUSH_BLOCKER.md)
