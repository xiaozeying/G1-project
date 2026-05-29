from __future__ import annotations

import json
import ipaddress
import re
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

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


def _localized_text(language: str, mandarin: str, cantonese: str, english: str) -> str:
    normalized = (language or "").strip()
    if normalized == "zh-YUE":
        return cantonese
    if normalized == "en":
        return english
    return mandarin


def _target_language_instruction(language: str) -> str:
    normalized = (language or "").strip()
    if normalized == "zh-YUE":
        return (
            "当前目标回复语言是粤语（zh-YUE）。"
            " 如果返回文本回复，必须只用自然粤语表达，不要夹普通话书面腔，也不要输出英文。"
        )
    if normalized == "en":
        return (
            "Current target reply language is English (en)."
            " If you return a text reply, respond only in natural English and do not mix in Chinese."
        )
    return (
        "当前目标回复语言是普通话（zh-CN）。"
        " 如果返回文本回复，必须只用自然普通话表达，不要夹粤语口语或英文。"
    )


def _system_prompt(language: str) -> str:
    return (
        "你是一个运行在机器人本地/局域网侧的文本决策脑。\n"
        "目标是根据用户输入，优先给出结构化工具调用；如果不适合调工具，再给简短文本回复。\n"
        "规则：\n"
        "1. 用户要求动作时，优先调用 perform_body_action。\n"
        "2. 用户要求灯光时，优先调用 set_led_color。\n"
        "3. 用户要求看前方/看画面时，优先调用 ask_camera_vision。\n"
        "4. 用户要求导航或保存地点时，优先调用导航相关工具。\n"
        "5. 开放闲聊、泛泛聊 AI、陪聊、寒暄、新闻、天气、知识问答，不要硬映射成动作或灯光工具。\n"
        "6. 只有当用户明确要求机器人执行现实世界动作/灯光/看前方/导航/记地点时，才调用对应工具。\n"
        "7. 做不到的能力要诚实拒答，不要假装已经执行。\n"
        "8. 默认跟随当前目标回复语言输出，不要固定偏向中文。\n"
        "9. 你是机器人本地决策组件，不要自称 Qwen、阿里云或任何底层模型厂商。\n"
        "10. 如果要返回工具调用，参数内容优先保持和用户说法一致；如果要返回文本回复，必须严格遵守目标语言要求。\n"
        "11. 如果用户要求“之后用粤语/英语/普通话回答”，这是上游 agent 负责记录的语言状态；你只需要遵守当前传入的目标语言。\n"
        f"12. 当前目标回复语言偏好：{language}。\n"
        f"13. {_target_language_instruction(language)}\n"
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


def _normalize_openai_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return normalized + "/v1"


def _build_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    return headers


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


def _parse_openai_tool_calls(message: dict[str, Any]) -> list[LocalTextToolCall]:
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
_OPEN_CHAT_PATTERNS = (
    "聊聊",
    "聊天",
    "闲聊",
    "閒聊",
    "随便聊",
    "隨便聊",
    "open chat",
    "let's chat",
    "lets chat",
    "casually chat",
    "chat about",
    "talk about",
    "artificial intelligence",
    "人工智能",
)
_SAVED_LOCATIONS_PATTERNS = (
    "哪些已保存地点",
    "有哪些已保存地点",
    "地点列表",
    "保存地点",
    "已保存地點",
    "有咩已儲存地點",
    "有哪些已儲存地點",
    "saved locations",
    "saved places",
    "location list",
)


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


def _looks_like_open_chat_request(user_text: str) -> bool:
    normalized = (user_text or "").strip().lower()
    if not normalized:
        return False
    return any(token in normalized for token in _OPEN_CHAT_PATTERNS)


def _looks_like_saved_locations_query(user_text: str) -> bool:
    normalized = (user_text or "").strip().lower()
    if not normalized:
        return False
    return any(token in normalized for token in _SAVED_LOCATIONS_PATTERNS)


def _sanitize_tool_calls(
    language: str,
    user_text: str,
    tool_calls: list[LocalTextToolCall],
    text_reply: str,
) -> tuple[list[LocalTextToolCall], str]:
    normalized_reply = (text_reply or "").strip()

    if _looks_like_open_chat_request(user_text):
        fallback_reply = normalized_reply or _localized_text(
            language,
            "当然可以，我们可以聊聊人工智能。你想先聊应用场景、发展趋势，还是机器人能力？",
            "當然可以，我哋可以傾下人工智能。你想先傾應用場景、發展趨勢，定係機械人能力？",
            "Of course. We can chat about artificial intelligence. Would you like to start with use cases, trends, or robot capabilities?",
        )
        if any(
            token in fallback_reply.lower()
            for token in (
                "online enhanced mode",
                "在线增强模式",
                "在線增強模式",
                "local offline tool",
                "本地离线工具",
                "本地離線工具",
            )
        ):
            fallback_reply = _localized_text(
                language,
                "当然可以，我们可以聊聊人工智能。你想先聊应用场景、发展趋势，还是机器人能力？",
                "當然可以，我哋可以傾下人工智能。你想先傾應用場景、發展趨勢，定係機械人能力？",
                "Of course. We can chat about artificial intelligence. Would you like to start with use cases, trends, or robot capabilities?",
            )
        return [], fallback_reply

    if not tool_calls:
        return tool_calls, text_reply

    normalized_text = (user_text or "").strip()

    if (
        _looks_like_saved_locations_query(normalized_text)
        and len(tool_calls) == 1
        and tool_calls[0].name == "navigate_to_saved_location"
    ):
        location = str(tool_calls[0].arguments.get("location") or "").strip()
        if location in {
            "已保存地点列表",
            "地点列表",
            "保存地点",
            "已保存地點列表",
            "地點列表",
            "已儲存地點",
            "saved locations",
            "saved places",
            "location list",
        }:
            return [LocalTextToolCall(name="list_saved_locations", arguments={})], text_reply

    return tool_calls, text_reply


def _urlopen_without_proxy(
    request: urllib.request.Request, *, timeout: float
) -> urllib.response.addinfourl:
    # 开发机常驻 HTTP_PROXY，localhost/LAN 请求如果被代理会出现假性 502。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def _urlopen_with_local_text_proxy_policy(
    request: urllib.request.Request, *, timeout: float, base_url: str
) -> urllib.response.addinfourl:
    host = (urlparse(base_url).hostname or "").strip().lower()
    try:
        if host in {"127.0.0.1", "localhost", "::1"} or ipaddress.ip_address(host).is_private:
            return _urlopen_without_proxy(request, timeout=timeout)
    except ValueError:
        pass
    return urllib.request.urlopen(request, timeout=timeout)


