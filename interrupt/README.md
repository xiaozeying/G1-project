# interrupt

`interrupt` 是面向 G1 机器人现场部署的一套语音交互运行时。  
它不是单一 agent 脚本，而是一个由前门唤醒、LiveKit 房间会话、在线/离线模型路由、G1/OM1 执行适配、安全中间层、视觉能力、部署恢复脚本共同组成的系统。

当前最准确的工程定位可以概括为：

- 面向现场的多语言机器人语音交互中台
- 上接 `LiveKit + Gemini realtime / local text brain / local VLM`
- 下接 `G1 / OM1 / 导航桥 / TTS / RTC`
- 中间用状态机、音频防回灌、安全门和恢复工具，把“能跑”收口成“能长期稳定跑、能恢复、能换机”

项目当前最新收口和现场口径，以 [PROJECT_PROGRESS.md](./PROJECT_PROGRESS.md) 和 `docs/` 下文档为准。

## 1. 当前操作口径

如果你现在的目标只是把机器人切回可用对话链路，请优先记住这三件事：

- 默认推荐模式是 `online`
- `offline` 入口保留，但当前仍未开发完整，只能视为实验链路
- 现场切换有两层入口：
  - 非容器运行面：`./robot_dialogue_mode.sh`
  - 统一容器运行面：`./scripts/mode.sh` 和 `./scripts/recover.sh`

两者职责不要混用：

- `./robot_dialogue_mode.sh` 只负责宿主机服务形态，核心是同步 `.env.local` 并重启 `interrupt-frontgate.service`
- `./scripts/mode.sh` 只负责统一容器形态，核心是同步 `.env.local` 并重建 `voice-stack` 容器入口
- `./scripts/recover.sh` 用于新机恢复、故障恢复、重拉整套 `voice-stack`

常用命令：

```bash
./robot_dialogue_mode.sh online
./robot_dialogue_mode.sh offline
./robot_dialogue_mode.sh status
```

统一容器运行面常用命令：

```bash
cp deploy/compose/env.voice-stack.example deploy/compose/env.voice-stack
./scripts/recover.sh online
./scripts/mode.sh offline
./scripts/mode.sh status
```

当前固定口径：

- `online` = 稳定生产链路
  - `INTERRUPT_AGENT_RUNTIME_MODE=online_full`
  - `INTERRUPT_AGENT_BACKEND=gemini_realtime`
  - `INTERRUPT_DIALOGUE_MODE_STABILITY=production_fixed`
- `offline` = 实验链路
  - `INTERRUPT_AGENT_RUNTIME_MODE=offline_singlebox`
  - `INTERRUPT_AGENT_BACKEND=local_text_ollama`
  - `INTERRUPT_DIALOGUE_MODE_STABILITY=experimental_incomplete`

## 2. 当前前门优化状态

当前仓库已经固定了前门三语优化的一期收口：

- 唤醒后并发拉房，不再等待自我介绍结束再建房
- 自我介绍保留，但不阻塞房间初始化
- room ready 后只播报一条同语言引导语
- 用户发言需命中显式前缀看门狗后才允许进入 room-agent
- 问什么语言，优先按什么语言回复

相关执行文档：

- [TRILINGUAL_FRONTGATE_DIALOG_OPTIMIZATION_EXECUTION_PLAN_2026-06-05.md](./docs/TRILINGUAL_FRONTGATE_DIALOG_OPTIMIZATION_EXECUTION_PLAN_2026-06-05.md)

## 3. 统一容器口径

当前仓库已经有两层容器化口径：

1. 一期拆分：

- `wakeword-frontgate`
- `online-brain`

2. 统一 voice-stack：

- `wakeword-frontgate`
- `online-brain`
- `offline-brain`
- `ollama`

这套统一编排的目标不是宣称 `offline` 已经完整生产化，而是把：

- 模式切换
- 容器恢复
- 一键部署
- 开机自启

全部收口到同一套命令接口上。

相关文档与部署文件：

- [WAKEWORD_ONLINE_SPLIT_CONTAINERS_2026-06-05.md](./docs/WAKEWORD_ONLINE_SPLIT_CONTAINERS_2026-06-05.md)
- [docker-compose.robot.wakeword-online.yaml](./deploy/compose/docker-compose.robot.wakeword-online.yaml)
- [deploy_robot_wakeword_online_over_ssh.sh](./deploy/compose/deploy_robot_wakeword_online_over_ssh.sh)
- [docker-compose.voice-stack.yaml](./deploy/compose/docker-compose.voice-stack.yaml)
- [env.voice-stack.example](./deploy/compose/env.voice-stack.example)
- [deploy_robot_voice_stack_over_ssh.sh](./deploy/compose/deploy_robot_voice_stack_over_ssh.sh)
- [interrupt-voice-stack-compose.service](./deploy/systemd/user/interrupt-voice-stack-compose.service)
- [scripts/mode.sh](./scripts/mode.sh)
- [scripts/recover.sh](./scripts/recover.sh)

