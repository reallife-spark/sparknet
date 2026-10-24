#!/usr/bin/env python3
"""Offline evaluation for the RAG reflex pilot (fabric scope only).

Reads ``tests/reflex/rag-golden.json`` — a small set of fabric queries with
the paths a human says are relevant — runs the real Chroma query path, and
reports the numbers Step 64E requires:

- precision@5 and recall@5, baseline versus reranked;
- shadow agreement@5 (how often the local reranker preserves the Chroma order);
- abstain rate (the fail-open path);
- p95 decision latency;
- cost per 1,000 queries (zero for the offline reranker; the live broker is
  measured in Step 64F).

The reranker is the same one ``scripts/sparknet-chroma.py --reflex`` uses, so
the evaluation cannot drift from the product. It is local and deterministic:
no network, no key, no chromadb *writes*. The scope is forced to ``fabric``
because the node and personal vaults are opt-in and require the data
governance decision in ``REFLEX_DECISION_DESIGN.md`` §7.

Usage::

    scripts/sparknet-reflex-eval.py [--mode shadow|assist] [--json FILE]
    REFLEX_LIVE=1 scripts/sparknet-reflex-eval.py --mode shadow
    REFLEX_LIVE=1 scripts/sparknet-reflex-eval.py --query "guard approval"

The live path is **operator-gated**. It refuses unless
``SPARKNET_REFLEX_GOVERNANCE=approved`` is set and the Master's broker
credential exists at ``$SPARKNET_STATE_DIR/secrets/typesafe-api-key`` with mode
0600. It then sends only fabric-allow-listed chunks to the Master broker, which
forwards them to Jev; no node or personal vault is read.

Exit codes: 0 ok, 1 user/golden error, 2 chromadb missing, 3 the index's
stamp does not match this build, 4 the live preflight is not satisfied.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import stat
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN = REPO_ROOT / "tests" / "reflex" / "rag-golden.json"
EXIT_PREFLIGHT = 4
RELEVANCE_INSTRUCTIONS = (
    "Is this passage sufficient to answer the query? Answer with a Noul probability: "
    "0 means it cannot help, 1 means it directly answers the query."
)


def _load_chroma():
    """Load ``sparknet-chroma.py`` (the filename is not a module name)."""
    path = REPO_ROOT / "scripts" / "sparknet-chroma.py"
    spec = importlib.util.spec_from_file_location("sparknet_chroma", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"reflex-eval: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_reflex():
    """Load the shared decision contract (the filename is not a module name)."""
    path = REPO_ROOT / "shared" / "sparknet-reflex.py"
    spec = importlib.util.spec_from_file_location("sparknet_reflex_eval_contract", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"reflex-eval: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def live_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The live pilot's settings, from the environment by default."""
    state_dir = Path(os.environ.get("SPARKNET_STATE_DIR", str(REPO_ROOT / ".state"))).expanduser()
    config = {
        "backend": os.environ.get("SPARKNET_REFLEX_BACKEND", "local"),
        "broker_url": os.environ.get("SPARKNET_REFLEX_BROKER_URL", "http://10.100.0.1:4224"),
        "governance": os.environ.get("SPARKNET_REFLEX_GOVERNANCE", ""),
        "key_file": str(state_dir / "secrets" / "typesafe-api-key"),
        "model": os.environ.get("SPARKNET_REFLEX_MODEL", "local"),
        "node_id": os.environ.get("SPARKNET_NODE_ID", "reflex-eval"),
        "policy_version": "rag-relevance-v1",
        "timeout": float(os.environ.get("SPARKNET_REFLEX_TIMEOUT", "2.0")),
        "usd_per_1k_tokens": float(os.environ.get("SPARKNET_REFLEX_USD_PER_1K_TOKENS", "0.0")),
    }
    if overrides:
        config.update({key: value for key, value in overrides.items() if value is not None})
    return config


