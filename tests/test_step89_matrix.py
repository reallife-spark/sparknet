"""Every Step 89 channel has a contract, implementation and evidence row."""

from __future__ import annotations

from contract_helpers import REPO_ROOT, load

STATES = {"contract", "loopback", "dry-run", "live", "implemented"}


def test_every_channel_has_contract_module_and_test():
    matrix = load("step89-matrix.json")
    ids = [row["id"] for row in matrix["channels"]]
    assert len(ids) == len(set(ids)), "duplicate channel id"
    for row in matrix["channels"]:
        assert row["state"] in STATES, row["id"]
        assert (REPO_ROOT / "contracts" / row["contract"]).is_file(), row["id"]
        if row["module"]:
            assert (REPO_ROOT / "shared" / row["module"]).is_file(), row["id"]
        assert row["tests"], row["id"]
        for test in row["tests"]:
            assert (REPO_ROOT / test).is_file(), f"{row['id']}: {test}"
        if row["state"] == "live":
            assert any(ch.isdigit() for ch in row["live"]), f"{row['id']} live row has no date"