统一容器运行面的最小闭环是：

```bash
cp deploy/compose/env.voice-stack.example deploy/compose/env.voice-stack
./scripts/recover.sh online
./scripts/mode.sh offline
./deploy/compose/deploy_robot_voice_stack_over_ssh.sh --activate
```

## 4. 总体版图

```text
用户
  -> 前门唤醒（wakeword frontgate）
  -> 唤醒确认 / 灯效 / 麦克风接管
  -> LiveKit 房间建立
  -> room-agent / rtc-endpoint 进入房间
  -> 语音转写 / 打断检测 / 回声抑制
  -> 决策层
       - 在线 Gemini realtime
       - 本地 local_text_brain（Ollama / OpenAI-compatible / vLLM / sglang）
  -> 工具执行层
       - 动作 / LED / speak
       - 视觉问答
       - 天气 / 新闻
       - 导航点查询 / 导航 / 记点
  -> G1/OM1 / 导航桥 / 外部脚本
  -> RTC 播报或本地 USB TTS 播报
```

一句话总结：

```text
frontgate + room-agent + rtc-endpoint + local/online brain + G1/OM1 adapter + nav bridge + recovery tooling
```

## 5. 项目目标

`interrupt` 主要解决的是以下问题：

- 让机器人能以普通话、粤语、英语稳定进入会话
- 让用户可以打断机器人，而机器人不会因为被打断而状态错乱
- 让机器人既能走在线实时链，也能在现场切到本地离线链
- 让动作、灯光、视觉、导航这些能力可统一暴露给 agent
- 让现场部署不依赖聊天记录手敲命令，而能通过脚本和服务恢复

它的重点并不是“聊天能力本身”，而是：

- 会话切换
- 音频链稳定
- 自播保护
- 状态机收口
- 跨设备恢复

## 6. 核心目录地图

### 3.1 运行时代码

- `src/`
  - 系统主运行时
  - 包含配置、agent、RTC 端点、机器人适配、VLM、本地文本脑、安全逻辑

### 3.2 现场工具与验收

- `tools/`
  - smoke test
  - backend probe
  - frontgate/session 工具
  - offline acceptance
  - 诊断与恢复辅助脚本

### 3.3 导航桥

- `bridge/`
  - 导航后端协议桥接
  - 当前核心是 `g1_3d_nav_bridge.py`

### 3.4 部署与恢复

- `deploy/compose/`
  - Dockerfile
  - 本地 compose
  - 机器人 compose
  - SSH 推送部署
- `deploy/systemd/`
  - systemd 服务定义
- `restore_assets/om1/`
  - 关键恢复脚本资产，尤其是外接 USB TTS 路径

### 3.5 文档与口径

- `docs/`
  - 工程边界文档
  - 现场恢复文档
  - 部署计划
  - 验收口径
  - 迁移与手册

## 7. 核心分层

### 4.1 配置层

配置入口在 [src/settings.py](./src/settings.py)。

职责：

- 从 `config.yaml`、`.env.local`、`.env` 读取配置
- 统一标准化 backend/runtime/provider 枚举
- 把配置整理成 `AppSettings`

主要配置对象：

- `LiveKitConfig`
- `AgentConfig`
- `WebConfig`
- `FeedbackConfig`
- `VisionConfig`
- `ConsoleConfig`
- `RtcEndpointConfig`
- `IntegrationConfig`

配置源优先级总体上是：

```text
env 覆盖 yaml 默认值
```

### 4.2 传输与会话层

LiveKit 是整套系统的传输骨架，入口在 [src/livekit_room.py](./src/livekit_room.py)。

职责：

- 生成 room token
- 建房
- dispatch room-agent
- 列出房间参与者
- 为网页端、前门房间、rtc-endpoint 提供统一房间入口

### 4.3 决策层

核心在 [src/agent.py](./src/agent.py) 和 [src/local_text_brain.py](./src/local_text_brain.py)。

包含两条路线：

- 在线实时脑：`Gemini realtime`
- 本地文本脑：`local_text_brain`

在线脑更偏完整语音会话；本地脑更偏：

