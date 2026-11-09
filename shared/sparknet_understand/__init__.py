"""The Understand-Anything core: a derived code-understanding graph.

The package is loaded by path from ``shared/sparknet-understand.py``. It is not
imported as an installed package, for the same reason the other shared modules
are loaded by path: a role must read the one implementation in this tree, not a
copy that happens to be on ``sys.path``.

Nothing here grants authority, writes a vault page or reaches the network. It
reads a repository, emits the graph defined by ``contracts/understand-schema.json``
and lets the node console or the Go service serve it.
"""

from .build import build_from_fragments, build_graph
from .core import (
    DATA_DIR,
    LEGACY_DATA_DIR,
    default_analyzed_at,
    diff_graphs,
    file_id,
    load_schema,
    make_edge,
    make_node,
    merge_fragments,
    normalize_graph,
    scan,
    validate_graph,
    write_graph,
)

__all__ = [
    "DATA_DIR",
    "LEGACY_DATA_DIR",
    "build_from_fragments",
    "build_graph",
    "default_analyzed_at",
    "diff_graphs",
    "file_id",
    "load_schema",
    "make_edge",
    "make_node",
    "merge_fragments",
    "normalize_graph",
    "scan",
    "validate_graph",
    "write_graph",
]
