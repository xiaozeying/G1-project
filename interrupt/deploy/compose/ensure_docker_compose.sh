#!/usr/bin/env bash
set -euo pipefail

VERSION="${DOCKER_COMPOSE_VERSION:-v2.40.3}"
PLUGIN_DIR="${HOME}/.docker/cli-plugins"
PLUGIN_PATH="${PLUGIN_DIR}/docker-compose"

if docker compose version >/dev/null 2>&1; then
  docker compose version
  exit 0
fi

mkdir -p "${PLUGIN_DIR}"

ARCH="$(uname -m)"
case "${ARCH}" in
  x86_64|amd64)
    ASSET_ARCH="x86_64"
    ;;
  aarch64|arm64)
    ASSET_ARCH="aarch64"
    ;;
  *)
    echo "unsupported architecture: ${ARCH}" >&2
    exit 1
    ;;
esac

URL="https://github.com/docker/compose/releases/download/${VERSION}/docker-compose-linux-${ASSET_ARCH}"
echo "installing docker compose plugin from ${URL}"
curl -fL "${URL}" -o "${PLUGIN_PATH}"
chmod +x "${PLUGIN_PATH}"

docker compose version
