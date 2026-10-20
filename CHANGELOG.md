# Changelog

All notable changes to this fabric are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the version follows
`VERSION`, which is the single source of truth (SemVer).

Entries are written per release, not per commit: the commit history and
`log.md` carry the detail (see `STYLE_GUIDE.md` §10).

## [Unreleased]

- NVIDIA/dsx standard-practice adoption arc (PLAN Steps 45–52): reference-repo
  inventory, `STYLE_GUIDE.md`, resource-first `make nv-search`, community
  files, GitHub Actions mirror, format/lint sweep, functional adoptions.
- AGX Xavier node surface (`goagx/`, fabric PLAN Step 56): the node image
  remade for Jetson AGX Xavier (sm_72 / 16 GB — L4T r35 base, vLLM v0.2.7
  built from source behind `VLLM_CLI`, llama.cpp embed/rerank, whisper.cpp
  behind the OpenAI audio shim), an AGX compose twin with identical
  services/ports/profiles, `sparknet-node-setup.sh --platform spark|agx`,
  and the parity gates in `tests/test_agx_node.py`.

## [0.1.0] — initial version

- The fabric: `contracts/` + `shared/` as the cross-role source of truth;
  `peer-node/` implemented; `master-node/` built with the isolated signer
  (election/signer arc proven live 2026-10-07).
- Local gates: `make ci`, `make test-all`, `make contract-test`,
  `make drift-check`, `make keys-check`, `make shims-check`; deterministic
  CycloneDX SBOM under `sbom/`.
- DGX Spark node image surface: `spark.docker`, `spark.compose.yml`,
  `spark-entrypoint.sh`, `sparknet-node-setup.sh`, including the CPU/stub tier
  that runs without a GPU.
