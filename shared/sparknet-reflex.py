#!/usr/bin/env python3
"""Sparknet reflex layer — typed decisions, never authority.

This module is the single implementation of the reflex decision contract.
It is loaded by path (like shared/sparknet-authz.py) and must remain stdlib only.
A backend's answers are untrusted input; the module makes abstain
first-class, forbids authority fields, and keeps audit logs free of state.

The contract lives in contracts/reflex-schema.json.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "1.0"
QUESTION_CLASSES = ("rag.relevance", "intent.route", "input.injection", "tool.risk", "output.grounded")
QUESTION_TYPES = ("noul", "choice", "score")
VERDICTS = ("accept", "reject", "abstain")
MODES = ("off", "local", "broker", "auto")
LOCAL_BACKENDS = ("local-rerank", "local-llm", "rules")
BACKENDS = ("broker", "local-rerank", "local-llm", "rules", "null")
LOCAL_MODEL_SENTINEL = "local"

FORBIDDEN_FIELDS = {"capability", "grant", "signature", "approve", "apply", "secret", "token", "key"}

_LEXICAL_TOKEN_RE = re.compile(r"[a-z0-9_]+")


class ReflexError(Exception):
    """Reflex-layer error."""


class ReflexPolicyError(ReflexError):
    """Policy/contract violation."""


class ReflexBudgetExhausted(ReflexError):
    """Budget exhausted -> caller must abstain."""


class ReflexNoSignal(ReflexError):
    """The local sensor had nothing to say -> caller must abstain.

    Distinct from a backend error so both roles report the same reason: silence
    is *no signal*, never a confident reject.
    """


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(obj: Any) -> str:
    return hashlib.sha256(_canonical_json(obj)).hexdigest()


def _check_no_forbidden(d: Any, path: str = "") -> None:
    if isinstance(d, dict):
        for k, v in d.items():
            if k in FORBIDDEN_FIELDS:
                raise ReflexPolicyError(f"forbidden field '{k}' in reflex request ({path or 'root'})")
            _check_no_forbidden(v, f"{path}.{k}" if path else k)
    elif isinstance(d, list):
        for i, item in enumerate(d):
            _check_no_forbidden(item, f"{path}[{i}]" if path else f"[{i}]")


def validate_request(req: dict[str, Any]) -> dict[str, Any]:
    """Validate a reflex request against the contract. Raises ReflexPolicyError on violation."""
    if not isinstance(req, dict):
        raise ReflexPolicyError("request must be an object")
    _check_no_forbidden(req)

    required = [
        "schema_version",
        "question_class",
        "state",
        "questions",
        "model",
        "policy_version",
        "node_id",
        "request_id",
    ]
    for key in required:
        if key not in req:
            raise ReflexPolicyError(f"missing required field: {key}")

    if req["schema_version"] != SCHEMA_VERSION:
        raise ReflexPolicyError(f"schema_version must be {SCHEMA_VERSION}")

    qclass = req["question_class"]
    if qclass not in QUESTION_CLASSES:
        raise ReflexPolicyError(f"unknown question_class: {qclass}")

    if req["model"] is None or str(req["model"]).strip() == "":
        raise ReflexPolicyError("model must be non-empty (pin an exact tag)")

    questions = req["questions"]
    if not isinstance(questions, dict) or not questions:
        raise ReflexPolicyError("questions must be a non-empty object")

    for qname, qspec in questions.items():
        if not isinstance(qspec, dict):
            raise ReflexPolicyError(f"question {qname} must be an object")
        qtype = qspec.get("type")
        if qtype not in QUESTION_TYPES:
            raise ReflexPolicyError(f"question {qname} has unknown type {qtype}")
        if qtype == "noul":
            if "instructions" not in qspec:
                raise ReflexPolicyError(f"noul question {qname} missing instructions")
        elif qtype == "choice":
            if "instructions" not in qspec or "criteria" not in qspec:
                raise ReflexPolicyError(f"choice question {qname} missing instructions/criteria")
        elif qtype == "score":
            if "instructions" not in qspec or "criteria" not in qspec:
                raise ReflexPolicyError(f"score question {qname} missing instructions/criteria")
            crit = qspec["criteria"]
            if not isinstance(crit, list) or len(crit) < 2 or len(crit) > 10:
                raise ReflexPolicyError(f"score question {qname} must have 2-10 levels")

    return req


def make_request(
    question_class: str,
    state: Any,
    questions: dict[str, dict[str, Any]],
    model: str,
    policy_version: str,
    node_id: str,
    request_id: str,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    req = {
        "schema_version": schema_version,
        "question_class": question_class,
        "state": state,
        "questions": questions,
        "model": model,
        "policy_version": policy_version,
        "node_id": node_id,
        "request_id": request_id,
    }
    validate_request(req)
    return req


@dataclass
class Budget:
    per_node_used: int = 0
    per_node_limit: int = 0
    global_used: int = 0
    global_limit: int = 0

    def check(self) -> None:
        if self.per_node_limit and self.per_node_used >= self.per_node_limit:
            raise ReflexBudgetExhausted("per-node budget exhausted")
        if self.global_limit and self.global_used >= self.global_limit:
            raise ReflexBudgetExhausted("global budget exhausted")

    def charge(self) -> None:
        self.per_node_used += 1
        self.global_used += 1


def abstain_decision(
    model: str,
    backend: str,
    policy_version: str,
    request: dict[str, Any],
    reason: str = "abstain",
) -> dict[str, Any]:
    """Create a first-class abstain decision. Never authority."""
    return {
        "verdict": "abstain",
        "confidence": None,
        "backend": backend,
        "model": model,
        "usage": None,
        "latency_ms": 0.0,
        "cached": False,
        "state_digest": _digest(request.get("state")),
        "model_drift": False,
        "_reason": reason,
    }


def noul_abstain(p: float, threshold: float = 0.7, margin: float = 0.2) -> bool:
    """Noul has no confidence; use p and distance from 0.5."""
    if p < 0.0:
        p = 0.0
    if p > 1.0:
        p = 1.0
    if p >= threshold:
        return False
    if p <= 1.0 - threshold:
        return False
    return abs(p - 0.5) < margin


def choice_abstain(
    confidence: float, top_p: float, second_p: float, min_conf: float = 0.6, min_margin: float = 0.15
) -> bool:
    if confidence is None or confidence < min_conf:
        return True
    return top_p - second_p < min_margin


def score_abstain(confidence: float, min_conf: float = 0.6) -> bool:
    return bool(confidence is None or confidence < min_conf)


def cache_key(request: dict[str, Any]) -> str:
    """Cache key = state hash + question hash + exact model + policy version. Never across models."""
    key = {
        "state": _digest(request.get("state")),
        "questions": _digest(request.get("questions")),
        "model": request.get("model"),
        "policy_version": request.get("policy_version"),
    }
    return _digest(key)


def audit_line(decision: dict[str, Any], request: dict[str, Any], class_name: str, latency_ms: float) -> str:
    """Emit an audit line with hashes only; never log state/questions/answers/keys."""
    line = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "class": class_name,
        "backend": decision.get("backend"),
        "model": decision.get("model"),
        "usage": decision.get("usage"),
        "latency_ms": latency_ms,
        "verdict": decision.get("verdict"),
        "cached": bool(decision.get("cached")),
        "request_digest": _digest(
            {
                "question_class": request.get("question_class"),
                "model": request.get("model"),
                "policy_version": request.get("policy_version"),
                "node_id": request.get("node_id"),
                "request_id": request.get("request_id"),
            }
        ),
    }
    return json.dumps(line, ensure_ascii=True)


def default_modes() -> dict[str, dict[str, str]]:
    return {
        "rag.relevance": {"mode": "local", "rollout": "shadow"},
        "intent.route": {"mode": "off", "rollout": "shadow"},
        "input.injection": {"mode": "off", "rollout": "shadow"},
        "tool.risk": {"mode": "off", "rollout": "shadow"},
        "output.grounded": {"mode": "off", "rollout": "shadow"},
    }


def is_authority_path(path: str) -> bool:
    """Guard/signer/registry paths must never consult reflex."""
    bad = ("guard", "signer", "registry", "authz", "authoriz", "approve", "revoke", "capability")
    p = path.lower()
    return any(b in p for b in bad)


# --- redaction ---------------------------------------------------------------

_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]+-----.*?-----END [A-Z0-9 ]+-----", re.DOTALL)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_SECRET = re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization)\b(\s*[:=]\s*)([^\s,;]+)")
_SECRET_KEYS = {"api_key", "apikey", "token", "secret", "password", "passwd", "authorization"}


def redact(text: str) -> str:
    """Remove the shapes that must never leave the fabric or reach an audit line."""
    if not isinstance(text, str):
        return text
    text = _PEM.sub("[REDACTED-PEM]", text)
    text = _BEARER.sub(r"\1[REDACTED]", text)
    return _SECRET.sub(r"\1\2[REDACTED]", text)


def redact_deep(value: Any) -> Any:
    """Recursively redact strings; a secret-named key has its value replaced."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_deep(v) for v in value]
    if isinstance(value, dict):
        return {k: "[REDACTED]" if str(k).lower() in _SECRET_KEYS else redact_deep(v) for k, v in value.items()}
    return value