- 优先判断是否应触发工具
- 本地能力白名单内尽量就地执行
- 超出能力范围时诚实降级

### 4.4 机器人执行层

统一适配在 [src/g1_om1_adapter.py](./src/g1_om1_adapter.py)。

职责：

- 统一调 OM1 Python 环境
- 执行动作命令
- 灯光控制
- speak
- 导航相关命令
- 管理导航后端 provider 差异

这是 `interrupt` 与外部 G1/OM1 资产之间最关键的边界层。

### 4.5 音频与 RTC 层

核心文件：

- [src/rtc_endpoint.py](./src/rtc_endpoint.py)
- [src/speech_feedback.py](./src/speech_feedback.py)
- [src/speech_loop_guard.py](./src/speech_loop_guard.py)
- [src/tts_mute_state.py](./src/tts_mute_state.py)
- [src/cantonese_tts.py](./src/cantonese_tts.py)

职责：

- 机器人麦克风发布到房间
- 房间远端音频播放
- 回声消除
- 麦克风 ducking
- 本地转写
- 自播保护
- assistant 回复本地镜像播报
- 粤语专用 TTS 分支
- 前门粤语播报、前门 room ready 粤语播报、对话粤语本地播报统一固定走 `src/cantonese_tts.py`，不回退 OM1 机械粤语

### 4.6 前门与唤醒层

核心文件：

- [tools/wakeword_session_frontgate.py](./tools/wakeword_session_frontgate.py)
- [src/om1_wakeword_gate.py](./src/om1_wakeword_gate.py)
- [src/wakeword_runtime.py](./src/wakeword_runtime.py)
- [src/mock_wakeword.py](./src/mock_wakeword.py)

职责：

- 待机监听唤醒词
- 播放唤醒确认
- 切换灯效
- 拉起房间会话
- 释放和接管音频设备
- 在真实 wakeword 工厂不可用时回退到 mock factory

### 4.7 视觉与安全层

核心文件：

- [src/vision_chat.py](./src/vision_chat.py)
- [src/safe_action_gateway.py](./src/safe_action_gateway.py)
- [src/safe_action_middleware.py](./src/safe_action_middleware.py)

职责：

- 单帧前视图问答
- 结构化视觉观察
- 动作安全判断
- 导航前安全判断

### 4.8 集成扩展层

核心文件：

- [src/integrations.py](./src/integrations.py)

职责：

- MCP stdio/HTTP 服务对接
- 输出当前集成摘要

## 8. 主运行模式

### 5.1 在线主链

```text
前门唤醒
  -> frontgate
  -> room-agent
  -> Gemini realtime
  -> tool calls / direct reply
  -> RTC 播报
  -> idle 超时后回待机
```

特点：

- 语音会话最完整
- 实时交互自然
- 强依赖外部在线模型

### 5.2 离线单机链

```text
前门唤醒
  -> frontgate room session
  -> rtc-endpoint
  -> local_text_brain
  -> 本地允许工具白名单
  -> 本地/局域网播报
```

当前仓库收口文档里，`offline_singlebox + local_text_ollama + prefer_tools` 已被作为重点现场口径之一。

特点：

- 本地能力优先
- 离线白名单更明确
- 主要用于现场抗网络依赖

### 5.3 网页演示链

核心文件：

- [dev_server.py](./dev_server.py)
- [web/main.js](./web/main.js)

流程：

```text
浏览器
  -> /defaults
  -> /token
  -> ensure_room_ready()
  -> connect LiveKit
  -> 打开麦克风
  -> 收发转写与远端音频
```

## 9. 关键入口文件

### 6.1 room-agent

入口脚本：[run_room_agent.sh](./run_room_agent.sh)

作用：

- 激活 Python 环境
- 装载 env
- 按需拉起导航桥
- 清理代理设置
- 设置 agent 负载参数
- 最终执行 `python -m src.agent start`

### 6.2 机器人前门

入口脚本：[run_robot_frontgate_session.sh](./run_robot_frontgate_session.sh)

作用：

- 装载现场 `.env`
- 强制单机本地文本链 loopback
- 选择 OM1 Python
- 设定 wakeword factory
- 修复 Pulse source/sink
- 音频预热与健康日志
- 最终拉起前门唤醒链

### 6.3 前门房间会话

入口脚本：[run_frontgate_room_session.sh](./run_frontgate_room_session.sh)

作用：

- 确保本地文本后端就绪
- 解析可用 VLM backend
- 拉起 `tools/frontgate_room_session.py`

### 6.4 RTC 端点

