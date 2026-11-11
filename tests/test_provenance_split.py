"""One provenance facade over lifecycle modules (ADR-0006/0007).

The facade stays the only path callers load. ``base`` owns the canonical form,
crypto loaders, contract reader, time/key-path helpers and shared patterns;
``scan`` owns secret scanning; ``note``, ``ledger`` and ``grant`` own their
lifecycle seams. This suite pins the module boundaries and the compatibility
surface so a future change cannot quietly reintroduce a second implementation.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import ModuleType

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"
BASE_PATH = SHARED / "sparknet-provenance-base.py"
SCAN_PATH = SHARED / "sparknet-provenance-scan.py"
NOTE_PATH = SHARED / "sparknet-provenance-note.py"
LEDGER_PATH = SHARED / "sparknet-provenance-ledger.py"
GRANT_PATH = SHARED / "sparknet-provenance-grant.py"
FACADE_PATH = SHARED / "sparknet-provenance.py"
YAML_PATH = SHARED / "sparknet-yaml.py"

# Every name an external caller or test reaches through the facade today. This
# is the compatibility surface, including the private names callers already
# use; the lifecycle split must keep all of them.
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
def note() -> ModuleType:
    return _load("sparknet_provenance_note", NOTE_PATH)


@pytest.fixture(scope="module")
def ledger() -> ModuleType:
    return _load("sparknet_provenance_ledger", LEDGER_PATH)


@pytest.fixture(scope="module")
def grant() -> ModuleType:
    return _load("sparknet_provenance_grant", GRANT_PATH)


@pytest.fixture(scope="module")
def yaml_module() -> ModuleType:
    return _load("sparknet_yaml", YAML_PATH)


@pytest.fixture(scope="module")
def facade() -> ModuleType:
    return _load("sparknet_provenance_split_facade", FACADE_PATH)


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


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


def test_all_lifecycle_files_exist() -> None:
    for path in (BASE_PATH, SCAN_PATH, NOTE_PATH, LEDGER_PATH, GRANT_PATH, FACADE_PATH):
        assert path.is_file(), path


def test_one_error_class_survives_the_split(
    base: ModuleType,
    note: ModuleType,
    ledger: ModuleType,
    grant: ModuleType,
    yaml_module: ModuleType,
    facade: ModuleType,
) -> None:
    for module in (base, note, ledger, grant, facade):
        assert module.ProvenanceError is yaml_module.ProvenanceError
    assert facade.FrontmatterError is yaml_module.FrontmatterError
    assert issubclass(facade.FrontmatterError, facade.ProvenanceError)


def test_facade_reexports_every_lifecycle_interface(
    base: ModuleType,
    scan: ModuleType,
    note: ModuleType,
    ledger: ModuleType,
    grant: ModuleType,
    facade: ModuleType,
) -> None:
    for module in (base, scan, note, ledger, grant):
        for name in module.__all__:
            assert hasattr(facade, name), f"facade lost export {name}"
            assert getattr(facade, name) is getattr(module, name), f"{name} is not the same object"


def test_the_compatibility_surface_is_still_present(facade: ModuleType) -> None:
    missing = sorted(name for name in COMPAT_NAMES if not hasattr(facade, name))
    assert missing == [], f"facade lost caller-visible names: {missing}"
    assert set(facade.__all__) >= COMPAT_NAMES
    assert callable(facade.main)


def test_facade_has_only_the_cli_adapter() -> None:
    assert _top_level_functions(FACADE_PATH) == {"_resolve_vault", "main"}


def test_each_lifecycle_owns_its_verbs(
    base: ModuleType,
    scan: ModuleType,
    note: ModuleType,
    ledger: ModuleType,
    grant: ModuleType,
) -> None:
    base_functions = _top_level_functions(BASE_PATH)
    scan_functions = _top_level_functions(SCAN_PATH)
    note_functions = _top_level_functions(NOTE_PATH)
    ledger_functions = _top_level_functions(LEDGER_PATH)
    grant_functions = _top_level_functions(GRANT_PATH)

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
    assert not (primitives & (scan_functions | note_functions | ledger_functions | grant_functions))

    scanner = {"scan", "_tracked_files", "_resolve_secret_ref"}
    assert scanner <= scan_functions
    assert not (scanner & (base_functions | note_functions | ledger_functions | grant_functions))

    note_verbs = {"sign_note", "verify_note", "add_co_signature", "verify_co_signatures", "ingest_note"}
    assert note_verbs <= note_functions
    assert not (note_verbs & (base_functions | scan_functions | ledger_functions | grant_functions))

    ledger_verbs = {"append_block", "verify_chain", "build_inbox_acceptance", "verify_vault", "checkpoint"}
    assert ledger_verbs <= ledger_functions
    assert not (ledger_verbs & (base_functions | scan_functions | note_functions | grant_functions))

    grant_verbs = {"write_granted_note", "promote_granted_note", "patch_granted_note", "grant_scope_allows"}
    assert grant_verbs <= grant_functions
    assert not (grant_verbs & (base_functions | scan_functions | note_functions | ledger_functions))


def test_dependency_direction_is_lifecycle_order() -> None:
    assert _loaded_filenames(SCAN_PATH) == {"sparknet-provenance-base.py"}
    assert _loaded_filenames(NOTE_PATH) == {"sparknet-provenance-base.py"}
    assert _loaded_filenames(LEDGER_PATH) == {
        "sparknet-provenance-base.py",
        "sparknet-provenance-note.py",
    }
    assert _loaded_filenames(GRANT_PATH) == {
        "sparknet-provenance-base.py",
        "sparknet-provenance-note.py",
        "sparknet-provenance-ledger.py",
    }


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


def test_acceptance_and_vault_verification_live_in_the_ledger(ledger: ModuleType, grant: ModuleType) -> None:
    assert ledger.build_inbox_acceptance.__module__ == "sparknet_provenance_ledger"
    assert ledger.verify_vault.__module__ == "sparknet_provenance_ledger"
    assert grant.write_granted_note.__module__ == "sparknet_provenance_grant"
