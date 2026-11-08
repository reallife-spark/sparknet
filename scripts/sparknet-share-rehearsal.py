#!/usr/bin/env python3
"""Three-node share rehearsal — offer, accept, payload, queue, signed lift.

This is the executable version of the share wire tests, not a second lifecycle.
It builds three real vault roots under a temporary directory, signed registry
entries and real Ed25519 keys, then moves every message over the signed HTTP
listener:

1. alice offers ``kb-share`` to bob; bob accepts.
2. alice sends a payload; bob stages it under ``01_Inbox/share-<id>/``.
3. bob's accepted share is queued on the Master's 4203 listener; the listener
   has no signer and cannot decide it.
4. a separate "operator" ratifier signs the approval; the signed envelope is
   delivered to both peers and verified there against the pinned Master key.

The transcript names each assertion. A failed assertion exits nonzero. This is
loopback evidence for the wire and the human gate, not a live-overlay claim.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PEER_SERVICE = ROOT / "peer-node" / "services" / "sparknet-share-serve.py"
MASTER_SERVICE = ROOT / "master-node" / "services" / "sparknet-share-ratify.py"
SHARED = ROOT / "shared"
CONTRACTS = ROOT / "contracts"
NOW = datetime.now(timezone.utc)

PASS = 0
FAIL = 0


def _load(name: str, path: Path) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok    {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}" + (f" ({detail})" if detail else ""))


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class Listener:
    def __init__(self, http: Any, router: Any, *, public_key: Any = None, public_keys: dict | None = None):
        self.port = _free_port()
        self.server = http.serve(
            router,
            bind="127.0.0.1",
            port=self.port,
            public_key=public_key,
            public_keys=public_keys,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def _identity(node_id: str, overlay: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "role": "peer",
        "wireguard_public_key_b64": "wg-" + node_id,
        "overlay_ipv4": overlay,
        "requested_capabilities": ["p2p-sync"],
    }


def _build(work: Path, authz: Any, master: Any) -> tuple[dict[str, dict], dict, Any]:
    work.mkdir(parents=True, exist_ok=True)
    nodes = {
        name: _identity(name, f"10.100.0.{index}/32") for index, name in enumerate(("alice", "bob", "carol"), start=2)
    }
    entries = [authz.sign_authorization(identity, master, ["p2p-sync"], ttl_days=1) for identity in nodes.values()]
    registry = {
        "schema_version": "1.0",
        "master_public_key_b64": authz.public_key_b64(master.public_key()),
        "authorizations": entries,
    }
    for name in nodes:
        vault = work / name
        (vault / "manifests").mkdir(parents=True, exist_ok=True)
        (vault / "01_Inbox").mkdir(parents=True, exist_ok=True)
        (vault / "manifests" / "node-identity.json").write_text(json.dumps(nodes[name]))
        (vault / "manifests" / "node-authorizations.json").write_text(json.dumps(registry))
    keys = {}
    for name in nodes:
        _, private = authz.generate_keypair()
        keys[name] = authz.private_key_from_b64(private)
        (work / name / "http.pub.b64").write_text(authz.public_key_b64(keys[name].public_key()) + "\n")
    (work / "master.pub.b64").write_text(authz.public_key_b64(master.public_key()) + "\n")
    return nodes, registry, keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Three-node share rehearsal (loopback)")
    parser.add_argument(
        "--work",
        type=Path,
        default=Path("/tmp/opencode/share-rehearsal"),  # noqa: S108 - fixed rehearsal root
    )
    args = parser.parse_args(argv)
    work = args.work.resolve()
    if work in {Path("/"), Path.home().resolve(), Path.cwd().resolve()} or work in Path.cwd().resolve().parents:
        raise SystemExit(f"refusing to remove unsafe rehearsal directory {work}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    http = _load("sparknet_http_share_rehearsal", SHARED / "sparknet-http.py")
    authz = http._load_authz()
    peer_service = _load("sparknet_share_serve_rehearsal", PEER_SERVICE)
    master_service = _load("sparknet_share_ratify_rehearsal", MASTER_SERVICE)
    master = authz.private_key_from_b64(authz.generate_keypair()[1])
    nodes, registry, keys = _build(work, authz, master)

    def service(name: str) -> Any:
        return peer_service.ShareService(
            work / name,
            state_path=work / name / "shares.json",
            node_id=name,
            now=lambda: NOW,
            contracts_dir=CONTRACTS,
            master_public_key=master.public_key(),
        )

    alice, bob = service("alice"), service("bob")
    alice_listener = Listener(
        http,
        peer_service.router_for(alice),
        public_keys={"bob": keys["bob"].public_key(), "carol": master.public_key()},
    )
    bob_listener = Listener(
        http,
        peer_service.router_for(bob),
        public_keys={"alice": keys["alice"].public_key(), "carol": master.public_key()},
    )

    queue_path = work / "ratify-queue.json"
    ratifier = master_service.ShareRatifier(
        work / "bob" / "manifests" / "node-authorizations.json",
        authz=authz,
        clock=lambda: NOW,
        state_path=queue_path,
    )
    master_listener = Listener(
        http,
        master_service._ratify_router(ratifier),
        public_keys={"alice": keys["alice"].public_key(), "bob": keys["bob"].public_key()},
    )
    try:
        print("== offer / accept ==")
        offer = alice.offer("kb-share", toward="bob")
        status, body = http.post_json(bob_listener.url, "POST", "/v1/share/message", {"message": offer}, keys["alice"])
        check("offer reached bob", status == 200 and body.get("ok"), str(body))
        accept = bob.accept(offer["share_id"], "kb-share")
        status, body = http.post_json(alice_listener.url, "POST", "/v1/share/message", {"message": accept}, keys["bob"])
        check("accept reached alice", status == 200 and body.get("ok"), str(body))
        check(
            "three-node share opens flagged with a ratification clock",
            alice.get(offer["share_id"])["endpoints"]["bob"]["trust"] == "flagged"
            and alice.get(offer["share_id"])["ratification_deadline"] is not None,
        )

        print("== payload ==")
        status, body = http.post_json(
            bob_listener.url,
            "POST",
            "/v1/share/payload",
            {"share_id": offer["share_id"], "files": {"notes/rehearsal.md": "# rehearsal\n"}},
            keys["alice"],
        )
        staged = work / "bob" / "01_Inbox" / f"share-{offer['share_id']}" / "notes" / "rehearsal.md"
        check(
            "payload staged in bob's review inbox", status == 200 and staged.read_text() == "# rehearsal\n", str(body)
        )

        print("== 4203 queue (no auto-ratify) ==")
        grant = authz.mint_grant(
            node_identity=nodes["bob"],
            grant_id="grant-rehearsal",
            user_identity="operator",
            conversation_key="share-rehearsal",
            capabilities=["p2p-sync"],
            vault_scope=["."],
            ttl_minutes=60,
            nonce="nonce-rehearsal",
            master_private_key=master,
            registry=registry,
            now=NOW,
        )
        request = {
            "share_id": offer["share_id"],
            "node_id": "bob",
            "share_type": "kb-share",
            "accepted_at": accept["at"],
            "grant": grant,
        }
        status, body = http.post_json(
            master_listener.url, "POST", "/v1/share/request", {"request": request}, keys["bob"]
        )
        check("signed request queued on 4203", status == 202 and body.get("status") == "pending", str(body))
        check("listener decided nothing", not ratifier.ratifications)

        envelope = {
            "msg_type": "share.ratify",
            "share_id": offer["share_id"],
            "decision": True,
            "by": "carol",
            "at": NOW.isoformat(),
        }
        status, body = http.post_json(alice_listener.url, "POST", "/v1/share/message", {"message": envelope}, master)
        check(
            "unsigned ratification is refused",
            status == 403 and body.get("reason") == "unsigned-ratification",
            str(body),
        )

        print("== human approval and signed lift ==")
        operator = master_service.ShareRatifier(
            work / "bob" / "manifests" / "node-authorizations.json",
            signer=lambda ratification: authz.sign_share_ratification(ratification, master),
            authz=authz,
            clock=lambda: NOW,
            state_path=queue_path,
        )
        result = operator.ratify(offer["share_id"], "approve", "rehearsal operator")
        signed = result["ratification"]
        ratified = {**envelope, "ratification": signed}
        for name, listener in (("alice", alice_listener), ("bob", bob_listener)):
            status, body = http.post_json(listener.url, "POST", "/v1/share/message", {"message": ratified}, master)
            check(f"signed ratification verified by {name}", status == 200 and body.get("ok"), str(body))
        check(
            "both endpoints are authenticated and retain the flag",
            all(
                endpoint["trust"] == "authenticated" and "flagged" in endpoint["retained_flags"]
                for endpoint in alice.get(offer["share_id"])["endpoints"].values()
            ),
        )

        print(f"\nrehearsal: {PASS} passed, {FAIL} failed (transcript under {work})")
        return 0 if FAIL == 0 else 1
    finally:
        for listener in (alice_listener, bob_listener, master_listener):
            listener.close()


if __name__ == "__main__":
    raise SystemExit(main())
