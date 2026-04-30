from __future__ import annotations

import base64
import glob
import json
import logging
import os
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
    api_key: str
    base_url: str
    model: str
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


def ask_camera_question(
    config: VisionChatConfig,
    *,
    question: str,
    reply_language: str,
) -> VisionChatResult:
    if not config.enabled:
        return VisionChatResult(ok=False, answer="", error="vision_disabled")
    if not config.api_key:
        return VisionChatResult(ok=False, answer="", error="missing_api_key")
    if cv2 is None:
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

    prompt = _build_prompt(question=question, reply_language=reply_language)
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
            answer = _request_gemini_vision(
                config,
                prompt=prompt,
                frame_b64=encoded,
            )
            return VisionChatResult(ok=True, answer=answer, camera_device=device)
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


def _build_prompt(*, question: str, reply_language: str) -> str:
    language_hint = {
        "zh-YUE": "请只用自然粤语回答。",
        "en": "Reply only in natural English.",
    }.get(reply_language, "请只用自然普通话回答。")
    cleaned_question = (question or "").strip()
    if not cleaned_question:
        cleaned_question = "请描述你现在看到的内容。"
    return (
        f"{language_hint}"
        "你正在查看机器人当前正前方相机的单帧画面。"
        "只回答画面中能直接观察到的内容，不要假装看到了画面外的信息。"
        "如果画面模糊、遮挡严重或无法判断，就明确说明看不清。"
        "如果看到了多个物体，请用完整短句回答，不要停在半句。"
        "回答保持简短、口语化、事实导向。"
        f" 用户问题：{cleaned_question}"
    )


def _request_gemini_vision(config: VisionChatConfig, *, prompt: str, frame_b64: str) -> str:
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
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url=config.base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(_proxy_handler_for_gemini())
    with opener.open(request, timeout=max(5.0, config.capture_timeout_s + 5.0)) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    choices = parsed.get("choices") or []
    if not choices:
        raise RuntimeError("vision_response_has_no_choices")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        texts = [part.get("text", "") for part in content if isinstance(part, dict)]
        content = "".join(texts)
    normalized = _normalize_vision_answer(str(content or "").strip())
    if not normalized:
        raise RuntimeError("vision_response_is_empty")
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


def _capture_jpeg_base64(config: VisionChatConfig, device: str) -> str:
    cap = cv2.VideoCapture(device)
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
    cap = cv2.VideoCapture(device)
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


def _proxy_handler_for_gemini() -> urllib.request.ProxyHandler:
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
    script = r"""
import base64, glob, json, os, sys, time
import cv2

preferred_device = sys.argv[1].strip()
width = int(sys.argv[2])
height = int(sys.argv[3])
jpeg_quality = int(sys.argv[4])
warmup_frames = int(sys.argv[5])
timeout_s = float(sys.argv[6])

def probe(device: str) -> bool:
    cap = cv2.VideoCapture(device)
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

cap = cv2.VideoCapture(device)
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
            timeout=max(10.0, config.capture_timeout_s + 5.0),
        )
    except Exception as exc:
        LOGGER.warning("external vision capture failed to start: python=%s error=%s", python_bin, exc)
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
