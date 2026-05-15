# 本机到 G1 的本地化部署执行手册

更新时间：2026-05-14

这份手册基于：

- `/home/zz/下载/robot_voice_arch_deep_analysis.md.pdf`
- `interrupt/docs/VOICE_VISION_SAFE_MIDDLEWARE_ARCH_2026-05-12.md`
- `interrupt/docs/AQ_WRAPUP_2026-05-13.md`

目标不是重新讨论架构，而是把“先本机验证，再推到 G1”收成一条能直接执行的路径。

## 0. 当前本地化状态

截至 2026-05-14，这条链已经分成两部分：

- `VLM / 视觉观察`
  - 已有可用离线路径
  - 本机 `Ollama + gemma3:latest` 可作为当前稳定基线
  - G1 已能通过局域网消费这条离线 VLM
- `主对话 Agent / 房间会话`
  - 还没有完全离线
  - `interrupt/src/agent.py` 当前仍固定使用 `google.realtime.RealtimeModel`
  - 因此正式房间会话依然依赖 Gemini native audio

这意味着：

1. `视觉本地化` 已经进入可测试、可部署阶段
2. `主对话本地化` 当前还处于“本机离线评测链已具备、正式 interrupt 会话未切换”的阶段

## 1. 对比结论

和深度分析文档相比，仓库当前实现已经基本落在正确方向上：

- 上层语音会话：已有 `LiveKit + interrupt/src/agent.py`
- 单次视觉观察：已有 `interrupt/src/vision_chat.py`
- 安全中间层雏形：已有 `interrupt/src/safe_action_gateway.py`
- G1/OM1 执行适配：已有 `interrupt/src/g1_om1_adapter.py`

当前最主要差异不是“没有实现”，而是“部署入口仍然偏手工”：

- 本机默认入口过去固定偏向 `ollama + gemma3`
- Qwen2.5-VL 路线已经有脚本，但需要单独切换
- 机器人侧测试要求显式配置 OpenAI-compatible 后端，否则容易误回退到在线链路

所以这次收口重点是：

1. 本机入口自动优先尝试本地离线 VLM
2. 本机离线不可用时，`localized stack` 允许回退到当前在线视觉，便于继续联调
3. 机器人侧离线验证坚持要求显式的离线/OpenAI-compatible 后端

## 2. 当前默认选择逻辑

新增的 `tools/resolve_vlm_runtime.py` 会按下面顺序解析视觉后端。

本机 `local` 模式：

1. 显式环境变量覆盖：`INTERRUPT_VLM_PROVIDER / BASE_URL / MODEL`
2. `Qwen2.5-VL-7B-Instruct @ http://127.0.0.1:8000/v1`
3. `Qwen2.5-VL-3B-Instruct @ http://127.0.0.1:8000/v1`
4. `gemma3:latest @ http://127.0.0.1:11434/v1`
5. 若允许在线回退，则回到当前 `config/.env.local` 中的已配置 provider

机器人 `robot` 模式：

1. 显式环境变量覆盖
2. 当前机器人环境里已配置的 provider
3. 不允许默默回退在线视觉；若离线/OpenAI-compatible 后端不可达则直接失败

## 3. 本机执行顺序

### 3.1 先做基础检查

```bash
cd interrupt
./.venv/bin/python tools/check_env.py
```

### 3.2 验证“本机优先、本地化优先”的解析结果

```bash
./.venv/bin/python tools/resolve_vlm_runtime.py --mode local --allow-online-fallback
```

如果本机离线服务已启动，预期会优先选中：

- `Qwen2.5-VL-7B-Instruct`
- 或 `Qwen2.5-VL-3B-Instruct`
- 或 `gemma3:latest`

如果都未启动，则会回退到当前在线 provider，方便继续联调语音主线。

### 3.3 做本机 localized stack 烟测

```bash
./run_local_localized_stack_probe.sh
```

这个脚本会输出：

- 解析后的 provider/source/reason
- 环境检查
- VLM backend probe
- 视觉烟测
- 安全中间层动作烟测

### 3.4 只做“纯离线 VLM”验证

```bash
./run_local_offline_vlm_validation.sh "这张图里有什么？"
```

这个命令现在会强制要求本地离线/OpenAI-compatible 后端可达；若本机没起服务，会直接失败，不再假装通过。

## 4. 机器人执行顺序

机器人侧推荐保持：

- 语音入口
- 摄像头采集
- 安全中间层
- 动作执行

离线 VLM 则优先放在：

- 本地开发机
- 或局域网 GPU 主机

机器人侧最小验证命令：

```bash
cd interrupt
./run_robot_offline_vlm_validation.sh "你前面有什么？"
```

要求提前设置：

```bash
export INTERRUPT_VLM_PROVIDER=openai_compatible
export INTERRUPT_VLM_BASE_URL=http://<LAN_GPU_HOST>:8000/v1
export INTERRUPT_VLM_MODEL=Qwen2.5-VL-7B-Instruct
```

如果机器人侧没有这些环境变量，或者目标服务不可达，脚本会直接失败，这正是我们希望的行为。

## 5. 推荐落地策略

结合文档和现有机器条件，当前建议仍然是：

