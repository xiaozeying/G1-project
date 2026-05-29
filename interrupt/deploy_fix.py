#!/usr/bin/env python3
"""Deploy the tracked interrupt voice-chain fixes to the robot over SSH."""

from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path

import paramiko

ROBOT_HOST = "192.168.100.30"
ROBOT_USER = "unitree"
ROBOT_PASSWORD = "123"
ROBOT_INTERRUPT_DIR = "/data/HongTu/interrupt"
ROOT_DIR = Path(__file__).resolve().parent

FILES_TO_UPDATE = [
    "config.yaml",
    "deploy/systemd/user/interrupt-frontgate.service",
    "deploy/systemd/user/interrupt-frontgate-compose.service",
    "deploy/systemd/user/interrupt-livekit.service",
    "restore_robot_voice_chain.sh",
    "run_frontgate_room_session.sh",
    "run_frontgate_session.sh",
    "run_robot_frontgate_session.sh",
    "run_robot_rtc_endpoint.sh",
    "run_room_agent.sh",
    "src/agent.py",
    "src/g1_om1_adapter.py",
    "src/local_rms_vad.py",
    "src/local_sensevoice_stt.py",
    "src/local_text_brain.py",
    "src/rtc_reply_audio.py",
    "src/speech_feedback.py",
    "src/vision_chat.py",
    "tools/frontgate_room_session.py",
    "tools/local_text_brain_smoke.py",
    "tools/local_text_trilingual_smoke.py",
    "tools/offline_singlebox_acceptance.py",
    "tools/wakeword_session_frontgate.py",
]


def connect_ssh() -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ROBOT_HOST, username=ROBOT_USER, password=ROBOT_PASSWORD, timeout=10)
    return ssh


def execute(ssh: paramiko.SSHClient, cmd: str) -> tuple[str, str]:
    stdin, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode(), stderr.read().decode()


def build_bundle() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for relative_path in FILES_TO_UPDATE:
            source_path = ROOT_DIR / relative_path
            if source_path.exists():
                tar.add(str(source_path), arcname=relative_path)
                print(f"   + {relative_path}")
            else:
                print(f"   ! missing {relative_path}")
    buffer.seek(0)
    return buffer.getvalue()


