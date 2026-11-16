# sparknet — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`.
Updated: 2026-11-16
## Plan cursor
- `PLAN.md` — `current: 113`; live 2026-11-16 on agx32/agx64/0003: Dex 9443 +
  lldap, Master SSO 8092, peer admin 8182, OIDC proxy 4180, `/nodes/` 200 for
  0002/0003, user 8181 unchanged, offline-repair accepted/applied false, OIDC
  admin 200/user-only 403; 8088 stopped. Remaining: fresh signed bundle and a
  Master/peer reboot check. `master-node/PLAN.md` — `current: done` with a Step
  113 pointer.
- #8/#9/#11 closed with dated evidence (0 open).
## Live fabric
- agx32 Master 0001 `10.100.0.1` (32GB); agx64 peer 0002 `10.100.0.2` (64GB);
  sparknet-node-0003 peer on vmx `10.100.0.3`. `10.99.0.0/30` carries `wg1`.
- Cluster root 1.3 `9157113f…` epoch 4 names 0001/0002/0003; registry
  sequence 12; WG keys rotated on 0001/0002.
- Text engine llama.cpp/llama-server live 2026-11-13; Ollama fallback; vLLM
  retired. agx64 30B Q4_K_M, agx32 4B Q4_K_M, 262k q8 KV.
- Storage: vaults/data `/mnt/ai`; active GGUF/KV `/opt/sparknet/models`;
  keys/state on root.
- Router 8101, resource directory 8089, memory router 4094; goagx `041a8d3`;
  goSpark `85815b3`; GitHub gate green 2026-11-16 on `5ebe0bf`.
- Auto-distill blocked on external CUDA; 16k bundle
  `sparknet-distill-e69b5e6f6247110d-20261115T024212Z.tar.gz`.
## Durable facts
- Human identity is federated: Master IdP (`sparknet-admins`/`sparknet-users`),
  node auth gateway, offline admin mTLS, per-node overrides; authentication,
  never a fabric capability.
- Live admin: Dex `10.100.0.1:9443`, SSO `8092`, peer admin `8182`,
  oauth2-proxy `4180`; user ingress 8181. Cert/key, lldap password and client
  secrets live under `~/.local/state/sparknet/master-node/identity/` on agx32
  (0600); never in the tree. 8088 is stopped.
- Memory plane: Go `sparknet-memory` 4110 behind gateway 4093; per-vault;
  Qdrant 6333/6334; 4223 signed.
- `model-uplift` is consented training/backup evidence, never answers.
- One `shared/sparknet-authz.py`; a role subvault is not a deployment; keys
  0700/0600.
- Live fleet uses iptables and userspace WireGuard; registry ships empty.
- Understand graph `.ua/`; issues `.scratch/issues/`; neither knowledge nor
  authority.
- Skill eval/catalog: schema + shared implementation; access via
  `.opencode/skills/.catalog.json` + MCP.
- ADRs 0009/0010/0011/0013/0018/0019/0020/0021; base skills 81, peer 125,
  master 1614.
## Security
- Signer live on agx32; operational key 0600; goSpark mTLS/bearer.
- WG keys exposed 2026-11-15 and rotated; PSKs on all three links.
## Command gotchas
- `make ci`/`make test-all` authoritative; full run >120 s.
- Rebuild before `bundle-verify`; run `wiki-preflight` before wiki.
## Local vs live
This host has no GPU/overlay. Code, tests, contracts, ledger and bundles are
verifiable here; WireGuard, iptables, systemd, signer and live election are
target-host checks.
