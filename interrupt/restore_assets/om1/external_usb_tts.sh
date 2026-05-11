#!/usr/bin/env bash
set -euo pipefail

TEXT="${1:-}"
if [[ -z "${TEXT}" ]]; then
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
resolve_interrupt_root() {
  local requested="${INTERRUPT_ROOT:-}"
  if [[ -n "${requested}" && -d "${requested}" ]]; then
    printf '%s\n' "${requested}"
    return 0
  fi
  local candidate
  for candidate in \
    "$(cd "${SCRIPT_DIR}/../../.." && pwd)" \
    "$(cd "${SCRIPT_DIR}/../.." && pwd)/interrupt" \
    "/home/unitree/HongTu/interrupt" \
    "/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt"; do
    if [[ -d "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  printf '%s\n' "/home/unitree/HongTu/interrupt"
}

INTERRUPT_ROOT="$(resolve_interrupt_root)"
EDGE_TTS_PYTHON="${OM1_EDGE_TTS_PYTHON:-${INTERRUPT_ROOT}/.venv/bin/python}"
EDGE_TTS_ZH_VOICE="${OM1_EDGE_TTS_ZH_VOICE:-zh-CN-XiaoxiaoNeural}"
EDGE_TTS_EN_VOICE="${OM1_EDGE_TTS_EN_VOICE:-en-US-JennyNeural}"
EDGE_TTS_RATE="${OM1_EDGE_TTS_RATE:-+0%}"
EDGE_TTS_VOLUME="${OM1_EDGE_TTS_VOLUME:-+0%}"
EDGE_TTS_PITCH="${OM1_EDGE_TTS_PITCH:-+0Hz}"
EDGE_TTS_TIMEOUT_S="${OM1_EDGE_TTS_TIMEOUT_S:-15}"

PREFERRED_SINK="${OM1_EXTERNAL_SINK:-}"
if [[ -z "${PREFERRED_SINK}" ]]; then
  DEFAULT_SINK="$(pactl info 2>/dev/null | awk -F': ' '/Default Sink/ {print $2}')"
  if [[ -n "${DEFAULT_SINK}" && "${DEFAULT_SINK}" == *usb* ]]; then
    PREFERRED_SINK="${DEFAULT_SINK}"
  else
    PREFERRED_SINK="$(pactl list short sinks 2>/dev/null | awk '/usb|USB|mvsilicon|B1/ {print $2; exit}')"
    if [[ -z "${PREFERRED_SINK}" ]]; then
      PREFERRED_SINK="${DEFAULT_SINK}"
    fi
  fi
fi

ESPEAK_BIN="$(command -v espeak-ng || command -v espeak)"

normalize_fixed_reply() {
  local raw="$1"
  case "${raw}" in
    "我在，请说"|"我在，请讲")
      echo "wo zai, qing shuo"
      ;;
    "好的，已经把灯调成红色。")
      echo "hao de, yi jing ba deng tiao cheng hong se"
      ;;
    "好的，已经把灯调成蓝色。")
      echo "hao de, yi jing ba deng tiao cheng lan se"
      ;;
    "好的，已经把灯调成绿色。")
      echo "hao de, yi jing ba deng tiao cheng lu se"
      ;;
    "好的，已经把灯调成黄色。")
      echo "hao de, yi jing ba deng tiao cheng huang se"
      ;;
    "好的，已经关闭灯光。")
      echo "hao de, yi jing guan bi deng guang"
      ;;
    "好的，我来挥手。")
      echo "hao de, wo lai hui shou"
      ;;
    "好的，我来握手。")
      echo "hao de, wo lai wo shou"
      ;;
    "好的，我来鼓掌。")
      echo "hao de, wo lai gu zhang"
      ;;
    "好的，我来击掌。")
      echo "hao de, wo lai ji zhang"
      ;;
    "好的，我来比心。")
      echo "hao de, wo lai bi xin"
      ;;
    *)
      echo "${raw}"
      ;;
  esac
}

SPEAK_TEXT="$(normalize_fixed_reply "${TEXT}")"
VOICE="default"
SPEED="${OM1_TTS_SPEED:-145}"
AMPLITUDE="${OM1_TTS_AMPLITUDE:-180}"
PITCH="${OM1_TTS_PITCH:-55}"

