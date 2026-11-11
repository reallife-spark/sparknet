"""Compatibility path for the split contract suite.

The contract conformance tests now live in ``tests/contracts/`` and are run as a
directory by ``make test-all`` and ``peer-node/Makefile:guard-contract``. This
file stays as a thin, test-free marker because the Phase 8 remediation register
still names it; a split must not make a historical inventory claim point at a
missing file.
"""

from __future__ import annotations
