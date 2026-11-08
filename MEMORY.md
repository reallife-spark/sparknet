# sparknet — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`; pre-2026-10-31
> detail is in `_archives/MEMORY_FULL_2026-10-30.md`.
Updated: 2026-11-08
## Plan cursor
- `PLAN.md` — `current: 90`; Step 90 is the 416-file Phase 8 remediation. Step 89 is archived in `_archives/PLAN_FULL_2026-11-08.md`.
- Critical open items: Step 90 is active; 52 fixed / 186 reviewed-clean / 176 test-verified / 2 needs-decision. The remaining items are unsigned bundle/goagx verify execution.
- Phase 8: closed 2026-11-08. All 416 files are dispositioned; high-risk audit findings (registry replay, signer/verifier asymmetry, script injection, peer pin, patch mode, WG injection, proxy bounds, guard audit, WLAN) are fixed.
- 89H/89I: private loopback OCI registry (`master-node/services/sparknet-container-registry.py`, port 5000, staged unit), GitFlow policy (`shared/sparknet-gitflow.py`), self-improvement source/target branches, signed package distribution. Registry live loopback probe passed on agx64 2026-11-08.
## Live fabric
- **`agx64` = Master = `sparknet-node-0001`** (`10.100.0.1/32`); **`agx32` = peer = `sparknet-node-0002`** (`10.100.0.2/32`). Peer egress only to Master.
- Master: signer/ledger/parity, 8088 admin, 8098 console, 8090/8091 intake, 4220–4223, 4201/4202 share, 4204 engine, Qdrant 6333, teacher.
- Peer: 9090 guard, 4096 bridge, 4201/4202 share, 4110/4093 memory, 8181 WebUI, 8099 console, 4204 engine, Qdrant 6333, student.
- **Teacher/student:** agx64 Qwen3.6-35B-A3B Q4_K_M; agx32 Qwen3.5-9B Q8.
- **Agents:** agx32 `sparknet-agent@engineering` and `@cyber` user units; agx64 `sparknet-orchestrator.service`. Live task returned `engineering.result` `summary=OK`.
- **Exec:** agx32 daemon live with exact allowlist `pwd`, `ls -la`, `git status --short`; cwd `01_Inbox`/`05_Knowledge`; audit `.state/exec-audit.jsonl`; no shell.
- **Secrets:** engine/memory/Qdrant rotated 2026-11-07; old tokens refused. Master/peer WebUI chat verified.
## Durable facts
- Memory plane: Go `sparknet-memory` 4110 behind Python gateway 4093; one store, per-vault scope.
- Qdrant 6333/6334; 4223 is the only signed surface.
- `model-uplift` carries consented training/backup evidence only, never answers.
- One `shared/sparknet-authz.py`; one authorization implementation.
- A role subvault is not a deployment; `make bundle` + `bundle-verify`.
- Keys live in `$SPARKNET_STATE_DIR` at 0700/0600; never in git or a vault.
- Live fleet uses iptables and userspace WireGuard.
- Registry ships empty; fresh nodes grant nothing.
## Security hardening 2026-11-08
- Signer: **live on agx64** as root with a root-owned 0600 operational key, socket group `sparknet-signer` at 0660, and the exact caller allowlist; probe succeeds, direct `python3 -c` is refused. Verifies ledger against the pinned operational key before signing. See `master-node/docs/signer-isolation.md`.
- Ledger: `verify_chain(..., expected_pubkey_b64)`; CLI pins from `--pubkey` or the trust root. Forward key rotation is accepted; a return to an old key after the current key took over is refused. Live 54-block ledger verified 2026-11-08.
- goSpark: pinned mutual TLS (`Server.ClientFingerprint`, `DialOptions.ClientCertificate`), cert→node origin binding, 64 incoming QUIC streams per connection; `sparknetctl send-block` requires `-pin`. Admin listener requires `GOSPARK_ADMIN_TOKEN` and fails closed without it; `sparknetctl`/MCP send the bearer token.
## Phase 8 state
- Wave A: shared boundary/fail-closed fixes, live-deployed to memory gateway.
- Wave B: scripts/goagx targeted rewrites, including safe tar extraction and master from-git bundle fix.
- Wave C: peer provisioner no longer copies personal categories; RFI SSRF, cluster job-id traversal, mesh/share fixes, anchor and helper repairs.
- Wave D: master uplift signed-entry/consent checks, vector reindex auth, proxy-disabled admin delivery; distill split/publish hardening.
- Wave E: WebUI capture redaction, query encoding, memory-filter status, installer token checks.
- Wave F: goSpark authz/registry/transport/memory race fixes.
- Wave G: focused tests added; full gate green.
## Command gotchas
- `make ci`/`make test-all` are authoritative; full run >120 s.
- Rebuild before `bundle-verify`; run `wiki-preflight` before wiki suite.
- A long-running service loads `shared/` at start; restart after changing shared modules.
- Do not commit the four pre-existing goSpark authz/identity changes without inspecting them first — they were committed in `b528abf`/`ff5dce2`; keep the checkout clean.
## Local vs live
This development host has no GPU/overlay. Code, tests, contracts, ledger and bundles are verifiable here; WireGuard, iptables, `chattr +i`, systemd, signer and live election are target-host checks.
