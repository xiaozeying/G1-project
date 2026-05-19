from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback for lean robot-side envs
    def load_dotenv(*_args: object, **_kwargs: object) -> bool:
        return False


@dataclass
class LiveKitConfig:
    url: str
    api_key: str
    api_secret: str


@dataclass
class AgentConfig:
    name: str
    backend: str
    runtime_mode: str
    local_text_decision_mode: str
    model: str
    voice: str
    language: str
    instructions: str
    interruption_acknowledgement: str
    enable_input_transcription: bool
    enable_output_transcription: bool
    allow_interruptions: bool
    interruption_mode: str
    min_endpointing_delay_ms: int
    max_endpointing_delay_ms: int
    min_interruption_duration_ms: int
    false_interruption_timeout_ms: int
    aec_warmup_duration_ms: int
    user_away_timeout_ms: int
    local_text_provider: str
    local_text_api_key: str
    local_text_base_url: str
    local_text_model: str


@dataclass
class WebConfig:
    host: str
    port: int
    room_name: str
    identity_prefix: str
    token_ttl_minutes: int


@dataclass
class LoggingConfig:
    level: str


@dataclass
class FeedbackConfig:
    assistant_audio_mode: str
    local_tool_ack_audio_mode: str


@dataclass
class VisionConfig:
    enabled: bool
    provider: str
    api_key: str
    model: str
    base_url: str
    image_path: str
    preferred_device: str
    width: int
    height: int
    jpeg_quality: int
    max_tokens: int
    capture_warmup_frames: int
    capture_timeout_s: float


@dataclass
class ConsoleConfig:
    input_device: str
    output_device: str
    text_mode: bool
    record: bool


@dataclass
class RtcEndpointConfig:
    enabled: bool
    room_name: str
    identity: str
    publish_microphone: bool
    subscribe_audio: bool
    input_device: str
    output_device: str
    auto_create_room: bool
    auto_dispatch_agent: bool
    auto_redispatch_on_agent_disconnect: bool
    redispatch_cooldown_s: float
    agent_absence_check_interval_s: float


@dataclass
class IntegrationConfig:
    wake_word_factory: str
    mcp_stdio_command: str
    mcp_http_urls: tuple[str, ...]


