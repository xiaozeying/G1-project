#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.settings import load_environment, load_settings


MODULES = ["yaml", "dotenv", "google.genai", "livekit.agents", "livekit.api"]
COMMANDS = ["livekit-server"]


def check_modules() -> None:
    print("Python 依赖检查:")
    for module in MODULES:
        try:
            importlib.import_module(module)
            print(f"  OK   {module}")
        except Exception as exc:
            print(f"  FAIL {module} -> {exc}")


def check_commands() -> None:
    print("\n系统命令检查:")
    for command in COMMANDS:
        path = shutil.which(command)
        if path:
            print(f"  OK   {command} -> {path}")
        else:
            print(f"  WARN {command} -> not found")


def check_livekit_server() -> None:
    print("\nLiveKit Server 检查:")
    if not shutil.which("livekit-server"):
        print("  WARN livekit-server 未安装，本地网页端将无法连接到自建服务。")
        return
    result = subprocess.run(
        ["livekit-server", "--version"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        print(f"  OK   {result.stdout.strip() or result.stderr.strip()}")
    else:
        print(f"  WARN version check failed -> {result.stderr.strip() or result.stdout.strip()}")


def check_env_var() -> None:
    print("\n环境变量检查:")
    print(f"  LIVEKIT_URL -> {'SET' if os.getenv('LIVEKIT_URL') else 'MISSING'}")
    print(f"  LIVEKIT_API_KEY -> {'SET' if os.getenv('LIVEKIT_API_KEY') else 'MISSING'}")
    print(f"  LIVEKIT_API_SECRET -> {'SET' if os.getenv('LIVEKIT_API_SECRET') else 'MISSING'}")
    print(f"  GEMINI_API_KEY -> {'SET' if os.getenv('GEMINI_API_KEY') else 'MISSING'}")
    print(
        "  INTERRUPT_WAKE_WORD_FACTORY -> "
        f"{'SET' if os.getenv('INTERRUPT_WAKE_WORD_FACTORY') else 'EMPTY'}"
    )
    print(
        "  INTERRUPT_MCP_STDIO_COMMAND -> "
        f"{'SET' if os.getenv('INTERRUPT_MCP_STDIO_COMMAND') else 'EMPTY'}"
    )
    print(
        "  INTERRUPT_MCP_HTTP_URLS -> "
        f"{'SET' if os.getenv('INTERRUPT_MCP_HTTP_URLS') else 'EMPTY'}"
    )


def check_config() -> None:
    print("\n配置检查:")
    try:
        settings = load_settings(ROOT_DIR / "config.yaml")
    except Exception as exc:
        print(f"  FAIL config -> {exc}")
        return

    print(
        "  OK   config -> "
        f"livekit={settings.livekit.url} "
        f"model={settings.agent.model} "
        f"voice={settings.agent.voice} "
        f"console_text={settings.console.text_mode} "
        f"web={settings.web.host}:{settings.web.port} "
        f"room={settings.web.room_name}"
    )


def check_g1_om1_adapter() -> None:
    print("\nG1/OM1 适配层检查:")
    try:
        from src.g1_om1_adapter import G1Om1Adapter
    except Exception as exc:
        print(f"  FAIL adapter import -> {exc}")
        return

    adapter = G1Om1Adapter()
    paths = adapter.script_paths()
    checks = adapter.validate_paths()
    for key, value in paths.items():
        if key == "unitree_interface":
            print(f"  INFO {key} -> {value}")
            continue
        status = "OK" if checks.get(key, False) else "WARN"
        print(f"  {status:<4} {key} -> {value}")


def check_wakeword_factory_slot() -> None:
    print("\n唤醒前门检查:")
    from src.wakeword_runtime import load_factory_from_spec

    factory_spec = os.getenv("INTERRUPT_WAKE_WORD_FACTORY", "").strip()
    if not factory_spec:
        print("  INFO wake_word_factory -> EMPTY (当前将回退到 mock stdin factory)")
        return

    try:
        load_factory_from_spec(factory_spec)
    except Exception as exc:
        print(f"  FAIL wake_word_factory -> {factory_spec} ({exc})")
        return

    print(f"  OK   wake_word_factory -> {factory_spec}")
    if "om1_wakeword_gate:factory" in factory_spec:
        wakeword_script = os.getenv("WAKEWORD_SCRIPT", "/home/unitree/g1-wakeword/wakeword_adaptive.py")
        exists = Path(wakeword_script).exists()
        status = "OK" if exists else "WARN"
        print(f"  {status:<4} wakeword_script -> {wakeword_script}")


def check_frontgate_session_command() -> None:
    print("\n前门会话命令检查:")
    command = os.getenv(
        "INTERRUPT_FRONTGATE_SESSION_COMMAND",
        str(ROOT_DIR / "run_local_voice_agent.sh"),
    ).strip()
    print(f"  INFO session_command -> {command}")
    if command == str(ROOT_DIR / "run_local_voice_agent.sh"):
        exists = Path(command).exists()
        status = "OK" if exists else "WARN"
        print(f"  {status:<4} default_session_launcher -> {command}")


def check_local_audio_stack() -> None:
    print("\n本地音频栈检查:")
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import sounddevice"],
            check=False,
            text=True,
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            print("  OK   sounddevice -> import succeeded")
        else:
            details = result.stderr.strip() or result.stdout.strip() or "unknown error"
            print(f"  WARN sounddevice -> {details}")
    except subprocess.TimeoutExpired:
        print("  WARN sounddevice -> import timeout")
    except Exception as exc:
        print(f"  WARN sounddevice -> {exc}")


if __name__ == "__main__":
    load_environment()
    check_modules()
    check_local_audio_stack()
    check_commands()
    check_livekit_server()
    check_env_var()
    check_config()
    check_g1_om1_adapter()
    check_wakeword_factory_slot()
    check_frontgate_session_command()
