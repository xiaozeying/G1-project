# interrupt

## 当前推荐启动方式

针对 G1 真机，当前唯一推荐的主启动路径是：

```bash
systemctl --user restart interrupt-frontgate.service
```

对应 service 文件已收录到仓库：

```text
interrupt/deploy/systemd/user/interrupt-frontgate.service
```

说明：

- 这是当前真机已验证的前门唤醒 -> 房间会话主路径
- 其他启动命令保留为调试/排障用途，不作为当前推荐主入口

## 真机快照状态

已验证：

- 前门唤醒可命中并进入房间会话
- 房间语音收音、回复、动作/LED 快路可工作
- 前门默认播放出口可走外接 USB 音频设备
- 房间 idle 退出后会回到前门待机，不会沿用旧唤醒历史立即再次命中

未完全收口：

- 唤醒词命中率仍需要继续调优，存在切碎识别和误识别
- 从“我在，请说”到房间真正 ready 中间仍有空白时间
- thinking 阶段用户再次插话时，Gemini Live 仍可能触发上游 `1008 policy violation`

当前推荐参数：

- `INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS=180000`
- `OM1_WAKEWORD_CHUNK_DURATION=1.6`
- `OM1_WAKEWORD_MERGE_HISTORY_CHUNKS=3`
- `OM1_AUDIO_GAIN=2.2`
- `PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
- `INTERRUPT_RTC_OUTPUT_DEVICE=pulse`

本目录现在以 `LiveKit Agents console mode + Gemini Live` 作为主运行路径。

目标能力：

- 本地单机会话，直接在终端里运行
- 麦克风输入、扬声器输出、支持打断
- 保持与 LiveKit Agents Playground 接近的会话能力
- 后续可接入外部三语言唤醒词模块
- 后续可接入 MCP 工具链
- 保留网页端 / LiveKit 房间模式作为可选分支，不再是主路径

## 主架构

```text
Local terminal
  -> LiveKit Agents console mode
  -> Gemini Live realtime model
  -> optional MCP servers
  -> optional wake-word adapter
