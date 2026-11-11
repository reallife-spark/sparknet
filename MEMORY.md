# sparknet — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`; pre-2026-10-31
> detail is in `_archives/MEMORY_FULL_2026-10-30.md`.
Updated: 2026-11-11
## Plan cursor
- `PLAN.md` — `current: done`; Steps 96–102 closed: skill-eval record/gate/
  harness, dependency guard, test tiers, ADR-0015's boundary, the console
  eval view, and two malformed-payload refusals.
- Commits: goSpark `2e8b2be`; fabric `7135b83`/pin; goagx `59a83e7` pinned.
  Peer `a4d3835`, master `9435b65`. `make drift-check` green.
- Critical open items: mirror complete (21 issues/5 repos, 18 closed); 9G
  nocturnal window, shell migrations and the peer→Master eval transport
  decision remain; peer precommit reports `peer-node/02_Daily/2026-11-02.md`.
- Phase 8 remains closed: 54 fixed, 186 reviewed-clean, 176 test-verified;
  register and inventory in `_archives/`.
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
- Understand graph is a build artifact (`.ua/`); issues are work items (`.scratch/issues/`). Neither is knowledge or authority.
- Understand graph: Python is the sole producer (`scan`/`build`/`merge`/`validate`/`diff`); Go consumes `query`/`export`/MCP and adapts `scan`/`diff`/`parse` through `shared/sparknet-understand.py`. Python core is split into `schema.py`, `production.py`, `algebra.py` behind the path-stable `core.py` facade.
- Issue model: `shared/sparknet-issue.py` owns parse, redaction, validation, ledger, triage and projection; `shared/sparknet-authz.py` still owns the envelope/signature. Triage history is append-only `triage.jsonl`, derived `triage.json`.
- Skill-eval model: `contracts/skill-eval-schema.json` + `shared/sparknet-skill-eval.py` is the one digest-bound pass/warn/fail record. Gate mode in `sparknet-self-improve.evaluate()` and `project report --require-review` require a passing record; the Go broker validates and stores it. `make skill-eval` runs the offline golden harness. Records are audit evidence: never authority, never knowledge.
- Skill catalog: `scripts/skill_catalog/` owns copy/digest/manifest/host-path mechanics; the four sync scripts remain adapters and keep their external manifest shapes.
- Architecture decisions recorded: issue module (root ADR 0009), skill catalog (root ADR 0010), core split (root ADR 0011), sandbox policy authority (root ADR 0013), graph producer/consumer (goSpark ADR 0018).
- Live Step 91 evidence: `live-step91-issue` delivered peer `agx32` → Master `agx64` on `10.100.0.1:8090`, triaged `done`/`wontfix`; Master Issues and both Understand tabs rendered in Chromium.
- Base skill tree: 80 skills (33 wiki, 9 understand, 38 mattpocock); role catalogs peer 125 / master 1614.
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
## Local vs live
This development host has no GPU/overlay. Code, tests, contracts, ledger and bundles are verifiable here; WireGuard, iptables, `chattr +i`, systemd, signer and live election are target-host checks.