入口脚本：[run_robot_rtc_endpoint.sh](./run_robot_rtc_endpoint.sh)

作用：

- 启动机器人 RTC 参与者
- 发布麦克风
- 播放远端音频
- 可自动重派发 agent

## 10. `agent.py` 的职责细分

[src/agent.py](./src/agent.py) 是系统编排中枢，不只是一个工具定义文件。

它实际承担了这些职责：

- 创建 `InterruptAssistant`
- 绑定 function tools
- 管理会话事件
- 跟踪用户语言偏好
- 过滤低价值转写
- 识别并忽略机器人自己的回声
- 做 fastpath 本地命令处理
- 管理离线单机模式白名单
- 触发本地工具前置播报
- 管理最近意图窗口，避免模型乱触发旧意图
- 将 assistant 文本镜像到 OM1 或 RTC

内含的 function tools 主要包括：

- `set_led_color`
- `perform_body_action`
- `check_action_safety`
- `check_navigation_safety`
- `execute_robot_command_text`
- `list_saved_locations`
- `navigate_to_saved_location`
- `remember_current_location`
- `get_weather`
- `get_news`
- `ask_camera_vision`
- `observe_camera_scene`

工程重点不是“tool 多不多”，而是这些工具的执行都被前后加了很多保护：

- recent intent guard
- duplicate suppression
- low-information transcript filter
- self-echo guard
- pre-ack suppression
- conflicting failure suppression

## 11. 模块依赖图

下面是逻辑依赖图，不是 Python import 的逐文件完整图，而是架构视角的主依赖关系。

```text
config.yaml / .env / .env.local
  -> src/settings.py

src/settings.py
  -> src/agent.py
  -> src/rtc_endpoint.py
  -> dev_server.py
  -> tools/*

src/livekit_room.py
  -> dev_server.py
  -> tools/frontgate_room_session.py
  -> src/rtc_endpoint.py

src/agent.py
  -> src/g1_om1_adapter.py
  -> src/local_text_brain.py
  -> src/vision_chat.py
  -> src/weather.py
  -> src/news.py
  -> src/safe_action_gateway.py
  -> src/safe_action_middleware.py
  -> src/speech_feedback.py
  -> src/speech_loop_guard.py
  -> src/integrations.py
  -> src/navigation_intents.py

src/speech_feedback.py
  -> src/cantonese_tts.py
  -> src/g1_om1_adapter.py
  -> src/speech_loop_guard.py

src/rtc_endpoint.py
  -> src/livekit_room.py
  -> src/speech_loop_guard.py
  -> src/tts_mute_state.py
  -> tools/local_funasr_worker.py

tools/wakeword_session_frontgate.py
  -> src/wakeword_runtime.py
  -> src/g1_om1_adapter.py
  -> src/speech_loop_guard.py
  -> run_frontgate_room_session.sh

src/wakeword_runtime.py
  -> src/om1_wakeword_gate.py
  -> src/mock_wakeword.py

src/g1_om1_adapter.py
  -> OM1 scripts
  -> navigation bridge
  -> g1_3d_nav runtime

bridge/g1_3d_nav_bridge.py
  -> waypoint files
  -> ROS1 / ROS2 action
  -> HTTP bridge API
```

## 12. 启动时序图

### 9.1 现场前门主链

```text
systemd / operator
  -> run_robot_frontgate_session.sh
  -> tools/wakeword_session_frontgate.py
  -> WakeWordGate.listen()
  -> 命中唤醒
  -> 本地 wake ack + LED
  -> run_frontgate_room_session.sh
  -> tools/frontgate_room_session.py
  -> ensure room ready
  -> 启动或重启 run_room_agent.sh
  -> 启动或重启 run_robot_rtc_endpoint.sh
  -> room-agent 进入房间
  -> rtc-endpoint 进入房间
  -> room-agent 发送或接收 room_ready_ack
  -> 用户开始正式会话
  -> idle / max-duration / signal file 触发退出
  -> 回到 frontgate 待机
```

### 9.2 room-agent 启动链

```text
run_room_agent.sh
  -> 读取 env
  -> 处理代理与 NO_PROXY
  -> 按需 ensure_navigation_bridge()
  -> python -m src.agent start
  -> AgentServer
  -> entrypoint(JobContext)
  -> _build_session()
  -> session.start(room, InterruptAssistant)
  -> 绑定用户/assistant/转写/工具事件
```

### 9.3 rtc-endpoint 启动链

