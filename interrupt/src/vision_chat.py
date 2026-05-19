from __future__ import annotations

import base64
import glob
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:
    import cv2
except ImportError:  # pragma: no cover - lean env fallback
    cv2 = None


LOGGER = logging.getLogger("interrupt.vision")


@dataclass
class VisionChatConfig:
    enabled: bool
    provider: str
    api_key: str
    base_url: str
    model: str
    image_path: str
    preferred_device: str
    width: int
    height: int
    jpeg_quality: int
    max_tokens: int
    capture_warmup_frames: int
    capture_timeout_s: float


@dataclass
class VisionChatResult:
    ok: bool
    answer: str
    error: str = ""
    camera_device: str = ""
    observation: dict[str, object] | None = None


def ask_camera_question(
    config: VisionChatConfig,
    *,
    question: str,
    reply_language: str,
    structured: bool = False,
) -> VisionChatResult:
    if not config.enabled:
        return VisionChatResult(ok=False, answer="", error="vision_disabled")
    if _vision_backend_requires_api_key(config) and not config.api_key:
        return VisionChatResult(ok=False, answer="", error="missing_api_key")
    if config.image_path.strip():
        image_path = Path(config.image_path.strip()).expanduser()
        if not image_path.exists() or not image_path.is_file():
            return VisionChatResult(ok=False, answer="", error="image_not_found", camera_device=str(image_path))
        try:
            encoded = _encode_image_file_base64(image_path)
        except Exception as exc:
            LOGGER.warning("failed to encode static image: path=%s error=%s", image_path, exc)
            return VisionChatResult(
                ok=False,
                answer="",
                error="image_encode_failed",
                camera_device=str(image_path),
            )
        device = f"image:{image_path}"
    elif cv2 is None:
        capture = _capture_with_external_python(config)
        if not capture.ok:
            return capture
        device = capture.camera_device
        encoded = capture.answer
    else:
        device = _find_camera_device(config.preferred_device)
        if not device:
            return VisionChatResult(ok=False, answer="", error="camera_not_found")

        encoded = _capture_jpeg_base64(config, device)
        if not encoded:
            return VisionChatResult(ok=False, answer="", error="capture_failed", camera_device=device)

    prompt = _build_prompt(
        question=question,
        reply_language=reply_language,
        structured=structured,
    )
    retry_attempts = max(1, int(os.getenv("INTERRUPT_VISION_CHAT_RETRY_ATTEMPTS", "4").strip() or "4"))
    retry_delay_s = max(
        0.1,
        float(os.getenv("INTERRUPT_VISION_CHAT_RETRY_INITIAL_DELAY", "1").strip() or "1"),
    )
    retry_max_delay_s = max(
        retry_delay_s,
        float(os.getenv("INTERRUPT_VISION_CHAT_RETRY_MAX_DELAY", "40").strip() or "40"),
    )
    for attempt in range(1, retry_attempts + 1):
        try:
            response_text = _request_vision_backend(
                config,
                prompt=prompt,
                frame_b64=encoded,
                structured=structured,
            )
            if not structured:
                return VisionChatResult(ok=True, answer=response_text, camera_device=device)
            observation = _parse_structured_observation(
                response_text,
                reply_language=reply_language,
            )
            return VisionChatResult(
                ok=True,
                answer=observation["natural_answer"],
                camera_device=device,
                observation=observation,
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            LOGGER.warning(
                "vision http error: device=%s code=%s attempt=%s/%s body=%s",
                device,
                exc.code,
                attempt,
                retry_attempts,
                detail,
            )
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retry_attempts:
                return VisionChatResult(ok=False, answer="", error=f"http_{exc.code}", camera_device=device)
        except Exception as exc:
            LOGGER.warning(
                "vision request failed: device=%s attempt=%s/%s error=%s",
                device,
                attempt,
                retry_attempts,
                exc,
            )
            if attempt >= retry_attempts:
                return VisionChatResult(ok=False, answer="", error=str(exc), camera_device=device)
        time.sleep(min(retry_max_delay_s, retry_delay_s * (2 ** (attempt - 1))))

    return VisionChatResult(ok=False, answer="", error="http_503", camera_device=device)


def _build_prompt(*, question: str, reply_language: str, structured: bool) -> str:
    language_hint = {
        "zh-YUE": "请只用自然粤语回答。",
        "en": "Reply only in natural English.",
    }.get(reply_language, "请只用自然普通话回答。")
    cleaned_question = (question or "").strip()
    if not cleaned_question:
        cleaned_question = "请描述你现在看到的内容。"
    if structured:
        return _build_structured_prompt(
            question=cleaned_question,
            reply_language=reply_language,
        )
    return (
        f"{language_hint}"
        "你正在查看机器人当前正前方相机的单帧画面。"
        "只回答画面中能直接观察到的内容，不要假装看到了画面外的信息。"
        "如果画面模糊、遮挡严重或无法判断，就明确说明看不清。"
        "如果看到了多个物体，请用完整短句回答，不要停在半句。"
        "回答保持简短、口语化、事实导向。"
        f" 用户问题：{cleaned_question}"
    )


def _build_structured_prompt(*, question: str, reply_language: str) -> str:
    natural_answer_hint = {
        "zh-YUE": "natural_answer 必须使用自然粤语。",
        "en": "natural_answer must be natural English.",
    }.get(reply_language, "natural_answer 必须使用自然普通话。")
    return (
        "你正在查看机器人当前正前方相机的单帧画面。"
        "只根据画面中直接可见的信息回答，不要猜测画面外内容。"
        "如果看不清、遮挡严重或无法判断，就明确标成 unknown。"
        f"{natural_answer_hint}"
        "请只返回一个 JSON 对象，不要使用 Markdown 代码块，不要添加额外说明。"
        'JSON 必须包含这些字段：'
        '"natural_answer",'
        '"person_detected",'
        '"person_count_estimate",'
        '"distance_band",'
        '"obstacle_near_arms",'
        '"free_space_front",'
        '"human_attention",'
        '"scene_visibility".'
        '字段约束：'
        '"person_detected" 只能是 "yes" / "no" / "unknown"；'
        '"person_count_estimate" 只能是整数或 null；'
        '"distance_band" 只能是 "near" / "mid" / "far" / "unknown"；'
        '"obstacle_near_arms" 只能是 "yes" / "no" / "unknown"；'
        '"free_space_front" 只能是 "clear" / "partial" / "blocked" / "unknown"；'
        '"human_attention" 只能是 "attending" / "not_attending" / "unknown"；'
        '"scene_visibility" 只能是 "clear" / "blurry" / "occluded" / "dark" / "unknown"。'
        f" 用户问题：{question}"
    )


def _vision_backend_requires_api_key(config: VisionChatConfig) -> bool:
    return config.provider == "gemini_openai_compat"


def _request_vision_backend(
    config: VisionChatConfig,
    *,
    prompt: str,
    frame_b64: str,
    structured: bool,
) -> str:
    provider = (config.provider or "").strip().lower()
    if provider in {"gemini_openai_compat", "openai_compatible"}:
        return _request_openai_compatible_vision(
            config,
            prompt=prompt,
            frame_b64=frame_b64,
            structured=structured,
        )
    if provider == "ollama_native":
        return _request_ollama_native_vision(
            config,
            prompt=prompt,
            frame_b64=frame_b64,
            structured=structured,
        )
    raise RuntimeError(f"unsupported_vision_provider:{provider or 'empty'}")


def _request_openai_compatible_vision(
    config: VisionChatConfig,
    *,
    prompt: str,
    frame_b64: str,
    structured: bool,
) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{frame_b64}",
                            "detail": "low",
                        },
                    },
                ],
            }
        ],
        "max_tokens": config.max_tokens,
    }
    if structured:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url=config.base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers=_request_headers(config),
        method="POST",
    )
    opener = urllib.request.build_opener(_proxy_handler_for_vision_backend(config))
    with opener.open(request, timeout=max(5.0, config.capture_timeout_s + 5.0)) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    choices = parsed.get("choices") or []
    if not choices:
        raise RuntimeError("vision_response_has_no_choices")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        texts = [part.get("text", "") for part in content if isinstance(part, dict)]
        content = "".join(texts)
    text = str(content or "").strip()
    if not text:
        raise RuntimeError("vision_response_is_empty")
    if structured:
        return text
    return _normalize_vision_answer(text)


