#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backport the MiniCPM-V 4.6 vLLM lab patches into a target vLLM "
            "site-packages tree."
        )
    )
    parser.add_argument(
        "--target-venv",
        default=str(ROOT_DIR / ".venv-minicpm-vllm-lab"),
        help=(
            "Target virtualenv directory. Used to resolve the real site-packages "
            "path dynamically."
        ),
    )
    parser.add_argument(
        "--target-site-packages",
        default="",
        help=(
            "Target site-packages directory to patch. Overrides --target-venv when set."
        ),
    )
    parser.add_argument(
        "--source-minicpmv46",
        default="",
        help=(
            "Optional path to minicpmv4_6.py to copy into the target env. "
            "If omitted, the script prefers the vendored repo copy and then "
            "falls back to a small set of known local candidates."
        ),
    )
    return parser.parse_args()


def _must_contain(path: Path, needle: str) -> str:
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        raise RuntimeError(f"expected marker {needle!r} not found in {path}")
    return text


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"failed to apply patch for {label}: marker not found")
    return text.replace(old, new, 1)


def _ensure_contains(text: str, snippet: str) -> str:
    return text if snippet in text else text + snippet


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
            "import sysconfig; print(sysconfig.get_paths()[\"purelib\"])",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    site_packages = result.stdout.strip()
    if not site_packages:
        raise RuntimeError(f"failed to resolve site-packages via {python_bin}")
    return Path(site_packages)


