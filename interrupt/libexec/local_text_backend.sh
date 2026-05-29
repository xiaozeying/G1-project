#!/usr/bin/env bash

interrupt_default_ollama_bin_dir() {
  printf '%s\n' "${INTERRUPT_LOCAL_TEXT_OLLAMA_BIN_DIR:-/data/HongTu/.local/bin}"
}

interrupt_default_ollama_models_dir() {
  printf '%s\n' "${INTERRUPT_LOCAL_TEXT_OLLAMA_MODELS_DIR:-/data/HongTu/ollama/models}"
}

interrupt_prepare_local_ollama_env() {
  local bin_dir
  local models_dir
  bin_dir="$(interrupt_default_ollama_bin_dir)"
  models_dir="$(interrupt_default_ollama_models_dir)"
  if [[ -d "${bin_dir}" ]]; then
    export PATH="${bin_dir}:${PATH}"
  fi
  export OLLAMA_MODELS="${OLLAMA_MODELS:-${models_dir}}"
}

interrupt_local_text_backend_required() {
  local runtime_mode="${INTERRUPT_AGENT_RUNTIME_MODE:-online_full}"
  local decision_mode="${INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE:-disabled}"
  [[ "${runtime_mode}" == "offline_singlebox" || "${decision_mode}" != "disabled" ]]
}

interrupt_is_loopback_url() {
  local raw_url="${1:-}"
  python3 - "${raw_url}" <<'PY'
from urllib.parse import urlparse
import sys

raw = (sys.argv[1] or "").strip()
host = (urlparse(raw).hostname or "").strip().lower()
if host in {"127.0.0.1", "localhost", "::1"}:
    raise SystemExit(0)
raise SystemExit(1)
PY
}

interrupt_maybe_force_singlebox_local_text_loopback() {
  local force_loopback="${INTERRUPT_SINGLEBOX_FORCE_LOCALHOST_LOCAL_TEXT:-1}"
  if [[ "${INTERRUPT_AGENT_RUNTIME_MODE:-online_full}" != "offline_singlebox" ]]; then
    return 0
  fi
  if [[ "${INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER:-ollama}" != "ollama" ]]; then
    return 0
  fi
  if [[ "${force_loopback}" != "1" ]]; then
    return 0
  fi
  local current_url="${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL:-}"
  if [[ -z "${current_url}" ]] || ! interrupt_is_loopback_url "${current_url}"; then
    export INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL="${INTERRUPT_SINGLEBOX_LOCAL_TEXT_BASE_URL:-http://127.0.0.1:11434}"
    echo "singlebox local text base_url forced to loopback: ${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL}"
  fi
}

interrupt_local_text_tags_url() {
  local raw_url="${1:-}"
  python3 - "${raw_url}" <<'PY'
import sys

base = (sys.argv[1] or "").strip().rstrip("/")
if not base:
    print("")
    raise SystemExit(0)
if base.endswith("/api/tags"):
    print(base)
elif base.endswith("/api"):
    print(base + "/tags")
elif base.endswith("/v1"):
    print(base[:-3] + "/api/tags")
else:
    print(base + "/api/tags")
PY
}

