from __future__ import annotations

import logging
import shlex

from src.settings import AppSettings


LOGGER = logging.getLogger("interrupt.integrations")


def build_mcp_servers(settings: AppSettings) -> list[object]:
    has_stdio = bool(settings.integrations.mcp_stdio_command)
    has_http = bool(settings.integrations.mcp_http_urls)
    if not has_stdio and not has_http:
        return []

    try:
        from livekit.agents import mcp
    except ImportError:
        LOGGER.warning(
            "检测到 MCP 配置，但当前环境未安装 MCP 依赖。请执行 `pip install 'livekit-agents[mcp]'`。"
        )
        return []

    servers: list[object] = []

    if has_stdio:
        parts = shlex.split(settings.integrations.mcp_stdio_command)
        if not parts:
            LOGGER.warning("INTERRUPT_MCP_STDIO_COMMAND 为空，跳过本地 MCP。")
        else:
            servers.append(
                mcp.MCPServerStdio(
                    command=parts[0],
                    args=parts[1:],
                )
            )

    for url in settings.integrations.mcp_http_urls:
        servers.append(mcp.MCPServerHTTP(url))

    return servers


def log_integration_summary(settings: AppSettings) -> None:
    LOGGER.info(
        "中断配置: allow=%s mode=%s min_interrupt=%sms false_interrupt_timeout=%sms aec_warmup=%sms",
        settings.agent.allow_interruptions,
        settings.agent.interruption_mode,
        settings.agent.min_interruption_duration_ms,
        settings.agent.false_interruption_timeout_ms,
        settings.agent.aec_warmup_duration_ms,
    )

    if settings.integrations.wake_word_factory:
        LOGGER.info(
            "已配置外部唤醒词适配器: %s",
            settings.integrations.wake_word_factory,
        )
    else:
        LOGGER.info("未配置外部唤醒词适配器，当前为常开麦本地会话模式。")

    if settings.integrations.mcp_stdio_command:
        LOGGER.info(
            "已配置本地 MCP stdio: %s",
            settings.integrations.mcp_stdio_command,
        )

    if settings.integrations.mcp_http_urls:
        LOGGER.info(
            "已配置 MCP HTTP: %s",
            ", ".join(settings.integrations.mcp_http_urls),
        )