```text
run_robot_rtc_endpoint.sh
  -> 读取 env
  -> resolve_vlm_runtime.py
  -> python -m src.rtc_endpoint
  -> RobotRtcEndpoint
  -> connect room
  -> publish microphone
  -> subscribe audio
  -> 本地转写与 AEC/ducking 生效
```

## 13. 在线链 / 离线链对照版图

| 维度 | 在线链 `online_full` | 离线链 `offline_singlebox` |
| --- | --- | --- |
| 主脑 | Gemini realtime | local_text_brain |
| 交互重心 | 完整实时语音会话 | 本地工具优先决策 |
| 模型依赖 | 云端实时模型 | Ollama / OpenAI-compatible / 本地服务 |
| 工具策略 | 模型 + tools | 白名单工具优先 |
| 天气/新闻 | 可直接查询 | 通常视口径决定是否允许 |
| 视觉 | 在线兼容或本地兼容 VLM | 优先本地/局域网 VLM |
| 会话体验 | 自然、连续 | 更强调稳和收口 |
| 网络依赖 | 高 | 低到中 |
| 典型现场用途 | 演示完整交互 | 断网/弱网/单机模式 |

### 10.1 在线主链图

```text
user speech
  -> rtc/frontgate transcript
  -> Gemini realtime session
  -> tool call or direct reply
  -> RTC transport
  -> robot RTC playback
```

### 10.2 离线主链图

```text
user speech
  -> rtc/frontgate transcript
  -> local_text_brain
  -> allowed local tool call
  -> G1/OM1 / nav / local VLM
  -> local reply fallback or RTC reply
```

### 10.3 现场快速切换

机器人现场推荐只通过切换脚本改模式，不再手改 `.env.local`。

如果当前目录就是 `interrupt/`：

```bash
./robot_dialogue_mode.sh online
./robot_dialogue_mode.sh offline
./robot_dialogue_mode.sh status
```

如果当前使用统一容器运行面：

```bash
cp deploy/compose/env.voice-stack.example deploy/compose/env.voice-stack
./scripts/recover.sh online
./scripts/mode.sh offline
./scripts/mode.sh online
./scripts/mode.sh status
```

如果当前目录是仓库上一级：

```bash
./interrupt/robot_dialogue_mode.sh online
./interrupt/robot_dialogue_mode.sh offline
./interrupt/robot_dialogue_mode.sh status
```

当前脚本会把“模式变量”和“前门稳定变量”一起原子写入并重启 `interrupt-frontgate.service`，避免只切到一半。

统一容器运行面则会：

- 通过 `switch_dialogue_mode.sh` 更新 `.env.local`
- 保持 `online-brain / offline-brain / ollama` 常驻
- 只让 `wakeword-frontgate` 按当前模式把唤醒事件路由到对应 brain
- `recover.sh` 负责整套容器恢复，`mode.sh` 负责日常 online/offline 切换

当前现场口径请固定理解为：

- `online` 是当前稳定生产链路，也是现场默认推荐入口
- `offline` 仍是实验链路，切换入口保留，但能力面还未开发完整，不应当视为等价生产链

在线链固定为：

- `INTERRUPT_AGENT_RUNTIME_MODE=online_full`
- `INTERRUPT_AGENT_BACKEND=gemini_realtime`
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=disabled`
- `INTERRUPT_ASSISTANT_AUDIO_MODE=transport_only`
- `INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=transport_only`
- `INTERRUPT_RTC_SUBSCRIBE_AUDIO=1`
- `INTERRUPT_RTC_AEC_ENABLED=1`

离线实验链当前配置为：

- `INTERRUPT_AGENT_RUNTIME_MODE=offline_singlebox`
- `INTERRUPT_AGENT_BACKEND=local_text_ollama`
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools`
- `INTERRUPT_ASSISTANT_AUDIO_MODE=om1_mirror`
- `INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=om1_mirror`
- `INTERRUPT_RTC_SUBSCRIBE_AUDIO=0`
- `INTERRUPT_RTC_AEC_ENABLED=1`

两种模式都会强制保留以下前门收口值：

- `INTERRUPT_ENABLE_FRONTGATE_IDLE_SESSION_EXIT=1`
- `INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS=180000`
- `INTERRUPT_FRONTGATE_SESSION_TIMEOUT=0`
- `INTERRUPT_FRONTGATE_ROOM_MAX_DURATION_S=0`
- `INTERRUPT_AGENT_JOB_EXECUTOR_TYPE=thread`

如果你只是想立即切回当前可用在线链路，直接执行：

```bash
./robot_dialogue_mode.sh online
```

现场验收建议至少做一轮：