@dataclass
class AppSettings:
    livekit: LiveKitConfig
    agent: AgentConfig
    web: WebConfig
    feedback: FeedbackConfig
    vision: VisionConfig
    console: ConsoleConfig
    rtc_endpoint: RtcEndpointConfig
    integrations: IntegrationConfig
    logging: LoggingConfig
    gemini_api_key: str


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def load_environment() -> None:
    root = _root_dir()
    load_dotenv(root / ".env.local", override=False)
    load_dotenv(root / ".env", override=False)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _normalize_feedback_mode(value: object, *, default: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return default
    alias_map = {
        "1": "om1_mirror",
        "true": "om1_mirror",
        "yes": "om1_mirror",
        "on": "om1_mirror",
        "mirror": "om1_mirror",
        "om1": "om1_mirror",
        "local": "om1_mirror",
        "0": "transport_only",
        "false": "transport_only",
        "no": "transport_only",
        "off": "transport_only",
        "remote": "transport_only",
        "transport": "transport_only",
        "transport_only": "transport_only",
        "disabled": "disabled",
        "none": "disabled",
    }
    return alias_map.get(normalized, normalized)


def _normalize_vision_provider(value: object) -> str:
    normalized = str(value or "").strip().lower()
    alias_map = {
        "": "gemini_openai_compat",
        "gemini": "gemini_openai_compat",
        "gemini_openai": "gemini_openai_compat",
        "gemini_openai_compat": "gemini_openai_compat",
        "openai": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "local_openai": "openai_compatible",
        "vllm": "openai_compatible",
        "sglang": "openai_compatible",
        "ollama": "ollama_native",
        "ollama_native": "ollama_native",
    }
    return alias_map.get(normalized, normalized or "gemini_openai_compat")


def _normalize_agent_backend(value: object) -> str:
    normalized = str(value or "").strip().lower()
    alias_map = {
        "": "gemini_realtime",
        "gemini": "gemini_realtime",
        "gemini_realtime": "gemini_realtime",
        "google_realtime": "gemini_realtime",
        "local_text": "local_text_ollama",
        "local_text_ollama": "local_text_ollama",
        "local_text_openai": "local_text_openai_compatible",
        "local_text_openai_compatible": "local_text_openai_compatible",
        "ollama_text": "local_text_ollama",
        "offline_text": "local_text_ollama",
    }
    return alias_map.get(normalized, normalized or "gemini_realtime")


def _normalize_local_text_provider(value: object) -> str:
    normalized = str(value or "").strip().lower()
    alias_map = {
        "": "ollama",
        "ollama": "ollama",
        "ollama_native": "ollama",
        "openai": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "local_openai": "openai_compatible",
        "vllm": "openai_compatible",
        "sglang": "openai_compatible",
        "minicpm": "openai_compatible",
        "minicpm_v46": "openai_compatible",
    }
    return alias_map.get(normalized, normalized or "ollama")


def _normalize_agent_runtime_mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    alias_map = {
        "": "online_full",
        "online": "online_full",
        "online_full": "online_full",
        "full": "online_full",
        "default": "online_full",
        "offline": "offline_singlebox",
        "offline_singlebox": "offline_singlebox",
        "singlebox": "offline_singlebox",
        "local_only": "offline_singlebox",
        "degraded": "offline_singlebox",
    }
    return alias_map.get(normalized, normalized or "online_full")


def _normalize_local_text_decision_mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    alias_map = {
        "": "disabled",
        "off": "disabled",
        "false": "disabled",
        "0": "disabled",
        "disabled": "disabled",
        "shadow": "shadow",
        "observe": "shadow",
        "log_only": "shadow",
        "prefer": "prefer_tools",
        "prefer_tools": "prefer_tools",
        "tool_first": "prefer_tools",
        "local_first": "prefer_tools",
        "prefer_all": "prefer_all",
        "all": "prefer_all",
        "reply_first": "prefer_all",
        "full": "prefer_all",
        "1": "prefer_tools",
        "true": "prefer_tools",
        "on": "prefer_tools",
    }
    return alias_map.get(normalized, normalized or "disabled")


def load_settings(config_path: str | os.PathLike[str] | None = None) -> AppSettings:
    load_environment()
    path = Path(config_path) if config_path else _root_dir() / "config.yaml"
    raw = _read_yaml(path)

    livekit = raw.get("livekit", {})
    agent = raw.get("agent", {})
    web = raw.get("web", {})
    feedback = raw.get("feedback", {})
    console = raw.get("console", {})
    rtc_endpoint = raw.get("rtc_endpoint", {})
    integrations = raw.get("integrations", {})
    logging = raw.get("logging", {})

    livekit_url = os.getenv("LIVEKIT_URL", livekit.get("url", "ws://127.0.0.1:7880")).strip()
    livekit_api_key = os.getenv("LIVEKIT_API_KEY", livekit.get("api_key", "devkey")).strip()
    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET", livekit.get("api_secret", "secret")).strip()
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    mcp_http_urls = tuple(
        url.strip()
        for url in os.getenv(
            "INTERRUPT_MCP_HTTP_URLS",
            ",".join(integrations.get("mcp_http_urls", [])),
        ).split(",")
        if url.strip()
    )
    legacy_mirror_env = os.getenv("INTERRUPT_MIRROR_ASSISTANT_SPEECH_TO_OM1", "")
    if legacy_mirror_env:
        default_assistant_audio_mode = _normalize_feedback_mode(
            legacy_mirror_env,
            default="om1_mirror",
        )
    else:
        default_assistant_audio_mode = _normalize_feedback_mode(
            feedback.get("assistant_audio_mode", "om1_mirror"),
            default="om1_mirror",
        )
    local_tool_ack_audio_mode = _normalize_feedback_mode(
        os.getenv(
            "INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE",
            feedback.get("local_tool_ack_audio_mode", "om1_mirror"),
        ),
        default="om1_mirror",
    )

    if not livekit_url or not livekit_api_key or not livekit_api_secret:
        raise RuntimeError("LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET 未完整设置。")

    vision_provider = _normalize_vision_provider(
        os.getenv(
            "INTERRUPT_VLM_PROVIDER",
            raw.get("vision", {}).get("provider", "gemini_openai_compat"),
        )
    )
    configured_vision_api_key = str(raw.get("vision", {}).get("api_key", "") or gemini_api_key)
    vision_api_key = os.getenv(
        "INTERRUPT_VLM_API_KEY",
        configured_vision_api_key,
    ).strip()

    return AppSettings(
        livekit=LiveKitConfig(
            url=livekit_url,
            api_key=livekit_api_key,
            api_secret=livekit_api_secret,
        ),
        agent=AgentConfig(
            name=agent.get("name", "interrupt-web-agent"),
            backend=_normalize_agent_backend(
                os.getenv(
                    "INTERRUPT_AGENT_BACKEND",
                    agent.get("backend", "gemini_realtime"),
                )
            ),
            runtime_mode=_normalize_agent_runtime_mode(
                os.getenv(
                    "INTERRUPT_AGENT_RUNTIME_MODE",
                    agent.get("runtime_mode", "online_full"),
                )
            ),
            local_text_decision_mode=_normalize_local_text_decision_mode(
                os.getenv(
                    "INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE",
                    agent.get("local_text_decision_mode", "disabled"),
                )
            ),
            model=agent.get("model", "gemini-2.5-flash-native-audio-preview-12-2025"),
            voice=agent.get("voice", "Aoede"),
            language=agent.get("language", "zh-CN"),
            instructions=agent.get(
                "instructions",
                "你是一个中文语音助手。回答简洁、自然，优先使用口语化表达。",
            ),
            interruption_acknowledgement=agent.get(
                "interruption_acknowledgement",
                "好的，那您还有其他需求吗？",
            ),
            enable_input_transcription=agent.get("enable_input_transcription", True),
            enable_output_transcription=agent.get("enable_output_transcription", True),
            allow_interruptions=agent.get("allow_interruptions", True),
            interruption_mode=agent.get("interruption_mode", "vad"),
            min_endpointing_delay_ms=int(
                os.getenv(
                    "INTERRUPT_MIN_ENDPOINTING_DELAY_MS",
                    str(agent.get("min_endpointing_delay_ms", 300)),
                )
            ),
            max_endpointing_delay_ms=int(
                os.getenv(
                    "INTERRUPT_MAX_ENDPOINTING_DELAY_MS",
                    str(agent.get("max_endpointing_delay_ms", 1200)),
                )
            ),
            min_interruption_duration_ms=int(
                os.getenv(
                    "INTERRUPT_MIN_INTERRUPTION_DURATION_MS",
                    str(agent.get("min_interruption_duration_ms", 80)),
                )
            ),
            false_interruption_timeout_ms=int(
                os.getenv(
                    "INTERRUPT_FALSE_INTERRUPTION_TIMEOUT_MS",
                    str(agent.get("false_interruption_timeout_ms", 500)),
                )
            ),
            aec_warmup_duration_ms=int(agent.get("aec_warmup_duration_ms", 0)),
            user_away_timeout_ms=int(
                os.getenv(
                    "INTERRUPT_USER_AWAY_TIMEOUT_MS",
                    str(agent.get("user_away_timeout_ms", 15000)),
                )
            ),
            local_text_provider=_normalize_local_text_provider(
                os.getenv(
                    "INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER",
                    str(agent.get("local_text_provider", "ollama")),
                )
            ),
            local_text_api_key=os.getenv(
                "INTERRUPT_AGENT_LOCAL_TEXT_API_KEY",
                str(agent.get("local_text_api_key", "")),
            ).strip(),
            local_text_base_url=os.getenv(
                "INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL",
                str(agent.get("local_text_base_url", "http://127.0.0.1:11434")),
            ).strip()
            or "http://127.0.0.1:11434",
            local_text_model=os.getenv(
                "INTERRUPT_AGENT_LOCAL_TEXT_MODEL",
                str(agent.get("local_text_model", "qwen2.5:7b")),
            ).strip()
            or "qwen2.5:7b",
        ),
        web=WebConfig(
            host=web.get("host", "127.0.0.1"),
            port=int(web.get("port", 3000)),
            room_name=web.get("room_name", "interrupt-demo"),
            identity_prefix=web.get("identity_prefix", "web-user"),
            token_ttl_minutes=int(web.get("token_ttl_minutes", 60)),
        ),
        feedback=FeedbackConfig(
            assistant_audio_mode=_normalize_feedback_mode(
                os.getenv(
                    "INTERRUPT_ASSISTANT_AUDIO_MODE",
                    default_assistant_audio_mode,
                ),
                default="om1_mirror",
            ),
            local_tool_ack_audio_mode=local_tool_ack_audio_mode,
        ),
        vision=VisionConfig(
            enabled=os.getenv(
                "INTERRUPT_VLM_ENABLED",
                str(raw.get("vision", {}).get("enabled", False)),
            )
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            provider=vision_provider,
            api_key=vision_api_key,
            model=os.getenv(
                "INTERRUPT_VLM_MODEL",
                os.getenv(
                    "GEMINI_VLM_MODEL",
                    raw.get("vision", {}).get("model", "gemini-2.5-flash"),
                ),
            ).strip()
            or "gemini-2.5-flash",
            base_url=os.getenv(
                "INTERRUPT_VLM_BASE_URL",
                os.getenv(
                    "GEMINI_BASE_URL",
                    raw.get("vision", {}).get(
                        "base_url",
                        "https://generativelanguage.googleapis.com/v1beta/openai/",
                    ),
                ),
            ).strip()
            or "https://generativelanguage.googleapis.com/v1beta/openai/",
            image_path=os.getenv(
                "INTERRUPT_VLM_IMAGE_PATH",
                raw.get("vision", {}).get("image_path", ""),
            ).strip(),
            preferred_device=os.getenv(
                "UNITREE_G1_CAMERA_DEVICE",
                os.getenv(
                    "INTERRUPT_VLM_CAMERA_DEVICE",
                    raw.get("vision", {}).get("preferred_device", ""),
                ),
            ).strip(),
            width=int(
                os.getenv(
                    "INTERRUPT_VLM_WIDTH",
                    str(raw.get("vision", {}).get("width", 640)),
                )
            ),
            height=int(
                os.getenv(
                    "INTERRUPT_VLM_HEIGHT",
                    str(raw.get("vision", {}).get("height", 480)),
                )
            ),
            jpeg_quality=int(
                os.getenv(
                    "INTERRUPT_VLM_JPEG_QUALITY",
                    str(raw.get("vision", {}).get("jpeg_quality", 75)),
                )
            ),
            max_tokens=int(
                os.getenv(
                    "INTERRUPT_VLM_MAX_TOKENS",
                    str(raw.get("vision", {}).get("max_tokens", 240)),
                )
            ),
            capture_warmup_frames=int(
                os.getenv(
                    "INTERRUPT_VLM_CAPTURE_WARMUP_FRAMES",
                    str(raw.get("vision", {}).get("capture_warmup_frames", 3)),
                )
            ),
            capture_timeout_s=float(
                os.getenv(
                    "INTERRUPT_VLM_CAPTURE_TIMEOUT_S",
                    str(raw.get("vision", {}).get("capture_timeout_s", 3.0)),
                )
            ),
        ),
        console=ConsoleConfig(
            input_device=os.getenv("INTERRUPT_INPUT_DEVICE", console.get("input_device", "")).strip(),
            output_device=os.getenv(
                "INTERRUPT_OUTPUT_DEVICE", console.get("output_device", "")
            ).strip(),
            text_mode=os.getenv("INTERRUPT_TEXT_MODE", str(console.get("text_mode", False)))
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            record=os.getenv("INTERRUPT_RECORD", str(console.get("record", False)))
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
        ),
        rtc_endpoint=RtcEndpointConfig(
            enabled=os.getenv(
                "INTERRUPT_RTC_ENDPOINT_ENABLED",
                str(rtc_endpoint.get("enabled", False)),
            )
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            room_name=os.getenv(
                "INTERRUPT_RTC_ROOM_NAME",
                rtc_endpoint.get("room_name", web.get("room_name", "interrupt-demo")),
            ).strip(),
            identity=os.getenv(
                "INTERRUPT_RTC_IDENTITY",
                rtc_endpoint.get("identity", "robot-rtc-endpoint"),
            ).strip(),
            publish_microphone=os.getenv(
                "INTERRUPT_RTC_PUBLISH_MICROPHONE",
                str(rtc_endpoint.get("publish_microphone", True)),
            )
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            subscribe_audio=os.getenv(
                "INTERRUPT_RTC_SUBSCRIBE_AUDIO",
                str(rtc_endpoint.get("subscribe_audio", True)),
            )
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            input_device=os.getenv(
                "INTERRUPT_RTC_INPUT_DEVICE",
                rtc_endpoint.get("input_device", console.get("input_device", "")),
            ).strip(),
            output_device=os.getenv(
                "INTERRUPT_RTC_OUTPUT_DEVICE",
                rtc_endpoint.get("output_device", console.get("output_device", "")),
            ).strip(),
            auto_create_room=os.getenv(
                "INTERRUPT_RTC_AUTO_CREATE_ROOM",
                str(rtc_endpoint.get("auto_create_room", True)),
            )
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            auto_dispatch_agent=os.getenv(
                "INTERRUPT_RTC_AUTO_DISPATCH_AGENT",
                str(rtc_endpoint.get("auto_dispatch_agent", True)),
            )
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            auto_redispatch_on_agent_disconnect=os.getenv(
                "INTERRUPT_RTC_AUTO_REDISPATCH_ON_AGENT_DISCONNECT",
                str(rtc_endpoint.get("auto_redispatch_on_agent_disconnect", True)),
            )
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            redispatch_cooldown_s=float(
                os.getenv(
                    "INTERRUPT_RTC_REDISPATCH_COOLDOWN_S",
                    str(rtc_endpoint.get("redispatch_cooldown_s", 8)),
                )
            ),
            agent_absence_check_interval_s=float(
                os.getenv(
                    "INTERRUPT_RTC_AGENT_ABSENCE_CHECK_INTERVAL_S",
                    str(rtc_endpoint.get("agent_absence_check_interval_s", 20)),
                )
            ),
        ),
        integrations=IntegrationConfig(
            wake_word_factory=os.getenv(
                "INTERRUPT_WAKE_WORD_FACTORY",
                integrations.get("wake_word_factory", ""),
            ).strip(),
            mcp_stdio_command=os.getenv(
                "INTERRUPT_MCP_STDIO_COMMAND",
                integrations.get("mcp_stdio_command", ""),
            ).strip(),
            mcp_http_urls=mcp_http_urls,
        ),
        logging=LoggingConfig(level=logging.get("level", "INFO")),
        gemini_api_key=gemini_api_key,
    )