def _request_headers(config: VisionChatConfig) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
    }
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def _request_ollama_native_vision(
    config: VisionChatConfig,
    *,
    prompt: str,
    frame_b64: str,
    structured: bool,
) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [frame_b64],
            }
        ],
        "stream": False,
    }
    body = json.dumps(payload).encode("utf-8")
    base_url = _normalize_ollama_native_base_url(config.base_url)
    request = urllib.request.Request(
        url=base_url + "/api/chat",
        data=body,
        headers=_request_headers(config),
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=max(5.0, config.capture_timeout_s + 15.0)) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    message = parsed.get("message") or {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise RuntimeError("vision_response_is_empty")
    if structured:
        return content
    return _normalize_vision_answer(content)


def _normalize_ollama_native_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3].rstrip("/")
    return normalized


def _normalize_vision_answer(answer: str) -> str:
    normalized = " ".join((answer or "").split()).strip()
    if not normalized:
        return ""
    for prefix in ("回答：", "回答:", "答案：", "答案:", "答：", "答:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
            break
    if not normalized:
        return ""
    if normalized[-1] in "。！？.!?":
        return normalized
    if any("a" <= ch.lower() <= "z" for ch in normalized):
        return normalized + "."
    return normalized + "。"


def _parse_structured_observation(response_text: str, *, reply_language: str) -> dict[str, object]:
    payload = _extract_json_object(response_text)
    if payload is None:
        raise RuntimeError("vision_structured_response_not_json")
    natural_answer = _normalize_vision_answer(str(payload.get("natural_answer") or "").strip())
    if not natural_answer:
        natural_answer = _default_natural_answer(reply_language)
    person_detected = _normalize_enum(payload.get("person_detected"), {"yes", "no", "unknown"})
    distance_band = _normalize_enum(payload.get("distance_band"), {"near", "mid", "far", "unknown"})
    obstacle_near_arms = _normalize_enum(payload.get("obstacle_near_arms"), {"yes", "no", "unknown"})
    free_space_front = _normalize_enum(payload.get("free_space_front"), {"clear", "partial", "blocked", "unknown"})
    human_attention = _normalize_enum(payload.get("human_attention"), {"attending", "not_attending", "unknown"})
    scene_visibility = _normalize_enum(payload.get("scene_visibility"), {"clear", "blurry", "occluded", "dark", "unknown"})
    person_count_estimate = _normalize_person_count(payload.get("person_count_estimate"))
    if person_detected == "no":
        person_count_estimate = 0
    return {
        "natural_answer": natural_answer,
        "person_detected": person_detected,
        "person_count_estimate": person_count_estimate,
        "distance_band": distance_band,
        "obstacle_near_arms": obstacle_near_arms,
        "free_space_front": free_space_front,
        "human_attention": human_attention,
        "scene_visibility": scene_visibility,
    }


def _extract_json_object(response_text: str) -> dict[str, object] | None:
    text = (response_text or "").strip()
    if not text:
        return None
    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    candidates.extend(fenced)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize_enum(value: object, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else "unknown"


def _normalize_person_count(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return max(0, value)
    text = str(value).strip().lower()
    if not text or text in {"unknown", "null", "none", "n/a"}:
        return None
    if text.isdigit():
        return max(0, int(text))
    return None


def _default_natural_answer(reply_language: str) -> str:
    if reply_language == "zh-YUE":
        return "我而家未能清楚判斷畫面內容。"
    if reply_language == "en":
        return "I can't clearly determine the scene right now."
    return "我现在还无法清楚判断画面内容。"


def _encode_image_file_base64(image_path: Path) -> str:
    suffix = image_path.suffix.strip().lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise RuntimeError(f"unsupported_image_suffix:{suffix or 'empty'}")
    return base64.b64encode(image_path.read_bytes()).decode("ascii")


def _open_camera_capture(device: str):
    if cv2 is None:
        return None
    if device.startswith("/dev/video"):
        index_text = device.rsplit("video", 1)[-1]
        if index_text.isdigit() and hasattr(cv2, "CAP_V4L2"):
            cap = cv2.VideoCapture(int(index_text), cv2.CAP_V4L2)
            if cap.isOpened():
                return cap
            cap.release()
    return cv2.VideoCapture(device)


def _capture_jpeg_base64(config: VisionChatConfig, device: str) -> str:
    cap = _open_camera_capture(device)
    if cap is None:
        return ""
    if not cap.isOpened():
        LOGGER.warning("failed to open camera: %s", device)
        return ""
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
    except Exception:
        pass
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    deadline = time.monotonic() + max(0.5, config.capture_timeout_s)
    frame = None
    warmup_remaining = max(0, config.capture_warmup_frames)
    while time.monotonic() < deadline:
        ok, current = cap.read()
        if not ok or current is None:
            time.sleep(0.05)
            continue
        frame = current
        if warmup_remaining > 0:
            warmup_remaining -= 1
            continue
        break

    cap.release()
    if frame is None:
        return ""

    ok, buffer = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), max(1, min(config.jpeg_quality, 100))],
    )
    if not ok:
        return ""
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def _find_camera_device(preferred_device: str) -> str:
    preferred = (preferred_device or "").strip()
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred if preferred.startswith("/dev/video") else os.path.join("/dev", preferred))
    candidates.extend(sorted(glob.glob("/dev/video*")))

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen or not os.path.exists(candidate):
            continue
        seen.add(candidate)
        if _probe_camera(candidate):
            return candidate
    return ""