```bash
./robot_dialogue_mode.sh online
./robot_dialogue_mode.sh offline
./robot_dialogue_mode.sh online
./robot_dialogue_mode.sh status
```

## 14. 关键环境变量全表

下面按功能域给出当前仓库最重要的一批环境变量。不是“系统中出现过的每一个 env 名字”，而是架构和部署最需要掌握的主变量。

### 11.1 LiveKit 与基础连接

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `LIVEKIT_URL` | LiveKit WebSocket 地址 | `ws://127.0.0.1:7880` |
| `LIVEKIT_API_KEY` | LiveKit API key | `devkey` |
| `LIVEKIT_API_SECRET` | LiveKit API secret | `secret` |
| `GEMINI_API_KEY` | Gemini API key | 现场私有值 |

### 11.2 Agent 主模式

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_AGENT_BACKEND` | 主 agent backend | `gemini_realtime` / `local_text_ollama` / `local_text_openai_compatible` |
| `INTERRUPT_AGENT_RUNTIME_MODE` | 运行模式 | `online_full` / `offline_singlebox` |
| `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE` | 本地文本脑决策模式 | `disabled` / `shadow` / `prefer_tools` / `prefer_all` |
| `INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER` | 本地文本后端类型 | `ollama` / `openai_compatible` |
| `INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL` | 本地文本服务地址 | `http://127.0.0.1:11434` |
| `INTERRUPT_AGENT_LOCAL_TEXT_MODEL` | 本地文本模型 | `qwen2.5:7b` |
| `INTERRUPT_AGENT_LOCAL_TEXT_API_KEY` | OpenAI-compatible 本地服务鉴权 | 可空 |

### 11.3 打断与会话控制

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_MIN_ENDPOINTING_DELAY_MS` | 最小收尾延迟 | `300` |
| `INTERRUPT_MAX_ENDPOINTING_DELAY_MS` | 最大收尾延迟 | `1200` |
| `INTERRUPT_MIN_INTERRUPTION_DURATION_MS` | 最小打断时长 | `80` |
| `INTERRUPT_FALSE_INTERRUPTION_TIMEOUT_MS` | 假打断超时 | `500` |
| `INTERRUPT_USER_AWAY_TIMEOUT_MS` | 用户离开超时 | `300000` 或现场覆盖值 |

### 11.4 前门链

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_WAKE_WORD_FACTORY` | 唤醒工厂 | `src.om1_wakeword_gate:factory` |
| `WAKEWORD_SCRIPT` | 真实唤醒词脚本路径 | `/home/unitree/g1-wakeword/wakeword_adaptive.py` |
| `INTERRUPT_FRONTGATE_SESSION_COMMAND` | 唤醒后启动会话命令 | `run_frontgate_room_session.sh` |
| `INTERRUPT_FRONTGATE_SESSION_TIMEOUT` | 前门 session 生命周期上限 | `0` |
| `INTERRUPT_FRONTGATE_ROOM_STARTUP_TIMEOUT_S` | 房间参与者启动等待 | `60` |
| `INTERRUPT_FRONTGATE_ROOM_PRE_DISPATCH_DELAY_S` | room-agent 启动后预留时间 | `2` |
| `INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS` | 前门房间空闲超时 | `180000` |
| `INTERRUPT_FRONTGATE_SESSION_EXIT_SIGNAL_FILE` | 房间退出信号文件 | `/tmp/interrupt_frontgate_room_exit.signal` |

### 11.4.1 统一容器链

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_FRONTGATE_ONLINE_BRIDGE_URL` | 前门命中在线 brain 的桥接地址 | `http://127.0.0.1:8787/wake-session` |
| `INTERRUPT_FRONTGATE_OFFLINE_BRIDGE_URL` | 前门命中离线 brain 的桥接地址 | `http://127.0.0.1:8788/wake-session` |
| `INTERRUPT_FRONTGATE_ONLINE_BRIDGE_PORT` | online-brain 桥接端口 | `8787` |
| `INTERRUPT_FRONTGATE_OFFLINE_BRIDGE_PORT` | offline-brain 桥接端口 | `8788` |
| `HOST_OLLAMA_MODELS_DIR` | ollama 模型持久化目录 | `/data/HongTu/interrupt/volumes/ollama-models` |

