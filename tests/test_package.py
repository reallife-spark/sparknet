"""Packages are signed data with a closed dependency plan; nothing executes."""

from __future__ import annotations

import hashlib
import sys

import pytest
from contract_helpers import REPO_ROOT, load
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sparknet_loader import load_by_path

PACKAGE_PATH = REPO_ROOT / "shared" / "sparknet-package.py"


def _load_package():
    return load_by_path("sparknet_package", PACKAGE_PATH)


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
    assert set(schema["artifact_selection"]["default_exclude_parts"]) == package.DEFAULT_EXCLUDE_PARTS
    assert set(schema["artifact_selection"]["default_exclude_names"]) == package.DEFAULT_EXCLUDE_NAMES


def test_directory_package_owns_excludes_and_never_follows_symlinks(tmp_path):
    root = tmp_path / "package"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tool").write_text("tool", encoding="utf-8")
    (root / ".env").write_text("HOST_LOCAL=1", encoding="utf-8")
    (root / "secrets-index.json").write_text("{}", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("no", encoding="utf-8")
    (root / "keys").mkdir()
    (root / "keys" / "node.key").write_text("no", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    (root / "bin" / "link").symlink_to(outside)

    built = package.make_package_from_directory(
        root,
        package_id="tool",
        version="1.0.0",
        signer_node_id="master",
    )
    assert [artifact["path"] for artifact in built["artifacts"]] == ["bin/tool"]


def test_directory_package_refuses_an_empty_or_symlink_only_root(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(package.PackageError) as refused:
        package.make_package_from_directory(empty, package_id="tool", version="1.0.0", signer_node_id="master")
    assert refused.value.code == "bad-artifact"

    linked = tmp_path / "linked"
    linked.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    (linked / "link").symlink_to(outside)
    with pytest.raises(package.PackageError) as symlink_only:
        package.make_package_from_directory(linked, package_id="tool", version="1.0.0", signer_node_id="master")
    assert symlink_only.value.code == "bad-artifact"


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


def test_package_and_index_signatures_verify_and_refuse_tampering():
    key = Ed25519PrivateKey.generate()
    public = key.public_key()
    signed = package.sign_package(manifest(), key)
    assert signed["signature_b64"]
    assert package.verify_package_signature(signed, public) is True
    signed["description"] = "tampered"
    assert package.verify_package_signature(signed, public) is False

    index = package.sign_index(package.make_index([manifest()]), key)
    assert package.verify_index_signature(index, public) is True
    index["updated_at"] = "2099-01-01T00:00:00Z"
    assert package.verify_index_signature(index, public) is False


def test_cli_install_verifies_signatures_and_copies_artifacts(tmp_path):
    import json
    import subprocess

    from contract_helpers import REPO_ROOT
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    authz = load_by_path("package_install_authz", REPO_ROOT / "shared" / "sparknet-authz.py")

    key = Ed25519PrivateKey.generate()
    signed = package.sign_package(manifest(artifacts=[{"path": "bin/tool", "sha256": DIGEST, "size": 8}]), key)
    index = package.sign_index(package.make_index([signed]), key)
    source = tmp_path / "source" / "tool" / "1.0.0"
    (source / "bin").mkdir(parents=True)
    (source / "bin" / "tool").write_bytes(b"artifact")
    (source / "package.json").write_text(json.dumps(signed))
    index_file = tmp_path / "index.json"
    index_file.write_text(json.dumps(index))
    public = tmp_path / "public.b64"
    public.write_text(authz.public_key_b64(key.public_key()))
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "sparknet-package.py"),
            "install",
            "--index",
            str(index_file),
            "--source",
            str(tmp_path / "source"),
            "--dest",
            str(tmp_path / "dest"),
            "--public-key",
            str(public),
            "--package",
            "tool@1.0.0",
            "--confirm",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "dest" / "tool" / "1.0.0" / "bin" / "tool").read_bytes() == b"artifact"
