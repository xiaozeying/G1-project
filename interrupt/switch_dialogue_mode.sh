#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env.local}"
SERVICE_NAME="${INTERRUPT_FRONTGATE_SERVICE_NAME:-interrupt-frontgate.service}"
PROFILE_DIR="${ROOT_DIR}/config/dialogue_modes"
BASE_PROFILE="${PROFILE_DIR}/frontgate_base.env"
ONLINE_PROFILE="${PROFILE_DIR}/online.env"
OFFLINE_PROFILE="${PROFILE_DIR}/offline.env"

usage() {
  cat <<'EOF'
usage: ./switch_dialogue_mode.sh <online|offline|status>

Switch robot dialogue chain between:
  online  -> fixed production chain (online_full + gemini_realtime)
  offline -> current experimental chain (offline_singlebox + local_text_ollama, incomplete)
  status  -> print current dialogue mode
EOF
}

need_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo "missing env file: ${ENV_FILE}" >&2
    exit 1
  fi
}

upsert_env_line() {
  local file="$1"
  local key="$2"
  local value="$3"
  python3 - "${file}" "${key}" "${value}" <<'PY'
from pathlib import Path
import shlex
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
line = f"{key}={shlex.quote(value)}"

existing = path.read_text(encoding="utf-8").splitlines()
updated = []
replaced = False
for raw in existing:
    if raw.startswith(f"{key}="):
        if not replaced:
            updated.append(line)
            replaced = True
        continue
    updated.append(raw)
if not replaced:
    updated.append(line)
path.write_text("\n".join(updated).rstrip("\n") + "\n", encoding="utf-8")
PY
}