interrupt_probe_local_text_backend() {
  local raw_url="${1:-}"
  local timeout_s="${2:-1.5}"
  local tags_url
  tags_url="$(interrupt_local_text_tags_url "${raw_url}")"
  [[ -n "${tags_url}" ]] || return 1
  python3 - "${tags_url}" "${timeout_s}" <<'PY'
import json
import sys
import urllib.request
from urllib.error import URLError, HTTPError

url = sys.argv[1]
timeout_s = float(sys.argv[2])
request = urllib.request.Request(url, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read()
        if not payload:
            raise SystemExit(0)
        json.loads(payload.decode("utf-8", errors="ignore"))
        raise SystemExit(0)
except (URLError, HTTPError, TimeoutError, json.JSONDecodeError):
    raise SystemExit(1)
PY
}

interrupt_local_text_should_manage_ollama() {
  [[ "${INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER:-ollama}" == "ollama" ]] || return 1
  interrupt_local_text_backend_required || return 1
  interrupt_is_loopback_url "${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL:-http://127.0.0.1:11434}"
}

interrupt_start_local_ollama_background() {
  local root_dir="${1:?root_dir required}"
  local log_file="${2:?log_file required}"
  local host_port="${INTERRUPT_LOCAL_TEXT_OLLAMA_HOST_PORT:-127.0.0.1:11434}"
  local serve_script="${INTERRUPT_LOCAL_TEXT_OLLAMA_SERVE_SCRIPT:-${root_dir}/run_lan_ollama_serve.sh}"

  interrupt_prepare_local_ollama_env

  if ! command -v ollama >/dev/null 2>&1; then
    echo "local text autostart skipped: ollama not found"
    return 1
  fi
  if [[ ! -f "${serve_script}" ]]; then
    echo "local text autostart skipped: serve script missing ${serve_script}"
    return 1
  fi
  if pgrep -f "ollama serve" >/dev/null 2>&1; then
    echo "local text autostart: existing ollama serve detected"
    return 0
  fi

  echo "local text autostart: launching ollama serve host=${host_port}"
  mkdir -p "${OLLAMA_MODELS}"
  nohup env OLLAMA_HOST="${host_port}" OLLAMA_MODELS="${OLLAMA_MODELS}" bash "${serve_script}" >> "${log_file}" 2>&1 &
}

interrupt_ensure_local_text_backend_ready() {
  local root_dir="${1:?root_dir required}"
  local log_file="${2:?log_file required}"
  local timeout_s="${INTERRUPT_LOCAL_TEXT_STARTUP_TIMEOUT_S:-20}"
  local probe_timeout_s="${INTERRUPT_LOCAL_TEXT_PROBE_TIMEOUT_S:-1.5}"
  local base_url="${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL:-http://127.0.0.1:11434}"

  interrupt_prepare_local_ollama_env
  interrupt_maybe_force_singlebox_local_text_loopback
  base_url="${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL:-http://127.0.0.1:11434}"

  if ! interrupt_local_text_should_manage_ollama; then
    echo "local text autostart: skipped provider=${INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER:-unset} base_url=${base_url} runtime_mode=${INTERRUPT_AGENT_RUNTIME_MODE:-unset}"
    return 0
  fi

  if interrupt_probe_local_text_backend "${base_url}" "${probe_timeout_s}"; then
    echo "local text backend ready: ${base_url}"
    return 0
  fi

  interrupt_start_local_ollama_background "${root_dir}" "${log_file}" || true

  if python3 - "${base_url}" "${timeout_s}" "${probe_timeout_s}" <<'PY'
import sys
import time
import urllib.request
from urllib.error import URLError, HTTPError

base_url = (sys.argv[1] or "").strip().rstrip("/")
timeout_s = float(sys.argv[2])
probe_timeout_s = float(sys.argv[3])

if base_url.endswith("/api/tags"):
    tags_url = base_url
elif base_url.endswith("/api"):
    tags_url = base_url + "/tags"
elif base_url.endswith("/v1"):
    tags_url = base_url[:-3] + "/api/tags"
else:
    tags_url = base_url + "/api/tags"

deadline = time.monotonic() + max(0.0, timeout_s)
request = urllib.request.Request(tags_url, headers={"Content-Type": "application/json"})
while time.monotonic() <= deadline:
    try:
        with urllib.request.urlopen(request, timeout=probe_timeout_s):
            raise SystemExit(0)
    except (URLError, HTTPError, TimeoutError):
        time.sleep(0.5)
raise SystemExit(1)
PY
  then
    echo "local text backend ready after autostart: ${base_url}"
    return 0
  fi

  echo "local text backend not ready after ${timeout_s}s: ${base_url}"
  return 1
}
