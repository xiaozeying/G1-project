from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError

from src.settings import AgentConfig


@dataclass
class LocalTextToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LocalTextDecision:
    ok: bool
    backend: str
    model: str
    text_reply: str
    tool_calls: list[LocalTextToolCall]
    raw_message: dict[str, Any]
    error: str = ""


def _system_prompt(language: str) -> str:
    return (
        "你是一个运行在机器人本地/局域网侧的文本决策脑。\n"
        "目标是根据用户输入，优先给出结构化工具调用；如果不适合调工具，再给简短文本回复。\n"
        "规则：\n"
        "1. 用户要求动作时，优先调用 perform_body_action。\n"
        "2. 用户要求灯光时，优先调用 set_led_color。\n"
        "3. 用户要求看前方/看画面时，优先调用 ask_camera_vision。\n"
        "4. 用户要求导航或保存地点时，优先调用导航相关工具。\n"
        "5. 做不到的能力要诚实拒答，不要假装已经执行。\n"
        "6. 默认用简洁中文输出；仅当用户明确要求其他语言时再切换。\n"
        "7. 你是机器人本地决策组件，不要自称 Qwen、阿里云或任何底层模型厂商。\n"
        f"8. 当前目标回复语言偏好：{language}。\n"
    )


def _build_user_prompt(user_text: str, language: str) -> str:
    return (
        "BASIC CONTEXT:\n"
        f"{_system_prompt(language)}\n"
        "AVAILABLE ACTIONS:\n"
        "1. set_led_color(color): 设置灯光颜色。\n"
        "2. perform_body_action(action): 执行上半身动作。\n"
        "3. execute_robot_command_text(text): 执行归一化机器人命令文本。\n"
        "4. ask_camera_vision(question): 询问当前前视画面内容。\n"
        "5. get_weather(location): 查询天气。\n"
        "6. get_news(topic): 查询新闻。\n"
        "7. list_saved_locations(): 列出已保存地点。\n"
        "8. navigate_to_saved_location(location): 导航到已保存地点。\n"
        "9. remember_current_location(location, description): 保存当前位置。\n\n"
        "USER INPUT:\n"
        f"{user_text}\n\n"
        "请优先返回工具调用；如果不需要调工具，再返回简短自然语言回复。"
    )


def _tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "set_led_color",
                "description": "Set the robot LED to a color.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "color": {"type": "string"},
                    },
                    "required": ["color"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "perform_body_action",
                "description": "Trigger a predefined upper-body gesture.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_robot_command_text",
                "description": "Execute a normalized direct robot command from text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_camera_vision",
                "description": "Inspect the current front camera view and answer a visual question.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                    },
                    "required": ["question"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city or region.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                    },
                    "required": ["location"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_news",
                "description": "Get current news headlines for a topic.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_saved_locations",
                "description": "List saved navigation locations.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "navigate_to_saved_location",
                "description": "Navigate to one saved location by exact name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                    },
                    "required": ["location"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remember_current_location",
                "description": "Save the current robot position as a named location.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["location"],
                },
            },
        },
    ]


def _normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if normalized.endswith("/api"):
        return normalized
    return normalized + "/api"


def _parse_ollama_tool_calls(message: dict[str, Any]) -> list[LocalTextToolCall]:
    tool_calls_raw = message.get("tool_calls") or []
    tool_calls: list[LocalTextToolCall] = []
    for item in tool_calls_raw:
        function = item.get("function") or {}
        name = str(function.get("name") or "").strip()
        arguments = function.get("arguments") or {}
        if not name:
            continue
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        tool_calls.append(LocalTextToolCall(name=name, arguments=arguments))
    return tool_calls


_PSEUDO_TOOL_CALL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", re.S)


def _parse_pseudo_tool_from_text(content: str) -> tuple[LocalTextToolCall | None, str]:
    normalized = (content or "").strip()
    if not normalized:
        return None, ""

    parsed: dict[str, Any] | None = None
    try:
        raw = json.loads(normalized)
        if isinstance(raw, dict):
            parsed = raw
    except json.JSONDecodeError:
        match = _PSEUDO_TOOL_CALL_RE.match(normalized)
        if match:
            name = match.group(1).strip()
            args_raw = match.group(2).strip()
            try:
                arguments = json.loads(args_raw) if args_raw else {}
            except json.JSONDecodeError:
                arguments = {"raw": args_raw}
            parsed = {"name": name, "arguments": arguments}

    if not parsed:
        return None, normalized

    name = str(parsed.get("name") or "").strip()
    arguments = parsed.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {"text": arguments}
    if not isinstance(arguments, dict):
        arguments = {"value": arguments}
    if not name:
        return None, normalized

    if name == "execute_robot_command_text":
        text = str(arguments.get("text") or "").strip()
        return None, text or normalized

    return LocalTextToolCall(name=name, arguments=arguments), ""


def _urlopen_without_proxy(
    request: urllib.request.Request, *, timeout: float
) -> urllib.response.addinfourl:
    # 开发机常驻 HTTP_PROXY，localhost/LAN 请求如果被代理会出现假性 502。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def run_local_text_brain(
    agent_config: AgentConfig,
    *,
    user_text: str,
    language: str = "zh-CN",
) -> LocalTextDecision:
    backend = agent_config.backend
    if backend != "local_text_ollama":
        return LocalTextDecision(
            ok=False,
            backend=backend,
            model=agent_config.local_text_model,
            text_reply="",
            tool_calls=[],
            raw_message={},
            error=f"unsupported_local_text_backend:{backend}",
        )

    payload = {
        "model": agent_config.local_text_model,
        "stream": False,
        "messages": [
            {"role": "user", "content": _build_user_prompt(user_text, language)},
        ],
        "tools": _tool_schemas(),
        "options": {
            "temperature": 0.2,
        },
    }
    url = _normalize_base_url(agent_config.local_text_base_url) + "/chat"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlopen_without_proxy(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return LocalTextDecision(
            ok=False,
            backend=backend,
            model=agent_config.local_text_model,
            text_reply="",
            tool_calls=[],
            raw_message={},
            error=f"ollama_http_error:{exc.code}:{detail}",
        )
    except (TimeoutError, URLError, OSError) as exc:
        return LocalTextDecision(
            ok=False,
            backend=backend,
            model=agent_config.local_text_model,
            text_reply="",
            tool_calls=[],
            raw_message={},
            error=f"ollama_request_failed:{exc}",
        )

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return LocalTextDecision(
            ok=False,
            backend=backend,
            model=agent_config.local_text_model,
            text_reply="",
            tool_calls=[],
            raw_message={},
            error=f"ollama_invalid_json:{exc}",
        )

    message = data.get("message") or {}
    content = str(message.get("content") or "").strip()
    tool_calls = _parse_ollama_tool_calls(message)
    if not tool_calls and content:
        pseudo_tool, normalized_text = _parse_pseudo_tool_from_text(content)
        if pseudo_tool is not None:
            tool_calls = [pseudo_tool]
            content = ""
        else:
            content = normalized_text
    return LocalTextDecision(
        ok=True,
        backend=backend,
        model=agent_config.local_text_model,
        text_reply=content,
        tool_calls=tool_calls,
        raw_message=message if isinstance(message, dict) else {},
    )