def _probe_camera(device: str) -> bool:
    if cv2 is None:
        return False
    cap = _open_camera_capture(device)
    if cap is None:
        return False
    if not cap.isOpened():
        return False
    try:
        for _ in range(2):
            ok, _frame = cap.read()
            if ok:
                return True
            time.sleep(0.05)
        return False
    finally:
        cap.release()


def _proxy_handler_for_vision_backend(config: VisionChatConfig) -> urllib.request.ProxyHandler:
    if config.provider != "gemini_openai_compat":
        return urllib.request.ProxyHandler({})
    https_proxy = (
        os.getenv("HTTPS_PROXY", "").strip()
        or os.getenv("https_proxy", "").strip()
        or os.getenv("WSS_PROXY", "").strip()
    )
    http_proxy = (
        os.getenv("HTTP_PROXY", "").strip()
        or os.getenv("http_proxy", "").strip()
        or https_proxy
    )
    proxies: dict[str, str] = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return urllib.request.ProxyHandler(proxies)


def _external_capture_python() -> str:
    configured = os.getenv("INTERRUPT_G1_OM1_PYTHON", "").strip()
    if configured:
        return configured
    candidates = (
        Path("/home/unitree/HongTu/OM1/.venv/bin/python"),
        Path("/home/zz/HongTu/OM1/.venv/bin/python"),
        Path("/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1/.venv/bin/python"),
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def _capture_with_external_python(config: VisionChatConfig) -> VisionChatResult:
    python_bin = _external_capture_python()
    if not python_bin:
        return VisionChatResult(ok=False, answer="", error="opencv_unavailable")
    process_timeout_s = max(
        10.0,
        float(os.getenv("INTERRUPT_VISION_EXTERNAL_CAPTURE_TIMEOUT_S", "").strip() or 0.0),
        config.capture_timeout_s + 8.0,
    )
    script = r"""
import base64, glob, json, os, sys, time
import cv2

preferred_device = sys.argv[1].strip()
width = int(sys.argv[2])
height = int(sys.argv[3])
jpeg_quality = int(sys.argv[4])
warmup_frames = int(sys.argv[5])
timeout_s = float(sys.argv[6])

def open_capture(device: str):
    if device.startswith("/dev/video"):
        index_text = device.rsplit("video", 1)[-1]
        if index_text.isdigit() and hasattr(cv2, "CAP_V4L2"):
            cap = cv2.VideoCapture(int(index_text), cv2.CAP_V4L2)
            if cap.isOpened():
                return cap
            cap.release()
    return cv2.VideoCapture(device)

def probe(device: str) -> bool:
    cap = open_capture(device)
    if not cap.isOpened():
        return False
    try:
        for _ in range(2):
            ok, _ = cap.read()
            if ok:
                return True
            time.sleep(0.05)
        return False
    finally:
        cap.release()

candidates = []
if preferred_device:
    if preferred_device.startswith("/dev/video"):
        candidates.append(preferred_device)
    else:
        candidates.append(os.path.join("/dev", preferred_device))
candidates.extend(sorted(glob.glob("/dev/video*")))

seen = set()
device = ""
for candidate in candidates:
    if candidate in seen or not os.path.exists(candidate):
        continue
    seen.add(candidate)
    if probe(candidate):
        device = candidate
        break

if not device:
    print(json.dumps({"ok": False, "error": "camera_not_found"}))
    raise SystemExit(0)

cap = open_capture(device)
if not cap.isOpened():
    print(json.dumps({"ok": False, "error": "capture_failed", "device": device}))
    raise SystemExit(0)
try:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
except Exception:
    pass
try:
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
except Exception:
    pass

deadline = time.monotonic() + max(0.5, timeout_s)
frame = None
remaining = max(0, warmup_frames)
while time.monotonic() < deadline:
    ok, current = cap.read()
    if not ok or current is None:
        time.sleep(0.05)
        continue
    frame = current
    if remaining > 0:
        remaining -= 1
        continue
    break
cap.release()

if frame is None:
    print(json.dumps({"ok": False, "error": "capture_failed", "device": device}))
    raise SystemExit(0)

ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), max(1, min(jpeg_quality, 100))])
if not ok:
    print(json.dumps({"ok": False, "error": "capture_failed", "device": device}))
    raise SystemExit(0)

print(json.dumps({
    "ok": True,
    "device": device,
    "image_b64": base64.b64encode(buffer.tobytes()).decode("ascii"),
}))
"""
    try:
        result = subprocess.run(
            [
                python_bin,
                "-c",
                script,
                config.preferred_device,
                str(config.width),
                str(config.height),
                str(config.jpeg_quality),
                str(config.capture_warmup_frames),
                str(config.capture_timeout_s),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=process_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        LOGGER.warning(
            "external vision capture timed out: python=%s preferred_device=%s process_timeout_s=%.1f capture_timeout_s=%.1f error=%s",
            python_bin,
            config.preferred_device,
            process_timeout_s,
            config.capture_timeout_s,
            exc,
        )
        return VisionChatResult(
            ok=False,
            answer="",
            error="capture_timeout",
            camera_device=config.preferred_device,
        )
    except Exception as exc:
        LOGGER.warning(
            "external vision capture failed to start: python=%s preferred_device=%s error=%s",
            python_bin,
            config.preferred_device,
            exc,
        )
        return VisionChatResult(ok=False, answer="", error="opencv_unavailable")

    if result.returncode != 0:
        LOGGER.warning(
            "external vision capture process failed: python=%s rc=%s stderr=%r",
            python_bin,
            result.returncode,
            result.stderr,
        )
        return VisionChatResult(ok=False, answer="", error="capture_failed")

    stdout = (result.stdout or "").strip().splitlines()
    if not stdout:
        return VisionChatResult(ok=False, answer="", error="capture_failed")
    try:
        payload = json.loads(stdout[-1])
    except json.JSONDecodeError:
        LOGGER.warning("external vision capture returned non-json stdout=%r", result.stdout)
        return VisionChatResult(ok=False, answer="", error="capture_failed")

    if not payload.get("ok"):
        return VisionChatResult(
            ok=False,
            answer="",
            error=str(payload.get("error") or "capture_failed"),
            camera_device=str(payload.get("device") or ""),
        )
    return VisionChatResult(
        ok=True,
        answer=str(payload.get("image_b64") or ""),
        camera_device=str(payload.get("device") or ""),
    )
