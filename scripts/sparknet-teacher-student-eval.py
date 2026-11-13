#!/usr/bin/env python3
"""Teacher -> student agreement eval for the two AGX model sets.

This is the small, honest distillation/eval pass: the teacher and student answer
the same held-out benchmark prompts, and the script records how often the
student agrees with the teacher. It does not train, merge an adapter or write a
GGUF. The result is a metrics file in the distillation-schema vocabulary.

Usage::

    scripts/sparknet-teacher-student-eval.py \
      --teacher-result /path/master-pc.json \
      --student-result /path/peer-pc.json \
      --out /path/agreement.json

The inputs are ``sparknet-model-bench.py`` result files with full ``answer``
rows. Both files must cover the same prompt ids.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"teacher-student-eval: {path} is not a JSON object")
    return data


def _rows(result: dict[str, Any], role: str) -> dict[str, dict[str, Any]]:
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SystemExit(f"teacher-student-eval: no candidates in the {role} result")
    rows: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict) or "rows" not in candidate:
            continue
        for row in candidate["rows"]:
            if isinstance(row, dict) and row.get("prompt_id"):
                rows[str(row["prompt_id"])] = row
    if not rows:
        raise SystemExit(f"teacher-student-eval: no answer rows in the {role} result")
    return rows


def _tokens(text: str) -> set[str]:
    return {word.lower().strip(".,:;!?()[]{}\"'") for word in text.split() if len(word) > 2}


def _overlap(teacher: str, student: str) -> float:
    a, b = _tokens(teacher), _tokens(student)
    return len(a & b) / max(1, len(a | b))


def evaluate(teacher: dict[str, Any], student: dict[str, Any], label: str) -> dict[str, Any]:
    teacher_rows = _rows(teacher, "teacher")
    student_rows = _rows(student, "student")
    prompt_ids = sorted(set(teacher_rows) & set(student_rows))
    if not prompt_ids:
        raise SystemExit("teacher-student-eval: the results share no prompt ids")
    missing_teacher = sorted(set(student_rows) - set(teacher_rows))
    missing_student = sorted(set(teacher_rows) - set(student_rows))
    overlaps: list[float] = []
    agreement: list[float] = []
    student_pass: list[bool] = []
    teacher_pass: list[bool] = []
    student_wall: list[float] = []
    teacher_wall: list[float] = []
    student_decode: list[float] = []
    teacher_decode: list[float] = []
    refusals: list[bool] = []
    for prompt_id in prompt_ids:
        t = teacher_rows[prompt_id]
        s = student_rows[prompt_id]
        t_answer = str(t.get("answer") or "")
        s_answer = str(s.get("answer") or "")
        overlaps.append(_overlap(t_answer, s_answer))
        t_ok = bool(t.get("quality_pass"))
        s_ok = bool(s.get("quality_pass"))
        teacher_pass.append(t_ok)
        student_pass.append(s_ok)
        agreement.append(1.0 if t_ok == s_ok else 0.0)
        if t.get("wall_s") is not None:
            teacher_wall.append(float(t["wall_s"]))
        if s.get("wall_s") is not None:
            student_wall.append(float(s["wall_s"]))
        if t.get("decode_tok_s") is not None:
            teacher_decode.append(float(t["decode_tok_s"]))
        if s.get("decode_tok_s") is not None:
            student_decode.append(float(s["decode_tok_s"]))
        if prompt_id == "refusal":
            refusals.append(not s_ok)
    metrics = {
        "schema": "sparknet-distill-eval/1",
        "label": label,
        "prompt_count": len(prompt_ids),
        "held_out_teacher_agreement": round(statistics.mean(overlaps), 4),
        "quality_agreement": round(statistics.mean(agreement), 4),
        "quality_pass_rate": round(sum(student_pass) / len(student_pass), 4),
        "teacher_quality_pass_rate": round(sum(teacher_pass) / len(teacher_pass), 4),
        "refusal_rate": round(sum(refusals) / len(refusals), 4) if refusals else 0.0,
        "latency_ms": round(statistics.median(student_wall) * 1000, 1) if student_wall else None,
        "teacher_latency_ms": round(statistics.median(teacher_wall) * 1000, 1) if teacher_wall else None,
        "student_decode_tok_s": round(statistics.median(student_decode), 2) if student_decode else None,
        "teacher_decode_tok_s": round(statistics.median(teacher_decode), 2) if teacher_decode else None,
        "missing_teacher_prompts": missing_teacher,
        "missing_student_prompts": missing_student,
    }
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="teacher -> student agreement eval")
    parser.add_argument("--teacher-result", type=Path, required=True)
    parser.add_argument("--student-result", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--label", default="precontext-on")
    args = parser.parse_args(argv)
    metrics = evaluate(_load(args.teacher_result), _load(args.student_result), args.label)
    args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.out.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out.chmod(0o600)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