def resolve_source_file(explicit: str) -> Path:
    candidates: list[Path] = []
    if explicit.strip():
        candidates.append(Path(explicit).expanduser())

    candidates.extend(
        [
            ROOT_DIR / "vendor" / "vllm_backports" / "minicpmv4_6.py",
            ROOT_DIR
            / ".venv-minicpm-vllm-lab"
            / "lib"
            / "python3.10"
            / "site-packages"
            / "vllm"
            / "model_executor"
            / "models"
            / "minicpmv4_6.py",
            Path("/tmp/vllm-main-probe/vllm/model_executor/models/minicpmv4_6.py"),
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    joined = "\n".join(f"  - {path}" for path in candidates)
    raise RuntimeError(
        "unable to locate a MiniCPM-V 4.6 source file; tried:\n" + joined
    )


def patch_registry(registry_path: Path) -> None:
    text = registry_path.read_text(encoding="utf-8")
    snippet = (
        '    "MiniCPMV4_6ForConditionalGeneration": (\n'
        '        "minicpmv4_6",\n'
        '        "MiniCPMV4_6ForConditionalGeneration",\n'
        "    ),\n"
    )
    if snippet not in text:
        anchors = [
            '    "MiniCPMV": ("minicpmv", "MiniCPMV"),\n',
            '    "MiniCPMV4_5": ("minicpmv", "MiniCPMV4_5"),\n',
        ]
        for anchor in anchors:
            if anchor in text:
                text = _replace_once(
                    text,
                    anchor,
                    anchor + snippet,
                    label="registry.minicpmv4_6",
                )
                registry_path.write_text(text, encoding="utf-8")
                return
        raise RuntimeError("failed to apply patch for registry.minicpmv4_6: no compatible anchor found")


def patch_chat_template_registry(chat_registry_path: Path) -> None:
    text = chat_registry_path.read_text(encoding="utf-8")
    anchor = '    "minicpmv": _get_minicpmv_chat_template_fallback,\n'
    insert = anchor + '    "minicpmv4_6": _get_minicpmv_chat_template_fallback,\n'
    if '"minicpmv4_6": _get_minicpmv_chat_template_fallback,' not in text:
        text = _replace_once(text, anchor, insert, label="chat_templates.minicpmv4_6")
        chat_registry_path.write_text(text, encoding="utf-8")


def patch_minicpmv(minicpmv_path: Path) -> None:
    text = minicpmv_path.read_text(encoding="utf-8")

    block_1_old = """        if version == (2, 0) or version == (2, 5):\n            return image_processor.get_slice_image_placeholder(image_size)\n\n        return image_processor.get_slice_image_placeholder(\n"""
    block_1_new = """        if version == (2, 0) or version == (2, 5):\n            return image_processor.get_slice_image_placeholder(image_size)\n\n        if version == (4, 6):\n            if max_slice_nums is None:\n                max_slice_nums = image_processor.max_slice_nums\n            grids = image_processor.get_sliced_grid(\n                image_size,\n                max_slice_nums=max_slice_nums,\n            )\n            patch_size = image_processor.patch_size\n            scale_resolution = image_processor.scale_resolution\n\n            allow_upscale = grids is None\n            best_size = image_processor.find_best_resize(\n                image_size,\n                scale_resolution,\n                patch_size,\n                allow_upscale=allow_upscale,\n            )\n            h_patches = best_size[1] // patch_size\n            w_patches = best_size[0] // patch_size\n            source_image_visual_tokens = (h_patches // 4) * (w_patches // 4)\n\n            if grids is not None:\n                refine_size = image_processor.get_refine_size(\n                    image_size,\n                    grids,\n                    scale_resolution,\n                    patch_size,\n                    allow_upscale=True,\n                )\n                pw = refine_size[0] // grids[0]\n                ph = refine_size[1] // grids[1]\n                patch_visual_tokens = (ph // patch_size // 4) * (pw // patch_size // 4)\n            else:\n                patch_visual_tokens = source_image_visual_tokens\n\n            return image_processor.get_slice_image_placeholder(\n                grids if grids is not None else [0, 0],\n                image_idx=image_idx,\n                max_slice_nums=max_slice_nums,\n                use_image_id=use_image_id,\n                source_image_visual_tokens=source_image_visual_tokens,\n                patch_visual_tokens=patch_visual_tokens,\n            )\n\n        return image_processor.get_slice_image_placeholder(\n"""
    if "source_image_visual_tokens" not in text:
        text = _replace_once(text, block_1_old, block_1_new, label="minicpmv.get_slice_image_placeholder")

    block_2_old = """    def get_num_image_tokens(\n        self,\n        image_size,\n        max_slice_nums: int | None = None,\n    ) -> int:\n        image_processor = self.get_image_processor()\n\n        grid = self.get_sliced_grid(\n            image_size,\n            max_slice_nums=max_slice_nums,\n        )\n"""
    block_2_new = """    def get_num_image_tokens(\n        self,\n        image_size,\n        max_slice_nums: int | None = None,\n    ) -> int:\n        image_processor = self.get_image_processor()\n        version = self.get_model_version()\n\n        grid = self.get_sliced_grid(\n            image_size,\n            max_slice_nums=max_slice_nums,\n        )\n\n        if version == (4, 6):\n            patch_size = image_processor.patch_size\n            scale_resolution = image_processor.scale_resolution\n\n            allow_upscale = grid is None\n            best_size = image_processor.find_best_resize(\n                image_size,\n                scale_resolution,\n                patch_size,\n                allow_upscale=allow_upscale,\n            )\n            h_p = best_size[1] // patch_size\n            w_p = best_size[0] // patch_size\n            source_tokens = (h_p // 4) * (w_p // 4)\n\n            if grid is None:\n                return source_tokens\n\n            refine_size = image_processor.get_refine_size(\n                image_size,\n                grid,\n                scale_resolution,\n                patch_size,\n                allow_upscale=True,\n            )\n            pw = refine_size[0] // grid[0]\n            ph = refine_size[1] // grid[1]\n            patch_tokens = (ph // patch_size // 4) * (pw // patch_size // 4)\n            ncols, nrows = grid\n            return source_tokens + ncols * nrows * patch_tokens\n"""
    if "version = self.get_model_version()" not in text:
        text = _replace_once(text, block_2_old, block_2_new, label="minicpmv.get_num_image_tokens")

    if "{(2, 6), (4, 0), (4, 5), (4, 6)}" not in text:
        text = text.replace(
            "        if self.info.get_model_version() in {(2, 6), (4, 0), (4, 5)}:\n",
            "        if self.info.get_model_version() in {(2, 6), (4, 0), (4, 5), (4, 6)}:\n",
        )

    block_4_candidates = [
        """            if version == (2, 0) or version == (2, 5):\n                im_start = getattr(\n                    image_processor,\n                    "im_start_token",\n                    getattr(tokenizer, "image_start_token", "<image>"),\n                )\n                im_end = getattr(\n                    image_processor,\n                    "im_end_token",\n                    getattr(tokenizer, "image_end_token", "</image>"),\n                )\n            else:\n                im_start = getattr(\n                    image_processor,\n                    "im_id_start",\n                    getattr(tokenizer, "image_id_start_token", "<image_id>"),\n                )\n                im_end = getattr(\n                    image_processor,\n                    "im_id_end",\n                    getattr(tokenizer, "image_id_end_token", "</image_id>"),\n                )\n\n            new_update = new_update.with_content(\n                PromptUpdateDetails.select_text(\n                    text.replace(\n                        f"{im_start}{prev_item_idx}{im_end}",\n                        f"{im_start}{new_item_idx}{im_end}",\n                        1,\n                    ),\n                    "<unk>",\n                )\n            )\n""",
        """            if version == (2, 0) or version == (2, 5):\n                im_start = image_processor.im_start_token\n                im_end = image_processor.im_end_token\n            else:\n                im_start = image_processor.im_id_start\n                im_end = image_processor.im_id_end\n\n            new_update = new_update.with_content(\n                PromptUpdateDetails.select_text(\n                    text.replace(\n                        f"{im_start}{prev_item_idx}{im_end}",\n                        f"{im_start}{new_item_idx}{im_end}",\n                        1,\n                    ),\n                    "<unk>",\n                )\n            )\n""",
    ]
    block_4_new = """            if version == (2, 0) or version == (2, 5):\n                im_start = image_processor.im_start_token\n                im_end = image_processor.im_end_token\n            elif hasattr(image_processor, "im_id_start"):\n                im_start = image_processor.im_id_start\n                im_end = image_processor.im_id_end\n            else:\n                # transformers v5.7+ keeps im_id tokens on the tokenizer.\n                im_start = getattr(tokenizer, "image_id_start_token", "<image_id>")\n                im_end = getattr(tokenizer, "image_id_end_token", "</image_id>")\n\n            embed_text = getattr(tokenizer, "image_token", "<unk>")\n            new_update = new_update.with_content(\n                PromptUpdateDetails.select_text(\n                    text.replace(\n                        f"{im_start}{prev_item_idx}{im_end}",\n                        f"{im_start}{new_item_idx}{im_end}",\n                        1,\n                    ),\n                    embed_text,\n                )\n            )\n"""
    if 'embed_text = getattr(tokenizer, "image_token", "<unk>")' not in text:
        for block_4_old in block_4_candidates:
            if block_4_old in text:
                text = _replace_once(
                    text,
                    block_4_old,
                    block_4_new,
                    label="minicpmv.prompt_rewrite",
                )
                break
        else:
            raise RuntimeError(
                "failed to apply patch for minicpmv.prompt_rewrite: no compatible block found"
            )

    minicpmv_path.write_text(text, encoding="utf-8")


def patch_minicpmv46(minicpmv46_path: Path) -> None:
    text = minicpmv46_path.read_text(encoding="utf-8")

    if "default_weight_loader" not in text or "maybe_remap_kv_scale_name" not in text:
        old = "from vllm.model_executor.layers.quantization import QuantizationConfig\n"
        new = old + "from vllm.model_executor.model_loader.weight_utils import (\n    default_weight_loader,\n    maybe_remap_kv_scale_name,\n)\n"
        text = _replace_once(text, old, new, label="minicpmv4_6.import_weight_utils")

    if "is_pp_missing_parameter" not in text:
        old = """from .utils import (\n    AutoWeightsLoader,\n    WeightsMapper,\n    _merge_multimodal_embeddings,\n    flatten_bn,\n    maybe_prefix,\n)\n"""
        new = """from .utils import (\n    AutoWeightsLoader,\n    WeightsMapper,\n    _merge_multimodal_embeddings,\n    flatten_bn,\n    is_pp_missing_parameter,\n    maybe_prefix,\n)\n"""
        text = _replace_once(text, old, new, label="minicpmv4_6.import_utils")

    old_loader = """    def load_weights(\n        self,\n        weights: Iterable[tuple[str, torch.Tensor]],\n    ) -> set[str]:\n        loader = AutoWeightsLoader(self, skip_prefixes=[\"mtp.\"])\n        return loader.load_weights(weights, mapper=self.hf_to_vllm_mapper)\n"""
    new_loader = """    def load_weights(\n        self,\n        weights: Iterable[tuple[str, torch.Tensor]],\n    ) -> set[str]:\n        stacked_params_mapping = [\n            # Vision merger self-attention\n            (\".qkv_proj\", \".q_proj\", \"q\"),\n            (\".qkv_proj\", \".k_proj\", \"k\"),\n            (\".qkv_proj\", \".v_proj\", \"v\"),\n            # Language model MLP / attention packed projections\n            (\".gate_up_proj\", \".gate_proj\", 0),\n            (\".gate_up_proj\", \".up_proj\", 1),\n            (\".in_proj_qkvz\", \".in_proj_qkv\", (0, 1, 2)),\n            (\".in_proj_qkvz\", \".in_proj_z\", 3),\n            (\".in_proj_ba\", \".in_proj_b\", 0),\n            (\".in_proj_ba\", \".in_proj_a\", 1),\n        ]\n\n        params_dict = dict(self.named_parameters())\n        loaded_params: set[str] = set()\n\n        for name, loaded_weight in self.hf_to_vllm_mapper.apply(weights):\n            if \"rotary_emb.inv_freq\" in name:\n                continue\n\n            if name.startswith(\"mtp.\"):\n                continue\n\n            if name.endswith(\"scale\"):\n                remapped_name = maybe_remap_kv_scale_name(name, params_dict)\n                if remapped_name is None:\n                    continue\n                name = remapped_name\n\n            stacked_matched = False\n            for param_name, weight_name, shard_id in stacked_params_mapping:\n                if weight_name not in name:\n                    continue\n\n                name_rewritten = name.replace(weight_name, param_name)\n\n                if (\n                    name_rewritten.endswith(\".bias\")\n                    and name_rewritten not in params_dict\n                ):\n                    continue\n\n                if is_pp_missing_parameter(name_rewritten, self):\n                    stacked_matched = True\n                    break\n\n                if name_rewritten not in params_dict:\n                    continue\n\n                param = params_dict[name_rewritten]\n                weight_loader = getattr(param, \"weight_loader\", default_weight_loader)\n                weight_loader(param, loaded_weight, shard_id)\n                loaded_params.add(name_rewritten)\n                stacked_matched = True\n                break\n\n            if stacked_matched:\n                continue\n\n            if name.endswith(\".bias\") and name not in params_dict:\n                continue\n\n            if is_pp_missing_parameter(name, self):\n                continue\n\n            if name not in params_dict:\n                continue\n\n            param = params_dict[name]\n            weight_loader = getattr(param, \"weight_loader\", default_weight_loader)\n            weight_loader(param, loaded_weight)\n            loaded_params.add(name)\n\n        return loaded_params\n"""
    if "stacked_params_mapping = [" not in text:
        text = _replace_once(text, old_loader, new_loader, label="minicpmv4_6.load_weights")

    minicpmv46_path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    target_site_packages = resolve_target_site_packages(
        args.target_venv,
        args.target_site_packages,
    )
    if not target_site_packages.exists():
        raise RuntimeError(f"target site-packages not found: {target_site_packages}")

    source_file = resolve_source_file(args.source_minicpmv46)

    model_dir = target_site_packages / "vllm" / "model_executor" / "models"
    chat_dir = target_site_packages / "vllm" / "transformers_utils" / "chat_templates"

    registry_path = model_dir / "registry.py"
    minicpmv_path = model_dir / "minicpmv.py"
    minicpmv46_path = model_dir / "minicpmv4_6.py"
    chat_registry_path = chat_dir / "registry.py"

    _must_contain(registry_path, "_MULTIMODAL_MODELS")
    _must_contain(minicpmv_path, "class MiniCPMVProcessingInfo")
    _must_contain(chat_registry_path, "_MODEL_TYPE_TO_CHAT_TEMPLATE_FALLBACK")

    if source_file.resolve() != minicpmv46_path.resolve():
        shutil.copyfile(source_file, minicpmv46_path)
    patch_registry(registry_path)
    patch_chat_template_registry(chat_registry_path)
    patch_minicpmv(minicpmv_path)
    patch_minicpmv46(minicpmv46_path)

    print(f"patched: {target_site_packages}")
    print(f"source_minicpmv4_6: {source_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
