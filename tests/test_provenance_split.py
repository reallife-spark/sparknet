"""Stage 1 of ADR-0006: one facade over provenance primitives and scanning.

The split is intentionally narrow. ``base`` owns the canonical form, crypto
loaders, contract reader, time/key-path helpers and shared key-shaped patterns;
``scan`` owns the secret detector. Every other lifecycle stays in the facade
until Stage 2, so this suite pins the seam that exists today rather than the
one the final split will add.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import ModuleType

import pytest
from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"
BASE_PATH = SHARED / "sparknet-provenance-base.py"
SCAN_PATH = SHARED / "sparknet-provenance-scan.py"
FACADE_PATH = SHARED / "sparknet-provenance.py"
YAML_PATH = SHARED / "sparknet-yaml.py"

# Every name an external caller or test reaches through the facade today. This
# is the compatibility surface, including the private names callers already
# use; Stage 2 must keep all of them.
COMPAT_NAMES = {
    "CO_SIGNATURE_FIELDS",
    "DEFAULT_SHARED_DIR",
    "FrontmatterError",
    "INBOX_SOURCES",
    "INBOX_UNTRUSTED_SOURCES",
    "ProvenanceError",
    "SECRET_INDEX_ENTRY_KEYS",
    "SECRET_INDEX_FORBIDDEN",
    "USER_KEY_FIELDS",
    "USER_RECORD_KEYS",
    "USER_RECORD_REF",
    "_PATTERNS",
    "_SCAN_EXEMPT",
    "_iso",
    "_load_authz",
    "_load_merkle",
    "_node_id",
    "_now",
    "_recorded_from_signature",
    "_verify_lock",
    "add_co_signature",
    "anchor",
    "append_block",
    "block_header_signable",
    "build_approval_data",
    "build_checkpoint_data",
    "build_conversation_root",
    "build_inbox_acceptance",
    "canonical_json",
    "check_shims",
    "check_user_record",
    "checkpoint",
    "consumed_grant_nonces",
    "contract",
    "dual_sign",
    "emit_note",
    "emit_yaml",
    "fingerprint_label_of_public_b64",
    "grant_scope_allows",
    "ingest_note",
    "iso",
    "load_anchored",
    "load_ledger",
    "main",
    "node_id",
    "node_public_b64",
    "note_message",
    "note_paths",
    "now",
    "parse_user_record",
    "parse_yaml_subset",
    "patch_granted_note",
    "promote_granted_note",
    "safe_vault_target",
    "scan",
    "sha256_hex",
    "sign_note",
    "split_note",
    "tracking_of",
    "user_fingerprint",
    "user_init",
    "user_is_filled",
    "user_public_b64",
    "user_record_path",
    "verify_approval_blocks",
    "verify_chain",
    "verify_checkpoint",
    "verify_co_signatures",
    "verify_note",
    "verify_vault",
    "write_granted_note",
}


def _load(name: str, path: Path) -> ModuleType:
    return load_by_path(name, path)


@pytest.fixture(scope="module")
def base() -> ModuleType:
    return _load("sparknet_provenance_base", BASE_PATH)


@pytest.fixture(scope="module")
def scan() -> ModuleType:
    return _load("sparknet_provenance_scan", SCAN_PATH)


@pytest.fixture(scope="module")
def yaml_module() -> ModuleType:
    return _load("sparknet_yaml", YAML_PATH)


@pytest.fixture(scope="module")
def facade() -> ModuleType:
    return _load("sparknet_provenance_stage1_test", FACADE_PATH)


def _top_level_functions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _loaded_filenames(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "load_shared" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.add(first.value)
    return names


def test_stage_one_files_exist() -> None:
    assert BASE_PATH.is_file()
    assert SCAN_PATH.is_file()
    assert FACADE_PATH.is_file()


def test_the_one_error_class_survives_the_split(base: ModuleType, yaml_module: ModuleType, facade: ModuleType) -> None:
    assert base.ProvenanceError is yaml_module.ProvenanceError
    assert facade.ProvenanceError is yaml_module.ProvenanceError
    assert facade.FrontmatterError is yaml_module.FrontmatterError
    assert issubclass(facade.FrontmatterError, facade.ProvenanceError)


def test_facade_reexports_exactly_the_stage_one_interfaces(
    base: ModuleType, scan: ModuleType, facade: ModuleType
) -> None:
    for module in (base, scan):
        for name in module.__all__:
            assert hasattr(facade, name), f"facade lost stage-one export {name}"
            assert getattr(facade, name) is getattr(module, name), f"{name} is not the same object"


def test_the_compatibility_surface_is_still_present(facade: ModuleType) -> None:
    missing = sorted(name for name in COMPAT_NAMES if not hasattr(facade, name))
    assert missing == [], f"facade lost caller-visible names: {missing}"
    assert callable(facade.main)


def test_primitives_have_one_definition_and_lifecycle_verbs_stay_out(
    base: ModuleType, scan: ModuleType, facade: ModuleType
) -> None:
    base_functions = set(_top_level_functions(BASE_PATH))
    scan_functions = set(_top_level_functions(SCAN_PATH))
    facade_functions = set(_top_level_functions(FACADE_PATH))

    primitives = {
        "canonical_json",
        "sha256_hex",
        "_load_authz",
        "_load_merkle",
        "_load_abac",
        "contract",
        "_now",
        "_iso",
        "_state_dir",
        "_user_key_path",
        "_node_key_path",
        "_find_vault_from_cwd",
        "_refuse_loose_key",
        "_node_id",
    }
    assert primitives <= base_functions
    assert not (primitives & facade_functions), "a primitive is still defined in the facade"
    assert not (primitives & scan_functions), "the scanner reimplemented a primitive"

    scanner = {"scan", "_tracked_files", "_resolve_secret_ref"}
    assert scanner <= scan_functions
    assert not (scanner & facade_functions), "the scanner is still defined in the facade"
    assert not (scanner & base_functions), "the primitives module carries scanner policy"

    lifecycle = {"sign_note", "verify_note", "append_block", "write_granted_note", "verify_vault"}
    assert not (lifecycle & base_functions), "base must not carry a lifecycle verb"
    assert not (lifecycle & scan_functions), "scan must not carry a lifecycle verb"
    assert lifecycle <= facade_functions, "stage 1 must leave the lifecycle verbs in the facade"


def test_scan_depends_only_on_the_primitives(scan: ModuleType, base: ModuleType) -> None:
    filenames = _loaded_filenames(SCAN_PATH)
    assert filenames == {"sparknet-provenance-base.py"}
    assert scan.scan is not None
    assert base.canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_no_provenance_module_carries_crypto() -> None:
    offenders = [
        path.name
        for path in SHARED.glob("sparknet-provenance*.py")
        if "import cryptography" in path.read_text() or "from cryptography" in path.read_text()
    ]
    assert offenders == [], f"a provenance module imports cryptography: {offenders}"


def test_scanner_exempts_the_pattern_definitions_it_uses(scan: ModuleType) -> None:
    assert "shared/sparknet-provenance.py" in scan._SCAN_EXEMPT
    assert "shared/sparknet-provenance-base.py" in scan._SCAN_EXEMPT
    assert "shared/sparknet-provenance-scan.py" in scan._SCAN_EXEMPT
