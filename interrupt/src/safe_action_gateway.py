from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActionObservation:
    natural_answer: str
    person_detected: str
    person_count_estimate: int | None
    distance_band: str
    obstacle_near_arms: str
    free_space_front: str
    human_attention: str
    scene_visibility: str


@dataclass
class SafetyDecision:
    allowed: bool
    reason_code: str
    reason_text: str
    observation: ActionObservation


def build_action_observation(payload: dict[str, object] | None) -> ActionObservation:
    data = payload or {}
    return ActionObservation(
        natural_answer=str(data.get("natural_answer") or "").strip(),
        person_detected=_enum(data.get("person_detected"), {"yes", "no", "unknown"}),
        person_count_estimate=_count(data.get("person_count_estimate")),
        distance_band=_enum(data.get("distance_band"), {"near", "mid", "far", "unknown"}),
        obstacle_near_arms=_enum(data.get("obstacle_near_arms"), {"yes", "no", "unknown"}),
        free_space_front=_enum(data.get("free_space_front"), {"clear", "partial", "blocked", "unknown"}),
        human_attention=_enum(data.get("human_attention"), {"attending", "not_attending", "unknown"}),
        scene_visibility=_enum(data.get("scene_visibility"), {"clear", "blurry", "occluded", "dark", "unknown"}),
    )


def evaluate_action_safety(action: str, observation_payload: dict[str, object] | None) -> SafetyDecision:
    observation = build_action_observation(observation_payload)
    normalized_action = (action or "").strip().lower()
    family = _action_family(normalized_action)

    if observation.scene_visibility in {"dark", "occluded"}:
        return SafetyDecision(
            allowed=False,
            reason_code="scene_visibility_low",
            reason_text="当前前方画面太暗或遮挡较重，我先不执行这个上身动作。",
            observation=observation,
        )
    if observation.obstacle_near_arms == "yes":
        return SafetyDecision(
            allowed=False,
            reason_code="obstacle_near_arms",
            reason_text="我前方靠近手臂活动范围的位置像是有遮挡物，我先不做这个动作。",
            observation=observation,
        )
    if observation.free_space_front == "blocked" and family in {"front_reach", "wide_gesture"}:
        return SafetyDecision(
            allowed=False,
            reason_code="front_space_blocked",
            reason_text="我前方空间看起来不够安全，先不做朝前伸展的动作。",
            observation=observation,
        )
    if (
        observation.person_detected == "yes"
        and observation.distance_band == "near"
        and family in {"front_reach", "wide_gesture"}
    ):
        return SafetyDecision(
            allowed=False,
            reason_code="person_too_close",
            reason_text="前面的人离我太近了，我先不做可能碰到人的动作。",
            observation=observation,
        )
    return SafetyDecision(
        allowed=True,
        reason_code="allowed",
        reason_text="safe_to_execute",
        observation=observation,
    )


def evaluate_navigation_safety(observation_payload: dict[str, object] | None) -> SafetyDecision:
    observation = build_action_observation(observation_payload)
    if observation.scene_visibility in {"dark", "occluded", "blurry"}:
        return SafetyDecision(
            allowed=False,
            reason_code="scene_visibility_low",
            reason_text="当前前方画面太暗或遮挡较重，我先不启动导航。",
            observation=observation,
        )
    if observation.free_space_front in {"blocked", "partial"}:
        return SafetyDecision(
            allowed=False,
            reason_code="front_space_blocked",
            reason_text="我前方空间看起来被挡住了，我先不启动导航。",
            observation=observation,
        )
    if observation.person_detected == "yes" and observation.distance_band in {"near", "unknown"}:
        return SafetyDecision(
            allowed=False,
            reason_code="person_too_close",
            reason_text="前面的人离我太近了，我先不启动导航。",
            observation=observation,
        )
    return SafetyDecision(
        allowed=True,
        reason_code="allowed",
        reason_text="safe_to_navigate",
        observation=observation,
    )


def _action_family(action: str) -> str:
    if action in {"high five", "shake hand"}:
        return "front_reach"
    if action in {"high wave"}:
        return "wide_gesture"
    if action in {"clap", "heart"}:
        return "compact_gesture"
    return "unknown"


def _enum(value: object, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else "unknown"


def _count(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return max(0, value)
    text = str(value).strip()
    if text.isdigit():
        return max(0, int(text))
    return None