### 11.5 音频链

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `PULSE_SOURCE` | Pulse 输入源 | USB 麦 source |
| `PULSE_SINK` | Pulse 输出 sink | USB 音箱 sink |
| `PULSE_SINK_VOLUME_PERCENT` | 默认输出音量 | `100%` |
| `OM1_CONSOLE_INPUT_DEVICE` | OM1 console 输入设备名 | `mvsilicon B1 usb audio` |
| `OM1_CONSOLE_OUTPUT_DEVICE` | OM1 console 输出设备 | `pulse` |
| `INTERRUPT_RTC_INPUT_DEVICE` | RTC 采集设备 | `plughw:CARD=audio,DEV=0` |
| `INTERRUPT_RTC_OUTPUT_DEVICE` | RTC 播放设备 | `pulse` |
| `INTERRUPT_RTC_AEC_ENABLED` | RTC AEC 开关 | `1` |
| `INTERRUPT_RTC_TRANSCRIBE_ENABLED` | 本地 RTC 转写开关 | `1` |
| `INTERRUPT_RTC_TRANSCRIBE_WORKER` | 本地转写 worker | `tools/local_funasr_worker.py` |
| `INTERRUPT_RTC_TRANSCRIBE_PYTHON` | 转写 Python | 机器人特定 Python |

### 11.6 本地文本后端与单机策略

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_SINGLEBOX_FORCE_LOCALHOST_LOCAL_TEXT` | 单机模式强制本地 loopback | `1` |
| `INTERRUPT_SINGLEBOX_LOCAL_TEXT_BASE_URL` | 单机模式本地文本地址 | `http://127.0.0.1:11434` |
| `INTERRUPT_LOCAL_TEXT_STARTUP_TIMEOUT_S` | 本地文本后端等待时间 | `20` |
| `INTERRUPT_LOCAL_TEXT_PROBE_TIMEOUT_S` | 探针超时 | `1.5` |
| `INTERRUPT_LOCAL_TEXT_REMOTE_START_COMMAND` | 远程本地文本后端启动命令 | 可选 |
| `INTERRUPT_LOCAL_TEXT_PREWARM_ON_READY` | 后端就绪后预热模型 | `1` |
| `INTERRUPT_LOCAL_TEXT_PREWARM_TIMEOUT_S` | 预热超时 | `45` |

### 11.7 机器人执行层

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_G1_OM1_PYTHON` | OM1 Python | `/home/unitree/HongTu/OM1/.venv-g1/bin/python` |
| `INTERRUPT_G1_DIRECT_COMMAND_SCRIPT` | 直接命令脚本 | `g1_direct_command_fallback.py` |
| `INTERRUPT_G1_FEEDBACK_SCRIPT` | 反馈/灯光/播报脚本 | `g1_watchdog_feedback.py` |
| `INTERRUPT_G1_SPEAK_SCRIPT` | 外部 speak 分流脚本 | `external_usb_tts.sh` 等 |
| `INTERRUPT_G1_INTERFACE` | Unitree 接口名 | `enP8p1s0` 等 |

### 11.8 导航层

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_G1_NAV_PROVIDER` | 导航 provider | `http_bridge` / `ros2_goal_pose` / `g1_3d_nav` |
| `INTERRUPT_G1_NAVIGATION_SCRIPT` | 导航脚本路径 | provider 对应默认值 |
| `INTERRUPT_G1_NAV_STACK_ROOT` | 导航工作区根路径 | 现场路径 |
| `INTERRUPT_G1_NAV_BASE_URL` | HTTP 导航桥地址 | `http://localhost:5000` |
| `INTERRUPT_G1_NAV_TIMEOUT_S` | 导航请求超时 | `5` |
| `INTERRUPT_G1_NAV_BRIDGE_RUNNER` | 导航桥启动脚本 | `run_g1_3d_nav_bridge.sh` 等 |
| `INTERRUPT_G1_3D_NAV_ROOT` | `g1_3d_nav` 仓库根路径 | 自动或手工指定 |

### 11.9 视觉层

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_VLM_ENABLED` | VLM 总开关 | `0/1` |
| `INTERRUPT_VLM_PROVIDER` | VLM provider | `gemini_openai_compat` / `openai_compatible` / `ollama_native` |
| `INTERRUPT_VLM_API_KEY` | VLM 鉴权 | 可空 |
| `INTERRUPT_VLM_BASE_URL` | VLM 基础地址 | provider 对应地址 |
| `INTERRUPT_VLM_MODEL` | VLM 模型名 | 现场指定 |
| `INTERRUPT_VLM_IMAGE_PATH` | 固定图片模式输入 | 可空 |
| `UNITREE_G1_CAMERA_DEVICE` | 相机设备 | `/dev/video2` 等 |
| `INTERRUPT_VISION_EXTERNAL_CAPTURE_TIMEOUT_S` | 外部采集超时 | 默认或现场覆盖 |

### 11.10 安全与反馈

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY` | 动作/导航安全门开关 | `0/1` |
| `INTERRUPT_ASSISTANT_AUDIO_MODE` | assistant 本地播报策略；现场建议在线=`transport_only`，离线=`om1_mirror` | `om1_mirror` / `transport_only` / `disabled` |
| `INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE` | 本地工具 ack 播报策略；现场建议在线=`transport_only`，离线=`om1_mirror` | `om1_mirror` / `transport_only` / `disabled` |
| `INTERRUPT_ENABLE_LOCAL_TEXT_REPLY_FALLBACK` | 本地回复播报兜底 | `1` |

