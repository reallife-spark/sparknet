"""overlay"""

from __future__ import annotations

import json
import re

from contract_helpers import (
    BROADCAST_HOST,
    MASTER,
    MASTER_HOST,
    PEER,
)


def test_master_is_the_anchor_and_the_peer_prefix_agrees(overlay: dict):
    prefix = overlay["master_anchor_ipv4"]
    assert prefix.startswith(overlay["peer_prefix"]), (
        f"the Master address {prefix} does not share the peer prefix "
        f"{overlay['peer_prefix']} — the two roles would compute different networks"
    )
    assert int(prefix.rsplit(".", 1)[1]) == MASTER_HOST
    assert prefix in overlay["reserved_peer_addresses"], "the Master address must be reserved against peer assignment"


def test_peer_range_excludes_the_master_and_the_broadcast(overlay: dict):
    low, high = overlay["peer_host_range"]
    assert low > MASTER_HOST, "the peer range must start above the Master address"
    assert high < BROADCAST_HOST, "the peer range must stop below the broadcast address"
    assert low <= high
    for reserved in overlay["reserved_peer_addresses"]:
        host = int(reserved.rsplit(".", 1)[1])
        assert not (low <= host <= high), f"{reserved} is reserved but sits inside the assignable peer range"


def test_peer_identity_is_a_single_host_inside_the_range(overlay: dict):
    identity = json.loads((PEER / "manifests" / "node-identity.json").read_text())
    address = identity["overlay_ipv4"]
    assert address.endswith(overlay["peer_mask"]), (
        f"a peer must be a {overlay['peer_mask']} host route, got {address} — a wider "
        f"mask would let it route for a sibling"
    )
    host = int(address.split("/")[0].rsplit(".", 1)[1])
    low, high = overlay["peer_host_range"]
    assert low <= host <= high, f"peer host {host} outside the contract range [{low}, {high}]"
    assert host != MASTER_HOST, "a peer must never claim the Master address"


def test_both_templates_use_the_contract_mtu_and_keepalive(overlay: dict):
    """A mismatch is invisible in review and shows up only as odd throughput."""
    mtu, keepalive = str(overlay["mtu"]), str(overlay["persistent_keepalive"])
    for path in (
        PEER / "configs" / "wireguard" / "wg0-node.conf.template",
        MASTER / "configs" / "wireguard" / "master-peer.template",
    ):
        text = path.read_text()
        assert f"MTU = {mtu}" in text, (
            f"{path.name} does not use the contract MTU {mtu} (contracts/overlay.json carries the rationale)"
        )
    peer_text = (PEER / "configs" / "wireguard" / "wg0-node.conf.template").read_text()
    assert f"PersistentKeepalive = {keepalive}" in peer_text, (
        "the peer template must keep the NAT mapping open, as the contract says"
    )


def test_master_template_offers_only_single_host_routes():
    """A wide master-side AllowedIPs would let a peer source-spoof a sibling.

    The placeholder form (`${NODE_ADDRESS}`) is correct — it defers to the
    signed entry. What must not appear is a *literal* that is wider than one
    host, because that is what someone would copy into production.
    """
    text = (MASTER / "configs" / "wireguard" / "master-peer.template").read_text()
    literals = re.findall(r"AllowedIPs\s*=\s*(\S+)", text)
    assert literals, "the template should show at least the AllowedIPs form to render"
    for value in literals:
        if "$" in value:
            continue  # a placeholder is rendered from the signed entry
        for part in value.split(","):
            part = part.strip()
            assert part.endswith("/32"), (
                f"master-side AllowedIPs offers {part!r}, wider than a single host — "
                f"that peer could then source-spoof a sibling "
                f"(contracts/overlay.json `peer_allowed_ips_rule`)"
            )
    assert overlay_rule_reference(text), "the master template must state the single-host rule"


def overlay_rule_reference(text: str) -> bool:
    return bool(re.search(r"only its own overlay address|source-spoof", text, re.I))


def test_templates_document_the_immutable_pin_and_config_mode(overlay: dict):
    """A peer config that is writable is a peer config a compromised peer owns."""
    assert overlay["pinned_immutable"] is True
    assert overlay["config_mode"] == "0600"
    text = (PEER / "configs" / "wireguard" / "wg0-node.conf.template").read_text()
    assert "chattr" in text, "the peer template must document the +i pin"
    assert "0600" in text, "the peer template must state the config mode from the contract"


def test_peer_template_anchors_on_the_master_address(overlay: dict):
    text = (PEER / "configs" / "wireguard" / "wg0-node.conf.template").read_text()
    assert f"{overlay['master_anchor_ipv4']}{overlay['peer_mask']}" in text, (
        "the peer's master-side AllowedIPs must be exactly the Master /32"
    )