read_env_value() {
  local key="$1"
  python3 - "${ENV_FILE}" "${key}" <<'PY'
from pathlib import Path
import shlex
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
for raw in path.read_text(encoding="utf-8").splitlines():
    if raw.startswith(f"{key}="):
        value = raw.split("=", 1)[1]
        try:
            parts = shlex.split(value, posix=True)
        except ValueError:
            print(value)
            raise SystemExit(0)
        if len(parts) == 1:
            print(parts[0])
        else:
            print(value)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

apply_profile_file() {
  local file="$1"
  [[ -f "${file}" ]] || {
    echo "missing profile file: ${file}" >&2
    exit 1
  }
  while IFS= read -r raw || [[ -n "${raw}" ]]; do
    [[ -z "${raw}" ]] && continue
    [[ "${raw}" =~ ^[[:space:]]*# ]] && continue
    local key="${raw%%=*}"
    local value="${raw#*=}"
    value="${value//__ROOT_DIR__/${ROOT_DIR}}"
    upsert_env_line "${ENV_FILE}" "${key}" "${value}"
  done < "${file}"
}

print_status() {
  need_env_file
  local runtime_mode backend decision_mode provider model profile dialogue_mode mode_stability
  local executor_type
  local assistant_audio_mode tool_ack_audio_mode rtc_subscribe_audio
  local rtc_output_device rtc_aec_enabled
  local frontgate_idle_exit frontgate_user_away_timeout wake_factory session_command
  local frontgate_session_timeout frontgate_room_max_duration
  local min_endpointing_delay max_endpointing_delay
  local min_interruption_duration false_interruption_timeout
  local prefix_padding rtc_playback_prebuffer realtime_start_sensitivity
  runtime_mode="$(read_env_value "INTERRUPT_AGENT_RUNTIME_MODE" 2>/dev/null || true)"
  backend="$(read_env_value "INTERRUPT_AGENT_BACKEND" 2>/dev/null || true)"
  decision_mode="$(read_env_value "INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE" 2>/dev/null || true)"
  provider="$(read_env_value "INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER" 2>/dev/null || true)"
  model="$(read_env_value "INTERRUPT_AGENT_LOCAL_TEXT_MODEL" 2>/dev/null || true)"
  profile="$(read_env_value "INTERRUPT_OFFLINE_PROFILE_NAME" 2>/dev/null || true)"
  dialogue_mode="$(read_env_value "INTERRUPT_DIALOGUE_MODE" 2>/dev/null || true)"
  mode_stability="$(read_env_value "INTERRUPT_DIALOGUE_MODE_STABILITY" 2>/dev/null || true)"
  executor_type="$(read_env_value "INTERRUPT_AGENT_JOB_EXECUTOR_TYPE" 2>/dev/null || true)"
  assistant_audio_mode="$(read_env_value "INTERRUPT_ASSISTANT_AUDIO_MODE" 2>/dev/null || true)"
  tool_ack_audio_mode="$(read_env_value "INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE" 2>/dev/null || true)"
  rtc_subscribe_audio="$(read_env_value "INTERRUPT_RTC_SUBSCRIBE_AUDIO" 2>/dev/null || true)"
  rtc_output_device="$(read_env_value "INTERRUPT_RTC_OUTPUT_DEVICE" 2>/dev/null || true)"
  rtc_aec_enabled="$(read_env_value "INTERRUPT_RTC_AEC_ENABLED" 2>/dev/null || true)"
  frontgate_idle_exit="$(read_env_value "INTERRUPT_ENABLE_FRONTGATE_IDLE_SESSION_EXIT" 2>/dev/null || true)"
  frontgate_user_away_timeout="$(read_env_value "INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS" 2>/dev/null || true)"
  wake_factory="$(read_env_value "INTERRUPT_WAKE_WORD_FACTORY" 2>/dev/null || true)"
  session_command="$(read_env_value "INTERRUPT_FRONTGATE_SESSION_COMMAND" 2>/dev/null || true)"
  frontgate_session_timeout="$(read_env_value "INTERRUPT_FRONTGATE_SESSION_TIMEOUT" 2>/dev/null || true)"
  frontgate_room_max_duration="$(read_env_value "INTERRUPT_FRONTGATE_ROOM_MAX_DURATION_S" 2>/dev/null || true)"
  min_endpointing_delay="$(read_env_value "INTERRUPT_MIN_ENDPOINTING_DELAY_MS" 2>/dev/null || true)"
  max_endpointing_delay="$(read_env_value "INTERRUPT_MAX_ENDPOINTING_DELAY_MS" 2>/dev/null || true)"
  min_interruption_duration="$(read_env_value "INTERRUPT_MIN_INTERRUPTION_DURATION_MS" 2>/dev/null || true)"
  false_interruption_timeout="$(read_env_value "INTERRUPT_FALSE_INTERRUPTION_TIMEOUT_MS" 2>/dev/null || true)"
  prefix_padding="$(read_env_value "INTERRUPT_REALTIME_PREFIX_PADDING_MS" 2>/dev/null || true)"
  rtc_playback_prebuffer="$(read_env_value "INTERRUPT_RTC_PLAYBACK_PREBUFFER_MS" 2>/dev/null || true)"
  realtime_start_sensitivity="$(read_env_value "INTERRUPT_REALTIME_START_SENSITIVITY" 2>/dev/null || true)"

  printf 'env_file=%s\n' "${ENV_FILE}"
  printf 'dialogue_mode=%s\n' "${dialogue_mode:-unset}"
  printf 'dialogue_mode_stability=%s\n' "${mode_stability:-unset}"
  printf 'runtime_mode=%s\n' "${runtime_mode:-unset}"
  printf 'backend=%s\n' "${backend:-unset}"
  printf 'local_text_decision_mode=%s\n' "${decision_mode:-unset}"
  printf 'local_text_provider=%s\n' "${provider:-unset}"
  printf 'local_text_model=%s\n' "${model:-unset}"
  printf 'assistant_audio_mode=%s\n' "${assistant_audio_mode:-unset}"
  printf 'local_tool_ack_audio_mode=%s\n' "${tool_ack_audio_mode:-unset}"
  printf 'rtc_subscribe_audio=%s\n' "${rtc_subscribe_audio:-unset}"
  printf 'rtc_output_device=%s\n' "${rtc_output_device:-unset}"
  printf 'rtc_aec_enabled=%s\n' "${rtc_aec_enabled:-unset}"
  printf 'wake_word_factory=%s\n' "${wake_factory:-unset}"
  printf 'frontgate_session_command=%s\n' "${session_command:-unset}"
  printf 'frontgate_idle_session_exit=%s\n' "${frontgate_idle_exit:-unset}"
  printf 'frontgate_user_away_timeout_ms=%s\n' "${frontgate_user_away_timeout:-unset}"
  printf 'frontgate_session_timeout=%s\n' "${frontgate_session_timeout:-unset}"
  printf 'frontgate_room_max_duration_s=%s\n' "${frontgate_room_max_duration:-unset}"
  printf 'min_endpointing_delay_ms=%s\n' "${min_endpointing_delay:-unset}"
  printf 'max_endpointing_delay_ms=%s\n' "${max_endpointing_delay:-unset}"
  printf 'min_interruption_duration_ms=%s\n' "${min_interruption_duration:-unset}"
  printf 'false_interruption_timeout_ms=%s\n' "${false_interruption_timeout:-unset}"
  printf 'realtime_prefix_padding_ms=%s\n' "${prefix_padding:-unset}"
  printf 'rtc_playback_prebuffer_ms=%s\n' "${rtc_playback_prebuffer:-unset}"
  printf 'realtime_start_sensitivity=%s\n' "${realtime_start_sensitivity:-unset}"
  printf 'job_executor_type=%s\n' "${executor_type:-unset}"
  printf 'offline_profile=%s\n' "${profile:-unset}"
  printf 'service=%s\n' "${SERVICE_NAME}"
  printf 'service_active=%s\n' "$(systemctl --user is-active "${SERVICE_NAME}" 2>/dev/null || true)"
}

apply_mode_common() {
  need_env_file
  apply_profile_file "${BASE_PROFILE}"
}

apply_online_mode() {
  apply_mode_common
  apply_profile_file "${ONLINE_PROFILE}"
  upsert_env_line "${ENV_FILE}" "INTERRUPT_DIALOGUE_MODE" "online"
  upsert_env_line "${ENV_FILE}" "INTERRUPT_DIALOGUE_MODE_STABILITY" "production_fixed"
}

apply_offline_mode() {
  apply_mode_common
  apply_profile_file "${OFFLINE_PROFILE}"
  upsert_env_line "${ENV_FILE}" "INTERRUPT_DIALOGUE_MODE" "offline"
  upsert_env_line "${ENV_FILE}" "INTERRUPT_DIALOGUE_MODE_STABILITY" "experimental_incomplete"
  echo "warning: offline dialogue chain is still experimental and not feature-complete" >&2
}

restart_service() {
  systemctl --user restart "${SERVICE_NAME}"
  sleep 2
  systemctl --user --no-pager --full status "${SERVICE_NAME}" | sed -n '1,18p'
}

main() {
  local mode="${1:-}"
  case "${mode}" in
    online)
      apply_online_mode
      restart_service
      print_status
      ;;
    offline)
      apply_offline_mode
      restart_service
      print_status
      ;;
    status)
      print_status
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      echo "unsupported mode: ${mode}" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