VOICE="$(python3 - "${SPEAK_TEXT}" "${TEXT}" <<'PY'
import sys

speak_text = sys.argv[1]
raw_text = sys.argv[2]

def has_han(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)

if has_han(speak_text):
    if any(ch in raw_text for ch in "咩佢哋喺冇嘅"):
        print("zh-yue")
    else:
        print("zh")
else:
    print("default")
PY
)"

resolve_playback_command() {
  local requested="${OM1_TTS_PLAYBACK_COMMAND:-}"
  if [[ -n "${requested}" ]] && command -v "${requested}" >/dev/null 2>&1; then
    printf '%s\n' "${requested}"
    return 0
  fi
  local candidate
  for candidate in mpg123 ffplay mpv gst-play-1.0 play; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  printf '\n'
}

play_audio_file() {
  local audio_path="$1"
  local player="$2"
  case "${player}" in
    mpg123)
      "${player}" -q "${audio_path}"
      ;;
    ffplay)
      "${player}" -nodisp -autoexit -loglevel error "${audio_path}"
      ;;
    mpv)
      "${player}" --no-video --really-quiet "${audio_path}"
      ;;
    play)
      "${player}" -q "${audio_path}"
      ;;
    gst-play-1.0)
      "${player}" --quiet "${audio_path}"
      ;;
    *)
      return 1
      ;;
  esac
}

run_edge_tts() {
  local language="$1"
  local voice=""
  case "${language}" in
    zh)
      voice="${EDGE_TTS_ZH_VOICE}"
      ;;
    default)
      voice="${EDGE_TTS_EN_VOICE}"
      ;;
    *)
      return 1
      ;;
  esac
  if [[ ! -x "${EDGE_TTS_PYTHON}" ]]; then
    return 1
  fi
  local player
  player="$(resolve_playback_command)"
  if [[ -z "${player}" ]]; then
    return 1
  fi
  local temp_audio
  temp_audio="$(mktemp --suffix=.mp3 /tmp/om1-edge-tts-XXXXXX)"
  if ! timeout "${EDGE_TTS_TIMEOUT_S}" "${EDGE_TTS_PYTHON}" - "${SPEAK_TEXT}" "${voice}" "${EDGE_TTS_RATE}" "${EDGE_TTS_VOLUME}" "${EDGE_TTS_PITCH}" "${temp_audio}" <<'PY'
import asyncio
import sys

text, voice, rate, volume, pitch, output_path = sys.argv[1:7]

async def main() -> None:
    import edge_tts
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )
    await communicate.save(output_path)

asyncio.run(main())
PY
  then
    rm -f "${temp_audio}"
    return 1
  fi
  local play_rc=0
  if [[ -n "${PREFERRED_SINK}" ]]; then
    PULSE_SINK="${PREFERRED_SINK}" play_audio_file "${temp_audio}" "${player}" || play_rc=$?
  else
    play_audio_file "${temp_audio}" "${player}" || play_rc=$?
  fi
  rm -f "${temp_audio}"
  return "${play_rc}"
}

ESPEAK_ARGS=(
  "-a" "${AMPLITUDE}"
  "-p" "${PITCH}"
  "-s" "${SPEED}"
)

if [[ "${VOICE}" != "default" ]]; then
  ESPEAK_ARGS+=("-v" "${VOICE}")
fi

if [[ "${VOICE}" == "zh" || "${VOICE}" == "default" ]]; then
  if run_edge_tts "${VOICE}"; then
    exit 0
  fi
fi

if [[ -z "${ESPEAK_BIN}" ]]; then
  echo "No TTS backend found" >&2
  exit 1
fi

if [[ -n "${PREFERRED_SINK}" ]]; then
  PULSE_SINK="${PREFERRED_SINK}" "${ESPEAK_BIN}" "${ESPEAK_ARGS[@]}" --stdout "${SPEAK_TEXT}" | paplay --device="${PREFERRED_SINK}" --volume=65536 --stream-name="om1-local-reply"
else
  "${ESPEAK_BIN}" "${ESPEAK_ARGS[@]}" --stdout "${SPEAK_TEXT}" | paplay --volume=65536 --stream-name="om1-local-reply"
fi
