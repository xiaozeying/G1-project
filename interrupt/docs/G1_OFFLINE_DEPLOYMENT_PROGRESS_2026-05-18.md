# G1 离线具身部署续推进展

更新时间：2026-05-20

## 0. 2026-05-20 离线验收口径补充

今天把一个容易混淆的点彻底说清了：

- 当前“测试通过”的主语主要还是在线主链
- 不能把在线主链通过直接记成“离线能力已验收完成”

当前真实状态是：

- 仓库已支持 `online_full / offline_singlebox`
- 默认启动仍是 `online_full`
- 当前还没有正式收口成“断网自动切到离线模式”

因此，离线能力是否成立，必须单独验收：

1. 显式切到 `offline_singlebox`
2. 按白名单能力逐项验证
3. 同时验证超界请求会被拒答

明天现场建议直接按：

- `interrupt/docs/OFFLINE_ACCEPTANCE_PLAN_2026-05-20.md`

执行，而不是继续复用在线主路测试结果。

## 0.1 2026-05-20 前门音频启动收口

本轮还把“开机首播偶发没声音”正式收口成启动自愈逻辑。

新增收口点：

- `run_robot_frontgate_session.sh`
  - 等待 Pulse source/sink readiness
  - 自动修正默认 USB sink/source
  - 启动无声 TTS 预热
  - 预热失败自动重试一次
  - 写健康日志到：
    - `logs/audio-startup-health.log`
- `OM1/scripts/external_usb_tts.sh`
  - 新增 `OM1_TTS_PREWARM_ONLY=1` 预热模式

现场实测已经看到：

- `robot pulse source ready`
- `robot pulse sink ready`
- `robot audio startup preflight: ok`
- `audio-startup-health.log -> status=ok`

因此当前“开机首播无声”已不再依赖人工修音频，而是作为前门启动链的一部分自动自愈。

## 0.2 2026-05-20 语音导航收口补充

- `interrupt/src/g1_om1_adapter.py` 现在显式支持 `INTERRUPT_G1_NAV_PROVIDER=g1_3d_nav`
- adapter 会自动解析：
  - `navigation_stack_root`
  - `navigation_bridge_runner`
  - 本地 `/home/zz/HongTu/g1_3d_nav-main`
  - 机器人侧 `/home/unitree/g1_3d_nav`
  - 当前仓库内 `G1Nav2D/run_nav_bridge.sh`
- 新增：
  - `interrupt/run_g1_3d_nav_bridge.sh`
  - `interrupt/bridge/g1_3d_nav_bridge.py`
  - `interrupt/tools/navigation_backend_probe.py` 的 `hongtu_nav_runtime` 输出
  - `interrupt/tools/g1_om1_cli.py start-nav-bridge`

其中 `g1_3d_nav_bridge.py` 对外仍暴露兼容 `interrupt` 现有语音导航链路的 HTTP 接口，但内部允许兼容两类现场数据面：

- `waypoints.yaml + NavigateToPose`
- `*_point.json + move_base`

在 2026-05-20 的机器人现场实测里，已确认当前现网更接近：

- `/home/unitree/g1_3d_nav/maps/waypoints.yaml`
- `ROS2 / NavigateToPose`

因此当前剩余阻塞应视为导航后端环境问题，例如：

- `nav2_msgs` 缺失
- overlay `setup.bash` 引用失效

而不再视为 `interrupt` 语音导航接口层未接好。

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

截至 `2026-05-20`，离线本地化推进的关键结论是：

1. `offline_singlebox` 的代码分流面已经具备。
2. 默认模式仍不是离线，且当前没有自动断网切离线收口。
3. 在线主链通过不能替代离线专项验收。
4. 前门音频启动链已补上自愈与健康日志。
5. 下一步最合理的是按专项文档完成离线验收，再并行继续模型升级验证：
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

### 6.6 `MiniCPM-V 4.6` 主分支 Python 回灌后状态更新

`2026-05-19` 继续验证后，状态已经前进了一大步：

- `vLLM main` 里的 `minicpmv4_6.py` / registry / chat-template 回灌后
- `MiniCPM-V-4.6` 已能被实验环境识别为
  `MiniCPMV4_6ForConditionalGeneration`
- 补完自定义 `load_weights` 后，之前的
  `vit_merger.self_attn.k_proj` 权重映射错误也已经越过去

这意味着当前主阻塞已经不再是“模型架构不支持”或“权重名对不上”。

### 6.7 当前新的真实阻塞

当前真实卡点变成两层：

1. 默认 `flashinfer` sampler 在 warmup 末尾会要求本机存在 `nvcc`
2. 关闭 `flashinfer sampler` 之后，`RTX 4060 8GB` 仍会在 KV cache 预留阶段失败

实测结论：

- `VLLM_USE_FLASHINFER_SAMPLER=0` 是这台机子的 MiniCPM lab 启动前置条件
- 即便如此，在：
  - `max_model_len=4096`
  - `gpu_memory_utilization=0.75`
  - 以及 `0.82`
  这两个实测点上，仍然会报：

```text
ValueError: No available memory for the cache blocks.
```

### 6.8 当前最准确的工程判断

截至 `2026-05-19`，`MiniCPM-V 4.6 + vLLM + qwen3_coder` 这条路线的状态是：

