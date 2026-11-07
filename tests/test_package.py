"""Packages are signed data with a closed dependency plan; nothing executes."""

from __future__ import annotations

import hashlib
import importlib.util
import sys

import pytest
from contract_helpers import REPO_ROOT, load

PACKAGE_PATH = REPO_ROOT / "shared" / "sparknet-package.py"


def _load_package():
    spec = importlib.util.spec_from_file_location("sparknet_package", PACKAGE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


package = _load_package()
DIGEST = hashlib.sha256(b"artifact").hexdigest()


def artifact(path="bin/tool", data=b"artifact"):
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def manifest(package_id="tool", version="1.0.0", dependencies=(), artifacts=None):
    return package.make_package(
        package_id=package_id,
        version=version,
        artifacts=artifacts or [artifact()],
        dependencies=dependencies,
        signer_node_id="master",
    )


def test_contract_vocabularies_match_the_module():
    schema = load("package-schema.json")
    assert schema["package"]["schema"] == package.PACKAGE_SCHEMA
    assert schema["index"]["schema"] == package.INDEX_SCHEMA
    assert set(schema["refusal_codes"]) >= {"dependency-cycle", "unknown-package", "bad-digest"}


def test_package_is_canonical_and_artifact_verified():
    built = manifest()
    assert package.package_message(built)
    assert package.verify_artifact(built["artifacts"][0], b"artifact") is True
    assert package.verify_artifact(built["artifacts"][0], b"tampered") is False


def test_bad_digest_and_path_are_refused():
    with pytest.raises(package.PackageError) as refused:
        manifest(artifacts=[{"path": "bin/tool", "sha256": "nope", "size": 1}])
    assert refused.value.code == "bad-digest"
    with pytest.raises(package.PackageError) as escaped:
        manifest(artifacts=[{"path": "../tool", "sha256": DIGEST, "size": 1}])
    assert escaped.value.code == "bad-artifact-path"


def test_duplicate_package_versions_are_refused():
    with pytest.raises(package.PackageError):
        package.make_index([manifest(), manifest()])


def test_install_plan_is_dependency_first():
    lib = manifest(package_id="lib", version="1.0.0")
    app = manifest(package_id="app", version="1.0.0", dependencies=[{"package_id": "lib", "version": "1.0.0"}])
    index = package.make_index([app, lib])
    plan = package.install_plan(index, [{"package_id": "app", "version": "1.0.0"}])
    assert plan == [
        {"package_id": "lib", "version": "1.0.0"},
        {"package_id": "app", "version": "1.0.0"},
    ]


def test_unknown_dependency_and_cycle_fail_closed():
    unknown = manifest(package_id="app", dependencies=[{"package_id": "missing", "version": "1.0.0"}])
    with pytest.raises(package.PackageError) as refused:
        package.install_plan(package.make_index([unknown]), [{"package_id": "app", "version": "1.0.0"}])
    assert refused.value.code == "unknown-package"

    a = manifest(package_id="a", dependencies=[{"package_id": "b", "version": "1.0.0"}])
    b = manifest(package_id="b", dependencies=[{"package_id": "a", "version": "1.0.0"}])
    with pytest.raises(package.PackageError) as cycle:
        package.install_plan(package.make_index([a, b]), [{"package_id": "a", "version": "1.0.0"}])
    assert cycle.value.code == "dependency-cycle"


def test_index_is_canonical_and_has_no_authority():
    index = package.make_index([manifest()])
    assert package.index_message(index)
    assert "capabilities" not in index
    assert "grant" not in index


def test_required_fields_are_not_defaulted():
    truncated = manifest()
    truncated.pop("dependencies")
    with pytest.raises(package.PackageError) as refused:
        package.validate_package(truncated)
    assert refused.value.code == "bad-dependency"
    unsigned = manifest()
    unsigned["signer_node_id"] = ""
    with pytest.raises(package.PackageError) as signer:
        package.validate_package(unsigned)
    assert signer.value.code == "malformed-package"


def test_dot_and_nul_paths_are_refused():
    for path in (".", "a/\x00b"):
        with pytest.raises(package.PackageError) as refused:
            manifest(artifacts=[{"path": path, "sha256": DIGEST, "size": 1}])
        assert refused.value.code == "bad-artifact-path"


def test_unreachable_cycle_is_refused():
    a = manifest(package_id="a", dependencies=[{"package_id": "b", "version": "1.0.0"}])
    b = manifest(package_id="b", dependencies=[{"package_id": "a", "version": "1.0.0"}])
    root = manifest(package_id="root")
    with pytest.raises(package.PackageError) as refused:
        package.install_plan(
            package.make_index([root, a, b]),
            [{"package_id": "root", "version": "1.0.0"}],
        )
    assert refused.value.code == "dependency-cycle"
