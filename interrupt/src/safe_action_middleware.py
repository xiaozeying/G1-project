from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from src.safe_action_gateway import evaluate_action_safety, evaluate_navigation_safety
from src.vision_chat import VisionChatConfig, ask_camera_question


LOGGER = logging.getLogger("interrupt.safe_middleware")


@dataclass
class SafetyMiddlewareResult:
    allowed: bool
    reason_code: str
    user_message: str
    camera_device: str
    backend_error: str = ""
    observation: dict[str, object] | None = None


async def precheck_body_action(
    vision_config: VisionChatConfig,
    *,
    action: str,
    reply_language: str,
    unavailable_message: str,
    denied_message: str,
) -> SafetyMiddlewareResult:
    result = await asyncio.to_thread(
        ask_camera_question,
        vision_config,
        question="请检查前方空间、人体接近情况，以及手臂活动范围附近是否有遮挡物。",
        reply_language=reply_language,
        structured=True,
    )
    if not result.ok:
        LOGGER.warning(
            "safe action gateway vision precheck failed: action=%s error=%s device=%s",
            action,
            result.error,
            result.camera_device,
        )
        return SafetyMiddlewareResult(
            allowed=False,
            reason_code="vision_precheck_failed",
            user_message=unavailable_message,
            camera_device=result.camera_device,
            backend_error=result.error,
        )

    decision = evaluate_action_safety(action, result.observation)
    LOGGER.info(
        "safe action gateway decision: action=%s allowed=%s code=%s observation=%r",
        action,
        decision.allowed,
        decision.reason_code,
        result.observation,
    )
    if decision.allowed:
        return SafetyMiddlewareResult(
            allowed=True,
            reason_code=decision.reason_code,
            user_message="",
            camera_device=result.camera_device,
            observation=result.observation,
        )
    return SafetyMiddlewareResult(
        allowed=False,
        reason_code=decision.reason_code,
        user_message=denied_message,
        camera_device=result.camera_device,
        observation=result.observation,
    )


async def precheck_navigation(
    vision_config: VisionChatConfig,
    *,
    reply_language: str,
    unavailable_message: str,
    denied_message: str,
) -> SafetyMiddlewareResult:
    result = await asyncio.to_thread(
        ask_camera_question,
        vision_config,
        question="请检查前方空间是否通畅、是否有人离得太近，以及当前画面是否足够清晰。",
        reply_language=reply_language,
        structured=True,
    )
    if not result.ok:
        LOGGER.warning(
            "safe navigation gateway vision precheck failed: error=%s device=%s",
            result.error,
            result.camera_device,
        )
        return SafetyMiddlewareResult(
            allowed=False,
            reason_code="vision_precheck_failed",
            user_message=unavailable_message,
            camera_device=result.camera_device,
            backend_error=result.error,
        )

    decision = evaluate_navigation_safety(result.observation)
    LOGGER.info(
        "safe navigation gateway decision: allowed=%s code=%s observation=%r",
        decision.allowed,
        decision.reason_code,
        result.observation,
    )
    if decision.allowed:
        return SafetyMiddlewareResult(
            allowed=True,
            reason_code=decision.reason_code,
            user_message="",
            camera_device=result.camera_device,
            observation=result.observation,
        )
    return SafetyMiddlewareResult(
        allowed=False,
        reason_code=decision.reason_code,
        user_message=denied_message,
        camera_device=result.camera_device,
        observation=result.observation,
    )
