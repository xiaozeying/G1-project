#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.settings import load_environment, load_settings
from src.vision_chat import VisionChatConfig, ask_camera_question


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the same visual prompts across multiple local/offline VLM backends."
    )
    parser.add_argument(
        "--matrix",
        required=True,
        help="Path to a JSON file describing candidate models and questions.",
    )
    parser.add_argument(
        "--image",
        default="",
        help="Optional static image override. Falls back to matrix.image or config image_path.",
    )
    parser.add_argument(
        "--language",
        default="",
        choices=["", "zh-CN", "zh-YUE", "en"],
        help="Optional reply language override. Falls back to matrix.reply_language or zh-CN.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON output path. Defaults to interrupt/tmp/vlm_compare_last.json.",
    )
    return parser.parse_args()


def _read_matrix(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"matrix_not_found:{path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"matrix_invalid_json:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("matrix_root_must_be_object")
    candidates = payload.get("candidates")
    questions = payload.get("questions")
    if not isinstance(candidates, list) or not candidates:
        raise SystemExit("matrix_candidates_missing")
    if not isinstance(questions, list) or not questions:
        raise SystemExit("matrix_questions_missing")
    return payload


def _build_config(
    settings,
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    image_path: str,
) -> VisionChatConfig:
    return VisionChatConfig(
        enabled=True,
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        image_path=image_path,
        preferred_device=settings.vision.preferred_device,
        width=settings.vision.width,
        height=settings.vision.height,
        jpeg_quality=settings.vision.jpeg_quality,
        max_tokens=settings.vision.max_tokens,
        capture_warmup_frames=settings.vision.capture_warmup_frames,
        capture_timeout_s=settings.vision.capture_timeout_s,
    )


def _print_summary(results: list[dict[str, object]]) -> None:
    print("summary:")
    for item in results:
        label = str(item["candidate_id"])
        question_id = str(item["question_id"])
        ok = "OK" if item["ok"] else "FAIL"
        elapsed_ms = int(item["elapsed_ms"])
        answer = str(item.get("answer") or "")
        if len(answer) > 80:
            answer = answer[:77] + "..."
        print(f"  - {label} | {question_id} | {ok} | {elapsed_ms}ms | {answer}")


def _build_probe_opener(base_url: str, provider: str) -> urllib.request.OpenerDirector:
    host = (urlparse(base_url).hostname or "").strip().lower()
    if provider == "ollama_native" or host in {"127.0.0.1", "localhost", "::1"}:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _probe_candidate_backend(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout_s: float = 3.0,
) -> tuple[bool, str, bool | None]:
    normalized_provider = provider.strip().lower()
    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    if normalized_provider == "ollama_native":
        url = base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        url = url.rstrip("/") + "/api/tags"
    elif normalized_provider in {"openai_compatible", "gemini_openai_compat"}:
        url = base_url.rstrip("/") + "/models"
    else:
        return True, "probe_skipped_unsupported_provider", None

    request = urllib.request.Request(url=url, headers=headers, method="GET")
    opener = _build_probe_opener(base_url, normalized_provider)
    try:
        with opener.open(request, timeout=max(1.0, timeout_s)) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}", None
    except Exception as exc:
        return False, str(exc), None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False, f"invalid_json:{exc}", None

    ids: list[str] = []
    if normalized_provider == "ollama_native":
        for item in payload.get("models", []):
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    ids.append(name)
    else:
        for item in payload.get("data", []):
            if isinstance(item, dict):
                name = str(item.get("id") or "").strip()
                if name:
                    ids.append(name)
    return True, "ok", model in ids