```

`console mode` 是 LiveKit 官方提供的本地单会话调试模式，不经过 LiveKit 房间，也不需要网页端。

当前回复播报策略支持通过配置显式切换：

- `INTERRUPT_ASSISTANT_AUDIO_MODE=om1_mirror`
  - 保持当前默认行为
  - assistant 回复镜像到 OM1 本地播报
- `INTERRUPT_ASSISTANT_AUDIO_MODE=transport_only`
  - 为后续 WebRTC 主播报预留
  - assistant 回复不再走 OM1 本地 TTS
- `INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=om1_mirror|transport_only|disabled`
  - 控制本地工具前置确认播报是否继续走 OM1

兼容旧开关：

- `INTERRUPT_MIRROR_ASSISTANT_SPEECH_TO_OM1=1` 等价于 `om1_mirror`
- `INTERRUPT_MIRROR_ASSISTANT_SPEECH_TO_OM1=0` 等价于 `transport_only`

## 目录结构

- `src/agent.py`：LiveKit Agent 入口，同时支持 `console` / `dev`
- `src/settings.py`：配置与环境变量加载
- `src/integrations.py`：外部唤醒词 / MCP 配置适配层
- `dev_server.py`：本地网页端和 token 接口
- `web/index.html`：网页端 UI
- `web/main.js`：网页端 LiveKit 客户端逻辑
- `config.yaml`：项目默认配置
- `run_livekit_server.sh`：启动本地 LiveKit Server
- `run_local_voice_agent.sh`：启动本地语音 console 模式
- `run_local_text_agent.sh`：启动本地文本 console 模式
- `run_room_agent.sh`：启动 LiveKit Room worker 模式
- `run_robot_rtc_endpoint.sh`：启动机器人侧 WebRTC endpoint 骨架
- `run_frontgate_room_session.sh`：前门唤醒后确保房间会话可用并等待本轮会话结束
- `run_local_playground.sh`：本地 Playground 入口别名
- `run_web_playground.sh`：启动本地网页端
- `tools/check_env.py`：检查依赖与配置

## 快速开始

```bash
cd /home/zz/HongTu/interrupt
chmod +x bootstrap.sh run_livekit_server.sh run_local_voice_agent.sh run_web_playground.sh
./bootstrap.sh
cp .env.example .env.local
```

编辑 `.env.local`：

```bash
LIVEKIT_URL=ws://127.0.0.1:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
GEMINI_API_KEY=你的密钥
# 如果 LiveKit 跑在本机/LAN，优先只给 Gemini Realtime 配 WSS 代理，
# 避免把 LiveKit 房间连接一并走代理。
WSS_PROXY=http://<gemini-wss-proxy-host>:<port>
INTERRUPT_INPUT_DEVICE=
INTERRUPT_OUTPUT_DEVICE=
INTERRUPT_TEXT_MODE=0
INTERRUPT_RECORD=0
INTERRUPT_WAKE_WORD_FACTORY=
INTERRUPT_MCP_STDIO_COMMAND=
INTERRUPT_MCP_HTTP_URLS=
```

如果需要让机器人或同网段设备连接开发机上的 LiveKit Server，再额外设置：

```bash
LIVEKIT_BIND_ADDRESS=0.0.0.0
LIVEKIT_NODE_IP=<livekit-lan-ip>
```

其中 `LIVEKIT_NODE_IP` 应替换成当前开发机局域网 IP。

然后检查环境：

```bash
source .venv/bin/activate
python tools/check_env.py
```

## 本地主路径

语音模式：

```bash
cd /home/zz/HongTu/interrupt
./run_local_voice_agent.sh
```

文本自测模式：

```bash
cd /home/zz/HongTu/interrupt
./run_local_text_agent.sh
```

多语言自适应自测建议：

- 普通话：`今天天气怎么样`
- 粤语：`你而家识唔识讲广东话`
- English: `What can you do for me?`
- 显式锁定粤语：`之后用粤语回答我`
- 恢复自动：`恢复自动，跟着我说的话回答`

预期行为：

- 默认跟随用户最近一轮输入语言回答
- 用户明确要求切换语言后，后续回复先保持该语言
- 用户要求“恢复自动”后，再回到按当前输入语言自适应
- 天气、新闻、本地动作/灯光确认播报也应尽量保持同语种

离线逻辑回归：

```bash
cd /home/zz/HongTu/interrupt
./.venv/bin/python tools/language_routing_smoke.py
```

这条脚本不依赖音频设备，也不依赖实时联网会话，主要用于验证：

- 用户输入语言检测
- 显式锁定回复语言
- 恢复自动跟随用户语言

列出可用音频设备：

```bash
cd /home/zz/HongTu/interrupt
source .venv/bin/activate
python -m src.agent console --list-devices
```

如需指定设备：

```bash
INTERRUPT_INPUT_DEVICE="USB" INTERRUPT_OUTPUT_DEVICE="USB" ./run_local_voice_agent.sh
```

旁路 WebRTC endpoint 验证：

```bash
cd /home/zz/HongTu/interrupt
LIVEKIT_BIND_ADDRESS=0.0.0.0 \
LIVEKIT_NODE_IP=<livekit-lan-ip> \
./run_livekit_server.sh
```

另一个终端：

```bash
cd /home/zz/HongTu/interrupt
./run_room_agent.sh
```

另一个终端：

```bash
cd /home/zz/HongTu/interrupt
INTERRUPT_RTC_ROOM_NAME=interrupt-demo \
INTERRUPT_RTC_IDENTITY=robot-rtc-endpoint \
INTERRUPT_RTC_INPUT_DEVICE=pulse \
INTERRUPT_RTC_OUTPUT_DEVICE=pulse \
./run_robot_rtc_endpoint.sh
```

这条链路当前是并行验证用，不会替换现有 `console` 主路径。
如果机器人连不上 `LIVEKIT_URL=ws://<开发机IP>:7880`，优先先确认本机 `run_livekit_server.sh`
是否以 `LIVEKIT_BIND_ADDRESS=0.0.0.0` 启动，否则 `livekit-server --dev` 在新版本里可能只监听 `127.0.0.1`。
建议先把主回答切到：

