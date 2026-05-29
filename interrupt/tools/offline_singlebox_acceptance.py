#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.g1_om1_adapter import G1Om1Adapter
from src.local_text_brain import run_local_text_brain
from src.settings import load_environment, load_settings
from src.vision_chat import VisionChatConfig, ask_camera_question


OFFLINE_SINGLEBOX_ALLOWED_LOCAL_TOOLS = {
    "perform_body_action",
    "set_led_color",
    "ask_camera_vision",
    "list_saved_locations",
    "navigate_to_saved_location",
    "remember_current_location",
}

ALLOWED_CASES = [
    ("action_wave", "挥挥手", "perform_body_action"),
    ("led_blue", "把灯变成蓝色", "set_led_color"),
    ("vision_front", "帮我看看前面有什么", "ask_camera_vision"),
    ("list_locations", "有哪些已保存地点", "list_saved_locations"),
    ("navigate_frontdesk", "带我去前台", "navigate_to_saved_location"),
    ("remember_meeting_room", "把这里记成会议室", "remember_current_location"),
]

BLOCKED_CASES = [
    ("weather", "今天天气怎么样"),
    ("news", "最近新闻是什么"),
    ("open_chat", "随便聊聊 AI"),
]


@dataclass
class CaseResult:
    name: str
    ok: bool
    detail: str
    payload: dict[str, object]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the offline_singlebox acceptance checklist."
    )
    parser.add_argument(
        "--language",
        default="zh-CN",
        choices=["zh-CN", "zh-YUE", "en"],
        help="Language hint for local text and VLM checks.",
    )
    parser.add_argument(
        "--question",
        default="你前面有什么？",
        help="Visual validation question.",
    )
    parser.add_argument(
        "--allow-actuation",
        action="store_true",
        help="Actually execute a harmless local action and LED command.",
    )
    parser.add_argument(
        "--allow-stateful-navigation",
        action="store_true",
        help="Actually execute navigate/remember commands that may change robot state.",
    )
    return parser.parse_args()


def build_vision_config(settings) -> VisionChatConfig:
    return VisionChatConfig(
        enabled=settings.vision.enabled,
        provider=settings.vision.provider,
        api_key=settings.vision.api_key,
        base_url=settings.vision.base_url,
        model=settings.vision.model,
        image_path=settings.vision.image_path,
        preferred_device=settings.vision.preferred_device,
        width=settings.vision.width,
        height=settings.vision.height,
        jpeg_quality=settings.vision.jpeg_quality,
        max_tokens=settings.vision.max_tokens,
        capture_warmup_frames=settings.vision.capture_warmup_frames,
        capture_timeout_s=settings.vision.capture_timeout_s,
    )


def run_allowed_case(settings, prompt: str, expected_tool: str, language: str) -> CaseResult:
    result = run_local_text_brain(
        settings.agent,
        user_text=prompt,
        language=language,
    )
    payload = {
        "prompt": prompt,
        "backend": result.backend,
        "model": result.model,
        "ok": result.ok,
        "error": result.error,
        "text_reply": result.text_reply,
        "tool_calls": [
            {"name": call.name, "arguments": call.arguments} for call in result.tool_calls
        ],
    }
    names = [call.name for call in result.tool_calls]
    disallowed = [name for name in names if name not in OFFLINE_SINGLEBOX_ALLOWED_LOCAL_TOOLS]
    if not result.ok:
        return CaseResult(expected_tool, False, "local_text_failed", payload)
    if expected_tool not in names:
        return CaseResult(expected_tool, False, "expected_tool_missing", payload)
    if disallowed:
        payload["disallowed_tool_calls"] = disallowed
        return CaseResult(expected_tool, False, "disallowed_tool_present", payload)
    return CaseResult(expected_tool, True, "allowed_tool_matched", payload)


def run_blocked_case(settings, prompt: str, language: str) -> CaseResult:
    result = run_local_text_brain(
        settings.agent,
        user_text=prompt,
        language=language,
    )
    payload = {
        "prompt": prompt,
        "backend": result.backend,
        "model": result.model,
        "ok": result.ok,
        "error": result.error,
        "text_reply": result.text_reply,
        "tool_calls": [
            {"name": call.name, "arguments": call.arguments} for call in result.tool_calls
        ],
    }
    allowed = [
        call.name for call in result.tool_calls if call.name in OFFLINE_SINGLEBOX_ALLOWED_LOCAL_TOOLS
    ]
    payload["allowed_tool_calls"] = allowed
    if allowed:
        return CaseResult(prompt, False, "blocked_prompt_resolved_to_allowed_tool", payload)
    return CaseResult(prompt, True, "blocked_prompt_out_of_scope", payload)


def run_list_locations_check(adapter: G1Om1Adapter) -> CaseResult:
    payload = {
        "navigation_available": adapter.navigation_available,
        "path_checks": adapter.validate_paths(),
    }
    if not adapter.navigation_available:
        return CaseResult("list_locations_exec", False, "navigation_backend_unavailable", payload)
    result = adapter.list_saved_locations(compact=True)
    payload["command"] = list(result.command)
    payload["returncode"] = result.returncode
    payload["stdout"] = result.stdout
    payload["stderr"] = result.stderr
    return CaseResult(
        "list_locations_exec",
        result.ok,
        "list_locations_ok" if result.ok else "list_locations_failed",
        payload,
    )