### 11.11 负载和 worker 行为

| 变量 | 作用 | 典型值 |
| --- | --- | --- |
| `INTERRUPT_AGENT_LOAD_THRESHOLD` | worker load threshold | `0.99` |
| `INTERRUPT_AGENT_FORCE_LOAD` | 强制 worker load | `0.20` |
| `INTERRUPT_AGENT_PATCH_JOB_TOKEN` | job token patch 开关 | `0/1` |
| `INTERRUPT_AGENT_NUM_IDLE_PROCESSES` | idle worker 数 | `0` |
| `INTERRUPT_AGENT_INITIALIZE_PROCESS_TIMEOUT_S` | worker 初始化超时 | `30` |
| `INTERRUPT_AGENT_JOB_EXECUTOR_TYPE` | job 执行器类型，机器人现场建议 `thread` | `thread` / `process` |

## 15. 机器人能力边界

当前 `interrupt` 明确不负责以下内容本体：

- Nav2 / move_base / 地图 / 定位 / 规划算法本体
- G1 硬件底层驱动本体
- OM1 仓库中动作和反馈脚本的全部实现细节
- 唤醒词模型训练本体

`interrupt` 负责的是这些能力的统一“语音交互接口层”：

- 动作
- 灯光
- 直接命令
- 视觉问答
- 导航点查询/导航/记点

## 16. 文档阅读顺序建议

如果你第一次接手这个仓库，建议按以下顺序读：

1. [PROJECT_PROGRESS.md](./PROJECT_PROGRESS.md)
2. [docs/G1_OFFLINE_DEPLOYMENT_PROGRESS_2026-05-18.md](./docs/G1_OFFLINE_DEPLOYMENT_PROGRESS_2026-05-18.md)
3. [docs/OFFLINE_SINGLEBOX_FIELD_STABILIZATION_2026-06-02.md](./docs/OFFLINE_SINGLEBOX_FIELD_STABILIZATION_2026-06-02.md)
4. [docs/VOICE_NAVIGATION_INTERFACE_CONTRACT_2026-05-20.md](./docs/VOICE_NAVIGATION_INTERFACE_CONTRACT_2026-05-20.md)
5. [src/agent.py](./src/agent.py)
6. [src/rtc_endpoint.py](./src/rtc_endpoint.py)
7. [tools/wakeword_session_frontgate.py](./tools/wakeword_session_frontgate.py)
8. [src/g1_om1_adapter.py](./src/g1_om1_adapter.py)

## 17. 常用诊断入口

- 环境检查：`python tools/check_env.py`
- 前门 smoke：`python tools/frontgate_smoke_test.py`
- 本地文本脑 smoke：`python tools/local_text_brain_smoke.py`
- 三语本地文本脑 smoke：`python tools/local_text_trilingual_smoke.py`
- 导航后端探针：`python tools/navigation_backend_probe.py`
- VLM 后端探针：`python tools/vlm_backend_probe.py`
- 离线单机验收：`python tools/offline_singlebox_acceptance.py`

## 18. 当前工程判断

从代码和文档可以看到，`interrupt` 已经不是“功能探索期”项目，而是进入了：

- 现场稳定性优化
- 离线链收口
- 音频自愈
- 设备恢复自动化
- 部署口径统一

当前最大的持续主题，不是继续堆功能，而是：

- 缩短本地回复时延
- 提升本地模型推理稳定性
- 继续固化在线/离线双链路切换口径

## 19. 补充说明

本 README 已经替换掉上游 `RAI` 总览式内容，转为 `interrupt` 子项目自己的架构说明。  
如果后续还要继续细化，建议下一步单独新增：

- `ARCHITECTURE.md`
- `DEPLOYMENT.md`
- `OPERATIONS.md`
- `ENV_REFERENCE.md`

这样 README 保持总览，深水区内容拆到专题文档里会更易维护。