```bash
export INTERRUPT_ASSISTANT_AUDIO_MODE=transport_only
```

这样可以验证“房间下行 + 外接设备播放”，同时避免 OM1 本地 TTS 双播报。

如果 `LIVEKIT_URL` 指向局域网地址，而 Gemini Realtime 需要科学上网，优先使用：

```bash
export WSS_PROXY=http://<gemini-wss-proxy-host>:<port>
```

不要默认给 worker 加整套 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`，否则可能干扰 LiveKit 房间连接。

机器人侧默认还会开启房间守护，避免 `away -> session.shutdown()` 后需要人工补一次 dispatch：

```bash
export INTERRUPT_RTC_AUTO_REDISPATCH_ON_AGENT_DISCONNECT=1
export INTERRUPT_RTC_REDISPATCH_COOLDOWN_S=8
export INTERRUPT_RTC_AGENT_ABSENCE_CHECK_INTERVAL_S=20
```

如果现场需要保守排障，也可以临时把自动恢复关掉，只保留手工 dispatch：

```bash
export INTERRUPT_RTC_AUTO_REDISPATCH_ON_AGENT_DISCONNECT=0
```

如果感觉“说话打不断”，先检查这三个参数：

```yaml
agent:
  interruption_mode: vad
  min_interruption_duration_ms: 80
  false_interruption_timeout_ms: 500
  aec_warmup_duration_ms: 0
```

其中 `aec_warmup_duration_ms` 如果大于 0，agent 开始说话后的这段时间会故意忽略打断。
`interruption_mode: vad` 更适合当前这种本地 console 链路，优先按“检测到你开口”来截断当前播报。

如果你希望用户说“停一下”“等一下”“先别说了”这类打断词后，agent 固定播报一句确认话术，可调整：

```yaml
agent:
  interruption_acknowledgement: 好的，那您还有其他需求吗？
