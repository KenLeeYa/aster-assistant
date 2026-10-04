from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class Case:
    name: str
    user: str
    schema: dict[str, object]


CASES = (
    Case(
        name="Traditional Chinese",
        user="請用一句台灣繁體中文說明：為什麼高風險工具執行前需要人工核准？",
        schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    ),
    Case(
        name="JSON schema",
        user="整理任務：明天下午三點備份資料庫。priority 必須是 low、medium 或 high。",
        schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "requires_approval": {"type": "boolean"},
            },
            "required": ["summary", "priority", "requires_approval"],
            "additionalProperties": False,
        },
    ),
    Case(
        name="Tool selection",
        user="使用者問明天台北的天氣。只選一個最適合的工具。",
        schema={
            "type": "object",
            "properties": {
                "tool": {
                    "type": "string",
                    "enum": ["calendar_lookup", "weather_lookup", "filesystem_read"],
                },
                "reason": {"type": "string"},
            },
            "required": ["tool", "reason"],
            "additionalProperties": False,
        },
    ),
    Case(
        name="Planning order",
        user="規劃三個不可顛倒的步驟：先備份、再驗證 checksum、最後做隔離還原演練。",
        schema={
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "order": {"type": "integer"},
                            "action": {
                                "type": "string",
                                "enum": ["backup", "checksum", "restore"],
                            },
                        },
                        "required": ["order", "action"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    ),
)


def validate_case(case: Case, value: dict[str, Any]) -> bool:
    if case.name == "Traditional Chinese":
        return isinstance(value.get("answer"), str) and len(value["answer"].strip()) >= 8
    if case.name == "JSON schema":
        return (
            isinstance(value.get("summary"), str)
            and value.get("priority") in {"low", "medium", "high"}
            and isinstance(value.get("requires_approval"), bool)
        )
    if case.name == "Tool selection":
        return value.get("tool") == "weather_lookup" and isinstance(value.get("reason"), str)
    steps = value.get("steps")
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        return False
    return [step.get("action") for step in steps] == [
        "backup",
        "checksum",
        "restore",
    ]


def gib(value: object) -> str:
    return f"{int(value) / (1024**3):.2f}" if isinstance(value, int) else "n/a"


def runtime_usage(client: httpx.Client, model: str) -> tuple[str, str]:
    response = client.get("/api/ps")
    response.raise_for_status()
    models = response.json().get("models", [])
    for item in models:
        if item.get("name") == model or item.get("model") == model:
            return gib(item.get("size")), gib(item.get("size_vram"))
    return "n/a", "n/a"


def unload(client: httpx.Client, model: str) -> None:
    response = client.post("/api/generate", json={"model": model, "keep_alive": 0})
    response.raise_for_status()


def run(chat_model: str, embedding_model: str, output: Path) -> bool:
    rows: list[tuple[str, bool, float, str, str]] = []
    excerpts: list[tuple[str, str]] = []
    with httpx.Client(base_url=BASE_URL, timeout=180.0) as client:
        version_response = client.get("/api/version")
        version_response.raise_for_status()
        ollama_version = version_response.json().get("version", "unknown")

        tags_response = client.get("/api/tags")
        tags_response.raise_for_status()
        installed = {item.get("name") for item in tags_response.json().get("models", [])}
        missing = [name for name in (chat_model, embedding_model) if name not in installed]
        if missing:
            raise RuntimeError(f"models are not installed: {', '.join(missing)}")

        for case in CASES:
            started = time.perf_counter()
            response = client.post(
                "/api/chat",
                json={
                    "model": chat_model,
                    "stream": False,
                    "think": False,
                    "format": case.schema,
                    "messages": [
                        {
                            "role": "system",
                            "content": "只輸出符合 schema 的 JSON；內容使用台灣繁體中文。",
                        },
                        {"role": "user", "content": case.user},
                    ],
                    "options": {"temperature": 0},
                },
            )
            elapsed = time.perf_counter() - started
            response.raise_for_status()
            body = response.json()
            content = body.get("message", {}).get("content", "")
            try:
                parsed = json.loads(content)
            except (TypeError, json.JSONDecodeError):
                parsed = {}
            passed = isinstance(parsed, dict) and validate_case(case, parsed)
            eval_count = body.get("eval_count")
            eval_duration = body.get("eval_duration")
            tokens_per_second = "n/a"
            if isinstance(eval_count, int) and isinstance(eval_duration, int) and eval_duration:
                tokens_per_second = f"{eval_count / (eval_duration / 1_000_000_000):.2f}"
            rows.append((case.name, passed, elapsed, tokens_per_second, str(eval_count or "n/a")))
            excerpts.append((case.name, content.replace("\n", " ")[:240]))

        chat_size, chat_vram = runtime_usage(client, chat_model)

        started = time.perf_counter()
        embed_response = client.post(
            "/api/embed",
            json={"model": embedding_model, "input": "人工核准可降低高風險工具誤執行。"},
        )
        embed_elapsed = time.perf_counter() - started
        embed_response.raise_for_status()
        embeddings = embed_response.json().get("embeddings", [])
        embedding_dimensions = len(embeddings[0]) if embeddings and embeddings[0] else 0
        embed_passed = embedding_dimensions > 0
        embed_size, embed_vram = runtime_usage(client, embedding_model)

        unload(client, chat_model)
        unload(client, embedding_model)

    all_passed = all(row[1] for row in rows) and embed_passed
    lines = [
        "# Model benchmark",
        "",
        f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
        "",
        f"Status: {'PASS' if all_passed else 'FAIL'} (local reproducible suite)",
        "",
        f"- Ollama: {ollama_version}",
        f"- Chat model: `{chat_model}`",
        f"- Embedding model: `{embedding_model}`",
        f"- Chat runtime size / VRAM: {chat_size} GiB / {chat_vram} GiB",
        f"- Embedding runtime size / VRAM: {embed_size} GiB / {embed_vram} GiB",
        "",
        "| Case | Result | Wall seconds | Tokens/s | Output tokens |",
        "|---|---|---:|---:|---:|",
    ]
    for name, passed, elapsed, tokens_per_second, output_tokens in rows:
        lines.append(
            f"| {name} | {'PASS' if passed else 'FAIL'} | {elapsed:.2f} | "
            f"{tokens_per_second} | {output_tokens} |"
        )
    lines.extend(
        [
            f"| Embedding | {'PASS' if embed_passed else 'FAIL'} | {embed_elapsed:.2f} "
            f"| n/a | {embedding_dimensions} dimensions |",
            "",
            "## Output excerpts for human review",
            "",
        ]
    )
    for name, excerpt in excerpts:
        lines.extend([f"### {name}", "", f"`{excerpt}`", ""])
    lines.append(
        "PASS verifies this bounded suite only; it is not a general model-quality or safety claim."
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark approved local Ollama models.")
    parser.add_argument("--chat-model", default="qwen3:8b")
    parser.add_argument("--embedding-model", default="nomic-embed-text:latest")
    parser.add_argument("--output", type=Path, default=Path("reports/model_benchmark.md"))
    args = parser.parse_args()
    try:
        return 0 if run(args.chat_model, args.embedding_model, args.output) else 1
    except (httpx.HTTPError, RuntimeError, OSError, ValueError) as exc:
        print(f"benchmark failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
