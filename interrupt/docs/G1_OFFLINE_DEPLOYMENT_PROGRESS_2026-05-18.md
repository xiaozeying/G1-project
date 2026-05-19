# G1 离线具身部署续推进展

更新时间：2026-05-18

## 1. 本次续推进做了什么

- 修正了 `tools/agent_backend_probe.py`
  - 现在会自动补 `src` 路径
  - 不再把 `local_text_ollama` 错误标成 `room_agent_not_integrated`
  - 会同时输出：
    - `runtime_mode`
    - `local_text_decision_mode`
    - `local_text_integrated`
    - `ready_for_offline_singlebox`
- 新增机器人侧一键巡检脚本：
  - `run_robot_localized_stack_probe.sh`
- 新增离线模型 profile 输出器：
  - `tools/apply_offline_model_profile.py`
  - `run_apply_offline_model_profile.sh`
- 新增 `MiniCPM-V 4.6` 本地 vLLM 启动包装：
  - `run_local_minicpm_v46_vllm.sh`
- 扩展了 `tools/resolve_vlm_runtime.py`
  - 增加 `MiniCPM-V 4.6`
  - 增加 `Qwen2.5-VL-3B`
  - 保留 `gemma3` / 当前基线

---

## 2. 2026-05-18 真机现状确认

通过 `ssh unitree@192.168.100.30` 实测：

- 机器人板端仓库路径是：
  - `~/HongTu/interrupt`
- 当前真机默认配置仍是：
  - `INTERRUPT_AGENT_RUNTIME_MODE=online_full`
  - `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools`
  - `INTERRUPT_AGENT_LOCAL_TEXT_MODEL=qwen2.5:7b`
  - `INTERRUPT_ROBOT_OFFLINE_VLM_MODEL=gemma3:latest`
- 真机 `tools/check_env.py` 可正常运行
- 但 `run_robot_text_brain_smoke.sh "挥挥手"` 当天失败，原因明确为：
  - `http://192.168.100.48:11434` 返回 `connection refused`

这说明当前最大阻塞不是 agent 分流逻辑，而是开发机侧本地模型服务当下没有对机器人提供可用监听。

---

## 3. 建议的实际推进顺序

### 3.1 先恢复当前基线链路

在开发机上先确认本地服务起来：

```bash
cd interrupt
bash ./run_lan_ollama_serve.sh
```

然后在开发机自查：

```bash
cd interrupt
curl http://127.0.0.1:11434/api/tags
bash ./run_local_text_brain_smoke.sh "挥挥手"
```

再到机器人侧一键巡检：

```bash
cd ~/HongTu/interrupt
bash ./run_robot_localized_stack_probe.sh "挥挥手" "你前面有什么？"
```

### 3.2 切 `MiniCPM-V 4.6` 候选档

开发机导出 profile：

```bash
cd interrupt
eval "$(bash ./run_apply_offline_model_profile.sh minicpm_v46 local)"
```

机器人导出 profile：

```bash
cd ~/HongTu/interrupt
eval "$(bash ./run_apply_offline_model_profile.sh minicpm_v46 robot)"
```

如果本机跑 vLLM：

```bash
cd interrupt
export VLM_SERVER_PYTHON_BIN=/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/.venv-qwen-vllm/bin/python
export VLM_SERVER_MODEL_PATH=/path/to/MiniCPM-V-4_6
bash ./run_local_minicpm_v46_vllm.sh
```

### 3.3 切 `Qwen2.5-VL-3B + Qwen3.5-4B` 生产档

开发机：

```bash
cd interrupt
eval "$(bash ./run_apply_offline_model_profile.sh qwen_split_prod local)"
```

机器人：

```bash
cd ~/HongTu/interrupt
eval "$(bash ./run_apply_offline_model_profile.sh qwen_split_prod robot)"
```

建议保持：

- 文本脑：
  - `qwen3.5:4b`
- 视觉：
  - `Qwen2.5-VL-3B-Instruct`

这条线最贴合当前仓库的代码结构，因为：

- 文本工具决策已经在 `local_text_brain` 里
- 视觉入口已经在 `resolve_vlm_runtime.py` / `vision_chat` 链路里

