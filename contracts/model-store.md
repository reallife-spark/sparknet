---
title: sparknet model store and runtime leases
role: both
updated: 2026-11-01
---

# Model store and runtime leases

This contract governs where model weights live, which node may serve them, and
how a large model runtime is started and stopped. It does not grant authority
and it does not carry user knowledge.

The model store is operator-owned. A model weight is not vault knowledge, not
uplift data, not telemetry and not an answer corpus. It never enters `4223`, a
vault, a bundle, `MEMORY.md` or a signed envelope.

## Placement

| Node | Role | May serve | Must not serve |
|---|---|---|---|
| `agx64` — peer, 64 GB | teacher | Teacher candidates, embedding models | Student training; Master authority |
| `agx32` — master, 32 GB | student | Student candidates, embedding models | The teacher; teacher backup weights |

The teacher is deliberately **not eligible for `agx32`**. A 32 GB node cannot
hold the teacher with context headroom, and copying the weights there is a cold
backup, not a serving path. This contract forbids the backup by default.

The catalog is the closed list: `contracts/model-catalog.json`. A model not in
the catalog is not pulled, served or reported as available. Adding a model is a
contract change and a new catalog entry with a license and a fit estimate.

## Store layout

```text
/mnt/ai/models/
  <model-id>/
    <files...>
  manifests/<model-id>.json
```

The store root is `/mnt/ai/models` unless the operator chooses another host
path. It is never a vault path and never a repository path. Model files are
read-only to the serving container. Manifests are `0600`.

A pull manifest records:

- catalog id, repo, requested revision and resolved commit;
- every downloaded file with its SHA-256 and size;
- the chosen `model_file` for llama.cpp;
- license and license URL;
- node, pull time and puller;
- `pinned: true` only after every file hash verifies.

A serving profile refuses a model whose manifest is absent, unpinned or whose
hash no longer verifies.

## Pull and verify

`scripts/sparknet-model-pull.py` is the only puller.

- `--node agx64` selects teacher and embedding candidates.
- `--node agx32` selects student and embedding candidates.
- `--check` validates the catalog without network access.
- `--dry-run` prints the planned files and bytes.
- `--verify` re-hashes an existing model and fails on drift.
- The puller checks free disk before a download and refuses below the catalog's
  `min_free_gb`.
- The Hugging Face token, if needed, comes from `HF_TOKEN` or a path named by
  `--token-file`. It is never printed, written to a manifest or committed.
- Revision acceptance is an operator action; the puller records the resolved
  commit, so a later `main` move does not silently change a serving model.

Downloading a model is not training, not a share and not a knowledge arrival.
It is an operator deployment action.

## Runtime leases

The teacher listens on `127.0.0.1:8100` on `agx64`; the student listens on
`127.0.0.1:8101` on `agx32`. Both are node-local model surfaces, not fabric
edges: Open WebUI reaches them through the host network namespace, and the
firewall does not publish them.

`scripts/sparknet-model-runtime.py` is the only on-demand start/stop path.

A profile names:

- one catalog model id;
- one compose file, project and profile;
- the services to start;
- the model environment variable;
- approximate fast memory and a health URL;
- conflicts and an idle-stop window.

Rules:

1. **No concurrent conflicting models.** Starting a profile refuses while a
   conflicting lease is active unless `--replace` explicitly stops it first.
2. **Memory guard.** Start refuses if `MemAvailable` is below the profile's
   `memory_gb` plus the safety margin. `--force` is an operator override and is
   audited.
3. **Health before ready.** A start is not complete until the health URL
   answers. A failed health check stops the profile and removes the lease.
4. **Idle stop.** A lease expires after `idle_stop_minutes`; `reap` stops it.
   A session may be pinned by the operator, but never by a model.
5. **Training is exclusive.** The Master's student inference and any competing
   runtime must be stopped before the trainer starts. The training service asks
   for the lease; it does not run `docker` directly.
6. **No LLM control.** The runtime API is human/UI only. A model cannot start,
   stop or replace a profile.
7. **State is local.** Leases and the audit log live under
   `$SPARKNET_STATE_DIR/model-runtime/` at `0600`; they are not a vault page.

Stopping a container frees unified memory and GPU access. It does not free the
model files. Disk is managed by catalog removal, dangling-image pruning and
builder-cache pruning; Qdrant volumes and pinned rollback images are never
pruned by this contract.

## Failure semantics

- Missing model, failed hash, unpinned manifest: refuse to serve.
- Insufficient free disk: refuse the pull.
- Insufficient free memory: refuse the start.
- Health timeout: stop the profile and remove the lease.
- Conflicting lease: refuse unless `--replace` is explicit.
- Idle lease: stop; the next explicit start warms again.
- A stopped or failed runtime is never treated as a model answer.

## What this contract is not

- It is not a knowledge channel. Model presence may be reported as inventory
  metadata; model outputs are not knowledge until they enter the normal answer
  path.
- It is not authority. A running model cannot sign, grant, revoke or widen a
  capability.
- It is not a backup contract. Vault and Qdrant backups remain with the
  recovery runbook; model weights are reproduced from the catalog and hashes.
