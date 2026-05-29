#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.settings import load_environment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit shell exports for one offline embodied deployment model profile."
    )
    parser.add_argument(
        "profile",
        choices=("baseline_current", "minicpm_v46", "qwen_split_prod", "cosmos_reason2_lab"),
        help="Profile name to apply.",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "robot"),
        default="robot",
        help="Emit values tuned for the dev machine or robot-side environment.",
    )
    parser.add_argument(
        "--format",
        choices=("shell", "json"),
        default="shell",
        help="Output format.",
    )
    return parser.parse_args()


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _baseline_profile(mode: str) -> dict[str, str]:
    values = {
        "INTERRUPT_OFFLINE_PROFILE_NAME": "baseline_current",
        "INTERRUPT_AGENT_RUNTIME_MODE": "online_full",
        "INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE": "prefer_tools",
        "INTERRUPT_AGENT_BACKEND": "gemini_realtime",
        "INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER": "ollama",
        "INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL": _env(
            "INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL",
            "http://127.0.0.1:11434",
        ),
        "INTERRUPT_AGENT_LOCAL_TEXT_MODEL": _env(
            "INTERRUPT_AGENT_LOCAL_TEXT_MODEL",
            "qwen2.5:1.5b",
        ),
        "INTERRUPT_ROBOT_OFFLINE_VLM_PROVIDER": _env(
            "INTERRUPT_ROBOT_OFFLINE_VLM_PROVIDER",
            "ollama_native",
        ),
        "INTERRUPT_ROBOT_OFFLINE_VLM_BASE_URL": _env(
            "INTERRUPT_ROBOT_OFFLINE_VLM_BASE_URL",
            "http://127.0.0.1:11434/v1",
        ),
        "INTERRUPT_ROBOT_OFFLINE_VLM_MODEL": _env(
            "INTERRUPT_ROBOT_OFFLINE_VLM_MODEL",
            "gemma3:latest",
        ),
    }
    return values


def _minicpm_profile(mode: str) -> dict[str, str]:
    host = "192.168.100.48" if mode == "robot" else "127.0.0.1"
    values = _baseline_profile(mode)
    values.update(
        {
            "INTERRUPT_OFFLINE_PROFILE_NAME": "minicpm_v46",
            "INTERRUPT_AGENT_RUNTIME_MODE": "offline_singlebox",
            "INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE": "prefer_tools",
            "INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER": "openai_compatible",
            "INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL": _env(
                "INTERRUPT_MINICPM_TEXT_BASE_URL",
                f"http://{host}:8000/v1",
            ),
            "INTERRUPT_AGENT_LOCAL_TEXT_MODEL": _env(
                "INTERRUPT_MINICPM_TEXT_MODEL",
                "MiniCPM-V-4_6",
            ),
            "INTERRUPT_AGENT_LOCAL_TEXT_API_KEY": _env(
                "INTERRUPT_MINICPM_TEXT_API_KEY",
                "",
            ),
            "INTERRUPT_ROBOT_OFFLINE_VLM_PROVIDER": "openai_compatible",
            "INTERRUPT_ROBOT_OFFLINE_VLM_BASE_URL": _env(
                "INTERRUPT_ROBOT_OFFLINE_MINICPM_BASE_URL",
                f"http://{host}:8000/v1",
            ),
            "INTERRUPT_ROBOT_OFFLINE_VLM_MODEL": _env(
                "INTERRUPT_ROBOT_OFFLINE_MINICPM_MODEL",
                "MiniCPM-V-4_6",
            ),
            "INTERRUPT_ROBOT_OFFLINE_MINICPM_PROVIDER": "openai_compatible",
            "INTERRUPT_ROBOT_OFFLINE_MINICPM_BASE_URL": _env(
                "INTERRUPT_ROBOT_OFFLINE_MINICPM_BASE_URL",
                f"http://{host}:8000/v1",
            ),
            "INTERRUPT_ROBOT_OFFLINE_MINICPM_MODEL": _env(
                "INTERRUPT_ROBOT_OFFLINE_MINICPM_MODEL",
                "MiniCPM-V-4_6",
            ),
            "INTERRUPT_LOCAL_MINICPM_BASE_URL": _env(
                "INTERRUPT_LOCAL_MINICPM_BASE_URL",
                "http://127.0.0.1:8000/v1",
            ),
            "INTERRUPT_LOCAL_MINICPM_MODEL": _env(
                "INTERRUPT_LOCAL_MINICPM_MODEL",
                "MiniCPM-V-4_6",
            ),
        }
    )
    return values


def _qwen_split_profile(mode: str) -> dict[str, str]:
    host = "192.168.100.48" if mode == "robot" else "127.0.0.1"
    values = _baseline_profile(mode)
    values.update(
        {
            "INTERRUPT_OFFLINE_PROFILE_NAME": "qwen_split_prod",
            "INTERRUPT_AGENT_RUNTIME_MODE": "offline_singlebox",
            "INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE": "prefer_tools",
            "INTERRUPT_AGENT_LOCAL_TEXT_MODEL": _env(
                "INTERRUPT_QWEN_SPLIT_TEXT_MODEL",
                "qwen3.5:4b",
            ),
            "INTERRUPT_ROBOT_OFFLINE_VLM_PROVIDER": "openai_compatible",
            "INTERRUPT_ROBOT_OFFLINE_VLM_BASE_URL": _env(
                "INTERRUPT_ROBOT_OFFLINE_QWEN_BASE_URL",
                f"http://{host}:8000/v1",
            ),
            "INTERRUPT_ROBOT_OFFLINE_VLM_MODEL": _env(
                "INTERRUPT_ROBOT_OFFLINE_QWEN_MODEL",
                "Qwen2.5-VL-3B-Instruct",
            ),
            "INTERRUPT_LOCAL_QWEN_BASE_URL": _env(
                "INTERRUPT_LOCAL_QWEN_BASE_URL",
                "http://127.0.0.1:8000/v1",
            ),
            "INTERRUPT_LOCAL_QWEN_3B_MODEL": _env(
                "INTERRUPT_LOCAL_QWEN_3B_MODEL",
                "Qwen2.5-VL-3B-Instruct",
            ),
        }
    )
    return values


def _cosmos_profile(mode: str) -> dict[str, str]:
    values = _qwen_split_profile(mode)
    values.update(
        {
            "INTERRUPT_OFFLINE_PROFILE_NAME": "cosmos_reason2_lab",
            "INTERRUPT_AGENT_RUNTIME_MODE": "offline_singlebox",
            "INTERRUPT_COSMOS_REASONING_PROFILE": _env(
                "INTERRUPT_COSMOS_REASONING_PROFILE",
                "cosmos_reason2_2b",
            ),
        }
    )
    return values


def build_profile(profile: str, mode: str) -> dict[str, str]:
    if profile == "baseline_current":
        return _baseline_profile(mode)
    if profile == "minicpm_v46":
        return _minicpm_profile(mode)
    if profile == "qwen_split_prod":
        return _qwen_split_profile(mode)
    if profile == "cosmos_reason2_lab":
        return _cosmos_profile(mode)
    raise ValueError(f"unsupported profile: {profile}")


def emit_shell(values: dict[str, str]) -> None:
    for key, value in values.items():
        print(f"export {key}={shlex.quote(value)}")


def main() -> int:
    args = parse_args()
    load_environment()
    values = build_profile(args.profile, args.mode)
    if args.format == "json":
        print(json.dumps(values, ensure_ascii=False, indent=2))
    else:
        emit_shell(values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
