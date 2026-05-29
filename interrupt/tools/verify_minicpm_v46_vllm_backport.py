#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that the MiniCPM-V 4.6 vLLM lab backport is present."
    )
    parser.add_argument(
        "--target-venv",
        default=str(ROOT_DIR / ".venv-minicpm-vllm-lab"),
        help="Target virtualenv directory to inspect.",
    )
    parser.add_argument(
        "--target-site-packages",
        default="",
        help="Target site-packages directory to inspect. Overrides --target-venv.",
    )
    return parser.parse_args()


def resolve_target_site_packages(target_venv: str, explicit_site_packages: str) -> Path:
    if explicit_site_packages.strip():
        return Path(explicit_site_packages).expanduser()

    venv_dir = Path(target_venv).expanduser()
    python_bin = venv_dir / "bin" / "python"
    if not python_bin.exists():
        raise RuntimeError(f"target venv python not found: {python_bin}")

    result = subprocess.run(
        [
            str(python_bin),
            "-c",
            "import sysconfig; print(sysconfig.get_paths()['purelib'])",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    site_packages = result.stdout.strip()
    if not site_packages:
        raise RuntimeError(f"failed to resolve site-packages via {python_bin}")
    return Path(site_packages)


def require_contains(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        raise RuntimeError(f"expected marker {needle!r} not found in {path}")


def main() -> int:
    args = parse_args()
    target_site_packages = resolve_target_site_packages(
        args.target_venv,
        args.target_site_packages,
    )
    model_dir = target_site_packages / "vllm" / "model_executor" / "models"
    chat_dir = target_site_packages / "vllm" / "transformers_utils" / "chat_templates"

    require_contains(
        model_dir / "registry.py",
        '"MiniCPMV4_6ForConditionalGeneration": (',
    )
    require_contains(
        chat_dir / "registry.py",
        '"minicpmv4_6": _get_minicpmv_chat_template_fallback,',
    )
    require_contains(
        model_dir / "minicpmv.py",
        "source_image_visual_tokens",
    )
    require_contains(
        model_dir / "minicpmv.py",
        "{(2, 6), (4, 0), (4, 5), (4, 6)}",
    )
    require_contains(
        model_dir / "minicpmv.py",
        'embed_text = getattr(tokenizer, "image_token", "<unk>")',
    )
    require_contains(
        model_dir / "minicpmv4_6.py",
        "stacked_params_mapping = [",
    )
    require_contains(
        model_dir / "minicpmv4_6.py",
        "maybe_remap_kv_scale_name",
    )

    print(f"verified: {target_site_packages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
