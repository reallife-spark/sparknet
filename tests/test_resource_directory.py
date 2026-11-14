"""Resource directory canonicalisation and signature verification."""

from __future__ import annotations

from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "shared" / "sparknet-resource-directory.py"


@pytest.fixture(scope="module")
def resource():
    return load_by_path("sparknet_resource_directory_test", MODULE)


def test_canonical_is_field_bounded(resource) -> None:
    document = {
        "directory_id": "d1",
        "issued_at": "2026-11-14T00:00:00Z",
        "expires_at": "2026-11-15T00:00:00Z",
        "nodes": [{"node_id": "sparknet-node-0001"}],
        "signature_b64": "ignored",
    }
    text = resource.canonical(document).decode()
    assert "signature_b64" not in text
    assert '"nodes"' in text


def test_missing_field_refused(resource) -> None:
    with pytest.raises(ValueError, match="missing"):
        resource.canonical({"directory_id": "d1"})