def live_preflight(*, config: dict[str, Any], check_health: bool = True) -> list[str]:
    """Everything that must be true before fabric text may leave the node."""
    problems: list[str] = []
    backend = str(config.get("backend", "local")).strip().lower()
    egress = backend in {"jev", "broker", "cloud"}
    if egress:
        if config["governance"] != "approved":
            problems.append(
                "data-governance approval missing: set SPARKNET_REFLEX_GOVERNANCE=approved "
                "only after the REFLEX_DECISION_DESIGN.md §7 review"
            )
        key_file = Path(config["key_file"])
        if not key_file.is_file():
            problems.append(f"broker credential missing: {key_file}")
        else:
            mode = stat.S_IMODE(key_file.stat().st_mode)
            if mode & 0o077:
                problems.append(f"broker credential must be 0600 (found {oct(mode)}): {key_file}")
    if check_health:
        try:
            with urllib.request.urlopen(config["broker_url"].rstrip("/") + "/healthz", timeout=2.0) as response:
                health = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"broker unreachable at {config['broker_url']}: {exc}")
        else:
            if not (isinstance(health, dict) and health.get("ok") is True):
                problems.append(f"broker healthz is not {{'ok': true}}: {health!r}")
    return problems


def post_decision(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """One broker call; every transport/shape failure is a first-class abstain."""
    payload = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    http_request = urllib.request.Request(
        config["broker_url"].rstrip("/") + "/v1/reflex/decide",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=config["timeout"]) as response:
            decision = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return {"verdict": "abstain", "confidence": None, "backend": "null", "usage": None, "_reason": "broker-error"}
    if not isinstance(decision, dict) or decision.get("verdict") not in ("accept", "reject", "abstain"):
        return {
            "verdict": "abstain",
            "confidence": None,
            "backend": "null",
            "usage": None,
            "_reason": "broker-malformed",
        }
    return decision


def live_relevance(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    reflex,
    post,
    config: dict[str, Any],
    limit: int,
) -> tuple[list[dict[str, Any]], bool, str, float, int]:
    """Score up to ``limit`` candidates through the broker, then order them.

    Returns ``(ordered, abstained, backend, latency_ms, tokens)``. A rejected
    chunk sorts below an abstained/unscored one; an accepted chunk sorts above
    both, by confidence. Any individual failure is an abstain, never an error.
    """
    if not candidates:
        return [], True, "null", 0.0, 0
    started = time.perf_counter()
    scored: dict[int, tuple[float, str]] = {}
    tokens = 0
    backend = "null"
    for index, candidate in enumerate(candidates[:limit]):
        request = reflex.make_request(
            "rag.relevance",
            {"query": query, "chunk": candidate.get("document", "")},
            {"relevant": {"type": "noul", "instructions": RELEVANCE_INSTRUCTIONS}},
            config["model"],
            config["policy_version"],
            config["node_id"],
            "rag-" + hashlib.sha256(f"{query}\0{candidate.get('id')}".encode()).hexdigest()[:16],
        )
        try:
            decision = post(request)
        except Exception:
            decision = {"verdict": "abstain", "confidence": None, "usage": None}
        verdict = decision.get("verdict") if isinstance(decision, dict) else "abstain"
        if isinstance(decision, dict) and decision.get("backend"):
            backend = str(decision["backend"])
        if verdict == "accept":
            score = float(decision.get("confidence") or 0.0)
        elif verdict == "reject":
            score = -1.0
        else:
            verdict = "abstain"
            score = 0.0
        scored[index] = (score, verdict)
        usage = decision.get("usage") if isinstance(decision, dict) else None
        if isinstance(usage, dict):
            tokens += int(usage.get("total_tokens") or usage.get("totalTokens") or 0)
    latency_ms = (time.perf_counter() - started) * 1000.0
    order = sorted(range(len(candidates)), key=lambda index: (-scored.get(index, (0.0, "abstain"))[0], index))
    ordered = [
        {
            **candidates[index],
            "reflex_score": round(scored.get(index, (0.0, "abstain"))[0], 6),
            "reflex_verdict": scored.get(index, (0.0, "abstain"))[1],
        }
        for index in order
    ]
    abstained = all(verdict == "abstain" for _score, verdict in scored.values()) if scored else True
    return ordered, abstained, backend, latency_ms, tokens


def precision_at_k(retrieved: list[str], expected: list[str], k: int = 5) -> float:
    """Fraction of the top ``k`` results that are relevant."""
    top = retrieved[:k]
    if not top:
        return 0.0
    # Positional, not set-based: every chunk from a relevant page counts, so a
    # page that fills all five slots scores 1.0 instead of 1/5.
    return sum(1 for path in top if path in expected) / len(top)


def recall_at_k(retrieved: list[str], expected: list[str], k: int = 5) -> float:
    """Fraction of the relevant paths found in the top ``k`` results."""
    if not expected:
        return 0.0
    return len(set(retrieved[:k]) & set(expected)) / len(expected)


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; deterministic for the tiny samples here."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def load_golden(path: Path) -> dict[str, Any]:
    """Read and validate the golden set; fail loudly on a malformed one."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"reflex-eval: cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise SystemExit(f"reflex-eval: {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("queries"), list):
        raise SystemExit(f"reflex-eval: {path} needs a 'queries' list")
    for number, item in enumerate(payload["queries"], start=1):
        if not isinstance(item, dict) or not isinstance(item.get("query"), str) or not item["query"].strip():
            raise SystemExit(f"reflex-eval: query {number} has no text")
        expected = item.get("expected")
        if not isinstance(expected, list) or not expected or not all(isinstance(p, str) for p in expected):
            raise SystemExit(f"reflex-eval: query {number} needs a non-empty 'expected' list of paths")
    return payload


def evaluate(
    chroma,
    scope: str,
    vault: Path,
    data_dir: Path,
    golden: dict[str, Any],
    mode: str,
    top_k: int,
    candidate_k: int,
    *,
    live: bool = False,
    reflex=None,
    post=None,
    config: dict[str, Any] | None = None,
    limit: int = 10,
    rate: float = 0.0,
) -> dict[str, Any]:
    """Run one mode over the golden set and return the measured summary."""
    if scope != "fabric":
        raise SystemExit("reflex-eval: the first pilot is the fabric scope only")
    config = config or live_config()
    collection = chroma.open_checked(scope, vault, data_dir, log_prefix="reflex-eval")
    rows: list[dict[str, Any]] = []
    for item in golden["queries"]:
        query = item["query"]
        expected = list(item["expected"])
        candidates = chroma.query_candidates(scope, data_dir, collection, query, candidate_k)
        baseline = [candidate["path"] for candidate in candidates[:top_k]]
        if live:
            ordered, abstained, backend, latency_ms, tokens = live_relevance(
                query, candidates, reflex=reflex, post=post, config=config, limit=limit
            )
        else:
            ordered, abstained, backend, latency_ms = chroma.rerank_candidates(query, candidates)
            tokens = 0
        reranked = [candidate["path"] for candidate in ordered[:top_k]]
        served = baseline if (mode == "shadow" or abstained) else reranked
        rows.append(
            {
                "abstained": abstained,
                "backend": backend,
                "baseline": baseline,
                "expected": expected,
                "latency_ms": latency_ms,
                "query": query,
                "tokens": tokens,
                "reranked": reranked,
                "served": served,
                "served_precision": precision_at_k(served, expected, top_k),
                "reranked_precision": precision_at_k(reranked, expected, top_k),
                "recall": recall_at_k(served, expected, top_k),
                "agreement": chroma.order_overlap(baseline, reranked),
            }
        )
    count = len(rows)
    tokens_per_query = (sum(row["tokens"] for row in rows) / count) if count else 0.0
    return {
        "abstain_rate": _mean([1.0 if row["abstained"] else 0.0 for row in rows]),
        "baseline_precision_at_k": _mean([precision_at_k(row["baseline"], row["expected"], top_k) for row in rows]),
        "backend": rows[0]["backend"] if rows else ("null" if live else "rules"),
        "candidate_k": candidate_k,
        "cost_per_1k_usd": tokens_per_query * rate,
        "live": live,
        "live_candidates": limit if live else 0,
        "mode": mode,
        "model": config["model"] if live else "local-rules",
        "p95_latency_ms": percentile([row["latency_ms"] for row in rows], 0.95),
        "queries": count,
        "recall_at_k": _mean([row["recall"] for row in rows]),
        "reranked_precision_at_k": _mean([row["reranked_precision"] for row in rows]),
        "rows": rows,
        "scope": scope,
        "served_precision_at_k": _mean([row["served_precision"] for row in rows]),
        "shadow_agreement_at_k": _mean([row["agreement"] for row in rows]),
        "tokens_per_1k_queries": tokens_per_query * 1000.0,
        "top_k": top_k,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print(
        f"reflex-eval: scope={summary['scope']} queries={summary['queries']} "
        f"mode={summary['mode']} backend={summary['backend']} candidate_k={summary['candidate_k']}"
    )
    print(f"  baseline precision@{summary['top_k']} = {summary['baseline_precision_at_k']:.3f}")
    print(
        f"  reranked precision@{summary['top_k']} = {summary['reranked_precision_at_k']:.3f} "
        f"(served {summary['served_precision_at_k']:.3f})"
    )
    print(f"  recall@{summary['top_k']} = {summary['recall_at_k']:.3f}")
    print(f"  shadow agreement@{summary['top_k']} = {summary['shadow_agreement_at_k']:.3f}")
    print(f"  abstain rate = {summary['abstain_rate']:.3f}")
    print(f"  p95 latency = {summary['p95_latency_ms']:.3f} ms")
    if summary["live"]:
        print(f"  tokens / 1k queries = {summary['tokens_per_1k_queries']:.0f} (model {summary['model']}, live broker)")
        print(
            f"  cost / 1k queries = ${summary['cost_per_1k_usd']:.4f} "
            f"(set SPARKNET_REFLEX_USD_PER_1K_TOKENS to price it)"
        )
    else:
        print(f"  cost / 1k queries = ${summary['cost_per_1k_usd']:.4f} (local, no egress)")
    if summary["mode"] == "shadow":
        print("  note: shadow returns the baseline order; reranked precision is the candidate signal")
    for row in summary["rows"]:
        flag = "ABSTAIN" if row["abstained"] else "ok"
        print(
            f"  [{flag:7}] p={row['served_precision']:.2f} agree={row['agreement']:.2f} "
            f"{row['latency_ms']:.3f} ms  {row['query'][:60]}"
        )


def _print_preflight(config: dict[str, Any], problems: list[str]) -> None:
    print(
        "reflex-live-check: "
        f"backend={config.get('backend', 'local')} "
        f"broker={config['broker_url']} model={config['model']} "
        + (
            f"governance={'approved' if config['governance'] == 'approved' else 'missing'} key={config['key_file']}"
            if str(config.get("backend", "local")).strip().lower() in {"jev", "broker", "cloud"}
            else "egress=disabled (local backend)"
        )
    )
    if problems:
        for problem in problems:
            print(f"  BLOCKED: {problem}")
    else:
        print("  ready: broker reachable; local backend sends nothing off-node")


def _run_live_query(
    chroma,
    reflex,
    post,
    config: dict[str, Any],
    scope: str,
    vault: Path,
    data_dir: Path,
    query: str,
    top_k: int,
    candidate_k: int,
) -> int:
    collection = chroma.open_checked(scope, vault, data_dir, log_prefix="reflex-live")
    candidates = chroma.query_candidates(scope, data_dir, collection, query, candidate_k)
    ordered, abstained, backend, latency_ms, tokens = live_relevance(
        query, candidates, reflex=reflex, post=post, config=config, limit=candidate_k
    )
    print(
        f"reflex-live: query={query!r} backend={backend} abstain={str(abstained).lower()} "
        f"latency_ms={latency_ms:.3f} tokens={tokens}"
    )
    for index, candidate in enumerate(ordered[:top_k], start=1):
        print(
            f"  [{index}] {candidate['path']}  "
            f"verdict={candidate['reflex_verdict']} score={candidate['reflex_score']:.3f}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline/live RAG reflex pilot (fabric scope only)")
    parser.add_argument("--scope", default="fabric", help="only 'fabric' is allowed for this pilot")
    parser.add_argument("--mode", choices=("shadow", "assist"), default="shadow")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--golden", default=str(GOLDEN))
    parser.add_argument("--vault", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--json", default=None, help="write the full summary as JSON to this path")
    parser.add_argument("--live", action="store_true", help="use the Master broker (also REFLEX_LIVE=1)")
    parser.add_argument("--live-candidates", type=int, default=10, help="chunks sent per query (default 10)")
    parser.add_argument("--check", action="store_true", help="print live posture and exit")
    parser.add_argument("--query", default=None, help="run one broker-backed fabric query and print it")
    parser.add_argument("--broker-url", default=None)
    parser.add_argument("--key-file", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--node-id", default=None)
    parser.add_argument("--usd-per-1k-tokens", type=float, default=None)
    args = parser.parse_args(argv)

    live = args.live or os.environ.get("REFLEX_LIVE") == "1"
    config = live_config(
        {
            "broker_url": args.broker_url,
            "key_file": args.key_file,
            "model": args.model,
            "node_id": args.node_id,
            "usd_per_1k_tokens": args.usd_per_1k_tokens,
        }
    )
    if args.check:
        problems = live_preflight(config=config)
        _print_preflight(config, problems)
        return EXIT_PREFLIGHT if problems else 0
    if not live:
        if args.query:
            print("reflex-eval: --query needs --live (or REFLEX_LIVE=1)", file=sys.stderr)
            return 1
        if args.top_k < 1 or args.candidate_k < args.top_k:
            print("reflex-eval: need 1 <= top-k <= candidate-k", file=sys.stderr)
            return 1
        golden = load_golden(Path(args.golden))
        chroma = _load_chroma()
        try:
            _collection_name, vault, default_data = chroma.resolve_scope(args.scope)
        except ValueError as exc:
            print(f"reflex-eval: {exc}", file=sys.stderr)
            return 1
        if args.vault:
            vault = Path(args.vault).expanduser()
        data_dir = Path(args.data_dir) if args.data_dir else default_data
        summary = evaluate(chroma, args.scope, vault, data_dir, golden, args.mode, args.top_k, args.candidate_k)
        _print_summary(summary)
        if args.json:
            Path(args.json).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"reflex-eval: wrote {args.json}")
        return 0

    problems = live_preflight(config=config)
    if problems:
        _print_preflight(config, problems)
        return EXIT_PREFLIGHT
    reflex = _load_reflex()
    post = lambda request: post_decision(request, config)  # noqa: E731 - one tiny injected seam
    chroma = _load_chroma()
    try:
        _collection_name, vault, default_data = chroma.resolve_scope(args.scope)
    except ValueError as exc:
        print(f"reflex-eval: {exc}", file=sys.stderr)
        return 1
    if args.vault:
        vault = Path(args.vault).expanduser()
    data_dir = Path(args.data_dir) if args.data_dir else default_data
    if args.query:
        if args.top_k < 1 or args.candidate_k < args.top_k:
            print("reflex-eval: need 1 <= top-k <= candidate-k", file=sys.stderr)
            return 1
        return _run_live_query(
            chroma, reflex, post, config, args.scope, vault, data_dir, args.query, args.top_k, args.candidate_k
        )
    if args.top_k < 1 or args.candidate_k < args.top_k:
        print("reflex-eval: need 1 <= top-k <= candidate-k", file=sys.stderr)
        return 1
    golden = load_golden(Path(args.golden))
    summary = evaluate(
        chroma,
        args.scope,
        vault,
        data_dir,
        golden,
        args.mode,
        args.top_k,
        args.candidate_k,
        live=True,
        reflex=reflex,
        post=post,
        config=config,
        limit=min(args.live_candidates, args.candidate_k),
        rate=config["usd_per_1k_tokens"],
    )
    _print_summary(summary)
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"reflex-eval: wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
