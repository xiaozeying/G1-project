#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINIFORGE_DIR="${HOME}/miniforge3"
ENV_NAME="${WAKEWORD_ENV_NAME:-wakeword-clean}"
ENV_PREFIX="${MINIFORGE_DIR}/envs/${ENV_NAME}"
PYTHON_BIN="${ENV_PREFIX}/bin/python"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

echo "[wakeword] root=${ROOT_DIR}"
echo "[wakeword] env=${ENV_PREFIX}"
echo "[wakeword] pip index=${PIP_INDEX_URL}"

if [[ ! -x "${MINIFORGE_DIR}/bin/conda" ]]; then
  echo "[wakeword] installing Miniforge..."
  cd "${HOME}"
  wget -O Miniforge3-Linux-aarch64.sh \
    https://mirrors.tuna.tsinghua.edu.cn/github-release/conda-forge/miniforge/LatestRelease/Miniforge3-Linux-aarch64.sh
  bash Miniforge3-Linux-aarch64.sh -b -p "${MINIFORGE_DIR}"
fi

eval "$("${MINIFORGE_DIR}/bin/conda" shell.bash hook)"

if [[ ! -d "${ENV_PREFIX}" ]]; then
  echo "[wakeword] creating conda env ${ENV_NAME}..."
  conda create -n "${ENV_NAME}" python=3.9 -y
fi

conda activate "${ENV_NAME}"

echo "[wakeword] using python: $(which python)"
if ! python -m pip --version >/dev/null 2>&1; then
  echo "[wakeword] pip missing in ${ENV_NAME}, installing via conda..."
  conda install -n "${ENV_NAME}" pip -y
fi

echo "[wakeword] using pip: $(python -m pip --version)"

python -m pip install -i "${PIP_INDEX_URL}" --upgrade pip setuptools wheel
python -m pip install -i "${PIP_INDEX_URL}" -r "${ROOT_DIR}/requirements-arm.txt"

"${PYTHON_BIN}" <<'PYEOF'
from modelscope.hub.snapshot_download import snapshot_download

print("[wakeword] downloading SenseVoiceSmall if needed...")
path = snapshot_download(
    "iic/SenseVoiceSmall",
    cache_dir="/home/unitree/.cache/modelscope/hub",
    revision="master",
)
print(f"[wakeword] model path: {path}")
PYEOF

"${PYTHON_BIN}" <<'PYEOF'
from funasr import AutoModel
import numpy as np

print("[wakeword] smoke test start")
model = AutoModel(
    model="/home/unitree/.cache/modelscope/hub/iic/SenseVoiceSmall",
    device="cpu",
    disable_update=True,
    disable_pbar=True,
)
audio = np.random.randn(16000).astype(np.float32)
result = model.generate(input=audio, batch_size=1, language="auto")
print(f"[wakeword] smoke test ok result_type={type(result).__name__}")
PYEOF

echo
echo "[wakeword] install complete"
echo "[wakeword] test with:"
echo "  ${PYTHON_BIN} ${ROOT_DIR}/wakeword_adaptive.py --list"