```

当前实现会把这条话术注入系统指令中，并在日志里输出打断候选与转写结果，便于继续排查。

机器人 RTC endpoint 默认会启用 LiveKit `AudioProcessingModule` 做参考信号 AEC：

```bash
export INTERRUPT_RTC_AEC_ENABLED=1
```

不要把“播报时静音麦克风”作为最终方案。当前 endpoint 会把下行播放帧喂给 AEC 作为 reverse stream，再把麦克风采样经 AEC 后 publish；只有 AEC 不可用时，才回退到临时的低能量回声 ducking。

真机上优先让 `pulse` 指向外接 USB 声卡，而不是写死 `hw:2,0` 这类 ALSA 卡号。卡号可能随启动顺序变化，`pactl info` 应显示：

```text
Default Sink: alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
Default Source: alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
```

## 外部模块接入

- 唤醒词：
  当前目录没有唤醒词实现，已预留 `INTERRUPT_WAKE_WORD_FACTORY` 配置位。
  后续把外部三语言唤醒词模块整理成 `module.submodule:factory` 形式即可接入。

- MCP：
  已预留 `INTERRUPT_MCP_STDIO_COMMAND` 和 `INTERRUPT_MCP_HTTP_URLS`。
  例如本地 stdio MCP：

```bash
INTERRUPT_MCP_STDIO_COMMAND="npx -y @modelcontextprotocol/server-filesystem /home/zz/HongTu" ./run_local_text_agent.sh
```

使用 MCP 前，需要额外安装：

```bash
pip install 'livekit-agents[mcp]'
```

- G1 / OM1 复用层：
  当前已新增 `interrupt` 侧适配入口，后续会话层或 MCP 工具都应复用它，而不是重新拼 Unitree 细节。

```bash
python tools/g1_om1_cli.py check
python tools/g1_om1_cli.py direct "把LED灯变为红色"
python tools/g1_om1_cli.py direct "向我挥手"
python tools/g1_om1_cli.py speak "我在，请说"
```

如需覆盖默认脚本路径，可设置：

```bash
export INTERRUPT_G1_OM1_PYTHON=/home/unitree/HongTu/OM1/.venv/bin/python
export INTERRUPT_G1_DIRECT_COMMAND_SCRIPT=/home/unitree/HongTu/OM1/scripts/g1_direct_command_fallback.py
export INTERRUPT_G1_FEEDBACK_SCRIPT=/home/unitree/HongTu/OM1/scripts/g1_watchdog_feedback.py
export INTERRUPT_G1_INTERFACE=eth1
```

- 唤醒前门：
  当前已补一个“等待唤醒 -> 拉起实时 session -> 会话退出后回待机”的本地编排脚本：

```bash
python tools/wakeword_session_frontgate.py --once
```

也可以直接用统一启动脚本：

```bash
./run_frontgate_session.sh
```

如果是在机器人环境上直接走真实三语言唤醒模块，优先用：

```bash
./run_robot_frontgate_session.sh
```

机器人前门现在默认不再拉起旧 `console` 会话，而是拉起房间会话 wrapper：

```bash
export INTERRUPT_FRONTGATE_SESSION_COMMAND="/home/unitree/HongTu/interrupt/run_frontgate_room_session.sh"
```

这个 wrapper 会：

- 确保 `run_room_agent.sh` 已在运行
- 确保 `run_robot_rtc_endpoint.sh` 已在运行
- 唤醒后补一次 room dispatch
- 前门侧等待本轮房间会话结束后再恢复待机 LED

如果需要临时回到旧路径排障，仍然可以显式覆盖：

```bash
export INTERRUPT_FRONTGATE_SESSION_COMMAND="/home/unitree/HongTu/interrupt/run_local_voice_agent.sh"
```

如果真实唤醒脚本路径不存在，或对应 factory 启动失败，前台门当前会默认回退到 `stdin` mock gate，便于先验证编排逻辑：

```bash
python tools/wakeword_session_frontgate.py --wakeword 笨笨同学 --once
```

如需关闭这个回退保护，可设置：

```bash
export INTERRUPT_FRONTGATE_ALLOW_FACTORY_FALLBACK=0
```

后续接入真实唤醒模块时，设置：

```bash
export INTERRUPT_WAKE_WORD_FACTORY=your_module.submodule:factory
```

如果直接复用机器人现有 `g1-wakeword/wakeword_adaptive.py`，可以先用：

```bash
export INTERRUPT_WAKE_WORD_FACTORY=src.om1_wakeword_gate:factory
export WAKEWORD_SCRIPT=/home/unitree/g1-wakeword/wakeword_adaptive.py
export INTERRUPT_FRONTGATE_SESSION_COMMAND="/home/zz/HongTu/interrupt/run_local_voice_agent.sh"
```

它会在前门阶段直接加载外部三语言唤醒模块，并在命中后拉起 session command。

前门自测脚本：

```bash
python tools/frontgate_smoke_test.py
python tools/frontgate_regression_test.py
```

这个测试不依赖真实麦克风，也不依赖真实唤醒模型；它只验证：

- 前门能收到唤醒事件
- session command 能被拉起
- session 退出后能回收

或者显式传入：

```bash
python tools/wakeword_session_frontgate.py \
  --factory your_module.submodule:factory \
  --session-command "/home/zz/HongTu/interrupt/run_local_voice_agent.sh"
```

## 网页端分支

如果后续仍然需要浏览器版 Playground，再使用下面三步：

```bash
./run_livekit_server.sh
./run_local_voice_agent.sh dev
./run_web_playground.sh
```

## 参考

- LiveKit startup modes: https://docs.livekit.io/agents/server/startup-modes
- LiveKit MCP: https://docs.livekit.io/agents/logic/tools/mcp
