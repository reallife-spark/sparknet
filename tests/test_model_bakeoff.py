"""The OpenAI bake-off path and the teacher -> student agreement eval."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "scripts" / "sparknet-model-bench.py"
EVAL = ROOT / "scripts" / "sparknet-teacher-student-eval.py"
REPORT = ROOT / "scripts" / "sparknet-model-bakeoff-report.py"
MODEL_SET = ROOT / "scripts" / "sparknet-model-set.py"


def _answer(prompt: str) -> str:
    if "17 * 23" in prompt:
        return "391"
    if "checksum" in prompt:
        return "A signature proves authenticity; a checksum detects accidental change."
    if "Return only JSON" in prompt:
        return '{"node":"agx64","role":"master","reachable":true}'
    if "def add" in prompt:
        return "def add(a, b):\n    return a + b"
    if "cannot sign" in prompt:
        return "I cannot sign a registry entry."
    if "third identifier" in prompt:
        return "gamma-91"
    return "ok"


class _OpenAIHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        request = json.loads(self.rfile.read(length) or b"{}")
        self.requests.append(request)
        prompt = str((request.get("messages") or [{}])[0].get("content") or "")
        body = {
            "choices": [{"message": {"role": "assistant", "content": _answer(prompt)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            "timings": {"predicted_per_second": 10.0, "prompt_per_second": 100.0},
        }
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def openai_server():
    _OpenAIHandler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_openai_measure_uses_timings_and_sends_template_kwargs(openai_server: str) -> None:
    bench = load_by_path("sparknet_model_bench_openai_test", BENCH)
    config = {
        "provider": {"kind": "openai", "base_url": openai_server},
        "options": {
            "runs": 1,
            "num_predict": 32,
            "temperature": 0,
            "seed": 42,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        "prompts": [{"id": "math", "prompt": "Compute 17 * 23.", "must_include": ["391"]}],
    }
    result = bench.measure(
        candidate={"id": "test-teacher", "model": "test-model", "role": "teacher"},
        provider=config["provider"],
        options=config["options"],
        prompts=config["prompts"],
        timeout=10,
    )
    assert result["quality_pass_rate"] == 1.0
    assert result["decode_tok_s_median"] == 10.0
    assert _OpenAIHandler.requests
    assert _OpenAIHandler.requests[-1]["chat_template_kwargs"] == {"enable_thinking": False}


def _result(role: str, rows: list[dict]) -> dict:
    return {"candidates": [{"id": role, "role": role, "rows": rows}]}


def test_agreement_eval_records_overlap_and_quality(tmp_path: Path) -> None:
    eval_module = load_by_path("sparknet_teacher_student_eval_test", EVAL)
    teacher = _result(
        "teacher",
        [
            {"prompt_id": "math", "answer": "391", "quality_pass": True, "wall_s": 1.0, "decode_tok_s": 10.0},
            {
                "prompt_id": "refusal",
                "answer": "I cannot sign it.",
                "quality_pass": True,
                "wall_s": 2.0,
                "decode_tok_s": 5.0,
            },
        ],
    )
    student = _result(
        "student",
        [
            {"prompt_id": "math", "answer": "391", "quality_pass": True, "wall_s": 2.0, "decode_tok_s": 5.0},
            {
                "prompt_id": "refusal",
                "answer": "I cannot sign it.",
                "quality_pass": True,
                "wall_s": 3.0,
                "decode_tok_s": 3.0,
            },
        ],
    )
    out = tmp_path / "agreement.json"
    teacher_path = tmp_path / "teacher.json"
    student_path = tmp_path / "student.json"
    teacher_path.write_text(json.dumps(teacher))
    student_path.write_text(json.dumps(student))
    assert (
        eval_module.main(
            [
                "--teacher-result",
                str(teacher_path),
                "--student-result",
                str(student_path),
                "--out",
                str(out),
                "--label",
                "precontext-on",
            ]
        )
        == 0
    )
    metrics = json.loads(out.read_text())
    assert metrics["prompt_count"] == 2
    assert metrics["held_out_teacher_agreement"] == 1.0
    assert metrics["quality_pass_rate"] == 1.0
    assert metrics["refusal_rate"] == 0.0
    assert metrics["student_decode_tok_s"] == 4.0


def _result_file(path: Path, candidate_id: str, decode: float, quality: float, memory: float = 10.0) -> Path:
    payload = {
        "candidates": [
            {
                "id": candidate_id,
                "decode_tok_s_median": decode,
                "quality_pass_rate": quality,
                "peak_memory_gb": memory,
                "wall_s_median": 1.0,
                "precontext": "on",
            }
        ]
    }
    path.write_text(json.dumps(payload))
    return path


def test_report_recommends_the_faster_eligible_student(tmp_path: Path) -> None:
    report_module = load_by_path("sparknet_model_bakeoff_report_test", REPORT)
    teacher_off = _result_file(tmp_path / "master-no-pc.json", "qwen3.6-35b", 10.0, 1.0)
    teacher_on = _result_file(tmp_path / "master-pc.json", "qwen3.6-35b", 9.0, 1.0)
    student_off = _result_file(tmp_path / "peer-no-pc.json", "qwen3.6-27b", 6.0, 1.0)
    student_on = _result_file(tmp_path / "peer-pc.json", "qwen3.6-27b", 5.0, 1.0)
    # The report needs both sets in the same files for the dual comparison.
    for path, candidate_id, decode, quality in (
        (teacher_off, "qwen3-32b", 12.0, 1.0),
        (teacher_on, "qwen3-32b", 11.0, 1.0),
        (student_off, "qwen3-0.6b", 30.0, 1.0),
        (student_on, "qwen3-0.6b", 28.0, 1.0),
    ):
        data = json.loads(path.read_text())
        data["candidates"].append(
            {
                "id": candidate_id,
                "decode_tok_s_median": decode,
                "quality_pass_rate": quality,
                "peak_memory_gb": 2.0,
                "wall_s_median": 1.0,
                "precontext": "on",
            }
        )
        path.write_text(json.dumps(data))
    report = report_module.build_report(
        teacher_no_pc=teacher_off,
        teacher_pc=teacher_on,
        student_no_pc=student_off,
        student_pc=student_on,
        agreements=[],
        quality_floor=1.0,
    )
    assert report["recommendation"] == "qwen3"
    assert "qwen3" in report_module.render(report)


def test_report_rejects_a_set_below_the_quality_floor(tmp_path: Path) -> None:
    report_module = load_by_path("sparknet_model_bakeoff_report_floor_test", REPORT)
    teacher_off = _result_file(tmp_path / "master-no-pc.json", "qwen3.6-35b", 10.0, 1.0)
    teacher_on = _result_file(tmp_path / "master-pc.json", "qwen3.6-35b", 9.0, 1.0)
    student_off = _result_file(tmp_path / "peer-no-pc.json", "qwen3.6-27b", 6.0, 1.0)
    student_on = _result_file(tmp_path / "peer-pc.json", "qwen3.6-27b", 5.0, 1.0)
    for path, candidate_id, decode, quality in (
        (teacher_off, "qwen3-32b", 12.0, 1.0),
        (teacher_on, "qwen3-32b", 11.0, 1.0),
        (student_off, "qwen3-0.6b", 30.0, 0.8),
        (student_on, "qwen3-0.6b", 28.0, 0.8),
    ):
        data = json.loads(path.read_text())
        data["candidates"].append(
            {
                "id": candidate_id,
                "decode_tok_s_median": decode,
                "quality_pass_rate": quality,
                "peak_memory_gb": 2.0,
                "wall_s_median": 1.0,
                "precontext": "on",
            }
        )
        path.write_text(json.dumps(data))
    report = report_module.build_report(
        teacher_no_pc=teacher_off,
        teacher_pc=teacher_on,
        student_no_pc=student_off,
        student_pc=student_on,
        agreements=[],
        quality_floor=1.0,
    )
    assert report["recommendation"] == "qwen3.6"
    assert any(not row["eligible"] for row in report["sets"])


def test_model_set_writes_the_peer_state_without_restarting(tmp_path: Path) -> None:
    module = load_by_path("sparknet_model_set_test", MODEL_SET)
    state = tmp_path / "model-set.env"
    assert (
        module.main(
            [
                "--role",
                "peer",
                "--set",
                "qwen3",
                "--precontext",
                "off",
                "--state-file",
                str(state),
                "--no-restart",
            ]
        )
        == 0
    )
    text = state.read_text()
    assert "VLLM_MODEL=qwen3-0.6b" in text
    assert "SPARKNET_LLM_MODEL_FILE=/opt/sparknet/models/qwen3-0.6b-q8_0.gguf" in text
    assert "SPARKNET_PRECONTEXT=0" in text