def main() -> int:
    print("🚀 开始部署到机器人...")
    print(f"   目标: {ROBOT_USER}@{ROBOT_HOST}")
    print(f"   目录: {ROBOT_INTERRUPT_DIR}")
    print()

    ssh = connect_ssh()
    print("✅ SSH连接成功")

    out, _ = execute(ssh, f"ls -d {ROBOT_INTERRUPT_DIR} 2>/dev/null")
    if not out.strip():
        print(f"❌ 机器人上不存在 {ROBOT_INTERRUPT_DIR} 目录")
        ssh.close()
        return 1
    print(f"✅ 目标目录存在: {out.strip()}")

    print()
    print("📦 创建修复包...")
    bundle = build_bundle()

    print()
    print("📤 上传文件到机器人...")
    sftp = ssh.open_sftp()
    remote_tar = "/tmp/interrupt-deploy-fix.tar.gz"
    with sftp.file(remote_tar, "wb") as handle:
        handle.write(bundle)
    sftp.close()
    print(f"✅ 上传完成: {remote_tar}")

    print()
    print("📥 解压文件...")
    out, err = execute(ssh, f"cd {ROBOT_INTERRUPT_DIR} && tar -xzf {remote_tar}")
    if out.strip():
        print(out)
    if err.strip():
        print(err)

    print()
    print("🔐 修正启动脚本执行权限...")
    out, err = execute(
        ssh,
        (
            f"chmod +x {ROBOT_INTERRUPT_DIR}/restore_robot_voice_chain.sh "
            f"{ROBOT_INTERRUPT_DIR}/run_frontgate_room_session.sh "
            f"{ROBOT_INTERRUPT_DIR}/run_frontgate_session.sh "
            f"{ROBOT_INTERRUPT_DIR}/run_robot_frontgate_session.sh "
            f"{ROBOT_INTERRUPT_DIR}/run_robot_rtc_endpoint.sh "
            f"{ROBOT_INTERRUPT_DIR}/run_room_agent.sh"
        ),
    )
    if out.strip():
        print(out)
    if err.strip():
        print(err)

    print()
    print("🧪 远端编译检查...")
    out, err = execute(
        ssh,
        (
            f"cd {ROBOT_INTERRUPT_DIR} && "
            ".venv/bin/python -m py_compile "
            "src/agent.py src/local_text_brain.py src/local_sensevoice_stt.py "
            "src/local_rms_vad.py src/rtc_reply_audio.py src/vision_chat.py"
        ),
    )
    if out.strip():
        print(out)
    if err.strip():
        print(err)

    print()
    print("🔍 检查代理配置...")
    out, err = execute(
        ssh,
        f"grep -o '^WSS_PROXY=.*' {ROBOT_INTERRUPT_DIR}/.env.local 2>/dev/null || echo ''",
    )
    if out.strip():
        print(f"✅ 已配置代理: {out.strip()}")
    else:
        print("⚠️  未配置 WSS_PROXY")
    if err.strip():
        print(err)

    print()
    print("🧭 写入推荐现场环境变量...")
    env_cmd = (
        f"cd {ROBOT_INTERRUPT_DIR} && "
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "path = Path('.env.local')\n"
        "existing = path.read_text(encoding='utf-8') if path.exists() else ''\n"
        "pairs = {\n"
        "    'INTERRUPT_AGENT_BACKEND': 'local_text_ollama',\n"
        "    'INTERRUPT_AGENT_RUNTIME_MODE': 'offline_singlebox',\n"
        "    'INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE': 'prefer_all',\n"
        "    'INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER': 'ollama',\n"
        "    'INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL': 'http://192.168.100.48:11434',\n"
        "    'INTERRUPT_AGENT_LOCAL_TEXT_MODEL': 'qwen2.5:7b',\n"
        "    'INTERRUPT_MIRROR_ASSISTANT_SPEECH_TO_OM1': '0',\n"
        "    'INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE': 'transport_only',\n"
        "    'INTERRUPT_FRONTGATE_ENABLE_READY_PROMPT': '1',\n"
        "    'INTERRUPT_FRONTGATE_READY_TEXT': '现在可以了',\n"
        "    'INTERRUPT_FRONTGATE_READY_PROMPT_MODE': 'room_agent_rtc',\n"
        "    'INTERRUPT_FRONTGATE_SET_IDLE_LED_ON_START': '1',\n"
        "    'INTERRUPT_FRONTGATE_ENABLE_WAKE_LED': '1',\n"
        "    'INTERRUPT_FRONTGATE_RESTORE_IDLE_LED': '1',\n"
        "    'INTERRUPT_FRONTGATE_ACTIVE_LED': 'green',\n"
        "    'INTERRUPT_FRONTGATE_IDLE_LED': 'blue',\n"
        "    'INTERRUPT_RTC_OUTPUT_DEVICE': 'mvsilicon B1 usb audio',\n"
        "    'INTERRUPT_USB_RTC_OUTPUT_DEVICE': 'mvsilicon B1 usb audio',\n"
        "    'OM1_CONSOLE_OUTPUT_DEVICE': 'mvsilicon B1 usb audio',\n"
        "}\n"
        "lines = [line for line in existing.splitlines() if '=' in line]\n"
        "kv = {}\n"
        "for line in lines:\n"
        "    key, value = line.split('=', 1)\n"
        "    kv[key] = value\n"
        "kv.update(pairs)\n"
        "ordered = []\n"
        "seen = set()\n"
        "for line in existing.splitlines():\n"
        "    if '=' not in line:\n"
        "        ordered.append(line)\n"
        "        continue\n"
        "    key = line.split('=', 1)[0]\n"
        "    if key in seen:\n"
        "        continue\n"
        "    seen.add(key)\n"
        "    ordered.append(f'{key}={kv[key]}')\n"
        "for key, value in pairs.items():\n"
        "    if key not in seen:\n"
        "        ordered.append(f'{key}={value}')\n"
        "path.write_text('\\n'.join(ordered).rstrip() + '\\n', encoding='utf-8')\n"
        "print(path.read_text(encoding='utf-8'))\n"
        "PY"
    )
    out, err = execute(ssh, env_cmd)
    if out.strip():
        print(out)
    if err.strip():
        print(err)

    print()
    print("🔄 重启服务...")
    out, err = execute(
        ssh,
        "systemctl --user restart interrupt-livekit.service && "
        "systemctl --user restart interrupt-frontgate.service || "
        "systemctl --user restart interrupt-frontgate-compose.service",
    )
    if out.strip():
        print(out)
    if err.strip():
        print(err)

    time.sleep(2)

    print()
    print("📊 服务状态:")
    out, err = execute(
        ssh,
        "printf 'frontgate=%s\\n' \"$(systemctl --user is-active interrupt-frontgate.service 2>/dev/null || true)\"; "
        "printf 'frontgate_compose=%s\\n' \"$(systemctl --user is-active interrupt-frontgate-compose.service 2>/dev/null || true)\"; "
        "printf 'livekit=%s\\n' \"$(systemctl --user is-active interrupt-livekit.service 2>/dev/null || true)\"",
    )
    print(out.strip())
    if err.strip():
        print(err)

    print()
    print("📝 最新日志 (10行):")
    print("-" * 50)
    out, err = execute(ssh, f"tail -n 10 {ROBOT_INTERRUPT_DIR}/logs/room-agent.log 2>/dev/null || true")
    if out.strip():
        print(out.strip())
    if err.strip():
        print(err)

    ssh.close()
    print()
    print("✅ 部署完成")
    print()
    print("后续查看日志：")
    print(f"  tail -f {ROBOT_INTERRUPT_DIR}/logs/room-agent.log")
    print(f"  tail -f {ROBOT_INTERRUPT_DIR}/logs/robot-frontgate.log")
    print(f"  tail -f {ROBOT_INTERRUPT_DIR}/logs/robot-rtc-endpoint.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