def redact_request(request: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe to send/log: redact state and question instructions."""
    out = copy.deepcopy(request)
    if "state" in out:
        out["state"] = redact_deep(out["state"])
    questions = out.get("questions")
    if isinstance(questions, dict):
        for q in questions.values():
            if isinstance(q, dict) and "instructions" in q:
                q["instructions"] = redact_deep(q["instructions"])
    return out


# --- answer parsing and consultation ----------------------------------------


def decision_from_answer(
    answer: dict[str, Any],
    request: dict[str, Any],
    *,
    backend: str = "broker",
    model: str | None = None,
    latency_ms: float = 0.0,
    usage: dict[str, Any] | None = None,
    cached: bool = False,
    positive_choice: Any = None,
    score_threshold: float = 0.5,
) -> dict[str, Any]:
    """Map one vendor answer to the decision contract. Unknown shapes abstain."""
    model = model or request.get("model", "")
    if not isinstance(answer, dict):
        return abstain_decision(model, backend, "", request, reason="malformed-answer")
    atype = answer.get("type")
    try:
        if atype == "noul":
            p = float(answer["noul"])
            if noul_abstain(p):
                return abstain_decision(model, backend, "", request, reason="low-signal")
            verdict = "accept" if p >= 0.5 else "reject"
            confidence = abs(p - 0.5) * 2.0
        elif atype == "choice":
            probs = answer.get("probabilities") or {}
            ordered = sorted((float(v) for v in probs.values()), reverse=True)
            top_p = ordered[0] if ordered else 0.0
            second_p = ordered[1] if len(ordered) > 1 else 0.0
            confidence = float(answer.get("confidence", 0.0))
            if choice_abstain(confidence, top_p, second_p):
                return abstain_decision(model, backend, "", request, reason="low-signal")
            choice = answer.get("choice")
            verdict = "accept" if positive_choice is None or choice in positive_choice else "reject"
        elif atype == "score":
            score = float(answer["score"])
            confidence = float(answer.get("confidence", 0.0))
            if score_abstain(confidence):
                return abstain_decision(model, backend, "", request, reason="low-signal")
            verdict = "accept" if score >= score_threshold else "reject"
        else:
            return abstain_decision(model, backend, "", request, reason="unknown-answer-type")
    except (KeyError, TypeError, ValueError):
        return abstain_decision(model, backend, "", request, reason="malformed-answer")

    return {
        "verdict": verdict,
        "confidence": confidence,
        "backend": backend,
        "model": model,
        "usage": usage,
        "latency_ms": latency_ms,
        "cached": cached,
        "state_digest": _digest(request.get("state")),
        "model_drift": False,
    }


def consult(
    call: Any,
    request: dict[str, Any],
    *,
    timeout_s: float = 2.0,
    budget: Budget | None = None,
    backend: str = "broker",
    model: str | None = None,
    positive_choice: Any = None,
    score_threshold: float = 0.5,
) -> dict[str, Any]:
    """Run a backend with a hard timeout. Timeout, error, exhaustion -> abstain.

    ``call`` is any ``callable(request) -> answer``. It runs on a bounded thread so a
    hung vendor socket cannot block the guard/dispatch path past ``timeout_s``.
    The thread is abandoned on timeout; the caller still gets an abstain.
    """
    model = model or request.get("model", "")
    if budget is not None:
        try:
            budget.check()
        except ReflexBudgetExhausted:
            return abstain_decision(model, backend, "", request, reason="budget-exhausted")

    started = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(call, request)
    try:
        answer = future.result(timeout=timeout_s)
    except FuturesTimeoutError:
        future.cancel()
        return abstain_decision(model, backend, "", request, reason="timeout")
    except ReflexBudgetExhausted:
        return abstain_decision(model, backend, "", request, reason="budget-exhausted")
    except ReflexNoSignal:
        return abstain_decision(model, backend, "", request, reason="low-signal")
    except Exception:
        return abstain_decision(model, backend, "", request, reason="backend-error")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if budget is not None:
        budget.charge()
    latency_ms = (time.monotonic() - started) * 1000.0
    if isinstance(answer, dict) and "answers" in answer and isinstance(answer["answers"], dict):
        usage = answer.get("usage")
        answers = answer["answers"]
        if len(answers) != 1:
            return abstain_decision(model, backend, "", request, reason="answer-count")
        answer = next(iter(answers.values()))
        return decision_from_answer(
            answer,
            request,
            backend=backend,
            model=model,
            latency_ms=latency_ms,
            usage=usage,
            positive_choice=positive_choice,
            score_threshold=score_threshold,
        )
    return decision_from_answer(
        answer,
        request,
        backend=backend,
        model=model,
        latency_ms=latency_ms,
        positive_choice=positive_choice,
        score_threshold=score_threshold,
    )


def backend_from_env(question_class: str = "rag.relevance") -> str:
    """The backend this node's environment selects. Local is the default.

    The selector vocabulary is ``off | local | broker | local-rerank |
    local-llm | rules``. ``broker`` names the Master's reflex broker, which is
    itself local — there is no egress backend in the vocabulary at all, so no
    spelling a node can select reaches outside the fabric. Anything unrecognised
    falls back to local, so a typo can never widen what runs.
    """
    backend = os.environ.get("SPARKNET_REFLEX_BACKEND", "").strip().lower()
    if backend in LOCAL_BACKENDS:
        return backend
    if backend == "local":
        if question_class == "rag.relevance":
            return "local-rerank"
        return "local-llm"
    if backend == "broker":
        return "broker"
    if backend == "off":
        return "null"
    # default local
    if question_class == "rag.relevance":
        return "local-rerank"
    return "local-llm"


def _local_llm_url() -> str:
    url = os.environ.get("SPARKNET_REFLEX_LOCAL_URL", "").strip()
    if not url:
        url = os.environ.get("SPARKNET_LOCAL_LLM_URL", "").strip()
    if not url:
        return "http://127.0.0.1:8000/v1/chat/completions"
    url = url.rstrip("/")
    if url.endswith("/v1/chat/completions") or url.endswith("/chat/completions"):
        return url
    return url + "/v1/chat/completions"


def _local_llm_model() -> str:
    return (
        os.environ.get("SPARKNET_REFLEX_LOCAL_MODEL", "").strip() or os.environ.get("SPARKNET_LOCAL_MODEL", "").strip()
    )


def resolve_local_model(model: str | None = None) -> str:
    """The endpoint's real tag for a request that pinned the ``local`` sentinel.

    A request may name ``local`` (the peer/eval default) because the tag is a
    property of the node, not of the caller. Refusing here is deliberate: an
    unconfigured endpoint must surface as an abstain, never as a call that asks
    the server for a model literally named ``local``.
    """
    name = (model or "").strip()
    if not name or name.lower() == LOCAL_MODEL_SENTINEL:
        name = _local_llm_model()
    if not name:
        raise ReflexPolicyError("no local model configured (set SPARKNET_REFLEX_LOCAL_MODEL)")
    return name


def relevance_pair(state: Any) -> tuple[str, str]:
    """The ``(query, chunk)`` a ``rag.relevance`` request carries.

    ``state`` is contract-free, so a caller may send the pair as an object, or
    send something else entirely. Anything that is not a usable pair yields
    ``("", "")`` and the caller must abstain — a malformed request is never a
    confident answer.
    """
    if not isinstance(state, dict):
        return "", ""
    query = str(state.get("query") or "").strip()
    chunk = str(state.get("chunk") or "").strip()
    if not query or not chunk:
        return "", ""
    return query, chunk


def lexical_relevance(query: str, text: str) -> float:
    """How much of the query ``text`` covers, in ``[0, 1]``.

    Coverage, not Jaccard: a chunk holding every query term scores 1.0 however
    long it is. Deterministic and stdlib-only, so the local relevance sensor is
    reproducible without a model download.
    """
    wanted = set(_LEXICAL_TOKEN_RE.findall(query.lower()))
    if not wanted:
        return 0.0
    return len(wanted & set(_LEXICAL_TOKEN_RE.findall(text.lower()))) / len(wanted)


def local_relevance_answer(request: dict[str, Any]) -> dict[str, Any]:
    """One ``rag.relevance`` answer from the node itself — the local sensor.

    Both roles call this, so the peer bridge and the Master broker cannot drift
    apart on what "locally relevant" means. Raises :class:`ReflexNoSignal` when
    the request carries no usable query/chunk pair or the chunk covers none of
    the query: silence abstains, it never becomes a confident reject.
    """
    query, chunk = relevance_pair(request.get("state"))
    if not query or not chunk:
        raise ReflexNoSignal("relevance request carries no query/chunk pair")
    score = lexical_relevance(query, chunk)
    if score <= 0.0:
        raise ReflexNoSignal("no lexical signal")
    return {"type": "noul", "noul": float(score)}


def _extract_json(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
        except (TypeError, ValueError):
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _prompt_for(qtype: str, instructions: str, criteria: Any, state: Any) -> str:
    state_json = json.dumps(state, ensure_ascii=True, sort_keys=True)
    if qtype == "noul":
        return f'Instructions: {instructions}\nState: {state_json}\nReturn {{"type":"noul","noul":0.5}}'
    criteria_json = json.dumps(criteria, ensure_ascii=True, sort_keys=True)
    if qtype == "choice":
        return (
            f"Instructions: {instructions}\nCriteria: {criteria_json}\nState: {state_json}\n"
            'Return {"type":"choice","choice":"x",'
            '"probabilities":{"x":0.5,"y":0.5},"confidence":0.5}'
        )
    if qtype == "score":
        return (
            f"Instructions: {instructions}\nCriteria: {criteria_json}\nState: {state_json}\n"
            'Return {"type":"score","score":0.5,"confidence":0.5}'
        )
    raise ValueError("unknown question type")


def _llm_content(outer: Any) -> str | None:
    if not isinstance(outer, dict):
        return None
    choices = outer.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"] or None
        if isinstance(choices[0].get("text"), str):
            return choices[0]["text"] or None
    message = outer.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"] or None
    if isinstance(outer.get("response"), str):
        return outer["response"] or None
    if isinstance(outer.get("content"), str):
        return outer["content"] or None
    return None


def local_llm_backend(model: str | None = None, timeout_s: float = 5.0) -> Any:
    """Build a backend that calls an OpenAI-compatible local LLM on loopback.

    Works with vLLM, Ollama and Open WebUI. It raises on any failure; the
    caller (`consult`) turns that into an abstain, so a missing local model
    can never be mistaken for a confident decision.
    """
    llm_model = resolve_local_model(model)

    def backend(request: dict[str, Any]) -> dict[str, Any]:
        url = _local_llm_url()
        questions = request.get("questions") or {}
        if not questions:
            raise ValueError("request has no questions")
        _qname, qspec = next(iter(questions.items()))
        if not isinstance(qspec, dict):
            raise ValueError("question spec is not an object")
        qtype = str(qspec.get("type", ""))
        instructions = str(qspec.get("instructions", ""))
        user = _prompt_for(qtype, instructions, qspec.get("criteria"), request.get("state"))
        payload = {
            "model": llm_model,
            "messages": [
                {"role": "system", "content": "Return ONLY valid JSON."},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": 256,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8")
        except Exception as exc:
            raise RuntimeError("local-llm unreachable") from exc
        try:
            outer = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("local-llm returned non-JSON") from exc
        content = _llm_content(outer)
        if not isinstance(content, str):
            raise RuntimeError("local-llm returned no content")
        parsed = _extract_json(content)
        if not isinstance(parsed, dict):
            raise RuntimeError("local-llm returned no JSON object")
        parsed.setdefault("type", qtype)
        return parsed

    return backend