def main() -> int:
    args = parse_args()
    load_environment()
    settings = load_settings(ROOT_DIR / "config.yaml")

    matrix_path = Path(args.matrix).expanduser()
    if not matrix_path.is_absolute():
        matrix_path = (Path.cwd() / matrix_path).resolve()
    matrix = _read_matrix(matrix_path)

    default_language = args.language.strip() or str(matrix.get("reply_language") or "zh-CN")
    default_image = args.image.strip() or str(matrix.get("image") or settings.vision.image_path)
    candidates = matrix["candidates"]
    questions = matrix["questions"]

    results: list[dict[str, object]] = []
    started_at = time.time()

    for candidate_index, candidate_raw in enumerate(candidates, start=1):
        if not isinstance(candidate_raw, dict):
            results.append(
                {
                    "candidate_id": f"candidate_{candidate_index}",
                    "question_id": "<none>",
                    "ok": False,
                    "error": "candidate_not_object",
                    "elapsed_ms": 0,
                }
            )
            continue
        candidate_id = str(candidate_raw.get("id") or f"candidate_{candidate_index}")
        provider = str(candidate_raw.get("provider") or settings.vision.provider).strip()
        base_url = str(candidate_raw.get("base_url") or settings.vision.base_url).strip()
        model = str(candidate_raw.get("model") or settings.vision.model).strip()
        api_key = str(candidate_raw.get("api_key") or settings.vision.api_key).strip()
        image_path = str(candidate_raw.get("image") or default_image).strip()
        reply_language = str(candidate_raw.get("reply_language") or default_language).strip() or "zh-CN"
        structured = bool(candidate_raw.get("structured", True))
        config = _build_config(
            settings,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            image_path=image_path,
        )
        backend_ok, backend_status, model_found = _probe_candidate_backend(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )

        if not backend_ok or model_found is False:
            for question_index, question_raw in enumerate(questions, start=1):
                if isinstance(question_raw, dict):
                    question_id = str(question_raw.get("id") or f"question_{question_index}")
                    question = str(question_raw.get("text") or "").strip()
                else:
                    question_id = f"question_{question_index}"
                    question = str(question_raw).strip()
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "provider": provider,
                        "base_url": base_url,
                        "model": model,
                        "image_path": image_path or "<camera>",
                        "question_id": question_id,
                        "question": question,
                        "reply_language": reply_language,
                        "structured": structured,
                        "elapsed_ms": 0,
                        "ok": False,
                        "camera_device": "",
                        "error": backend_status if not backend_ok else "model_not_found",
                        "backend_ok": backend_ok,
                        "model_found": model_found,
                    }
                )
            continue

        for question_index, question_raw in enumerate(questions, start=1):
            if isinstance(question_raw, dict):
                question_id = str(question_raw.get("id") or f"question_{question_index}")
                question = str(question_raw.get("text") or "").strip()
                per_question_language = (
                    str(question_raw.get("reply_language") or reply_language).strip() or reply_language
                )
            else:
                question_id = f"question_{question_index}"
                question = str(question_raw).strip()
                per_question_language = reply_language
            if not question:
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "question_id": question_id,
                        "ok": False,
                        "error": "question_empty",
                        "elapsed_ms": 0,
                    }
                )
                continue

            run_started = time.perf_counter()
            result = ask_camera_question(
                config,
                question=question,
                reply_language=per_question_language,
                structured=structured,
            )
            elapsed_ms = round((time.perf_counter() - run_started) * 1000, 1)

            row: dict[str, object] = {
                "candidate_id": candidate_id,
                "provider": provider,
                "base_url": base_url,
                "model": model,
                "image_path": image_path or "<camera>",
                "question_id": question_id,
                "question": question,
                "reply_language": per_question_language,
                "structured": structured,
                "elapsed_ms": elapsed_ms,
                "ok": result.ok,
                "camera_device": result.camera_device,
                "backend_ok": backend_ok,
                "model_found": model_found,
            }
            if result.ok:
                row["answer"] = result.answer
                if result.observation is not None:
                    row["observation"] = result.observation
            else:
                row["error"] = result.error
            results.append(row)

    payload = {
        "matrix_path": str(matrix_path),
        "started_at_epoch_s": started_at,
        "total_candidates": len(candidates),
        "total_questions": len(questions),
        "results": results,
    }

    output_path = args.output.strip()
    if output_path:
        target = Path(output_path).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
    else:
        target = ROOT_DIR / "tmp" / "vlm_compare_last.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    _print_summary(results)
    print(f"output_json: {target}")

    return 0 if all(bool(item.get("ok")) for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
