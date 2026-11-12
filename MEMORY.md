# sparknet — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`; pre-2026-10-31
> detail is in `_archives/MEMORY_FULL_2026-10-30.md`.
Updated: 2026-11-12
## Plan cursor
- `PLAN.md` — `current: 104` (restored from `done`); Step 104D target-host
  verification is open. `master-node/PLAN.md` — `current: 9`; Step 9G live
  nocturnal window is open.
- Merged: fabric #18 (review triage), #19 (loader diagnostics), #20 (peer
  guard-status pin), #21 (AGX digest pin), #22 (KV/GPU ADRs); peer #2
  (guard-status); goagx signed release `2a925a6`; master plan truth `d227733`.
- Critical open items: 104D target-host deployment/image rebuild (#11); 9G
  next window 2026-11-13 02:00–05:00 (#8); peer→Master eval transport (#9);
  sandbox 20E/20F code; Step 10 live 4203 needs a third host; Phase 9
  destructive legs; KV/GPU ADR backlog. Mirror has 3 open issues (#8/#9/#11).
- Phase 8 remains closed: 54 fixed, 186 reviewed-clean, 176 test-verified;
  register and inventory in `_archives/`.
## Live fabric
- **`agx64` = Master = `sparknet-node-0001`** (`10.100.0.1/32`, hostname
  `red-team`); **`agx32` = peer = `sparknet-node-0002`** (`10.100.0.2/32`,
  hostname `blue-team`). Peer egress only to Master. The overlay is `wg1`, not
  `wg0`.
- Both hosts still carry the pre-104 shell entrypoint at
  `/home/raxxar/sparknet`; `sparknet-agx-node:dev` was built 2026-10-21. 104D
  needs a deployment/image rebuild, not just a command run.
- Master: signer/ledger/parity, 8088 admin, 8098 console, 8090/8091 intake, 4220–4223, 4201/4202 share, 4204 engine, Qdrant 6333, teacher.
- Peer: 9090 guard, 4096 bridge, 4201/4202 share, 4110/4093 memory, 8181 WebUI, 8099 console, 4204 engine, Qdrant 6333, student.
- **agx32 disk hygiene (2026-11-12):** root 869G→70G used. Qdrant snapshots live at `/mnt/ai/qdrant-snapshots` (keep 1/collection); Ollama store merged into `/mnt/ai/ollama/models`; `~/.cache/huggingface` → `/mnt/ai/hf-cache`; uplift outbox capped at 5 GiB; `sparknet-console@master` disabled. `sparknet-uplift-sync.timer` runs daily at 06:15; goagx is pinned at `08b9429` and drift-clean from HEAD (unrelated `.gitignore` `/learn/` change uncommitted).
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
- Base skill tree: 80 skills (33 wiki, 9 understand, 38 mattpocock); role catalogs peer 125 / master 1614.
## Security hardening 2026-11-08
- Signer live on agx64 as root, operational key 0600, socket 0660/allowlist, ledger pinned before signing. Ledger `verify_chain` pins the key and refuses a return to an old key; live 54-block ledger verified. goSpark uses pinned mTLS and a bearer-gated admin listener.
## Phase 8 state
- Closed: 54 fixed, 186 reviewed-clean, 176 test-verified; waves A–G hardened shared boundaries, scripts/goagx, peer provisioner/share, master uplift/vector, WebUI, goSpark and tests. Register/inventory in `_archives/`.
## Command gotchas
- `make ci`/`make test-all` are authoritative; full run >120 s.
- Rebuild before `bundle-verify`; run `wiki-preflight` before wiki suite.
- A long-running service loads `shared/` at start; restart after changing shared modules.
## Local vs live
This development host has no GPU/overlay. Code, tests, contracts, ledger and bundles are verifiable here; WireGuard, iptables, `chattr +i`, systemd, signer and live election are target-host checks.
