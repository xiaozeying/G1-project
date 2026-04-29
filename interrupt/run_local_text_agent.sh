#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export INTERRUPT_TEXT_MODE=1
export INTERRUPT_DISABLE_CONSOLE_AUDIO_COMPAT=1
exec "${ROOT_DIR}/run_local_voice_agent.sh"
