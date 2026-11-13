#!/usr/bin/env python3
"""Summarize the dual teacher/student bake-off and recommend a set.

The report is deliberately simple: it shows the teacher and student decode
speeds for the no-precontext and fabric-precontext passes, enforces the quality
floor, and recommends a set using the student's precontext-on speed first,
the teacher's precontext-on speed second, and peak memory third.

Usage::

    scripts/sparknet-model-bakeoff-report.py \
      --teacher-no-pc master-no-pc.json \
      --teacher-pc master-pc.json \
      --student-no-pc peer-no-pc.json \
      --student-pc peer-pc.json \
      --agreement agreement-qwen36.json --agreement agreement-qwen3.json

The inputs are ``sparknet-model-bench.py`` result files. A set is eligible only
if every teacher/student quality pass rate meets ``--quality-floor``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SETS = {
    "qwen3.6": {"teacher": "qwen3.6-35b", "student": "qwen3.6-27b"},
    "qwen3": {"teacher": "qwen3-32b", "student": "qwen3-0.6b"},
}


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"bakeoff-report: {path} is not a JSON object")
    return data


def _candidate(result: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    for candidate in result.get("candidates", []):
        if isinstance(candidate, dict) and candidate.get("id") == candidate_id:
            return candidate
    raise SystemExit(f"bakeoff-report: candidate {candidate_id!r} not found")


def _summary(result: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    candidate = _candidate(result, candidate_id)
    if "error" in candidate:
        return {"error": candidate["error"]}
    return {
        "decode_tok_s": candidate.get("decode_tok_s_median"),
        "quality_pass_rate": candidate.get("quality_pass_rate"),
        "peak_memory_gb": candidate.get("peak_memory_gb"),
        "wall_s": candidate.get("wall_s_median"),
        "precontext": candidate.get("precontext"),
    }


def _agreement(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    data = _load(path)
    return {
        "held_out_teacher_agreement": data.get("held_out_teacher_agreement"),
        "quality_agreement": data.get("quality_agreement"),
        "quality_pass_rate": data.get("quality_pass_rate"),
        "refusal_rate": data.get("refusal_rate"),
        "latency_ms": data.get("latency_ms"),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_report(
    *,
    teacher_no_pc: Path,
    teacher_pc: Path,
    student_no_pc: Path,
    student_pc: Path,
    agreements: list[Path],
    quality_floor: float,
) -> dict[str, Any]:
    teacher_off = _load(teacher_no_pc)
    teacher_on = _load(teacher_pc)
    student_off = _load(student_no_pc)
    student_on = _load(student_pc)
    rows: list[dict[str, Any]] = []
    for name, ids in SETS.items():
        teacher = {
            "no_pc": _summary(teacher_off, ids["teacher"]),
            "pc": _summary(teacher_on, ids["teacher"]),
        }
        student = {
            "no_pc": _summary(student_off, ids["student"]),
            "pc": _summary(student_on, ids["student"]),
        }
        quality_values = [
            teacher["no_pc"].get("quality_pass_rate"),
            teacher["pc"].get("quality_pass_rate"),
            student["no_pc"].get("quality_pass_rate"),
            student["pc"].get("quality_pass_rate"),
        ]
        quality_values = [float(value) for value in quality_values if value is not None]
        quality = min(quality_values) if quality_values else None
        eligible = quality is not None and quality >= quality_floor
        agreement = None
        for path in agreements:
            if path.stem != f"agreement-{name}":
                continue
            agreement = _agreement(path)
            break
        rows.append(
            {
                "set": name,
                "teacher": teacher,
                "student": student,
                "quality": quality,
                "eligible": eligible,
                "agreement": agreement,
            }
        )
    eligible = [row for row in rows if row["eligible"]]
    ranked = sorted(
        eligible,
        key=lambda row: (
            row["student"]["pc"].get("decode_tok_s") or 0,
            row["teacher"]["pc"].get("decode_tok_s") or 0,
            -(row["student"]["pc"].get("peak_memory_gb") or 0),
        ),
        reverse=True,
    )
    return {
        "schema": "sparknet-model-bakeoff-report/1",
        "quality_floor": quality_floor,
        "sets": rows,
        "recommendation": ranked[0]["set"] if ranked else None,
        "ranking_rule": (
            "student precontext-on decode tok/s, then teacher precontext-on decode tok/s, "
            "then lower peak memory; quality floor enforced"
        ),
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        "| Set | Teacher no-pc | Teacher pc | Student no-pc | Student pc | Quality | Eligible | Agreement |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report["sets"]:
        teacher = row["teacher"]
        student = row["student"]
        agreement = row.get("agreement") or {}
        lines.append(
            "| {set} | {tn} | {tp} | {sn} | {sp} | {q} | {e} | {a} |".format(
                set=row["set"],
                tn=_fmt(teacher["no_pc"].get("decode_tok_s")),
                tp=_fmt(teacher["pc"].get("decode_tok_s")),
                sn=_fmt(student["no_pc"].get("decode_tok_s")),
                sp=_fmt(student["pc"].get("decode_tok_s")),
                q=_fmt(row.get("quality")),
                e="yes" if row["eligible"] else "no",
                a=_fmt(agreement.get("held_out_teacher_agreement")),
            )
        )
    lines.append("")
    if report["recommendation"]:
        lines.append(f"Recommendation: **{report['recommendation']}**")
    else:
        lines.append("Recommendation: no eligible set — quality floor not met.")
    lines.append("")
    lines.append(f"Rule: {report['ranking_rule']}.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="summarize the dual model bake-off")
    parser.add_argument("--teacher-no-pc", type=Path, required=True)
    parser.add_argument("--teacher-pc", type=Path, required=True)
    parser.add_argument("--student-no-pc", type=Path, required=True)
    parser.add_argument("--student-pc", type=Path, required=True)
    parser.add_argument("--agreement", type=Path, action="append", default=[])
    parser.add_argument("--quality-floor", type=float, default=1.0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = build_report(
        teacher_no_pc=args.teacher_no_pc,
        teacher_pc=args.teacher_pc,
        student_no_pc=args.student_no_pc,
        student_pc=args.student_pc,
        agreements=args.agreement,
        quality_floor=args.quality_floor,
    )
    text = render(report)
    print(text, end="")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.out.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
