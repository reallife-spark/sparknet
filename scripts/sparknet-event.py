#!/usr/bin/env python3
"""Publish or subscribe to one sparknet event on the NATS bus."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from sparknet_loader import load_shared

BUS = load_shared("sparknet-event-bus.py", "sparknet_event_bus_cli")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sparknet-event", description="Publish or receive one sparknet event")
    parser.add_argument("--url", default=os.environ.get("SPARKNET_NATS_URL", "nats://127.0.0.1:4222"))
    sub = parser.add_subparsers(dest="command", required=True)
    publish = sub.add_parser("publish", help="publish one envelope")
    publish.add_argument("--event", required=True, help="JSON file containing the event")
    subscribe = sub.add_parser("subscribe", help="receive one event")
    subscribe.add_argument("--subject", required=True)
    subscribe.add_argument("--timeout", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "publish":
            payload = json.loads(Path(args.event).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("event file must contain a JSON object")
            published = BUS.publish(args.url, payload)
            print(json.dumps({"published": len(published), "topic": payload.get("topic")}, sort_keys=True))
            return 0
        received = BUS.subscribe_once(args.url, args.subject, timeout=args.timeout)
        print(json.dumps(received, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, BUS.NatsError, BUS.EventError) as exc:
        print(f"sparknet-event: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