1. 本机先跑通 `localized stack`
2. 本机离线服务优先尝试 `Qwen2.5-VL`
3. 若本机显存不够，则先用 `gemma3` 保持可验证基线
4. 机器人只消费外部 VLM 服务，不在 Orin NX 上直接承担大视觉模型

这条路径最符合当前代码状态，也最符合文档里“混合部署 + 安全中间层 + 先本地后实体”的主线。

## 6. 本地文本 LLM 推进路径

如果下一步要继续推进“除了 VLM 以外的大模型也尽量本地化”，当前最适合先走的是本机文本评测链，而不是直接改正式房间 agent。

原因：

- `interrupt` 正式 agent 还绑着 Gemini realtime 音频模型
- 但仓库已经有 `OM1 + Ollama` 的离线文本动作评测链
- 这条链足够先验证：
  - 文本对话质量
  - 工具/动作调用稳定性
  - 能力边界是否诚实

统一入口：

```bash
cd interrupt
./run_local_text_offline_eval.sh batch
```

默认行为：

- 探测本机 `http://127.0.0.1:11434`
- 默认使用 `qwen2.5:7b`
- 跑 `offline_eval/run_phase1_batch.py`
- 输出结果 CSV 和 runtime log

如果只想先开交互式本地文本 runtime：

```bash
cd interrupt
./run_local_text_offline_eval.sh interactive
```

然后在另一个终端发送文本：

```bash
python OM1/scripts/send_mock_input.py "挥挥手" --port 8879
```

这一步的意义不是替代正式前门，而是先把“主对话脑子”从 Gemini 上拆下来做第一轮本机离线验证。

### 2026-05-15 适配层推进状态

`interrupt` 侧已经新增了本地文本脑适配层和 smoke 入口：

- `src/local_text_brain.py`
- `tools/local_text_brain_smoke.py`
- `run_local_text_brain_smoke.sh`
- `run_lan_ollama_serve.sh`
- `run_robot_text_brain_smoke.sh`

同时，正式房间 agent 已新增显式 backend 配置：

- `INTERRUPT_AGENT_BACKEND=gemini_realtime`
- `INTERRUPT_AGENT_BACKEND=local_text_ollama`
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=disabled`
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools`
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_all`

当前状态：

- 代码层已经能区分：
  - 正式房间会话 backend
  - 本地文本脑 smoke/backend probe
- 正式房间会话已具备“混合接入”能力：
  - `gemini_realtime + prefer_tools`
    - 实时语音壳仍由 Gemini 负责
    - 动作/视觉/导航类工具决策可优先转交本地文本脑
  - `gemini_realtime + prefer_all`
    - 在 `prefer_tools` 基础上，允许本地文本脑接普通文本回复
    - 适合下一阶段灰度，不建议一开始直接全量默认
- 本机 `Ollama` 已恢复可用，但有一个关键前提：
  - 如果只监听 `127.0.0.1:11434`，G1 会得到 `connection refused`
  - 必须用 `OLLAMA_HOST=0.0.0.0:11434` 对局域网开放
- 2026-05-15 已完成一轮真机 smoke：
  - 开发机 `192.168.100.48` 上 `qwen2.5:7b` 的 `/api/chat` 返回 `200`
  - G1 上 `tools.agent_backend_probe` 可确认 `local_text_reachable=true`
  - G1 上 `run_robot_text_brain_smoke.sh "挥挥手"` 成功返回 `perform_body_action`
  - G1 上 `run_robot_text_brain_smoke.sh "帮我看看前面有什么"` 成功返回 `ask_camera_vision`

因此，当前阻塞点已经从“本机服务异常”推进成：

- 正式 `LiveKit room agent` 已完成本地文本脑的混合接入
- 但当前默认仍更适合使用 `prefer_tools`
- 若要继续扩大本地化比例，下一步应灰度测试 `prefer_all`

推荐的真机复测顺序：

```bash
cd interrupt
bash ./run_lan_ollama_serve.sh
```

然后在 G1 上：

```bash
cd ~/HongTu/interrupt
bash ./run_robot_text_brain_smoke.sh "挥挥手"
bash ./run_robot_text_brain_smoke.sh "帮我看看前面有什么"
```

### 2026-05-14 本机小样本结论

使用 `offline_eval/phase1_local_smoke_subset.csv` 的 5 个代表性 case 做过一轮快速对比：

- `qwen2.5:7b`
  - `request_success: 3/5`
  - 动作类和边界类基本可用：
    - `挥挥手`
    - `把灯调成蓝色`
    - `你能导航去电梯吗`
  - 开放问答/视觉占位类仍不稳定：
    - `你是谁`
    - `帮我看看前面有什么`
- `gemma3:latest`
  - 当前 `Ollama` 版本下对这条工具调用评测链返回：
    - `does not support tools`
  - 不适合作为当前本地文本动作链的主模型候选

因此，当前更推荐的推进顺序是：

1. 继续以 `qwen2.5:7b` 作为本地文本主模型评测基线
2. `gemma3` 保留给视觉链，不作为这条文本工具调用主线候选
3. 等文本链稳定后，再考虑把 `interrupt/src/agent.py` 的正式房间会话从 Gemini realtime 迁出去