### 3.4 `Cosmos Reason2 2B`

当前只建议保留为实验 profile，不建议直接切成默认主链。

原因：

- 当前仓库还没有专门的空间推理执行接口
- 更适合作为后续 `robot_state / motion_plan_dry_run / spatial_reasoning` 增强层

---

## 4. 现在最值得先验收的命令

开发机：

```bash
cd interrupt
bash ./run_local_text_brain_smoke.sh "挥挥手"
bash ./run_local_offline_vlm_validation.sh "这张图里有什么？"
```

机器人：

```bash
cd ~/HongTu/interrupt
bash ./run_robot_text_brain_smoke.sh "挥挥手"
bash ./run_robot_offline_vlm_validation.sh "你前面有什么？"
bash ./run_robot_localized_stack_probe.sh "开蓝灯" "你前面有什么？"
```

---

## 5. 当前结论

截至 `2026-05-18`，离线本地化推进的关键结论是：

1. `offline_singlebox` 的代码分流面已经具备。
2. 真机当前阻塞点是开发机局域网模型服务未就绪，不是 agent 主逻辑缺失。
3. 下一步最合理的是先恢复基线 `Ollama/qwen2.5:7b + gemma3`，再并行切入：
   - `MiniCPM-V 4.6`
   - `Qwen2.5-VL-3B + Qwen3.5-4B`

---

## 6. MiniCPM-V 4.6 后端实测补充

### 6.1 当前 `vLLM` 版本过旧

本机 `interrupt/.venv-qwen-vllm` 当前是：

- `vllm==0.20.2`
- `transformers==5.8.1`

实测 `openbmb/MiniCPM-V-4.6` 在这套 `vLLM` 上会直接失败：

```text
Model architectures ['MiniCPMV4_6ForConditionalGeneration'] are not supported for now.
```

因此 `MiniCPM-V 4.6 + vLLM + qwen3_coder` 这条路线在当前机器上不是“仓库没接好”，而是“本机 vLLM 版本不支持该架构”。

### 6.2 `transformers serve` 比当前 `vLLM` 更接近可用

实测：

- `transformers serve` 已可用，并提供 OpenAI-compatible `/v1/chat/completions`
- 补装 `accelerate` / `bitsandbytes` 后，MiniCPM 服务能继续进入模型加载流程

说明如果只是想先把 `8000/v1` 跑起来，`transformers serve` 是当前更现实的验证方向。

### 6.3 `MiniCPM-V-4.6-BNB` 当前组合仍有兼容性坑

实测：

```bash
./.venv-qwen-vllm/bin/transformers serve openbmb/MiniCPM-V-4.6-BNB ...
```

会在量化配置解析时报：

```text
AttributeError: 'NoneType' object has no attribute 'get'
```

这更像是当前 `transformers 5.8.1` 与 BNB 仓库格式的兼容问题，而不是显存先撞墙。

### 6.4 已补新版 `vLLM` 隔离实验环境

新增：

- `run_setup_minicpm_vllm_lab.sh`
- `run_local_minicpm_v46_vllm_lab.sh`

用途是：

- 用 `.venv-minicpm-vllm-lab` 单独安装新版 `vLLM`
- 不影响当前已跑通的 `Ollama + gemma3` 基线

实测该环境已安装：

- `vllm=0.21.0`
- `transformers=5.8.1`
- `torch=2.11.0+cu130`

### 6.5 `vLLM 0.21.0` 结论已经很明确

静态检查：

- `qwen3_coder` tool parser 已存在
- `MiniCPMV` 运行时代码只覆盖到 `4.5`

真实启动验证：

```bash
cd interrupt
VLM_SERVER_PORT=8011 ./run_local_minicpm_v46_vllm_lab.sh
```

最终报：

```text
Model architectures ['MiniCPMV4_6ForConditionalGeneration'] are not supported for now.
```

所以现在可以确认：

- `vLLM 0.21.0` 已经足够支持 `qwen3_coder`
- 但仍不足以支持 `MiniCPM-V 4.6`
