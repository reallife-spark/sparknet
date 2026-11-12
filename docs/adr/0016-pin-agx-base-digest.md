# 0016 — Pin the AGX L4T base image by digest

## Status

Accepted (2026-11-12).

## Context

The AGX image builds from
`nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3`. The tag is release-shaped and
part of the resource-first L4T decision, but a tag can move. The AGX image is a
multi-hour source build, and a silently changed base would change the compiler,
CUDA runtime and Python baseline under the same tag.

The manifest-list digest resolved for that tag on 2026-11-12 is
`sha256:545a0f62fb4a5fd2d8c511134f6c55d451ae1565075dcc67123b0c422a469472`.

## Decision

Pin the AGX base by digest in both surfaces:

- the `L4T_BASE` default in `goagx/sparknet.agx.docker`;
- the compose build argument default in `goagx/sparknet.agx.compose.yml`.

Keep the `r35.2.1-pth2.0-py3` tag beside the digest so the platform intent stays
readable. The digest is the build identity; the tag is documentation.

## Consequences

- A rebuild cannot silently move to a different L4T/PyTorch base.
- Changing the base requires a new digest, a fresh ADR decision, and a goagx
  republish; the AgX node image is not a floating tag.
- The digest is platform-specific to this manifest list. A future base change
  must resolve the new digest on the target architecture before pinning.
- The existing `tests/test_agx_node.py` pin checks now require a digest on both
  surfaces.
