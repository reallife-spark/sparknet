# sparknet — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`; pre-2026-10-31
> detail is in `_archives/MEMORY_FULL_2026-10-30.md`.
Updated: 2026-11-08
## Plan cursor
- `PLAN.md` — `current: 89`; Step 88 closed. Step 89 implementation is live; Phase 8 rewrite is in progress.
- Critical open items: full 416-file rewrite and Step 89 closure (89H private container registry/GitFlow and final 89I confirmations). Signer allowlist, ledger key pinning and transport mTLS are implemented and live for the signer.
- Phase 8: Waves A–F have targeted rewrites and tests; Wave G test coverage is green. The rewrite register is not fully closed.
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
- Signer: exact caller allowlist (`--allow-caller`, `SO_PEERCRED` plus bounded ancestor walk) is **live on agx64**; probe script succeeds, direct `python3 -c` is refused. Verifies ledger against the pinned operational key before signing.
- Ledger: `verify_chain(..., expected_pubkey_b64)`; CLI pins from `--pubkey` or the trust root. Forward key rotation is accepted; a return to an old key after the current key took over is refused. Live 54-block ledger verified 2026-11-08.
- goSpark: pinned mutual TLS (`Server.ClientFingerprint`, `DialOptions.ClientCertificate`), 64 incoming QUIC streams per connection; `sparknetctl send-block` requires `-pin`. Admin listener requires `GOSPARK_ADMIN_TOKEN` and fails closed without it; `sparknetctl`/MCP send the bearer token.
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