def run_vision_check(settings, question: str, language: str) -> CaseResult:
    config = build_vision_config(settings)
    payload = {
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
        "image_path": config.image_path or "<camera>",
    }
    result = ask_camera_question(
        config,
        question=question,
        reply_language=language,
        structured=True,
    )
    payload["ok"] = result.ok
    payload["error"] = result.error
    payload["camera_device"] = result.camera_device
    payload["answer"] = result.answer
    if result.observation is not None:
        payload["observation"] = result.observation
    return CaseResult(
        "vision_exec",
        result.ok,
        "vision_ok" if result.ok else "vision_failed",
        payload,
    )


def run_optional_actuation_checks(adapter: G1Om1Adapter) -> list[CaseResult]:
    cases: list[CaseResult] = []
    if not adapter.available:
        payload = {"available": adapter.available, "path_checks": adapter.validate_paths()}
        cases.append(CaseResult("action_exec", False, "g1_adapter_unavailable", payload))
        cases.append(CaseResult("led_exec", False, "g1_adapter_unavailable", payload))
        return cases

    action = adapter.execute_direct_text("挥挥手")
    cases.append(
        CaseResult(
            "action_exec",
            action.ok,
            "action_ok" if action.ok else "action_failed",
            {
                "command": list(action.command),
                "returncode": action.returncode,
                "stdout": action.stdout,
                "stderr": action.stderr,
            },
        )
    )
    led = adapter.set_led("blue")
    cases.append(
        CaseResult(
            "led_exec",
            led.ok,
            "led_ok" if led.ok else "led_failed",
            {
                "command": list(led.command),
                "returncode": led.returncode,
                "stdout": led.stdout,
                "stderr": led.stderr,
            },
        )
    )
    return cases


def run_optional_stateful_navigation_checks(adapter: G1Om1Adapter) -> list[CaseResult]:
    cases: list[CaseResult] = []
    if not adapter.navigation_available:
        payload = {
            "navigation_available": adapter.navigation_available,
            "path_checks": adapter.validate_paths(),
        }
        cases.append(CaseResult("navigate_exec", False, "navigation_backend_unavailable", payload))
        cases.append(CaseResult("remember_exec", False, "navigation_backend_unavailable", payload))
        return cases

    navigate = adapter.navigate_to_location("前台")
    cases.append(
        CaseResult(
            "navigate_exec",
            navigate.ok,
            "navigate_ok" if navigate.ok else "navigate_failed",
            {
                "command": list(navigate.command),
                "returncode": navigate.returncode,
                "stdout": navigate.stdout,
                "stderr": navigate.stderr,
            },
        )
    )
    remember = adapter.remember_location(
        "离线验收点",
        description="offline_singlebox acceptance checkpoint",
    )
    cases.append(
        CaseResult(
            "remember_exec",
            remember.ok,
            "remember_ok" if remember.ok else "remember_failed",
            {
                "command": list(remember.command),
                "returncode": remember.returncode,
                "stdout": remember.stdout,
                "stderr": remember.stderr,
            },
        )
    )
    return cases


def main() -> int:
    args = parse_args()
    load_environment()
    settings = load_settings(ROOT_DIR / "config.yaml")
    adapter = G1Om1Adapter()

    results: list[CaseResult] = []

    config_payload = {
        "runtime_mode": settings.agent.runtime_mode,
        "local_text_decision_mode": settings.agent.local_text_decision_mode,
        "backend": settings.agent.backend,
        "local_text_provider": settings.agent.local_text_provider,
        "local_text_base_url": settings.agent.local_text_base_url,
        "local_text_model": settings.agent.local_text_model,
        "vision_provider": settings.vision.provider,
        "vision_base_url": settings.vision.base_url,
        "vision_model": settings.vision.model,
    }
    results.append(
        CaseResult(
            "runtime_config",
            settings.agent.runtime_mode == "offline_singlebox"
            and settings.agent.local_text_decision_mode != "disabled",
            "runtime_config_ok"
            if settings.agent.runtime_mode == "offline_singlebox"
            and settings.agent.local_text_decision_mode != "disabled"
            else "runtime_config_mismatch",
            config_payload,
        )
    )

    for case_name, prompt, expected_tool in ALLOWED_CASES:
        result = run_allowed_case(settings, prompt, expected_tool, args.language)
        result.name = case_name
        results.append(result)

    for case_name, prompt in BLOCKED_CASES:
        result = run_blocked_case(settings, prompt, args.language)
        result.name = case_name
        results.append(result)

    results.append(run_list_locations_check(adapter))
    results.append(run_vision_check(settings, args.question, args.language))

    if args.allow_actuation:
        results.extend(run_optional_actuation_checks(adapter))
    if args.allow_stateful_navigation:
        results.extend(run_optional_stateful_navigation_checks(adapter))

    failures = [item for item in results if not item.ok]
    payload = {
        "ok": not failures,
        "summary": {
            "total": len(results),
            "passed": len(results) - len(failures),
            "failed": len(failures),
        },
        "results": [asdict(item) for item in results],
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
