# Phase 8 rewrite register

416 files, closed 2026-11-08. Disposition is the Step 90 verdict; the machine-readable execution state is `_archives/phase8-inventory.json`.

| File | LOC | Risk | Disposition | Evidence |
|---|---:|---|---|---|
| `goagx/goagx/bootstrap-agx.sh` | 193 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `goagx/goagx/sparknet-audio-shim.py` | 146 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `gospark/cmd/sparknet-agent/main.go` | 92 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/sparknet-backup/main.go` | 314 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/sparknet-control/main.go` | 220 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/sparknet-gpu/main.go` | 169 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/sparknet-ingest/main.go` | 149 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/sparknet-mcp/main.go` | 44 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/sparknet-memory/config.go` | 112 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/sparknet-memory/main.go` | 140 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/sparknet-memory/server.go` | 691 | medium | fixed | go test ./cmd/sparknet-memory |
| `gospark/cmd/sparknet-memory/server_test.go` | 238 | low | test-verified | gospark/cmd/sparknet-memory/server_test.go |
| `gospark/cmd/sparknetctl/main.go` | 718 | medium | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/stub-vllm/main.go` | 188 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/cmd/stub-vllm/main_test.go` | 132 | low | test-verified | gospark/cmd/stub-vllm/main_test.go |
| `gospark/compute/compute_worker.py` | 255 | low | fixed | python3 -m py_compile compute/compute_worker.py |
| `gospark/compute/kv_cache_router.py` | 192 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/apiv1/canonical.go` | 110 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/apiv1/canonical_test.go` | 68 | low | test-verified | gospark/internal/apiv1/canonical_test.go |
| `gospark/internal/apiv1/types.go` | 240 | low | fixed | go test ./internal/authz ./internal/server |
| `gospark/internal/authz/capabilities.go` | 92 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/authz/nonce.go` | 64 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/authz/registry.go` | 431 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/authz/registry_test.go` | 285 | high | test-verified | gospark/internal/authz/registry_test.go |
| `gospark/internal/authz/verify.go` | 142 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/authz/verify_test.go` | 222 | high | test-verified | gospark/internal/authz/verify_test.go |
| `gospark/internal/backup/backup.go` | 520 | medium | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/backup/backup_test.go` | 230 | low | test-verified | gospark/internal/backup/backup_test.go |
| `gospark/internal/bus/bus.go` | 56 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/bus/memory.go` | 141 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/bus/memory_test.go` | 144 | low | test-verified | gospark/internal/bus/memory_test.go |
| `gospark/internal/bus/nats.go` | 213 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/bus/nats_integration_test.go` | 213 | low | test-verified | gospark/internal/bus/nats_integration_test.go |
| `gospark/internal/compute/executor.go` | 201 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/compute/executor_test.go` | 192 | low | test-verified | gospark/internal/compute/executor_test.go |
| `gospark/internal/config/config.go` | 494 | medium | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/config/config_test.go` | 216 | low | test-verified | gospark/internal/config/config_test.go |
| `gospark/internal/delegates/broker.go` | 370 | low | fixed | go test ./internal/delegates ./cmd/sparknet-memory |
| `gospark/internal/delegates/broker_test.go` | 158 | low | test-verified | gospark/internal/delegates/broker_test.go |
| `gospark/internal/delegates/store.go` | 141 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/delegates/types.go` | 264 | low | fixed | go test ./internal/delegates |
| `gospark/internal/embed/embedder.go` | 250 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/embed/embedder_test.go` | 186 | low | test-verified | gospark/internal/embed/embedder_test.go |
| `gospark/internal/gateway/admission_test.go` | 67 | high | test-verified | gospark/internal/gateway/admission_test.go |
| `gospark/internal/gateway/drain_test.go` | 59 | high | test-verified | gospark/internal/gateway/drain_test.go |
| `gospark/internal/gateway/gateway.go` | 282 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/gateway/gateway_test.go` | 272 | high | test-verified | gospark/internal/gateway/gateway_test.go |
| `gospark/internal/gateway/limiter.go` | 141 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/gateway/limiter_test.go` | 126 | high | test-verified | gospark/internal/gateway/limiter_test.go |
| `gospark/internal/gputel/dcgm/dcgm_cgo.go` | 58 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/gputel/dcgm/dcgm_stub.go` | 7 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/gputel/gputel.go` | 226 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/gputel/gputel_test.go` | 122 | low | test-verified | gospark/internal/gputel/gputel_test.go |
| `gospark/internal/gputel/nvml/nvml_cgo.go` | 89 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/gputel/nvml/nvml_stub.go` | 7 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/gputel/sim/collector.go` | 106 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/gputel/sim/collector_test.go` | 76 | low | test-verified | gospark/internal/gputel/sim/collector_test.go |
| `gospark/internal/gputel/wire.go` | 41 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/identity/identity.go` | 216 | low | fixed | go test ./internal/identity |
| `gospark/internal/identity/identity_test.go` | 101 | low | test-verified | gospark/internal/identity/identity_test.go |
| `gospark/internal/identity/json.go` | 11 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/ingest/index.go` | 65 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/ingest/index_test.go` | 104 | low | test-verified | gospark/internal/ingest/index_test.go |
| `gospark/internal/ingest/ingest.go` | 203 | low | fixed | go test ./internal/ingest |
| `gospark/internal/ingest/ingest_test.go` | 111 | low | test-verified | gospark/internal/ingest/ingest_test.go |
| `gospark/internal/kvrouter/router.go` | 219 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/kvrouter/router_test.go` | 156 | low | test-verified | gospark/internal/kvrouter/router_test.go |
| `gospark/internal/kvtransfer/canonical.go` | 45 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/kvtransfer/delta.go` | 80 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/kvtransfer/helpers.go` | 8 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/kvtransfer/nvfp4.go` | 189 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/kvtransfer/nvfp4_test.go` | 146 | high | test-verified | gospark/internal/kvtransfer/nvfp4_test.go |
| `gospark/internal/mcp/mcp.go` | 274 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/mcp/mcp_test.go` | 145 | low | test-verified | gospark/internal/mcp/mcp_test.go |
| `gospark/internal/memory/indexer.go` | 110 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/memory/indexer_test.go` | 46 | low | test-verified | gospark/internal/memory/indexer_test.go |
| `gospark/internal/memory/redact.go` | 34 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/memory/retention.go` | 55 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/memory/semantic.go` | 320 | low | fixed | go test ./internal/memory ./cmd/sparknet-memory |
| `gospark/internal/memory/semantic_test.go` | 100 | low | test-verified | gospark/internal/memory/semantic_test.go |
| `gospark/internal/memory/store.go` | 820 | medium | fixed | go test ./internal/memory ./cmd/sparknet-memory |
| `gospark/internal/memory/store_test.go` | 243 | low | test-verified | gospark/internal/memory/store_test.go |
| `gospark/internal/memory/types.go` | 252 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/mesh/mesh.go` | 133 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/mesh/mesh_test.go` | 52 | low | test-verified | gospark/internal/mesh/mesh_test.go |
| `gospark/internal/metrics/gateway_test.go` | 39 | high | test-verified | gospark/internal/metrics/gateway_test.go |
| `gospark/internal/metrics/metrics.go` | 272 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/metrics/metrics_test.go` | 133 | low | test-verified | gospark/internal/metrics/metrics_test.go |
| `gospark/internal/placement/placement.go` | 274 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/placement/placement_test.go` | 213 | low | test-verified | gospark/internal/placement/placement_test.go |
| `gospark/internal/registryfile/registryfile.go` | 45 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/registryfile/registryfile_test.go` | 57 | high | test-verified | gospark/internal/registryfile/registryfile_test.go |
| `gospark/internal/router/router.go` | 217 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/router/router_test.go` | 86 | low | test-verified | gospark/internal/router/router_test.go |
| `gospark/internal/server/admin.go` | 396 | low | fixed | go test ./internal/server |
| `gospark/internal/server/admin_test.go` | 320 | low | test-verified | gospark/internal/server/admin_test.go |
| `gospark/internal/server/agent.go` | 207 | low | fixed | go test ./internal/server |
| `gospark/internal/server/app.go` | 352 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/server/compute_bridge_test.go` | 222 | low | test-verified | gospark/internal/server/compute_bridge_test.go |
| `gospark/internal/server/control.go` | 352 | low | fixed | go test ./internal/server |
| `gospark/internal/server/drain.go` | 36 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/server/drain_test.go` | 72 | low | test-verified | gospark/internal/server/drain_test.go |
| `gospark/internal/server/gpu.go` | 79 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/server/gpu_test.go` | 121 | low | test-verified | gospark/internal/server/gpu_test.go |
| `gospark/internal/server/health.go` | 184 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/server/health_test.go` | 126 | low | test-verified | gospark/internal/server/health_test.go |
| `gospark/internal/server/integration_test.go` | 172 | low | test-verified | gospark/internal/server/integration_test.go |
| `gospark/internal/server/kvcache_test.go` | 195 | low | test-verified | gospark/internal/server/kvcache_test.go |
| `gospark/internal/server/metrics.go` | 105 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/server/metrics_test.go` | 86 | low | test-verified | gospark/internal/server/metrics_test.go |
| `gospark/internal/server/nats_integration_test.go` | 159 | low | test-verified | gospark/internal/server/nats_integration_test.go |
| `gospark/internal/server/ops.go` | 268 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/server/ops_test.go` | 88 | low | test-verified | gospark/internal/server/ops_test.go |
| `gospark/internal/server/placement.go` | 114 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/server/placement_test.go` | 275 | low | test-verified | gospark/internal/server/placement_test.go |
| `gospark/internal/server/registry_test.go` | 186 | high | test-verified | gospark/internal/server/registry_test.go |
| `gospark/internal/telemetry/telemetry.go` | 67 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/telemetry/telemetry_test.go` | 53 | low | test-verified | gospark/internal/telemetry/telemetry_test.go |
| `gospark/internal/testutil/testutil.go` | 68 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/transport/tls.go` | 77 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/transport/transport.go` | 294 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/internal/transport/transport_test.go` | 124 | high | test-verified | gospark/internal/transport/transport_test.go |
| `gospark/proto/sparknet/v1/cluster.proto` | 68 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/proto/sparknet/v1/compute.proto` | 36 | low | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `gospark/proto/sparknet/v1/control.proto` | 121 | low | fixed | go test ./... |
| `gospark/proto/sparknet/v1/kvtransfer.proto` | 44 | high | reviewed-clean | gospark audit 2026-11-08 + go test ./... |
| `master-node/configs/train_lora.py` | 118 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-approval-deliver.sh` | 233 | low | fixed | tests/test_master_scripts.py |
| `master-node/scripts/sparknet-approval-issue.sh` | 210 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-approval-sign-socket.sh` | 122 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-distill-trainer.sh` | 30 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-election-approve.sh` | 87 | high | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-killswitch.sh` | 27 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-master-env.sh` | 53 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-master-keygen.sh` | 126 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-master-wireguard-anchor.sh` | 88 | high | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-registry-deliver.sh` | 256 | high | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-registry-publish.sh` | 268 | high | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-registry-revoke.sh` | 66 | high | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-registry-sign-socket.sh` | 107 | high | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-registry-sign.sh` | 82 | high | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-registry-verify.sh` | 64 | high | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-rfi-answer.sh` | 469 | medium | fixed | tests/test_master_scripts.py |
| `master-node/scripts/sparknet-share-ratify-unit.sh` | 43 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/scripts/sparknet-wg-render-master.sh` | 85 | low | fixed | tests/test_wg_render.py::test_registry_and_out_paths_cannot_inject_python |
| `master-node/services/sparknet-admin-console.py` | 739 | medium | fixed | tests/test_admin_console.py |
| `master-node/services/sparknet-distill-status.py` | 130 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-distill.py` | 416 | medium | fixed | tests/test_distill.py::test_redaction_masks_the_value_not_only_the_keyword |
| `master-node/services/sparknet-evidence-capture.py` | 265 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-file-share.py` | 194 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-killswitch.py` | 364 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-ledger.py` | 184 | high | fixed | tests/test_signer_isolation.py |
| `master-node/services/sparknet-nat-status.py` | 183 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-parity.py` | 149 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-peer-intake.py` | 497 | medium | fixed | tests/test_peer_intake.py |
| `master-node/services/sparknet-reflex-broker.py` | 363 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-review-agents.py` | 203 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-rfi-responder.py` | 333 | low | fixed | tests/test_rfi_responder.py |
| `master-node/services/sparknet-scheduler.py` | 1345 | medium | fixed | tests/test_scheduler.py |
| `master-node/services/sparknet-share-ratify.py` | 531 | medium | fixed | tests/test_share_ratify.py |
| `master-node/services/sparknet-signer.py` | 1196 | high | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-uplift-intake.py` | 522 | medium | fixed | tests/test_uplift_intake.py |
| `master-node/services/sparknet-vector-serve.py` | 295 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/services/sparknet-wg-observer.py` | 283 | low | reviewed-clean | master audit 2026-11-08 + master-node/tests |
| `master-node/tests/conftest.py` | 52 | low | test-verified | master-node/tests/conftest.py |
| `master-node/tests/test_admin_console.py` | 556 | medium | test-verified | master-node/tests/test_admin_console.py |
| `master-node/tests/test_admin_services.py` | 147 | low | test-verified | master-node/tests/test_admin_services.py |
| `master-node/tests/test_admin_surface.py` | 448 | medium | test-verified | master-node/tests/test_admin_surface.py |
| `master-node/tests/test_approval.py` | 497 | medium | test-verified | master-node/tests/test_approval.py |
| `master-node/tests/test_distill.py` | 73 | low | test-verified | master-node/tests/test_distill.py |
| `master-node/tests/test_evidence_and_review.py` | 202 | low | test-verified | master-node/tests/test_evidence_and_review.py |
| `master-node/tests/test_killswitch.py` | 234 | low | test-verified | master-node/tests/test_killswitch.py |
| `master-node/tests/test_master_parity.py` | 119 | low | test-verified | master-node/tests/test_master_parity.py |
| `master-node/tests/test_master_scripts.py` | 194 | low | test-verified | master-node/tests/test_master_scripts.py |
| `master-node/tests/test_master_spec.py` | 405 | medium | test-verified | master-node/tests/test_master_spec.py |
| `master-node/tests/test_peer_intake.py` | 376 | low | test-verified | master-node/tests/test_peer_intake.py |
| `master-node/tests/test_reflex_broker.py` | 330 | low | test-verified | master-node/tests/test_reflex_broker.py |
| `master-node/tests/test_registry_cli.py` | 136 | high | test-verified | master-node/tests/test_registry_cli.py |
| `master-node/tests/test_registry_cli_step3.py` | 73 | high | test-verified | master-node/tests/test_registry_cli_step3.py |
| `master-node/tests/test_registry_dist.py` | 502 | high | test-verified | master-node/tests/test_registry_dist.py |
| `master-node/tests/test_registry_schema.py` | 242 | high | test-verified | master-node/tests/test_registry_schema.py |
| `master-node/tests/test_rfi_responder.py` | 114 | low | test-verified | master-node/tests/test_rfi_responder.py |
| `master-node/tests/test_rfi_transport.py` | 799 | high | test-verified | master-node/tests/test_rfi_transport.py |
| `master-node/tests/test_scheduler.py` | 727 | medium | test-verified | master-node/tests/test_scheduler.py |
| `master-node/tests/test_share_ratify.py` | 319 | low | test-verified | master-node/tests/test_share_ratify.py |
| `master-node/tests/test_signer_isolation.py` | 1745 | high | test-verified | master-node/tests/test_signer_isolation.py |
| `master-node/tests/test_step1_keypair.py` | 526 | medium | test-verified | master-node/tests/test_step1_keypair.py |
| `master-node/tests/test_uplift_intake.py` | 170 | low | test-verified | master-node/tests/test_uplift_intake.py |
| `master-node/tests/test_vector_serve.py` | 179 | low | test-verified | master-node/tests/test_vector_serve.py |
| `master-node/tests/test_wg_anchor.py` | 76 | low | test-verified | master-node/tests/test_wg_anchor.py |
| `master-node/tests/test_wg_observer.py` | 204 | low | test-verified | master-node/tests/test_wg_observer.py |
| `master-node/tests/test_wg_render.py` | 208 | low | test-verified | master-node/tests/test_wg_render.py |
| `peer-node/agents/cyber/agent.py` | 2 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/agents/engineering/agent.py` | 2 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/agents/vault-curator/agent.py` | 551 | medium | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/configs/opencode-runtime/unix-proxy.py` | 80 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/container/anchor/entrypoint.sh` | 45 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/container/entrypoint.sh` | 36 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/container/healthcheck.sh` | 29 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-chattr-preflight.sh` | 59 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-election-request.sh` | 93 | high | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-env.sh` | 51 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-firewall.sh` | 218 | low | fixed | peer-node/tests/test_firewall.py |
| `peer-node/scripts/sparknet-identity-capture.sh` | 137 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-install-config.sh` | 89 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-install-units.sh` | 178 | low | fixed | peer-node/tests/test_scripts.py |
| `peer-node/scripts/sparknet-keygen.sh` | 127 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-lockdown.sh` | 4 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-masterspike.py` | 174 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-node-containment.sh` | 87 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-provision.sh` | 17 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-registry-fetch.sh` | 50 | high | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-registry-verify-peer.sh` | 64 | high | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-sharectl.py` | 131 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-sync.sh` | 76 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-validate.sh` | 98 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-vllm-kv-dump.py` | 104 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-vllm-kv-patch.sh` | 55 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-webui-workspace.py` | 1041 | medium | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-wg-bringup.sh` | 192 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-wg-render-peer.sh` | 39 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-wireguard-anchor.sh` | 106 | high | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-wireguard-render.sh` | 122 | high | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/scripts/sparknet-wlan-guard.sh` | 81 | high | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/services/sparknet-admin-agent.py` | 429 | medium | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/services/sparknet-checkpoint-anchor.py` | 241 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/services/sparknet-dispatch-bridge.py` | 2128 | medium | fixed | peer-node/tests/test_bridge.py |
| `peer-node/services/sparknet-guard-d.py` | 1315 | high | fixed | peer-node/tests/test_guard.py |
| `peer-node/services/sparknet-inventory-agent.py` | 448 | medium | fixed | peer-node/tests/test_inventory_agent.py |
| `peer-node/services/sparknet-liveness-monitor.py` | 539 | medium | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/services/sparknet-opencode-engine.py` | 1275 | high | fixed | peer-node/tests/test_services.py |
| `peer-node/services/sparknet-proposal-exchange.py` | 257 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/services/sparknet-registry-client.py` | 169 | high | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/services/sparknet-rfi-client.py` | 203 | low | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/services/sparknet-share-regime.py` | 898 | medium | fixed | peer-node/tests/test_share_serve.py |
| `peer-node/services/sparknet-share-serve.py` | 702 | medium | fixed | peer-node/tests/test_share_serve.py::test_delivery_rejects_a_share_id_that_escapes_the_inbox |
| `peer-node/services/sparknet-telemetry-push.py` | 503 | medium | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/services/sparknet-vault-provisioner.py` | 854 | medium | reviewed-clean | peer audit 2026-11-08 + peer-node/tests |
| `peer-node/tests/conftest.py` | 49 | low | test-verified | peer-node/tests/conftest.py |
| `peer-node/tests/test_admin_agent.py` | 232 | low | test-verified | peer-node/tests/test_admin_agent.py |
| `peer-node/tests/test_admin_supervise.py` | 691 | medium | test-verified | peer-node/tests/test_admin_supervise.py |
| `peer-node/tests/test_authz.py` | 504 | high | test-verified | peer-node/tests/test_authz.py |
| `peer-node/tests/test_bridge.py` | 851 | medium | test-verified | peer-node/tests/test_bridge.py |
| `peer-node/tests/test_containment.py` | 193 | low | test-verified | peer-node/tests/test_containment.py |
| `peer-node/tests/test_conversation_passing.py` | 390 | low | test-verified | peer-node/tests/test_conversation_passing.py |
| `peer-node/tests/test_env.py` | 85 | low | test-verified | peer-node/tests/test_env.py |
| `peer-node/tests/test_firewall.py` | 107 | low | test-verified | peer-node/tests/test_firewall.py |
| `peer-node/tests/test_grants.py` | 504 | medium | test-verified | peer-node/tests/test_grants.py |
| `peer-node/tests/test_guard.py` | 1051 | high | test-verified | peer-node/tests/test_guard.py |
| `peer-node/tests/test_inventory_agent.py` | 81 | low | test-verified | peer-node/tests/test_inventory_agent.py |
| `peer-node/tests/test_manifests.py` | 110 | low | test-verified | peer-node/tests/test_manifests.py |
| `peer-node/tests/test_masterspike.py` | 196 | low | test-verified | peer-node/tests/test_masterspike.py |
| `peer-node/tests/test_node_ai_stack.py` | 303 | low | test-verified | peer-node/tests/test_node_ai_stack.py |
| `peer-node/tests/test_node_container.py` | 231 | low | test-verified | peer-node/tests/test_node_container.py |
| `peer-node/tests/test_proposal_exchange.py` | 324 | low | test-verified | peer-node/tests/test_proposal_exchange.py |
| `peer-node/tests/test_reflex_surface.py` | 258 | low | test-verified | peer-node/tests/test_reflex_surface.py |
| `peer-node/tests/test_rfi_client.py` | 85 | low | test-verified | peer-node/tests/test_rfi_client.py |
| `peer-node/tests/test_scripts.py` | 609 | medium | test-verified | peer-node/tests/test_scripts.py |
| `peer-node/tests/test_services.py` | 242 | low | test-verified | peer-node/tests/test_services.py |
| `peer-node/tests/test_share_regime.py` | 660 | medium | test-verified | peer-node/tests/test_share_regime.py |
| `peer-node/tests/test_share_serve.py` | 427 | medium | test-verified | peer-node/tests/test_share_serve.py |
| `peer-node/tests/test_vault_curator.py` | 253 | low | test-verified | peer-node/tests/test_vault_curator.py |
| `peer-node/tests/test_vault_health.py` | 70 | low | test-verified | peer-node/tests/test_vault_health.py |
| `peer-node/tests/test_vault_provisioner.py` | 428 | medium | test-verified | peer-node/tests/test_vault_provisioner.py |
| `peer-node/tests/test_webui_surface.py` | 406 | medium | test-verified | peer-node/tests/test_webui_surface.py |
| `peer-node/tests/test_webui_workspace.py` | 285 | low | test-verified | peer-node/tests/test_webui_workspace.py |
| `peer-node/tests/test_wireguard.py` | 634 | high | test-verified | peer-node/tests/test_wireguard.py |
| `scripts/make-gpu-fixture.py` | 98 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/plugins/kde-notify.ts` | 68 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/pre-merge-gate.sh` | 97 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-bundle.sh` | 530 | medium | fixed | tests/test_goagx_repo.py / bundle-verify |
| `scripts/sparknet-chroma.py` | 29 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-console.py` | 755 | medium | fixed | tests/test_webui_console.py |
| `scripts/sparknet-context-pack.py` | 281 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-election-rehearsal-container.sh` | 109 | high | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-env-init.sh` | 224 | low | fixed | tests/test_keys.py |
| `scripts/sparknet-goagx-publish.sh` | 546 | medium | fixed | tests/test_goagx_repo.py::test_staged_verify_mode_passes |
| `scripts/sparknet-governance-check.py` | 162 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-keys-check.sh` | 192 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-kv-export.py` | 138 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-memory-bundle.py` | 162 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-memory-index.py` | 77 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-model-bench.py` | 511 | medium | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-model-pull.py` | 508 | medium | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-model-runtime.py` | 487 | medium | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-model-survey.py` | 351 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-model-update.py` | 217 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-nv-search.sh` | 160 | low | fixed | tests/test_nv_search.py |
| `scripts/sparknet-project.py` | 396 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-rag-corpus.py` | 302 | low | fixed | tests/test_rag_corpus.py |
| `scripts/sparknet-recovery.py` | 256 | low | fixed | tests/test_recovery.py |
| `scripts/sparknet-reflex-eval.py` | 519 | medium | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-reflex-plan-eval.py` | 274 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-rehearsal.sh` | 550 | medium | fixed | tests/test_shell.py |
| `scripts/sparknet-render.py` | 177 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-safe-build.sh` | 196 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-sbom.py` | 401 | medium | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-share-rehearsal.py` | 285 | low | fixed | tests/test_share_rehearsal.py |
| `scripts/sparknet-share-rehearsal.sh` | 7 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-test-report.sh` | 144 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-uplift-push.py` | 363 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-vault-health.py` | 265 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-vector.py` | 1378 | medium | fixed | tests/test_vector.py |
| `scripts/sparknet-verify-plans.py` | 96 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sparknet-webui-users.py` | 333 | low | fixed | tests/test_webui_console.py |
| `scripts/sparknet-wiki-env.sh` | 185 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sync-role-skills.py` | 1056 | medium | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `scripts/sync-wiki-skills.py` | 502 | medium | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `shared/sparknet-authz.py` | 2167 | high | fixed | tests/test_contracts.py |
| `shared/sparknet-cluster.py` | 173 | low | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet-consensus.py` | 896 | high | reviewed-clean | tests/test_consensus.py |
| `shared/sparknet-election.py` | 1365 | high | fixed | tests/test_election.py |
| `shared/sparknet-http.py` | 513 | medium | fixed | tests/test_http_transport.py |
| `shared/sparknet-idle.py` | 266 | low | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet-liveness.py` | 229 | low | fixed | tests/test_liveness_service.py |
| `shared/sparknet-memory-filter.py` | 164 | low | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet-memory-gateway.py` | 759 | high | fixed | tests/test_memory_gateway.py |
| `shared/sparknet-memory-mcp.py` | 268 | low | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet-merkle.py` | 449 | medium | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet-nocturnal.py` | 446 | medium | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet-notify.py` | 222 | low | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet-oob.py` | 200 | low | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet-proposal.py` | 748 | medium | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet-provenance.py` | 2750 | high | fixed | tests/test_provenance.py |
| `shared/sparknet-reflex.py` | 710 | medium | fixed | tests/test_reflex_plan.py |
| `shared/sparknet-registry-install.py` | 245 | high | fixed | tests/test_registry_install_record.py |
| `shared/sparknet-registry-schema.py` | 494 | high | fixed | master-node/tests/test_registry_schema.py |
| `shared/sparknet-rfi-install.py` | 179 | low | fixed | tests/test_provenance.py |
| `shared/sparknet-verify.py` | 371 | low | fixed | tests/test_reflex_plan.py |
| `shared/sparknet-yaml.py` | 388 | low | reviewed-clean | tests/ shared audit 2026-11-08 |
| `shared/sparknet_loader.py` | 107 | low | reviewed-clean | tests/ shared audit 2026-11-08 |
| `tests/conftest.py` | 74 | low | test-verified | tests/conftest.py |
| `tests/contract_helpers.py` | 29 | low | test-verified | tests/contract_helpers.py |
| `tests/test_agents.py` | 174 | low | test-verified | tests/test_agents.py |
| `tests/test_agx_node.py` | 489 | medium | test-verified | tests/test_agx_node.py |
| `tests/test_authz_golden.py` | 217 | high | test-verified | tests/test_authz_golden.py |
| `tests/test_checkpoint_anchor.py` | 280 | low | test-verified | tests/test_checkpoint_anchor.py |
| `tests/test_checkpoints.py` | 465 | medium | test-verified | tests/test_checkpoints.py |
| `tests/test_ci.py` | 179 | low | test-verified | tests/test_ci.py |
| `tests/test_claims.py` | 201 | low | test-verified | tests/test_claims.py |
| `tests/test_cluster.py` | 88 | low | test-verified | tests/test_cluster.py |
| `tests/test_consensus.py` | 964 | high | test-verified | tests/test_consensus.py |
| `tests/test_context_pack.py` | 69 | low | test-verified | tests/test_context_pack.py |
| `tests/test_contracts.py` | 2277 | medium | test-verified | tests/test_contracts.py |
| `tests/test_cpu_node_smoke.py` | 210 | low | test-verified | tests/test_cpu_node_smoke.py |
| `tests/test_distill_status.py` | 71 | low | test-verified | tests/test_distill_status.py |
| `tests/test_distillation_authz.py` | 69 | high | test-verified | tests/test_distillation_authz.py |
| `tests/test_election.py` | 1504 | high | test-verified | tests/test_election.py |
| `tests/test_election_container.py` | 84 | high | test-verified | tests/test_election_container.py |
| `tests/test_election_simulation.py` | 704 | high | test-verified | tests/test_election_simulation.py |
| `tests/test_goagx_repo.py` | 290 | low | test-verified | tests/test_goagx_repo.py |
| `tests/test_gpu_telemetry_hardware_free.py` | 122 | low | test-verified | tests/test_gpu_telemetry_hardware_free.py |
| `tests/test_hardening.py` | 279 | low | test-verified | tests/test_hardening.py |
| `tests/test_http_transport.py` | 445 | high | test-verified | tests/test_http_transport.py |
| `tests/test_identity_pages.py` | 107 | low | test-verified | tests/test_identity_pages.py |
| `tests/test_idle_evidence.py` | 164 | low | test-verified | tests/test_idle_evidence.py |
| `tests/test_keys.py` | 259 | low | test-verified | tests/test_keys.py |
| `tests/test_knowledge_flow.py` | 50 | low | test-verified | tests/test_knowledge_flow.py |
| `tests/test_kv_export.py` | 53 | low | test-verified | tests/test_kv_export.py |
| `tests/test_layout.py` | 480 | medium | test-verified | tests/test_layout.py |
| `tests/test_liveness.py` | 219 | low | test-verified | tests/test_liveness.py |
| `tests/test_liveness_service.py` | 325 | low | test-verified | tests/test_liveness_service.py |
| `tests/test_memory_bundle.py` | 92 | low | test-verified | tests/test_memory_bundle.py |
| `tests/test_memory_gateway.py` | 230 | high | test-verified | tests/test_memory_gateway.py |
| `tests/test_memory_index.py` | 65 | low | test-verified | tests/test_memory_index.py |
| `tests/test_memory_mcp.py` | 116 | low | test-verified | tests/test_memory_mcp.py |
| `tests/test_merkle.py` | 434 | medium | test-verified | tests/test_merkle.py |
| `tests/test_model_bench.py` | 184 | low | test-verified | tests/test_model_bench.py |
| `tests/test_model_catalog.py` | 130 | low | test-verified | tests/test_model_catalog.py |
| `tests/test_model_pull.py` | 176 | low | test-verified | tests/test_model_pull.py |
| `tests/test_model_runtime.py` | 190 | low | test-verified | tests/test_model_runtime.py |
| `tests/test_model_survey.py` | 87 | low | test-verified | tests/test_model_survey.py |
| `tests/test_model_update.py` | 81 | low | test-verified | tests/test_model_update.py |
| `tests/test_nocturnal.py` | 148 | low | test-verified | tests/test_nocturnal.py |
| `tests/test_node_setup_join.py` | 219 | low | test-verified | tests/test_node_setup_join.py |
| `tests/test_notify.py` | 204 | low | test-verified | tests/test_notify.py |
| `tests/test_nv_search.py` | 151 | low | test-verified | tests/test_nv_search.py |
| `tests/test_oob.py` | 115 | low | test-verified | tests/test_oob.py |
| `tests/test_plugin.py` | 166 | low | test-verified | tests/test_plugin.py |
| `tests/test_precontext.py` | 159 | low | test-verified | tests/test_precontext.py |
| `tests/test_project_script.py` | 144 | low | test-verified | tests/test_project_script.py |
| `tests/test_proposal.py` | 488 | medium | test-verified | tests/test_proposal.py |
| `tests/test_provenance.py` | 1222 | high | test-verified | tests/test_provenance.py |
| `tests/test_rag_corpus.py` | 283 | low | test-verified | tests/test_rag_corpus.py |
| `tests/test_recovery.py` | 95 | low | test-verified | tests/test_recovery.py |
| `tests/test_reflex_contract.py` | 638 | medium | test-verified | tests/test_reflex_contract.py |
| `tests/test_reflex_plan.py` | 300 | low | test-verified | tests/test_reflex_plan.py |
| `tests/test_reflex_rag.py` | 371 | low | test-verified | tests/test_reflex_rag.py |
| `tests/test_registry_crossverify.py` | 334 | high | test-verified | tests/test_registry_crossverify.py |
| `tests/test_release.py` | 358 | low | test-verified | tests/test_release.py |
| `tests/test_render.py` | 135 | low | test-verified | tests/test_render.py |
| `tests/test_role_skills.py` | 127 | low | test-verified | tests/test_role_skills.py |
| `tests/test_service_timeouts.py` | 90 | low | test-verified | tests/test_service_timeouts.py |
| `tests/test_share_rehearsal.py` | 23 | low | test-verified | tests/test_share_rehearsal.py |
| `tests/test_shell.py` | 316 | low | test-verified | tests/test_shell.py |
| `tests/test_shims.py` | 128 | low | test-verified | tests/test_shims.py |
| `tests/test_telemetry_push.py` | 333 | low | test-verified | tests/test_telemetry_push.py |
| `tests/test_vector.py` | 392 | low | test-verified | tests/test_vector.py |
| `tests/test_vector_corpus.py` | 151 | low | test-verified | tests/test_vector_corpus.py |
| `tests/test_webui_console.py` | 425 | medium | test-verified | tests/test_webui_console.py |
| `tests/test_webui_engine.py` | 126 | low | test-verified | tests/test_webui_engine.py |
| `tests/test_webui_patch.py` | 86 | low | test-verified | tests/test_webui_patch.py |
| `tests/test_wiki_skills.py` | 497 | medium | test-verified | tests/test_wiki_skills.py |
| `webui/console/app.js` | 551 | medium | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/console/index.html` | 143 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/console/sparknet-menu.js` | 113 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/console/style.css` | 74 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/functions/sparknet_capture.py` | 101 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/functions/sparknet_memory_filter.py` | 164 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/install-console.py` | 97 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/install-memory-filter.py` | 125 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/patch-openwebui.py` | 138 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/tools/sparknet_memory.py` | 104 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/tools/sparknet_rfi.py` | 66 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/tools/sparknet_status.py` | 42 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
| `webui/tools/sparknet_vault.py` | 77 | low | reviewed-clean | scripts/webui/goagx audit 2026-11-08 |