def _run_ollama_local_text_brain(
    agent_config: AgentConfig,
    *,
    user_text: str,
    language: str,
) -> LocalTextDecision:
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
        with _urlopen_with_local_text_proxy_policy(
            request,
            timeout=20,
            base_url=agent_config.local_text_base_url,
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return LocalTextDecision(
            ok=False,
            backend=agent_config.backend,
            model=agent_config.local_text_model,
            text_reply="",
            tool_calls=[],
            raw_message={},
            error=f"ollama_http_error:{exc.code}:{detail}",
        )
    except (TimeoutError, URLError, OSError) as exc:
        return LocalTextDecision(
            ok=False,
            backend=agent_config.backend,
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
            backend=agent_config.backend,
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
    tool_calls, content = _sanitize_tool_calls(language, user_text, tool_calls, content)
    return LocalTextDecision(
        ok=True,
        backend=agent_config.backend,
        model=agent_config.local_text_model,
        text_reply=content,
        tool_calls=tool_calls,
        raw_message=message if isinstance(message, dict) else {},
    )


def _run_openai_compatible_local_text_brain(
    agent_config: AgentConfig,
    *,
    user_text: str,
    language: str,
) -> LocalTextDecision:
    payload = {
        "model": agent_config.local_text_model,
        "messages": [
            {"role": "user", "content": _build_user_prompt(user_text, language)},
        ],
        "tools": _tool_schemas(),
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    url = _normalize_openai_base_url(agent_config.local_text_base_url) + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=_build_headers(agent_config.local_text_api_key),
        method="POST",
    )
    try:
        with _urlopen_with_local_text_proxy_policy(
            request,
            timeout=30,
            base_url=agent_config.local_text_base_url,
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return LocalTextDecision(
            ok=False,
            backend=agent_config.backend,
            model=agent_config.local_text_model,
            text_reply="",
            tool_calls=[],
            raw_message={},
            error=f"openai_http_error:{exc.code}:{detail}",
        )
    except (TimeoutError, URLError, OSError) as exc:
        return LocalTextDecision(
            ok=False,
            backend=agent_config.backend,
            model=agent_config.local_text_model,
            text_reply="",
            tool_calls=[],
            raw_message={},
            error=f"openai_request_failed:{exc}",
        )

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return LocalTextDecision(
            ok=False,
            backend=agent_config.backend,
            model=agent_config.local_text_model,
            text_reply="",
            tool_calls=[],
            raw_message={},
            error=f"openai_invalid_json:{exc}",
        )

    choices = data.get("choices") or []
    message = {}
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "\n".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and str(item.get("type") or "") == "text"
        )
    content = str(content or "").strip()
    tool_calls = _parse_openai_tool_calls(message if isinstance(message, dict) else {})
    if not tool_calls and content:
        pseudo_tool, normalized_text = _parse_pseudo_tool_from_text(content)
        if pseudo_tool is not None:
            tool_calls = [pseudo_tool]
            content = ""
        else:
            content = normalized_text
    tool_calls, content = _sanitize_tool_calls(language, user_text, tool_calls, content)
    return LocalTextDecision(
        ok=True,
        backend=agent_config.backend,
        model=agent_config.local_text_model,
        text_reply=content,
        tool_calls=tool_calls,
        raw_message=message if isinstance(message, dict) else {},
    )


def run_local_text_brain(
    agent_config: AgentConfig,
    *,
    user_text: str,
    language: str = "zh-CN",
) -> LocalTextDecision:
    provider = str(agent_config.local_text_provider or "").strip().lower()
    if provider == "openai_compatible" or agent_config.backend == "local_text_openai_compatible":
        return _run_openai_compatible_local_text_brain(
            agent_config,
            user_text=user_text,
            language=language,
        )
    if provider == "ollama" or agent_config.backend == "local_text_ollama":
        return _run_ollama_local_text_brain(
            agent_config,
            user_text=user_text,
            language=language,
        )
    return LocalTextDecision(
        ok=False,
        backend=agent_config.backend,
        model=agent_config.local_text_model,
        text_reply="",
        tool_calls=[],
        raw_message={},
        error=f"unsupported_local_text_provider:{provider or 'empty'}",
    )
