#!/usr/bin/env python3
"""Run one bounded self-improvement candidate and promote only on benchmark pass."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
from sparknet_loader import load_shared  # noqa: E402 - shared/ is added by path above

IMPROVE = load_shared("sparknet-self-improve.py", "sparknet_self_improve_cli")
AUTHZ = load_shared("sparknet-authz.py", "sparknet_self_improve_authz")
GITFLOW = load_shared("sparknet-gitflow.py", "sparknet_self_improve_gitflow")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def _probe_firecracker() -> bool:
    return Path("/dev/kvm").exists() and shutil.which("firecracker") is not None


def _thresholds(value: str) -> dict[str, Any]:
    path = Path(value)
    raw = path.read_text(encoding="utf-8") if path.is_file() else value
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise IMPROVE.SelfImproveError("benchmark-missing", "thresholds must be an object")
    return data


def _cleanup(repo: Path, worktree: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)], capture_output=True, text=True
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sparknet-self-improve")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--patch", required=True)
    parser.add_argument(
        "--benchmark", required=True, help="argv command run inside the worktree; stdout must be metrics JSON"
    )
    parser.add_argument("--thresholds", required=True, help="JSON object or a file containing it")
    parser.add_argument("--mode", choices=("auto", "worktree", "firecracker"), default="auto")
    parser.add_argument("--state-dir", default=os.environ.get("SPARKNET_SELF_IMPROVE_STATE", ""))
    parser.add_argument("--key-file", default="")
    parser.add_argument("--promote", action="store_true", help="fast-forward the managed repo only on pass")
    parser.add_argument(
        "--require-review",
        action="store_true",
        help="promote only when a valid, passing skill-eval record is supplied",
    )
    parser.add_argument("--skill-eval", default="", help="path to a sparknet-skill-eval/1 JSON record")
    parser.add_argument("--source-branch", default="", help="source branch for the GitFlow edge (default: current)")
    parser.add_argument("--target-branch", default="", help="target branch for the GitFlow edge (default: current)")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    state = Path(args.state_dir) if args.state_dir else Path.home() / ".local/state/sparknet/self-improve"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_id = "si_" + uuid.uuid4().hex[:16]
    worktree = state / "worktrees" / run_id
    patch = Path(args.patch).resolve()
    (state / "runs").mkdir(parents=True, exist_ok=True, mode=0o700)

    mode = ("firecracker" if _probe_firecracker() else "worktree") if args.mode == "auto" else args.mode
    if mode == "firecracker" and not _probe_firecracker():
        print("sparknet-self-improve: kvm-unavailable", file=sys.stderr)
        return 2

    if not (repo / ".git").exists():
        print("sparknet-self-improve: --repo is not a git repository", file=sys.stderr)
        return 2
    try:
        base = _git(repo, "rev-parse", args.base_ref).stdout.strip()
        current_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        source_branch = GITFLOW.validate_branch(args.source_branch or current_branch)
        target_branch = GITFLOW.validate_branch(args.target_branch or current_branch)
        worktree.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "--detach", str(worktree), base)
        _git(worktree, "apply", "--whitespace=nowarn", str(patch))
        mutation = hashlib.sha256(patch.read_bytes()).hexdigest()
        completed = subprocess.run(
            shlex.split(args.benchmark),
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
        try:
            metrics = json.loads(completed.stdout or "")
        except json.JSONDecodeError:
            metrics = None
        if not isinstance(metrics, dict):
            raise IMPROVE.SelfImproveError(
                "benchmark-missing", "benchmark did not write a metrics JSON object to stdout"
            )
        thresholds = _thresholds(args.thresholds)
        skill_eval = None
        if args.skill_eval:
            try:
                skill_eval = json.loads(Path(args.skill_eval).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise IMPROVE.SelfImproveError("review-invalid", f"cannot read the skill-eval record: {exc}") from exc
        verdict = IMPROVE.evaluate(metrics, thresholds, skill_eval=skill_eval, gate=args.require_review)
        decision = "pending" if verdict["decision"] == "promote" and not args.promote else verdict["decision"]
        promoted = None
        if decision == "promote":
            GITFLOW.require_promotion(source_branch, target_branch)
            _git(worktree, "add", "-A")
            _git(
                worktree,
                "-c",
                "user.name=sparknet-self-improve",
                "-c",
                "user.email=self-improve@sparknet.invalid",
                "commit",
                "-m",
                f"self-improve: {run_id}",
            )
            promoted = _git(worktree, "rev-parse", "HEAD").stdout.strip()
            restore = False
            if target_branch != current_branch:
                _git(repo, "checkout", target_branch)
                restore = True
            try:
                _git(repo, "merge", "--ff-only", promoted)
            finally:
                if restore:
                    _git(repo, "checkout", current_branch)
        if decision == "rollback" or promoted:
            _cleanup(repo, worktree)
        record = {
            "schema_version": IMPROVE.SCHEMA,
            "run_id": run_id,
            "mode": mode,
            "base_commit": base,
            "worktree": str(worktree),
            "mutation_sha256": mutation,
            "benchmark_suite": args.benchmark,
            "metrics": metrics,
            "thresholds": thresholds,
            "decision": decision,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "created_at": IMPROVE.now_iso(),
        }
        key_file = Path(args.key_file) if args.key_file else state / "keys" / "ed25519-node.key.b64"
        if not key_file.is_file():
            raise IMPROVE.SelfImproveError("key-unavailable", f"signing key is missing: {key_file}")
        key = AUTHZ.load_private_key(key_file)
        record = IMPROVE.sign_run(record, key, AUTHZ)
        path = state / "runs" / f"{run_id}.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        print(
            json.dumps(
                {
                    "ok": True,
                    "run_id": run_id,
                    "decision": decision,
                    "promoted": promoted,
                    "run": str(path),
                    "metrics": verdict["metrics"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if decision in ("promote", "pending") else 2
    except (IMPROVE.SelfImproveError, subprocess.SubprocessError, OSError, ValueError) as exc:
        if worktree.exists():
            _cleanup(repo, worktree)
        print(f"sparknet-self-improve: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
