# External review triage — 2026-11-11

- **Baseline:** `5743d68`
- **Status:** triage record; the documentation corrections described below land
  in the same change
- **Source:** an external review synthesized from the course materials, not a
  code audit of this tree

The review’s `PR-*` identifiers are its own labels, not GitHub issue numbers.
Each claim below was checked against the current contracts, tests, services and
ADRs before being accepted.

## Verdicts

| Review item | Verdict | Evidence and action |
|---|---|---|
| PR-SPK-01 — manual/contract drift | **Confirmed** | The manual carried a stale compose-service count and called the master file/vector ports spec-only. Corrected in this change, with a test that every compose service is named in the manual. |
| PR-SPK-02 — gate table incomplete | **Confirmed** | The manual’s gate table omitted `context-check`, `governance-check` and `phase8-check`. Corrected here; the script remains the canonical order and `tests/test_ci.py` pins it. |
| PR-SPK-03 — loader diagnostics | **Valid follow-up** | `shared/sparknet_loader.py` names the file it could not locate but not every candidate path it tried. A separate change should add the candidate list and a focused test. |
| PR-PEER-01 — standalone peer confusion | **Already covered** | `peer-node/scripts/sparknet-validate.sh` fails when `contracts/` or `shared/` is unreachable and prints the resolved path. `make bundle ROLE=peer` remains the documented deployment path. |
| PR-PEER-02 — guard refusal classification | **Mechanism exists; enhancement** | The guard uses fixed refusal codes, appends refusals to its ledger, and `guard-status` reports manifest and authorization posture. A structured per-refusal view in `guard-status` is useful, but it is not a missing mechanism. |
| PR-MST-01 — key permission startup probe | **Already implemented** | `master-node/services/sparknet-signer.py::check_key_permissions` refuses an operational key readable by group or other before the signer starts. |
| PR-MST-02 — JSON-RPC ledger health endpoint | **Rejected for now** | A new endpoint would add a second health/authority surface. `contracts/service-health.md` defines one data-plane `/healthz` route, and `make -C master-node ledger` is the operator check. Revisit only through an ADR. |
| PR-AGX-01 — distribution drift | **Already implemented** | `make drift-check` calls `make goagx-drift-check`; the published tree is compared against this source. |
| PR-AGX-02 — L4T/CUDA base pin | **Premise stale; separate decision** | The AGX image pins `nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3`, not R35.5.0. Adding digest pinning is a hardening decision for its own change. |
| PR-GSP-01 — Go capability drift | **Already implemented** | `tests/test_registry_crossverify.py` exercises `issue-report` and `sandbox-supervise` across the Python and Go verifiers in both directions. |
| PR-GSP-02 — typed-memory boundary | **Already documented** | `contracts/memory-schema.json` `authority_boundary` states that the Go store holds no key, verifies no signature and writes no vault page; the Python gateway narrows to one vault. |
| Strategic — shallow wrappers | **No new finding** | The deep-module audit already records which modules are deliberately deep and which adapters are thin; there is no open shallow-wrapper defect. |
| Strategic — immutable state / append-only audit | **Already the pattern** | The ledger, provenance chain and issue triage ledger are append-only; no second state store is justified by this review. |
| Strategic — submodule pin validation | **Already the rule** | Cross-role changes pin role commits first and prove the pair with `make contract-test`; no new pin gate is needed. |

## What this change fixes

- `USER_MANUAL.md`: stale compose-service counts, missing memory/Qdrant rows,
  missing dispatcher subcommands, the master port state, the test-count
  sentence, the bundle key requirements and the incomplete gate table.
- `contracts/README.md` and `contracts/guard-protocol.md`: the approval field
  count and the missing `operator_os` row.
- `tests/test_claims.py`: regression checks for the service table, the gate
  steps, the approval fields, the bundle keys and the master port state.

## Follow-ups recorded, not implemented

1. **Loader diagnostics** (`PR-SPK-03`) — include candidate paths when
   `load_shared` fails closed.
2. **Guard refusal view** (`PR-PEER-02`) — surface the fixed refusal vocabulary
   in `guard-status` without changing the refusal path.
3. **AGX base digest pin** (`PR-AGX-02`) — decide whether the L4T base should be
   pinned by digest; record the decision in an ADR.

No submodule is changed by this triage. No live-host claim is made.
