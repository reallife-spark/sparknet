#!/usr/bin/env python3
"""GitFlow branch naming and promotion policy for bounded self-improvement.

This module decides one thing: may a commit produced on ``source`` be promoted
to ``target``? It does not create branches, merge, push or deploy. A run remains
a proposal until the operator invokes promotion, and the Git operation still has
to be a fast-forward.

The policy is deliberately smaller than a GitFlow tool. The fabric has one
managed repository per node, and the relevant edges are:

    feature/*  -> develop
    release/*  -> main or master
    hotfix/*   -> main or master
    same branch -> same branch (a normal fast-forward on the managed branch)

``main`` and ``master`` are aliases because this repository and goSpark use
different default names. A promotion outside those edges is refused rather than
guessed at.
"""

from __future__ import annotations

import re

BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
PROTECTED = ("main", "master", "develop")
KINDS = {
    "feature": ("develop",),
    "release": ("main", "master"),
    "hotfix": ("main", "master"),
}


class GitFlowError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_branch(name: str) -> str:
    if not isinstance(name, str) or not name or not BRANCH_RE.fullmatch(name):
        raise GitFlowError("branch-invalid", f"invalid branch name: {name!r}")
    if name.endswith("/") or name.startswith("/") or "//" in name or ".." in name:
        raise GitFlowError("branch-invalid", f"invalid branch name: {name!r}")
    if any(part in ("", ".", "..") or part.endswith(".lock") for part in name.split("/")):
        raise GitFlowError("branch-invalid", f"invalid branch name: {name!r}")
    return name


def branch_kind(name: str) -> str:
    name = validate_branch(name)
    if name in PROTECTED:
        return name
    return name.split("/", 1)[0]


def promotion_allowed(source: str, target: str) -> bool:
    """True only for the same branch or a declared GitFlow edge."""
    source = validate_branch(source)
    target = validate_branch(target)
    if source == target:
        return True
    kind = branch_kind(source)
    return target in KINDS.get(kind, ())


def require_promotion(source: str, target: str) -> None:
    if not promotion_allowed(source, target):
        raise GitFlowError(
            "promotion-refused",
            f"GitFlow refuses promotion {source!r} -> {target!r}; expected feature/* -> develop, "
            "release/* or hotfix/* -> main/master, or a same-branch fast-forward",
        )


def describe() -> dict[str, object]:
    return {
        "protected": list(PROTECTED),
        "edges": {kind: list(targets) for kind, targets in KINDS.items()},
        "same_branch": "allowed",
        "does": "validate a promotion edge; never merges, pushes or deploys",
    }
