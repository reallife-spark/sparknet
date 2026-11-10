"""The one build-time skill catalog engine.

The four existing sync scripts remain the family adapters:

- ``scripts/sync-wiki-skills.py``
- ``scripts/sync-mattpocock-skills.py``
- ``scripts/sync-understand-skills.py``
- ``scripts/sync-role-skills.py``

They own their family policy and transforms. This package owns the repeated
mechanics: tree copy, digests, manifest read/write, host-path refusal and
missing-source handling. The external manifest shapes are deliberately stable.
"""

from .engine import (
    copy_tree,
    file_digest,
    host_path_hits,
    prune_symlinks,
    read_manifest,
    sha256_bytes,
    source_available,
    source_digest,
    tree_digest,
    write_manifest,
)

__all__ = [
    "copy_tree",
    "file_digest",
    "host_path_hits",
    "prune_symlinks",
    "read_manifest",
    "sha256_bytes",
    "source_available",
    "source_digest",
    "tree_digest",
    "write_manifest",
]
