# Qwen-VL vLLM Bring-up

更新时间：2026-05-13

目标：

- 保持现有 `gemma3` 基线不动
- 新增 `Qwen2.5-VL-7B-Instruct -> vLLM -> OpenAI-compatible`
- 接入 `interrupt` 的统一横评脚本做第一轮对比

## 0. 本地机与机器人条件对比

截至 2026-05-13，实际环境核对如下。

本地开发机：

- GPU：`NVIDIA GeForce RTX 4060 Laptop GPU`
- 显存：`8188 MiB`
- 驱动：`580.142`
- Python：`3.10.12`
- 磁盘可用：`113G`
- 现状：
  - `ollama` 已可用
  - `vllm / transformers / sglang` 初始未安装

机器人本机：

- 主机：`unitree-g1-nx`
- 架构：`aarch64`
- GPU：`Orin (nvgpu)`
- 驱动：`540.4.0`
- 内存：`15Gi`
- 交换分区：`7.6Gi`
- 磁盘可用：`89G`
- Python：`3.10.12`
- `/dev/video0` 到 `/dev/video5` 可见
- 现状：
  - `ollama` 不存在
  - `torch / transformers / vllm / sglang` 都不存在

这意味着：

1. 第一轮 `Qwen-VL -> vLLM` 更适合在本地开发机验证。
2. 机器人更适合作为后续“接同一 OpenAI-compatible 接口”的消费端。
3. 如果最终一定要把视觉模型也直接落到机器人本机，需要单独评估 Jetson/Orin 友好的推理方案，不建议把“本地开发机 vLLM 验证通过”直接等同于“机器人本机可原样起 vLLM”。
4. 对这台 `RTX 4060 Laptop 8GB` 来说，首轮建议优先尝试：
   - `Qwen2.5-VL-3B-Instruct`
   - 或 `Qwen2.5-VL-7B` 的量化版本
   而不是默认把 `7B bf16` 当作第一枪。

2026-05-13 本地实测补充：

- `Qwen2.5-VL-3B-Instruct` 已完成本地 snapshot 下载
- 在 `vLLM 0.20.2 + bf16 + RTX 4060 8GB` 下，模型权重可加载
- 但在多模态 profile 阶段触发：
  - `torch.OutOfMemoryError`
  - 额外申请 `160 MiB` 时失败
- 日志显示模型加载本体已占约 `7.16 GiB`

这意味着：

1. `Qwen2.5-VL-3B bf16 + vLLM` 对这张 `8GB` 卡仍然偏紧
2. 下一步不建议继续硬顶同配置
3. 更合适的路线是：
   - 尝试更小的 Qwen-VL 规格
   - 或切到量化模型
   - 或换更大显存 GPU

## 1. 当前仓库已准备好的入口

- 启动模板：
  - `run_local_vllm_vision_server.sh`
  - `run_local_qwen25_vl_vllm.sh`
  - `run_local_qwen25_vl_3b_vllm.sh`
- 横评脚本：
  - `run_local_vlm_compare.sh`
  - `tools/vlm_compare_matrix.py`
- 推荐矩阵：
  - `config/vlm_eval_matrix.qwen_vs_gemma.json`
  - `config/vlm_eval_matrix.qwen3b_vs_gemma.json`

## 2. 前置条件

需要一台满足以下条件的机器：

- GPU 驱动正常
- `nvidia-smi` 可用
- 已安装 `vllm`
- 可访问 `Qwen2.5-VL-7B-Instruct` 模型目录或 Hugging Face 缓存

当前这台开发机截至 2026-05-13 的初始状态：

- `vllm` 未安装
- 但 `nvidia-smi` 已验证可用
- 因此本地验证路线成立，当前主要缺的是推理环境而不是硬件

所以这份文档的主要用途是把步骤固定下来，换到合适机器后可直接执行。

## 3. 最短启动方式

先准备环境变量：

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
export VLM_SERVER_PYTHON_BIN=/path/to/vllm-env/bin/python
export VLM_SERVER_MODEL_PATH=/models/Qwen2.5-VL-7B-Instruct
export VLM_SERVER_SERVED_MODEL_NAME=Qwen2.5-VL-7B-Instruct
./run_local_qwen25_vl_vllm.sh
```

如果按当前这台 `8GB` 显存机器的保守路线，优先建议：

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
export VLM_SERVER_PYTHON_BIN=/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/.venv-qwen-vllm/bin/python
export VLM_SERVER_MODEL_PATH=Qwen/Qwen2.5-VL-3B-Instruct
export VLM_SERVER_SERVED_MODEL_NAME=Qwen2.5-VL-3B-Instruct
./run_local_qwen25_vl_3b_vllm.sh
```

默认行为：

- host: `127.0.0.1`
- port: `8000`
- dtype: `bfloat16`
- max model len: `8192`
- tensor parallel size: `1`
- extra args: `--limit-mm-per-prompt {"image":1}`

## 4. 最小验活

服务起来后先跑：

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
python tools/vlm_backend_probe.py \
  --provider openai_compatible \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen2.5-VL-7B-Instruct \
  --require-model
```

期望结果：

- `status: OK`
- `model_found: yes`

## 5. 第一轮横评

确认 `gemma3` 仍在线后，直接跑：

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
./run_local_vlm_compare.sh config/vlm_eval_matrix.qwen_vs_gemma.json
```

如果先走 `3B`，则改成：

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
./run_local_vlm_compare.sh config/vlm_eval_matrix.qwen3b_vs_gemma.json
```

期望输出：

- `gemma3_ollama_local` 为 `OK`
- `qwen25_vl_vllm_local` 为 `OK`
- 结果落盘到：
  - `interrupt/tmp/vlm_compare_last.json`

## 6. 下一步判断标准

只有当以下条件都满足，才建议继续上真机：

- `Qwen-VL` 本地横评通过
- 结构化 observation 字段完整
- 与 `gemma3` 相比没有明显退化
- 安全字段至少在 `scene_visibility / free_space_front / obstacle_near_arms` 上稳定
