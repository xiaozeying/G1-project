# MiniCPM-V 4.6 OpenAI-Compatible Tool Entry

更新时间：2026-05-18

## 1. 本次接入内容

- `src/local_text_brain.py`
  - 新增 `openai_compatible` 本地文本脑后端
  - 支持 `/v1/chat/completions`
  - 支持 OpenAI-style `tool_calls`
- `tools/apply_offline_model_profile.py`
  - `minicpm_v46` profile 现在会把：
    - `INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER`
    - `INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL`
    - `INTERRUPT_AGENT_LOCAL_TEXT_MODEL`
    直接切到 `MiniCPM-V-4_6`
- 新增快捷脚本：
  - `run_local_minicpm_text_brain_smoke.sh`
  - `run_robot_minicpm_text_brain_smoke.sh`

## 2. 当前定位

这次接入的目标不是立刻替换默认链，而是把 `MiniCPM-V 4.6` 做成：

- 一个新的本地 OpenAI-compatible 多模态工具调用候选入口
- 可用于验证“视觉理解 + 工具调用”一体化路线

## 3. 典型用法

本机：

```bash
cd interrupt
bash ./run_local_minicpm_text_brain_smoke.sh "挥挥手"
```

机器人：

```bash
cd ~/HongTu/interrupt
bash ./run_robot_minicpm_text_brain_smoke.sh "帮我看看前面有什么"
```

如果要切 profile：

```bash
cd interrupt
eval "$(bash ./run_apply_offline_model_profile.sh minicpm_v46 local)"
```

```bash
cd ~/HongTu/interrupt
eval "$(bash ./run_apply_offline_model_profile.sh minicpm_v46 robot)"
```

## 4. 当前现实限制

截至 `2026-05-18`：

- `MiniCPM-V-4_6` 的 `8000/v1` 服务仍未在这台开发机上跑通
- `Qwen2.5-VL-3B-Instruct` 已实测在当前 `RTX 4060 8GB` 上 `vLLM bf16` 会 OOM

因此这次接入完成的是“入口与链路”，不是“MiniCPM 已正式跑通”。

## 5. 2026-05-18 后端实测结论补充

### 5.1 `vLLM 0.20.2` 不是当前可用解

开发机现有虚拟环境：

- `vllm==0.20.2`
- `transformers==5.8.1`

其中 `transformers` 已经包含 `MiniCPMV4_6ForConditionalGeneration`，但现有 `vLLM` 直接启动 `openbmb/MiniCPM-V-4.6` 时会报：

```text
Model architectures ['MiniCPMV4_6ForConditionalGeneration'] are not supported for now.
```

这说明当前阻塞点不是我们仓库接线，而是本机 `vLLM` 版本太旧，尚未支持 `MiniCPM-V 4.6` 架构。

### 5.2 `transformers serve` 是更现实的下一条验证线

本机 `transformers 5.8.1` 已自带：

- `transformers serve`
- FastAPI / Uvicorn / `sse_starlette`

补装：

- `accelerate`
- `bitsandbytes`

之后，`transformers serve` 可以继续进入模型加载阶段，说明它比当前 `vLLM 0.20.2` 更接近可落地状态。

### 5.3 `MiniCPM-V-4.6-BNB` 现有组合还不稳定

实测：

```bash
./.venv-qwen-vllm/bin/transformers serve openbmb/MiniCPM-V-4.6-BNB ...
```

会在量化配置解析阶段报错：

```text
AttributeError: 'NoneType' object has no attribute 'get'
```

当前更像是 `MiniCPM-V-4.6-BNB` 与我们这套 `transformers 5.8.1` 组合的兼容问题，而不是显存不够。

### 5.4 当前最值得继续试的组合

优先级建议：

1. 升级到支持 `minicpmv4_6` 的较新 `vLLM` 版本，再复测 `qwen3_coder` 工具调用链
2. 如果短期目标是先跑通 `8000/v1`，优先继续试：
   - `transformers serve openbmb/MiniCPM-V-4.6 --quantization bnb-4bit`
3. 在确认服务可稳定启动前，不建议把 `minicpm_v46` profile 切成默认主链

## 6. 2026-05-18 新版 vLLM 实测

### 6.1 新增隔离实验环境

为了不污染现有基线链，新增了：

- `run_setup_minicpm_vllm_lab.sh`
- `run_local_minicpm_v46_vllm_lab.sh`

其中：

- `run_setup_minicpm_vllm_lab.sh` 会创建 `.venv-minicpm-vllm-lab`
- `run_local_minicpm_v46_vllm_lab.sh` 会用该环境直接起 `MiniCPM-V-4.6`

### 6.2 `vLLM 0.21.0` 已确认包含 `qwen3_coder`

隔离环境安装结果：

- `vllm=0.21.0`
- `transformers=5.8.1`
- `torch=2.11.0+cu130`

静态检查确认：

- `vllm.tool_parsers.qwen3coder_tool_parser` 存在
- `vllm` 已内置 `qwen3_coder` parser

### 6.3 但 `MiniCPM-V 4.6` 运行时仍不支持

实测：

```bash
cd interrupt
VLM_SERVER_PORT=8011 ./run_local_minicpm_v46_vllm_lab.sh
```

已经能正确把参数传到 `vLLM 0.21.0`，并进入模型配置阶段，但最终仍报：

```text
Model architectures ['MiniCPMV4_6ForConditionalGeneration'] are not supported for now.
```

同时，静态代码检查显示当前 `vllm.model_executor.models.minicpmv` 支持的版本上限是：

- `MiniCPMV2_0`
- `MiniCPMV2_5`
- `MiniCPMV2_6`
- `MiniCPMV4_0`
- `MiniCPMV4_5`

也就是说：

- `vLLM 0.21.0` 已经具备 `qwen3_coder` 工具调用解析能力
- 但仍然**没有** `MiniCPM-V 4.6` 的运行时架构支持

### 6.4 当前最准确的工程判断

截至 `2026-05-18`，想在本机走：

- `MiniCPM-V 4.6`
- `vLLM`
- `qwen3_coder`
- OpenAI-compatible `/v1/chat/completions`

这条路线，至少还需要：

1. 更高版本、且明确支持 `MiniCPMV4_6ForConditionalGeneration` 的 `vLLM`
2. 或者改用非 `vLLM` 的 OpenAI-compatible 推理后端