- 仓库接线：已完成
- OpenAI-compatible 入口：已完成
- `vLLM` Python 侧架构/权重适配：基本推进到可加载
- 当前主要阻塞：宿主机 CUDA / `nvcc` 条件与 `8GB` 显存余量

所以这条线现在已经从“框架不支持”推进成了“本机资源与运行参数调优问题”。

### 6.9 `MiniCPM-V 4.6` 已在本机和机器人上完成第一轮真测闭环

`2026-05-19` 继续收缩运行参数后，以下组合已经在开发机 `RTX 4060 8GB`
上成功把服务挂起：

- `max_model_len=2048`
- `gpu_memory_utilization=0.90`
- `VLLM_USE_FLASHINFER_SAMPLER=0`
- `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0`
- `--enforce-eager`
- `--skip-mm-profiling`

在这组参数下，开发机已成功提供：

- `http://127.0.0.1:8011/v1`
- `http://0.0.0.0:8000/v1`

并完成了：

1. `/v1/models` 可访问
2. `/v1/chat/completions` 普通文本回复可用
3. `tool_calls` 可返回 `perform_body_action`

### 6.10 机器人侧 MiniCPM 真机验证结果

机器人 `unitree@192.168.100.30` 实测结果：

1. `run_robot_minicpm_text_brain_smoke.sh "请你挥挥手"` 成功
2. `run_robot_offline_vlm_validation.sh "你前面有什么？"` 成功

其中第二条验证已经从机器人 `/dev/video2` 取图，并通过
`http://192.168.100.48:8000/v1` 的 `MiniCPM-V-4_6` 返回视觉回答。

### 6.11 当前仍需记住的限制

当前这条成功链仍然依赖两点：

1. `.venv-minicpm-vllm-lab` 内已回灌 `vLLM main` 的 `MiniCPM-V 4.6` 相关 Python 补丁
2. 需要使用 8GB 卡安全参数组合，不能直接回退到默认 `vLLM 0.21.0` 启动参数

### 6.12 已开始把回灌过程脚本化

为了减少“重建环境后还要手工 patch `site-packages`”，本轮新增：

- `run_backport_minicpm_v46_vllm_lab.sh`
- `tools/backport_minicpm_v46_vllm_lab.py`

以及：

- `run_setup_minicpm_vllm_lab.sh` 现在会在装完实验环境后尝试自动执行 backport

当前这一步已经验证：

- 对现有 `.venv-minicpm-vllm-lab` 可重复执行
- 脚本本身可 `py_compile`

不过当前仍属于“半自动恢复”：

- patch 逻辑已进仓库
- `minicpmv4_6.py` 已 vendored 到
  `interrupt/vendor/vllm_backports/minicpmv4_6.py`
- backport 脚本会优先使用仓库内 vendored 源文件

### 6.13 `MiniCPM-V 4.6` 冷启动恢复已完成端到端验证

`2026-05-19` 新增并验证：

- `run_validate_minicpm_v46_vllm_coldstart.sh`
- `tools/verify_minicpm_v46_vllm_backport.py`

完整冷启动回归已真实跑通：

1. 新建临时 `venv`
2. 安装 `vLLM 0.21.0`
3. 自动执行 `MiniCPM-V 4.6` backport
4. 自动验证 `registry / chat-template / minicpmv / minicpmv4_6` 关键补丁位

也就是说，`MiniCPM-V 4.6` 这条链已经从“半自动恢复”推进到了：

- 仓库自带 backport 源文件
- 可脚本化冷启动恢复
- 已有端到端冷启动验证结果

### 6.14 `offline_singlebox` 验收脚本已补齐

本轮新增：

- `tools/offline_singlebox_acceptance.py`
- `run_local_offline_singlebox_acceptance.sh`
- `run_robot_offline_singlebox_acceptance.sh`

默认会验证：

1. `offline_singlebox` 运行时配置
2. 允许能力的本地文本意图：
   - 动作
   - 灯光
   - 视觉问句
   - 地点列表
   - 导航
   - 记住当前位置
3. 超界请求边界：
   - 天气
   - 新闻
   - 开放闲聊
4. 无副作用执行链：
   - 地点列表查询
   - 视觉问答执行

### 6.15 `offline_singlebox` 当前真机剩余缺口

机器人 `unitree@192.168.100.30` 以
`INTERRUPT_OFFLINE_PROFILE=minicpm_v46`
运行验收后，当前还剩两条基础设施级缺口：

1. 导航 bridge 未在 `http://localhost:5000` 监听
   - `navigation_backend_probe.py` 明确报 `connection refused`
2. 机器人宿主机当前没有 `/dev/video*`
   - 验收脚本中的 `vision_exec` 因 `camera_not_found` 失败

这两条已经不是文本脑或验收脚本逻辑问题，而是：

- 导航本地服务未拉起
- 当前 shell 环境下没有可用相机设备

### 6.16 安全中间层继续从 `agent.py` 拆出

本轮新增：

- `src/safe_action_middleware.py`

已将以下职责从 `agent.py` 抽成独立域层：

1. 动作前视安全预检
2. 导航前视安全预检
3. 视觉抓图失败 / 安全拒绝的统一中间结果封装

当前 `agent.py` 保留为更薄的一层：

- 负责把中间层结果转换成当前会话所需的本地化回复
- 执行动作 / 导航前只调用中间层预检
