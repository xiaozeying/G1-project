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

## 7. 2026-05-19 主分支 Python 回灌实测

### 7.1 架构支持已经不再是主阻塞

把 `vLLM main` 里的 `minicpmv4_6.py` 和相关 registry/chat-template 回灌到
`.venv-minicpm-vllm-lab` 后，`MiniCPM-V-4.6` 已经能被 `vLLM 0.21.0`
真实识别：

```text
Resolved architecture: MiniCPMV4_6ForConditionalGeneration
```

这说明当前阶段已经不是“架构名不支持”。

### 7.2 额外补过的兼容点

为了把服务推进到真实加载权重阶段，还额外补过这些 Python 兼容项：

1. `minicpmv.py` 适配 `transformers v5` 的 image processor 字段
2. `minicpmv.py` 适配 image-id prompt rewrite 接口差异
3. `MiniCPM-V 4.6` 自定义 `load_weights`，显式处理
   `vit_merger.self_attn.{q,k,v}_proj -> qkv_proj`

补完后，模型已经能成功完成：

- 结构解析
- 权重下载
- 权重加载
- 编译 warmup

### 7.3 `vit_merger.self_attn.k_proj` 这层已经越过去了

此前的关键报错是：

```text
There is no module or parameter named 'vit_merger.self_attn.k_proj'
```

现在这层已经被定制 `load_weights` 越过，不再是当前阻塞点。

### 7.4 新阻塞已经变成宿主机运行时条件

当前最新的两个真实阻塞是：

1. 默认 `flashinfer` sampler 会在 warmup 末尾触发 JIT，并要求本机有 `nvcc`
2. 在关闭 `flashinfer sampler` 后，`RTX 4060 8GB` 仍会在 KV cache 预留阶段撞到显存边界

对应实测现象：

- 默认 sampler 路线：

```text
RuntimeError: Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist
```

- 关闭 `VLLM_USE_FLASHINFER_SAMPLER=0` 后：

```text
ValueError: No available memory for the cache blocks.
```

### 7.5 当前最准确的状态判断

截至 `2026-05-19`：

- `MiniCPM-V 4.6 + qwen3_coder + OpenAI-compatible` 这条链路的 **Python 侧主阻塞已基本打穿**
- 当前更像是 **宿主机运行时条件问题**
  - 缺 `nvcc`，默认 `flashinfer sampler` 不能直接用
  - `8GB` 显存下，`4096` 上下文 + 当前 warmup / KV cache 预算仍偏紧

换句话说，现在离“真挂起服务”已经比昨天近很多，但最后卡点已经主要落在：

1. `vLLM` 运行参数再收缩
2. 关闭更多 warmup / cudagraph / cache 预算
3. 或换更大显存 GPU / 有 `nvcc` 的 CUDA 环境

## 8. 2026-05-19 可运行参数组合与真测结果

### 8.1 8GB 卡可运行组合

在开发机 `RTX 4060 8GB` 上，以下组合已实测可把
`MiniCPM-V 4.6` OpenAI-compatible 服务挂起：

```bash
VLLM_USE_FLASHINFER_SAMPLER=0
VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0
VLM_SERVER_MAX_MODEL_LEN=2048
VLM_SERVER_GPU_MEMORY_UTILIZATION=0.90
VLM_SERVER_EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser qwen3_coder --enforce-eager --skip-mm-profiling"
```

对应服务：

- `http://127.0.0.1:8011/v1`
- `http://0.0.0.0:8000/v1`

### 8.2 已验证的接口能力

本地已验证：

1. `/v1/models`
2. `/v1/chat/completions` 普通回复
3. `/v1/chat/completions` `tool_calls`

工具调用实测已返回：

```json
{
  "name": "perform_body_action",
  "arguments": {
    "action": "wave"
  }
}
```

### 8.3 机器人侧已打通

机器人侧已完成两条真测：

1. `run_robot_minicpm_text_brain_smoke.sh "请你挥挥手"`
2. `run_robot_offline_vlm_validation.sh "你前面有什么？"`

两条都成功，其中第二条已从机器人相机 `/dev/video2` 实取图片并返回视觉回答。

### 8.4 仍需注意的工程事实

当前成功链还不是“纯官方包开箱即用”，而是：

1. `vLLM 0.21.0` + 回灌 `main` 分支 MiniCPM-V 4.6 Python 适配
2. 再叠加 8GB 卡安全启动参数

所以后续如果重建 `.venv-minicpm-vllm-lab`，还需要把这套 backport
过程脚本化，否则服务不会直接按当前状态复现。

## 9. 2026-05-19 恢复脚本化进展

为减少手工改 `site-packages`，新增了：

- `run_backport_minicpm_v46_vllm_lab.sh`
- `tools/backport_minicpm_v46_vllm_lab.py`

用途：

1. 向目标 `site-packages` 注入 `minicpmv4_6.py`
2. 自动补 `registry.py` 的 `MiniCPMV4_6ForConditionalGeneration` 注册
3. 自动补 chat-template registry 的 `minicpmv4_6` fallback
4. 自动补 `minicpmv.py` 的 `transformers v5` / prompt rewrite 兼容
5. 自动补 `minicpmv4_6.py` 的定制 `load_weights`

同时，`run_setup_minicpm_vllm_lab.sh` 现在会在安装完 `vLLM`
实验环境后尝试自动调用这一步。

当前这意味着：

- “重建 lab 环境后再手工 patch” 这件事已经开始被脚本接管
- `minicpmv4_6.py` 现在优先使用仓库内
  `interrupt/vendor/vllm_backports/minicpmv4_6.py`
- 只有显式指定 `--source-minicpmv46` 或仓库内 vendored 文件缺失时，
  才会退回现有 lab 环境或 `/tmp/vllm-main-probe`

所以它已经从“纯手工恢复”推进到了“仓库自带源文件的半自动恢复”。

## 10. 2026-05-19 冷启动恢复端到端验证

在本轮后，以下完整冷启动流程已经真实跑通：

1. `run_validate_minicpm_v46_vllm_coldstart.sh`
2. 新建临时 `venv`
3. 安装 `vLLM 0.21.0`
4. 自动执行 `run_backport_minicpm_v46_vllm_lab.sh`
5. 自动执行 `tools/verify_minicpm_v46_vllm_backport.py`

这一步中还顺手补稳了两类兼容差异：

1. 新装 `vLLM 0.21.0` 的 `registry.py` 锚点差异
2. 新装 `minicpmv.py` 与当前实验环境 `minicpmv.py` 的 prompt rewrite / version gate 差异

所以当前更准确的状态是：

- `MiniCPM-V 4.6` 回灌源文件：已 vendored
- cold-start backport 脚本：已完成
- cold-start verify 脚本：已完成
- 端到端冷启动恢复：已验证通过
