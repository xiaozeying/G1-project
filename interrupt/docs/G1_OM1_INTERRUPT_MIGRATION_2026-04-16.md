# G1 + OM1 打断功能最小迁移方案

更新时间：2026-04-20

## 2026-05-20 补充边界

当前需要特别注意一个边界：

- `interrupt` 负责语音导航接口层
- 不负责导航工作区、规划器、Nav2、move_base、地图和点位运行时

也就是说，后续如果看到：

- `nav2_msgs` 不可导入
- `localhost:5000` 没桥
- 机器人导航 overlay 缺文件

这些都应优先归到导航后端环境，而不是继续回头修改语音链主逻辑。

当前语音导航层只要求稳定提供：

- `list_saved_locations`
- `navigate_to_saved_location`
- `remember_current_location`

并将请求通过统一适配层转交给机器人现有导航后端。

## 2026-04-20 当前可继续推进的技术状态

### 当前整机架构

```text
用户说话
  -> USB 麦克风 / arecord
  -> tools/wakeword_session_frontgate.py
  -> src/om1_wakeword_gate.py
  -> run_local_voice_agent.sh
  -> python -m src.agent console
  -> src/console_audio_compat.py
  -> Gemini Realtime
  -> src/g1_om1_adapter.py
  -> G1 LED / 动作 / OM1 本地播报
```

### 当前状态机口径

- 蓝灯：空闲 / 需要唤醒
- 绿呼吸灯：当前会话仍在监听
- 紫灯：动作执行中
- `away` 超时：`300000ms`
- `away` 后动作：
  - 切蓝灯
  - `session.shutdown(drain=False)`
  - 前门回到下一轮唤醒等待

### 当前真实收口点

1. 真机前门唤醒已通

- `src.om1_wakeword_gate:factory` 在机器人上可用
- 真实日志已反复出现：

```text
[FrontGate] wake_detected ...
[FrontGate] wake_ack ...
[FrontGate] session_cmd=/home/unitree/HongTu/interrupt/run_local_voice_agent.sh
```

2. 第二阶段会话已固定到本地 console mode

- 真机当前不是网页端房间模式
- 而是：

```text
python -m src.agent console --input-device 0 --output-device 0
```

3. 输入链路已增加 watchdog

- 历史问题是动作执行后 `sounddevice.InputStream` 会静默停摆
- 当前 [src/console_audio_compat.py](/home/zz/HongTu/interrupt/src/console_audio_compat.py) 已加入 watchdog
- 若输入回调停摆，会自动重开输入流

4. 控制类命令已加本地快路

- 根因日志已确认，Gemini Realtime 在真机上有时会出现：

```text
server cancelled tool calls
```

- 这会导致：
  - 用户语音已经识别成功
  - 但远端工具调用在真正执行前被取消
- 当前 [src/agent.py](/home/zz/HongTu/interrupt/src/agent.py) 已增加“本地快路”
  - 对明确的灯光/动作控制命令
  - 优先本地落地到 `G1_ADAPTER`
  - 并对同轮远端重复执行做抑制

5. 天气 / 新闻当前不属于“链路坏了”，而是“工具未接入”

- 当前配置：

```yaml
integrations:
  mcp_stdio_command: ""
  mcp_http_urls: []
```

- 所以机器人会话目前没有 weather/news 外部实时数据工具
- 模型只能给非实时兜底回答，不能保证“实时新闻 / 实时天气”

### 当前最小回归命令

#### 代码侧静态自检

```bash
cd /home/zz/HongTu/interrupt
python3 -m py_compile src/agent.py src/console_audio_compat.py src/integrations.py
python3 -m py_compile tools/wakeword_session_frontgate.py src/om1_wakeword_gate.py
```

#### 前门回归

```bash
cd /home/zz/HongTu/interrupt
python tools/frontgate_smoke_test.py
python tools/frontgate_regression_test.py
```

#### G1/OM1 适配器最小验证

```bash
cd /home/zz/HongTu/interrupt
python tools/g1_om1_cli.py check
python tools/g1_om1_cli.py direct "把LED灯变为红色"
python tools/g1_om1_cli.py direct "向我挥手"
python tools/g1_om1_cli.py speak "我在，请说"
```

#### 真机联调启动

```bash
ssh <robot-user>@<robot-ip>
cd /home/unitree/HongTu/interrupt
nohup env \
  INTERRUPT_INPUT_DEVICE=0 \
  INTERRUPT_OUTPUT_DEVICE=0 \
  INTERRUPT_USER_AWAY_TIMEOUT_MS=300000 \
  INTERRUPT_ACTIVE_LISTEN_LED_COLOR=green \
  INTERRUPT_ACTION_BUSY_LED_COLOR=purple \
  INTERRUPT_ACTION_BUSY_HOLD_S=6.0 \
  INTERRUPT_ENABLE_LOCAL_TOOL_PRE_ACK=1 \
  ./run_robot_frontgate_session.sh \
  >/home/unitree/HongTu/interrupt/logs/robot-frontgate.log 2>&1 &
```

#### 真机日志查看

```bash
tail -F /home/unitree/HongTu/interrupt/logs/robot-frontgate.log
tail -F /home/unitree/HongTu/interrupt/logs/agent.log
```

### 当前继续推进时不要再误判的点

1. “天气 / 新闻答不出来”

- 优先判断 MCP/HTTP 工具是否根本没有配置
- 不要先怀疑音频链路

2. “灯光 / 动作收到但没执行”

- 优先查：

```text
server cancelled tool calls
```

- 如果出现，优先查本地快路是否命中，而不是只盯远端 function tool

3. “动作后第二轮听不到”

- 优先查：

```text
console audio compat restarting input stream
```

- 这表示 watchdog 已介入恢复输入流

## 2026-04-20 代码同步补记

### 前台门工厂回退保护

- 当前 `interrupt` 侧前台门已补一层安全回退：
  - 当机器人默认真实唤醒工厂启动失败
  - 例如 `WAKEWORD_SCRIPT` 路径失效、脚本未同步、factory 导入异常
  - 会自动回退到 `src.mock_wakeword:factory`
- 目的不是替代真实唤醒，而是避免前台门在机器人环境里因为单点路径问题直接无法启动
- 如需强制失败而不是回退，可设置：

```text
INTERRUPT_FRONTGATE_ALLOW_FACTORY_FALLBACK=0
```

### 最小回归检查已补

- 当前仓库已新增：

```text
tools/frontgate_regression_test.py
```

- 覆盖三类最小回归：
  - 唤醒别名归一
  - 会话态状态机
  - `G1/OM1` 默认接口仍为 `eth1`

## 2026-04-17 追加收口

### 2026-04-17 前台门 + realtime session 关键修复

- 已确认新两阶段架构当前最大的真实阻塞，不是唤醒词本身，也不是 Gemini realtime 本身
- 而是：
  - `wakeword_session_frontgate.py` 之前用普通 `subprocess.Popen(...)` 拉起
  - `python -m src.agent console`
  - 在这种“无终端编排子进程”场景下，LiveKit console mode 会退化成：

```text
using audio io: (none) -> AgentSession -> (none)
```

- 表现就是：
  - 日志里 agent 已经进入 `listening`
  - 但没有真实麦克风输入
  - 也没有真实扬声器输出
  - 所以现场会误以为“唤醒后 session 没起来”或者“长对话链路坏了”

- 现在已将前台门改为：
  - 用 PTY 方式拉起 session 子进程
  - 让 `console` 会话即使由前台门/守护脚本启动，也仍然拿到可用终端语义

- 机器人实测日志已经从：

```text
using audio io: (none) -> AgentSession -> (none)
```

- 恢复为：

```text
using audio io: `Console` -> `AgentSession` -> `TranscriptSynchronizer` -> `Console`
```

- 这意味着当前两阶段架构已经打通到：
  - 前台门可拉起 realtime session
  - session 已绑定真实 console 音频链路
  - 后续重点转到“真实语音回归联调”，不再是启动方式问题

### 2026-04-17 G1/OM1 默认路径修正

- 另一个已确认问题是：
  - `interrupt` 侧 G1/OM1 适配器默认路径此前仍指向我本地快照目录
  - 机器人环境上会直接变成 `adapter unavailable`
  - 结果就是前台门虽然已经执行“唤醒后本地播报 / 会话态 LED”逻辑
  - 但实际不会落到机器人 OM1 脚本

- 现在默认路径优先级已修正为：
  - `/home/unitree/HongTu/OM1`
  - `/home/zz/HongTu/OM1`
  - `/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1`

- 因此后续这些能力在机器人上不再需要先手工改环境变量才可用：
  - 唤醒后 `我在，请说`
  - 会话态绿色呼吸灯
  - 会话退出后蓝色待机灯
  - 会话层 LED / 动作工具调用

### 2026-04-17 第二阶段麦克风绑定修正

- 现场继续联调后确认：
  - 当前第一阶段已经通了
  - 三语言唤醒、`我在，请说`、绿色呼吸灯都正常
  - 但第二阶段 `interrupt` session 里，用户 follow-up 语音仍可能完全进不去

- 关键表现是：
  - session 已进入 `agent_state_changed: initializing -> listening`
  - 但没有任何 `user_input_transcribed`
  - 最后直接 `user_state_changed: listening -> away`

- 当前收口判断是：
  - 这不再是唤醒问题
  - 也不只是冷启动窗口问题
  - 而是 session 使用的输入设备必须与唤醒前门保持同一路麦克风

- 机器人上已确认唤醒前门实际命中的采集设备是：

```text
mvsilicon B1 usb audio
```

- 前一版尝试把第二阶段 session 也强行固定到 USB 设备名：

```text
INTERRUPT_INPUT_DEVICE=mvsilicon B1 usb audio
```

- 但现场日志已确认，这会触发 PortAudio 打开失败：

```text
PortAudioError: Error opening InputStream: Invalid sample rate
```

- 随后继续做了 PortAudio 最小回调验证，结果确认：
  - `default` / `pulse` 回调虽然会触发
  - 但 RMS 持续为 `0.0`
  - 也就是这两条 PortAudio 输入源在机器人当前环境下拿到的是静音源
  - 真正有声的是 PortAudio 输入设备 `0`

- 当前修正为：
  - 第一阶段唤醒前门仍直接使用 USB 麦克风
  - 第二阶段 `interrupt` console session 默认固定为 PortAudio 输入设备 `0`
  - 这一路实测可以拿到非零 RMS

```text
INTERRUPT_INPUT_DEVICE=0
```

- 第二阶段输出当前也同步固定为 PortAudio 输出设备 `0`
- 目的是避免 `default` 继续落到不确定的系统逻辑设备，导致“模型已 speaking，但现场无声”

```text
INTERRUPT_OUTPUT_DEVICE=0
```

- 如需后续切换设备，优先改：

```text
OM1_CONSOLE_INPUT_DEVICE
```

- 目标是让第二阶段 session 与第一阶段唤醒使用同一只麦克风，避免出现：
  - 唤醒能听到
  - 进入会话后却听不到 follow-up

### 2026-04-17 唤醒误识别别名追加

- 现场继续观察到一些高频误识别：
  - `笨笨你好`
  - `笨笨，你好`
  - `本本`
  - `贝贝同学`

- 当前前台门已在送入底层唤醒词检查前，先做一层轻量文本归一：
  - `笨笨你好` / `笨笨，你好` -> `你好笨笨`
  - `本本` -> `笨笨`
  - `贝贝同学` -> `笨笨同学`
- 另外当前默认额外追加的中文唤醒别名包含：
  - `笨笨`
  - `笨笨同学`

- 目的不是改掉底层三语言模型，而是吸收现场常见误转写，提高唤醒命中率

### 当前内置音响路线的最新结论

- 当前优先路线继续固定为：
  - 内置音响
  - 内置 LED
  - 内置上身动作
  - 唤醒词桥接 + OM1 文本输入 + 打断

- 不再把外接音响作为当前联调主线
- 当前主目标是先恢复并收稳：
  - 唤醒后有明确播报
  - 对话中能打断
  - LED / 动作命令能稳定执行
  - 用户能感知“机器人已经收到指令”

### 关键接口修正

- G1 现场实际可用的 Unitree 接口是 `eth1`
- 不是 `eth0`
- 因此前续涉及以下能力时，必须优先使用 `eth1`：
  - 本地 TTS
  - LED 控制
  - 手臂动作
  - watchdog feedback

- 这次代码同步也一并将默认接口口径修正为：
  - `direct-command-interface -> eth1`
  - `g1_direct_command_fallback.py --interface` 默认值 -> `eth1`
  - 本地 TTS 自动接口优先级 -> `eth1 > eth0 > wlan0`

### 新增的人机可感知反馈

- 桥接层已补充“收到指令后的前置语音确认”
- 对于本地可直接处理的命令，不再只在执行后说结果
- 现在会先回答一类确认话术，例如：
  - `好的，我这就把灯调成红色。`
  - `好的，我这就挥手。`

- 目的不是增加花哨播报，而是解决现场联调时最关键的问题：
  - 用户无法判断机器人到底有没有收到指令

### 2026-04-17 响应时序修正

- 现场联调发现：
  - 直接命令虽然已经能播报确认
  - 但顺序仍是“先执行动作 / 灯光，再播报”
  - 用户体感上会觉得响应慢

- 因此桥接层再次调整为：
  - 先播报确认
  - 再执行本地 LED / 动作指令

- 目标时序改成：

```text
识别到命令 -> 立即说“好的，我这就……” -> 再执行动作/灯光
```

- 这样即便动作执行本身还有固有延迟，用户也能立刻知道机器人已经听懂并开始处理

### 2026-04-17 低延迟收口

- 现场继续验证后确认，当前主要抖动点不是单一模块故障，而是：
  - ASR 分块过大
  - follow-up 聚合等待过长
  - 短控制命令仍可能卡在 `buffered_followup`

- 因此桥接默认策略继续下调到低延迟模式：
  - `chunk_duration = 0.8s`
  - `followup_flush_timeout = 0.8s`

- 同时新增一条激进规则：
  - 如果 follow-up 文本已经明显是本地短控制命令
  - 例如 `向我挥手` / `把灯变成红色`
  - 则不再继续等待聚合超时
  - 直接立即 flush 到本地执行分支

- 目标是降低两类现场问题：
  - 响应过慢
  - 响应不稳定

### 新增的会话态 LED 规则

- 默认待机态：
  - 蓝色常亮

- 唤醒进入会话态后：
  - 绿色呼吸灯

- 会话超时退出后：
  - 回到蓝色常亮

- 但如果用户明确下达了 LED 颜色命令，则该次显式 LED 指令优先
- 不会在命令刚执行后立刻又被会话绿呼吸灯覆盖
- 现在进一步调整为：
  - 显式 LED 颜色一旦设置成功
  - 后续再次唤醒也不再自动切回绿色呼吸
  - 只有会话超时退出后，才恢复默认蓝色待机
- 另外补一条启动约束：
  - 前台门进程刚启动时也必须立即下发一次蓝色待机灯
  - 不能依赖“上次退出时是否成功恢复”
  - 这样可以避免服务重启后机器人还残留在绿色呼吸态
  - 现在进一步补上：
    - 打蓝灯前先清理残留的 `breathe` 灯效进程
    - 避免旧绿呼吸后台进程继续覆盖 LED

### 当前推荐验证点

按下面顺序做内置链路回归：

1. 唤醒词
   - `你好笨笨`
   - 期望：
     - 播报 `我在，请说`
     - LED 切到绿色呼吸

2. 直接 LED 指令
   - `笨笨同学，把灯变成红色`
   - 期望：
     - 先播报 `好的，我这就把灯调成红色。`
     - LED 变红

3. 直接动作指令
   - `笨笨同学，挥手`
   - 期望：
     - 先播报 `好的，我这就挥手。`
     - 上身动作执行

4. 会话超时
   - 停止说话直到超时
   - 期望：
     - LED 回到蓝色常亮

## 2026-04-16 16:55 最新收口

### 已确认修复

- 外接音频设备现在已有声音输出
- 原因不是“打断逻辑本身失效”，而是播报链路此前被改成：
  - `OM1 speak -> external_audio -> external_usb_tts.sh -> paplay`
  - 同时桥接脚本本地回复“我在，请说”也走了同一外接输出
- 这说明之前的异常确实混入了“输出路由/默认 sink”问题，不只是打断接入问题

### 已做的最小化调整

- 将 `unitree_g1_text_arm_led_external_audio_gemini` 重新建立在
  - `unitree_g1_text_arm_led_gemini`
  的能力集之上
- 恢复了原本 OM1 文本模式的重要能力面：
  - `ConversationHistoryInput max_rounds=6`
  - `tool_choice=required`
  - `live_info` action
- 仅保留一个必要差异：
  - `speak.connector = external_audio`
  - 输出到外接设备

### 当前剩余主阻塞

- 现在 LED/天气等“像是没响应”的主因，已经不是音频，也不是桥接
- 机器人日志已明确显示：

```text
HTTP 429 Too Many Requests
Quota exceeded for metric: ... gemini-2.5-flash
```

- 也就是：
  - 文本已经送进 OM1
  - OM1 的 websocket、LED、arm、speak 连接器都已初始化成功
  - 但 LLM 在生成动作/播报前被 Gemini 配额拦住

### 当前采取的收口方向

为了不再把“固定控制命令”绑死在 Gemini 配额上，下一步改为：

- 桥接层增加本地确定性兜底
- 对简单高频命令优先本地执行，不依赖 LLM：
  - LED 颜色
  - 常用手臂动作
- 普通开放式聊天、后续视觉 VLM 问答，仍然走 OM1 / Gemini

### 2026-04-16 17:10 唤醒词策略修正

- 不再把 `--wakeword` 视为“覆盖默认三语言唤醒词”
- 改为：
  - 底层三语言唤醒词模型保持不变
  - 桥接层的 `--wakeword` 只做追加别名
- 这样最终行为是：
  - 普通话 / 粤语 / 英语唤醒继续保留
  - 同时允许追加业务别名，例如 `笨笨同学`

- 另外增加了桥接层文本归一化，用于吸收常见误识别：
  - `笨本同学 -> 笨笨同学`
  - `本笨同学 -> 笨笨同学`
  - `奔笨同学 -> 笨笨同学`

- 启动日志也会改成打印“实际参与匹配的唤醒词列表”，避免出现：
  - 日志写的是 `你好笨笨 / 雷猴笨笨 / hello benben`
  - 实际却只匹配 `笨笨同学`
这种误导

### 2026-04-16 17:30 当前已定位问题

- 唤醒和本地 LED 指令其实已经能命中
- 但机器人运行文件缺失 `local_ack_for_direct_command()`，导致：
  - LED 已执行
  - 本地确认播报在执行前抛出 `NameError`
  - 用户侧表现为“灯可能变了，但没有语音反馈”

- 当前优先收口要求改为：
  - 唤醒后必须本地播报 `我在，请说`
  - 本地 LED / 动作命令执行后必须本地播报确认
  - 不再允许“只在日志里体现，用户听不到反馈”

### 2026-04-16 17:40 播报脚本收口

- `local_reply=...` 已经证明桥接会调用本地回复分支
- 下一步不再只看日志成功，而是强化外接播报脚本：
  - 优先锁定 USB sink
  - `espeak` 显式指定中文音色
  - 提高 `amplitude`
  - `paplay` 固定 `--volume=65536`

- 目标是让下面两句稳定可听：
  - `我在，请说`
  - `好的，已经把灯调成红色。`

### 2026-04-16 17:45 外接中文 TTS 根因

- 机器人当前 `espeak` 环境缺少完整中文词典
- 直接使用 `-v zh` 时会报：

```text
Full dictionary is not installed for 'zh'
```

- 因此当前务实方案不是继续赌中文音色，而是：
  - 对固定确认话术做拼音化兜底
  - 先保证“用户能听到有反馈”

- 当前优先保障的话术包括：
  - `我在，请说`
  - `好的，已经把灯调成红色。`
  - 常见灯光/动作确认句

## 今日结论

### 2026-04-17 补充修正

- 机器人当前真正可用的 Unitree 有线接口不是 `eth0`，而是 `eth1`
- 之前大量“功能失效”并不是逻辑坏了，而是：
  - OM1 用 `eth0` 启动
  - 桥接内置 TTS 也用 `eth0`
  - 导致 Unitree 动作通道初始化失败

- 这会直接影响：
  - 内置音响播报
  - LED 控制
  - 上身动作

- 现场已确认：
  - `ip -brief address` 中 `eth0` 为 `DOWN`
  - `eth1` 为 `UP`
  - 切换到 `eth1` 后，OM1 日志恢复为：
    - `Unitree action channel initialized on eth1`
    - `G1 local TTS connector initialized successfully`
    - `G1 Arm Action Client initialized successfully`
    - `G1 LED connector initialized successfully`

- 同时还补齐了 `wakeword-clean` 环境中的：
  - `cyclonedds`

- 这样桥接侧终于可以合法走：
  - `--local-reply-backend onboard`
  - `--tts-interface eth1`

### 1. 当前主链路现状

- 三语言唤醒桥接已经接入机器人侧 OM1 链路
- 本地 LED 指令兜底已经能够命中
- 外接 USB 音频设备本身可以被系统识别，也可以建立播放流
- 但“外接设备上的中文播报”目前仍不稳定

### 2. 已明确根因

- 机器人内置扬声器能正常播报，是因为走的是：
  - `Unitree AudioClient.TtsMaker()`
- 外接音响走的是另一条链：
  - `文本 -> 本机 TTS 引擎 -> Pulse/ALSA -> USB 声卡`
- 当前真正卡住的不是 USB 声卡本身，而是：
  - 机器人本机没有一个稳定可用的中文外接 TTS 后端
- 当前 `espeak` 路线不适合继续作为正式方案推进

### 3. 工程判断

如果目标是：

- 尽快稳定交付
- 先完成唤醒 / 对话 / 打断 / LED / 动作的可用闭环

那么当前阶段应优先选择：

- 内置音响路线

原因：

- 内置音响是机器人原生能力
- 中文播报稳定
- 风险最低
- 不需要继续消耗时间在外接中文 TTS 适配上

而外接音响应视为：

- 下一阶段的输出模块替换工作

而不是当前收口阶段的主线

## 明日执行建议

### 总策略

明天按“先内置、后外接”的顺序推进：

```text
先用内置音响把整条能力链收稳
再把播报出口从内置替换成外接
```

### 明日 P0

先切回内置音响，完成以下闭环：

1. 三语言唤醒
2. 唤醒后固定回复
3. 普通对话
4. 打断
5. LED 控制
6. 手臂动作控制

要求：

- 每个关键动作都必须有明确语音反馈
- 不允许只在日志中看到成功

### 明日 P1

在内置音响链路稳定后，再做“播报出口替换”：

- 保持以下模块不动：
  - 唤醒词识别
  - 对话状态机
  - 打断逻辑
  - OM1 文本输入
  - LED / 动作控制

- 仅替换：
  - 播报输出模块

这样可以把问题收敛成单一变量：

- 只调“外接播报”
- 不再同时影响识别 / 控制 / 打断

### 明日对外接音响的正确目标

不是继续使用当前 `espeak` 中文方案硬撑，而是二选一：

1. 先用预制中文提示音做固定反馈
2. 接入真正可用的中文 TTS 后端，再承接开放式对话播报

### 明日不建议继续做的事

- 不建议继续把大量时间投入在 `espeak` 中文修补
- 不建议在“外接中文播报未稳定”时继续扩大测试面
- 不建议把 VLM、外接中文 TTS、长对话三件事同时并行调试

## 明日优先级

```text
P0: 内置音响收稳整条能力链
P1: 外接音响只替换播报出口
P2: 外接中文 TTS 正式方案
P3: VLM 并回统一模式
```

## 目标

在**不改 OM1 主体逻辑**、**不破坏机器人现有唤醒词/动作/LED 文件**的前提下，只把“对话态 + 打断词”迁移到机器人现有链路中。

## 2026-04-17 目标架构修正

### 当前链路的根本局限

当前 `wakeword_adaptive_to_om1.py` 的本质仍然是：

```text
持续监听
-> 每 0.8s / 1.0s 做一次 ASR 分块
-> 再用 follow-up 聚合把切片拼回去
-> 送入 OM1 文本 websocket
```

这条链路适合：

- 唤醒
- 简单命令
- 短句文本转发
- 本地 LED / 动作兜底

但它不适合直接达成下面这个目标：

- 唤醒后进入真正的长对话模式
- 像本地 `interrupt` 项目一样连续实时对话
- 在播报中被稳定打断
- 不再反复依赖唤醒词

原因不是参数没调好，而是架构层级不同：

- 当前 OM1 路线是“分块 ASR -> 文本转发”
- 本地 `interrupt` 路线是“实时语音 session -> 实时模型 -> 实时打断”

### 最终建议的两阶段架构

最终应该切成：

```text
阶段 1：唤醒阶段
唤醒词系统常驻，仅负责：
- 监听唤醒词
- 唤醒确认
- 进入会话态

阶段 2：会话阶段
唤醒成功后，切换到独立会话引擎，仅负责：
- 持续语音对话
- 实时查询
- 长对话上下文
- 打断
- 会话超时退出

会话退出后：
- 再回到唤醒词监听阶段
```

### 唤醒阶段和会话阶段的职责边界

#### 唤醒阶段保留

- 多语言唤醒词识别
- 唤醒确认播报
- 空闲 / 监听 LED 状态

#### 会话阶段接管

- 连续语音输入
- 连续语音输出
- 打断检测
- 实时问答
- 长上下文会话

### 对应到当前仓库的实现建议

#### 当前最接近的现成能力

- `wakeword_adaptive_to_om1.py`
  - 适合做阶段 1 的唤醒入口

- `voice_command_session_to_om1.py`
  - 已经证明可以做“唤醒后单次会话录制”
  - 但当前仍只是“一次录音 -> 一次转写 -> 一次转发”
  - 还不是长对话 session

- `interrupt/src/agent.py`
  - 才是更接近目标的阶段 2 能力
  - 它本质是实时会话 agent
  - 支持更合理的 VAD、打断和实时转写

### 明确结论

如果最终目标是：

- 唤醒一次后进入连续对话
- 不再把每句话都切成 follow-up 片段
- 稳定打断
- 实时查询

那么后续主线不应继续停留在：

- `wakeword_adaptive_to_om1.py` 参数微调

而应切到：

- `唤醒词前门`
  -> `进入会话态`
  -> `interrupt 风格实时会话引擎`
  -> `超时退出`
  -> `重新启用唤醒词`

### 下一步建议

下一阶段不再把当前桥接脚本视为最终主对话链路，而改为：

1. 保留当前桥接脚本做唤醒入口与本地控制兜底
2. 新建一个“长对话会话管理脚本”
3. 唤醒成功后暂停/旁路当前唤醒词 follow-up 处理
4. 将麦克风控制权交给实时会话引擎
5. 会话超时后释放麦克风并恢复唤醒词监听

目标效果：

```text
待机
  -> 说唤醒词
  -> 响应“我在，请说”
  -> 进入对话模式

对话模式
  -> 普通内容送入 OM1
  -> 支持打断词
  -> 打断后回复固定确认话术
  -> 继续下一轮对话

## 2026-04-17 会话层复用落点

为了避免后面把 G1 的 LED、动作、播报又各接一遍，`interrupt` 侧已经补了一个最小复用层：

- `interrupt/src/g1_om1_adapter.py`
- `interrupt/tools/g1_om1_cli.py`

这层只负责统一调用现有 OM1 / G1 helper：

- `g1_direct_command_fallback.py`
- `g1_watchdog_feedback.py`

它不负责唤醒，也不负责长对话，只负责给后续会话层提供统一执行面：

- 直接文本动作命令
- 静态 LED
- 呼吸灯
- 本地播报

这样后续无论采用哪种 session 入口，都会收敛成：

```text
interrupt 实时会话层
-> 本地工具 / MCP 工具
-> g1_om1_adapter
-> OM1 现有 helper
-> G1 动作 / LED / 播报
```

这一步的意义是：

- 会话层可以直接复用 OM1 已有动作与 LED 能力
- 不再把“动作控制逻辑”写死在唤醒桥接脚本里
- 后面接视觉 VLM 进入同一个 session 时，也能继续复用同一套工具出口

## 2026-04-17 会话层当前进度

`interrupt/src/agent.py` 已经开始接入本地 function tool，而不是只停留在文档设计：

- `set_led_color`
- `perform_body_action`
- `execute_robot_command_text`

这些工具当前都通过：

```text
InterruptAssistant
-> g1_om1_adapter
-> g1_direct_command_fallback.py / g1_watchdog_feedback.py
```

也就是说，会话层复用 OM1 现有 LED / 动作能力这一步已经开始落地。

当前边界仍然要明确：

- 已完成：会话层本地工具接点
- 未完成：机器人侧真实实时 session 接管麦克风与扬声器
- 未完成：唤醒前门在命中后真正切到 `interrupt` 实时会话

所以接下来主线仍然是：

1. 让唤醒前门只负责唤醒和切换
2. 让 `interrupt` 实时 session 真正跑在机器人链路里
3. 用已接好的 function tool 承担会话内 LED / 动作控制
4. 最后再把视觉 VLM 接入同一 session

## 2026-04-17 唤醒前门当前进度

`interrupt` 侧已经补了一个前门编排脚本：

- `interrupt/tools/wakeword_session_frontgate.py`

它的职责是：

```text
等待唤醒
-> 命中唤醒事件
-> 拉起 interrupt 实时 session 命令
-> session 退出
-> 回到待机
```

同时补了通用唤醒适配接口：

- `interrupt/src/wakeword_runtime.py`

以及本地 mock gate：

- `interrupt/src/mock_wakeword.py`

同时也补了一个“直接复用机器人现有三语言唤醒模块”的 factory：

- `interrupt/src/om1_wakeword_gate.py`

并新增统一启动入口：

- `interrupt/run_frontgate_session.sh`
- `interrupt/run_robot_frontgate_session.sh`

另外补了一个本地 smoke test：

- `interrupt/tools/frontgate_smoke_test.py`

这个 smoke test 的意义是先验证：

```text
前门编排
-> 唤醒事件
-> session command 拉起
-> session 退出
```

至少在进入真机前，这条控制链已经有自动化最小验证。

这意味着当前已经不只是“概念上有两阶段”，而是：

- 会话层工具出口已接好
- 唤醒前门运行器已补上
- 真实唤醒模块的接线位也已补上
- 剩下的关键工作变成“把真实三语言唤醒模块按 factory 形式接进来”

当前仍未完成的点：

- 真实机器人链路里的麦克风 / 扬声器切换
- 唤醒命中后自动收拢到单一 realtime session 进程
- 会话超时后自动优雅退出 realtime session

业务能力
  -> OM1 已有 LED
  -> OM1 已有上身手臂动作
  -> 最终需恢复 VLM 视觉聊天
```

## 最终目标补充

当前这轮并不是要做一个“只有语音、没有视觉”的临时系统。

最终目标仍然是：

```text
唤醒词
  -> 进入对话态
  -> 支持语音对话
  -> 支持打断
  -> 支持 LED / 动作
  -> 支持视觉 VLM 聊天
```

也就是说，最终机器人应同时具备：

1. 语音对话
2. 打断控制
3. LED / 动作执行
4. 视觉理解与 VLM 问答

## 为什么当前先收口“文本语音链”

因为这次现场已经证明两个问题会互相干扰：

- 旧 runtime memory 会把文本模式切回视觉模式
- 语音桥接碎片化会让动作、LED、播报判断混乱

如果在这两个底层问题还没稳定前就一起调 VLM，会很难分清：

- 是视觉输入有问题
- 还是语音链有问题
- 还是 hot reload 把配置切回旧模式

所以当前正确顺序是：

### 第一步

先把这一条链稳定：

```text
唤醒词
  -> 对话态
  -> 打断
  -> 文本送入 OM1
  -> LED / 动作 / 播报稳定执行
```

### 第二步

再把视觉输入重新挂回同一套稳定链路：

```text
唤醒词 + 语音
        + VLM 输入
  -> 同一个 OM1 模式
  -> 同时具备对话 / 动作 / LED / 视觉回答
```

## 对 VLM 的具体建议

最终不要再依赖 `config/memory/.runtime.json5` 里残留的旧视觉配置。

应该单独整理出一个“正式的目标模式”，例如：

```text
unitree_g1_voice_interrupt_vlm
```

这个模式里统一包含：

- `MockInput`
- `ConversationHistoryInput`
- `UnitreeG1CameraVLMGemini`
- `external_audio`
- `arm_g1`
- `led_g1`

这样：

- 唤醒词/打断逻辑仍由桥接层负责
- VLM 仍由 OM1 模式内输入负责
- 动作/LED/播报仍由 OM1 action 负责

## 当前结论

VLM 不是后面“另起一个项目”再做，而是当前这套链路收口后要自然并回来的下一阶段工作。

## 已确认的机器人侧现状

### 关键目录

- 机器人总代码目录：
  - `/home/unitree/HongTu`
- OM1 工程：
  - `/home/unitree/HongTu/OM1`
- 唤醒词工程：
  - `/home/unitree/g1-wakeword`
- OM1 语音桥接脚本：
  - `/home/unitree/HongTu/OM1/scripts/wakeword_adaptive_to_om1.py`
  - `/home/unitree/HongTu/OM1/scripts/voice_command_session_to_om1.py`
  - `/home/unitree/HongTu/OM1/scripts/wakeword_followup_helpers.py`

### 关键环境

- 机器人默认 Python：
  - `/home/unitree/miniforge3/bin/python3`
- 已有环境：
  - `/home/unitree/miniforge3/envs/om1`
  - `/home/unitree/miniforge3/envs/wakeword-clean`

### OM1 当前入口方式

当前 `OM1` 并不是直接吃实时音频，而是通过 `MockInput` 吃外部文本输入：

- [send_mock_input.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/HongTu/OM1/scripts/send_mock_input.py)

这意味着：

```text
唤醒词/语音桥接脚本
  -> 把文本发到 OM1 的 websocket
  -> OM1 再驱动 Gemini / arm / led
```

所以打断功能最合理的接入点不是改 OM1 主体，而是改“唤醒词到 OM1”的桥接层。

## 当前桥接链路

当前机器人侧已经存在：

```text
g1-wakeword/wakeword_adaptive.py
  -> HongTu/OM1/scripts/wakeword_adaptive_to_om1.py
  -> HongTu/OM1/scripts/send_mock_input.py
  -> OM1 MockInput
  -> OM1 的 Gemini / arm / led
```

这条链已经证明：

- 唤醒词可识别
- 文本可送到 OM1
- OM1 已能驱动机器人动作和 LED

所以这次最小改造只需要增强桥接层的状态管理。

## 为什么这次不直接搬本地 interrupt 到机器人

本地 `interrupt` 项目已经验证了“支持打断的会话逻辑”，但机器人现有系统并不是 LiveKit console 直跑链路，而是：

```text
唤醒词工程 + OM1 + MockInput
```

如果现在整套替换成 `interrupt`，会同时引入：

- 机器人音频链路重做
- OM1 接口重做
- 动作/LED 接口重做
- 唤醒词系统重做

这会破坏当前已经能工作的机器人侧链路，不符合“只迁移打断功能”的要求。

## 正确的最小改造方式

### 状态机

需要补一个轻量状态机，工作方式如下：

```text
IDLE
  -> 命中唤醒词
  -> 进入 DIALOG
  -> 回复“我在，请说”

DIALOG
  -> 普通输入：直接转发给 OM1
  -> 打断词：执行打断逻辑
  -> 超时：回到 IDLE
```

### 两类词

#### 1. 会话唤醒词

用于从待机进入对话：

- 普通话：`笨笨同学` / `笨笨`
- 粤语：已有现成词表
- 英语：已有现成词表

#### 2. 打断词

用于在对话态、尤其是播报态打断当前输出：

- `笨笨同学，先别说了`
- `笨笨同学，等一下`
- `笨笨同学，停一下`
- `笨笨同学，暂停`

注意：

- 打断词建议做成“唤醒词 + 命令词”
- 不建议当前阶段只靠自然插话检测
- 这样更稳，更适合机器人真实部署

## 第一阶段建议实现

### P0：桥接层支持会话态

目标：

- 唤醒后进入短时对话态
- 对话态里不用重复每句话都说完整唤醒词

行为：

- `笨笨同学`
  - 回复：`我在，请说`
  - 进入对话态
- 对话态内普通句子
  - 直接转发给 OM1
- 对话态超时
  - 自动回到待机

### P1：桥接层支持打断词

目标：

- 在不动 OM1 主体的前提下，优先把“打断词”做稳

行为：

- 在对话态内识别：
  - `笨笨同学，先别说了`
  - `笨笨同学，等一下`
- 命中后：
  - 尝试触发当前播报终止
  - 回固定确认句：
    - `好的，那您还有其他需求吗？`
  - 保持在对话态，等待下一轮内容

### P2：是否需要程序级停播

这里需要分两种情况：

1. **如果 OM1 在收到新 MockInput 时会中断当前播报**
   - 只需在桥接层发新的控制文本即可

2. **如果 OM1 不会中断当前播报**
   - 还需要继续查外部音频播放器或 TTS 进程的中止入口
   - 但这一步应尽量晚做，先验证 MockInput 是否已经足够

## 建议改动的文件

### 机器人侧优先改这三个

1. `~/HongTu/OM1/scripts/wakeword_followup_helpers.py`
   - 扩展为“对话会话状态 + 打断词判断”

2. `~/HongTu/OM1/scripts/wakeword_adaptive_to_om1.py`
   - 当前主要负责唤醒词识别和一次性 follow-up
   - 需要改成“会话态桥接”

3. `~/HongTu/OM1/scripts/voice_command_session_to_om1.py`
   - 当前更像“唤醒后只采一轮命令”
   - 后续可按需要并入对话态逻辑，或保持备用

### 明确不动的

- OM1 主体核心代码
- OM1 的 arm / led connector
- 机器人现有动作代码
- 机器人现有 LED 控制代码

## 本地可先做的事

因为当前不要直接改机器人主体，建议先在本地完成：

1. 设计桥接层状态机
2. 实现：
   - 会话态
   - 打断词检测
   - 超时退出
3. 明确 OM1 文本转发的控制文本格式
4. 最后再把最小改动迁回机器人

## 当前最合理的下一步

### 步骤 1

先把本地状态机和打断词解析做成独立 helper。

### 步骤 2

在机器人桥接脚本里替换掉当前“只支持唤醒后一次跟随命令”的逻辑。

### 步骤 3

联调下面这个闭环：

```text
笨笨同学
  -> 我在，请说
  -> 用户下发动作或 LED 命令
  -> OM1 执行动作/灯光
  -> 用户说：笨笨同学，先别说了
  -> 打断并继续下一轮
```

## 风险点

### 1. 打断“停播”是否真的能中断当前 TTS

这取决于 OM1 收到新的 MockInput 后，是否会抢占当前播报。

这件事需要联调验证，不能只靠代码猜。

### 2. 音频误触发

桥接层进入“对话态”后，会把后续识别文本直接转给 OM1。

这意味着：

- 如果环境噪声较大，可能把噪声误判成 follow-up
- 当前阶段更适合先用“唤醒词 + 打断词”的显式命令做稳定版本

## 2026-04-16 已完成落地

### 已在机器人上部署的文件

- `/home/unitree/HongTu/OM1/scripts/wakeword_followup_helpers.py`
- `/home/unitree/HongTu/OM1/scripts/wakeword_adaptive_to_om1.py`

### 本次脚本改动点

1. `wakeword_followup_helpers.py`
   - 新增 `WakewordDialogueController`
   - 支持：
     - 唤醒后进入对话态
     - 对话态内 follow-up 直接转发
     - `唤醒词 + 打断短语` 命中后触发打断事件
     - 对话态超时自动退出

2. `wakeword_adaptive_to_om1.py`
   - 从“一次性 wake + follow-up”改为“会话态桥接”
   - 新增本地播报 `LocalReplySpeaker`
   - 唤醒时本地播报：`我在，请说`
   - 打断时：
     - 向 OM1 发送停播控制文本
     - 本地播报：`好的，那您还有其他需求吗？`
   - 新增自动网卡选择：
     - 优先选当前 `UP` 的 `wlan0/eth0/eth1`

## 机器人侧已验证结果

### 已通过

1. 脚本语法检查通过
   - `python3 -m py_compile .../wakeword_followup_helpers.py .../wakeword_adaptive_to_om1.py`

2. 对话状态机逻辑通过

验证序列：

```text
笨笨同学
-> wake_ack

把灯变成蓝色
-> forward_followup

笨笨同学，先别说了
-> interrupt

帮我挥手
-> forward_followup
```

3. 机器人本地播报链路通过

实际验证结果：

```text
[Bridge] Local TTS ready interface=eth0 speaker_id=0 volume=80
[Bridge] local_reply=桥接脚本本地播报测试 tts_ret=0
```

这说明：

- 唤醒应答和打断确认可以不经过 OM1 主对话链路
- 可以直接由机器人板载播报负责

## 2026-04-16 最新问题定位

### 1. LED 不响应的根因

不是 LLM 或 LED connector 出错，而是桥接没有连上 OM1。

现场日志已经明确显示：

```text
ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 8766)
```

机器人现场检查结果：

- `8766` 端口未监听
- 没有 OM1 `src/run.py` 进程

这说明当时只启动了桥接，没有启动 OM1 主程序。

### 2. 当前“我在，请说”为什么走了机器人默认扬声器

这是桥接脚本的本地回复，不是 OM1 的 `external_audio` 主播报。

也就是说：

- `我在，请说`
- `好的，那您还有其他需求吗？`

这两句之前走的是桥接里的板载 TTS，不是 OM1 的外接音频输出。

### 3. 外接 USB 声卡已经确认

机器人现场设备清单：

```text
card 2: audio [mvsilicon B1 usb audio], device 0: USB Audio
```

这就是当前要优先使用的外放设备。

## 新增修正

桥接脚本现已补充：

1. 本地回复后端可选
   - `external`
   - `onboard`
   - `console`
   - `none`

2. `external` 模式下
   - 优先用 `espeak --stdout`
   - 再通过 `aplay -D plughw:CARD=audio,DEV=0` 一类 ALSA 设备播放
   - 默认优先匹配 `mvsilicon / B1 usb audio / usb audio`

3. OM1 未启动时
   - 桥接层先做端口探测
   - 只输出简短错误
   - 不再抛整屏 websocket traceback

## 当前仍需现场闭环验证

只剩一个关键未知点：

### OM1 是否会被新的 MockInput 真正抢占

打断事件发生时，桥接脚本现在会向 OM1 发送：

```text
请停止当前播报，等待我的下一条指令。
```

如果 OM1 / external audio 在收到新文本时会抢占当前播报，那么这条链路就闭环了。

如果不会抢占，那么下一步要补的是：

- 找到 OM1 当前 external audio / TTS 的显式 stop 接口
- 让桥接脚本在打断事件时先 stop，再播报确认句

## 明天建议的现场测试命令

### 1. 启动 OM1

在机器人上：

```bash
cd /home/unitree/HongTu/OM1
/home/unitree/miniforge3/envs/om1/bin/python src/run.py unitree_g1_text_arm_led_external_audio_gemini
```

### 2. 启动唤醒词桥接

另开一个终端，在机器人上：

```bash
cd /home/unitree/HongTu/OM1
/home/unitree/miniforge3/envs/wakeword-clean/bin/python scripts/wakeword_adaptive_to_om1.py \
  --enable-local-tts \
  --tts-interface auto \
  --wakeword 笨笨同学 \
  --wakeword 笨笨 \
  --wakeword Benben \
  --interrupt-phrase 先别说了 \
  --interrupt-phrase 等一下 \
  --interrupt-phrase 停一下 \
  --interrupt-phrase 暂停 \
  --interrupt-phrase wait \
  --interrupt-phrase stop
```

说明：

- `--wakeword` 可以重复传，三语都可以一起配
- `--interrupt-phrase` 也可以重复传，后续如果你改唤醒词或改打断词，这里一起改即可
- 如果不传 `--wakeword`，桥接层会退回使用原唤醒词系统里的内置词表

### 3. 联调口令

按下面顺序测：

```text
笨笨同学
把灯变成蓝色
笨笨同学，先别说了
帮我挥手
```

### 4. 判定标准

成功标准：

- 说 `笨笨同学` 后，机器人本地播报 `我在，请说`
- `把灯变成蓝色` 能正常送入 OM1
- 说 `笨笨同学，先别说了` 后，当前播报停止或被明显抢占
- 机器人本地播报 `好的，那您还有其他需求吗？`
- 紧接着 `帮我挥手` 能继续执行

失败分支：

- 如果本地播报正常，但 OM1 旧播报不停
  - 说明“显式停播接口”还需要补
- 如果 follow-up 没有进入 OM1
  - 优先检查麦克风设备和当前 ASR 分块

## 当前结论

到 2026-04-16 为止，已经不是“方向不清”的阶段了。

现在架构已经确定为：

```text
唤醒词 / 三语言 ASR
  -> 会话态桥接脚本
  -> OM1 MockInput
  -> OM1 动作 / LED / 对话

唤醒应答 / 打断确认
  -> 机器人板载本地播报
```

剩余工作不再是大改架构，而是完成“打断时 OM1 旧播报是否被真正抢占”的最后闭环。

## 2026-04-16 最终现场结论补充

### 一. `LED` 不响应的真实原因

这次已经排查清楚，不是单一问题，而是两层问题叠加：

1. **桥接启动时，OM1 没有运行**
   - 现场报错：

   ```text
   ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 8766)
   ```

   含义：

   - `MockInput` websocket 没启动
   - 桥接识别到了文本，但无法把文本发给 OM1

2. **OM1 启动后，机器人动作/LED 网卡配置错误**
   - 默认配置使用 `eth1`
   - 但当前 G1 现场可用网卡应使用 `eth0`

   错误日志：

   ```text
   eth1: does not match an available interface
   Failed to initialize G1 Arm Action Client
   Failed to initialize G1 LED connector
   ```

### 二. 已确认可用的正确运行方式

OM1 必须以 `eth0` 启动。

正确日志特征：

```text
Using eth0 as the Unitree Network Ethernet Adapter
Mock Input webSocket server started at ws://127.0.0.1:8766
G1 Arm Action Client initialized successfully
G1 LED connector initialized successfully
```

### 三. `LED` 链路已实测闭环

已直接绕过麦克风桥接，用文本注入验证：

```bash
/home/unitree/HongTu/OM1/.venv/bin/python /home/unitree/HongTu/OM1/scripts/send_mock_input.py '把灯变成蓝色'
```

OM1 日志确认：

```text
本轮新输入: Voice: 把灯变成蓝色
本轮动作: speak=好的，我把灯变成蓝色。 | led_color=blue
Set G1 LED color to blue -> (0, 0, 255)
```

这说明：

- LLM 理解没有问题
- LED connector 已恢复正常
- 如果后续语音说“把灯变成蓝色”仍不生效，优先排查的是桥接识别质量，不是 LED 模块

### 四. 外接音频设备已确认

现场 `aplay -l` / `arecord -l` 结果显示：

```text
card 2: audio [mvsilicon B1 usb audio], device 0: USB Audio
```

这就是当前外接收音和外放设备。

### 五. 为什么之前外放总走默认扬声器

原因分两部分：

1. 桥接本地回复：
   - `我在，请说`
   - `好的，那您还有其他需求吗？`

   这两句原先走的是桥接脚本内部的板载 TTS，不走 OM1 的 `external_audio`

2. OM1 主播报：
   - 原配置虽然叫 `external_audio`
   - 但外部播放器选择和设备绑定不稳定

### 六. 外放策略最终收敛

#### 桥接本地回复

桥接脚本已改为支持：

- `--local-reply-backend external`
- 本地回复使用 `espeak`
- 不再强行直打板载扬声器

#### OM1 主播报

`unitree_g1_text_arm_led_external_audio_gemini.json5` 已改为：

- `speak.connector = external_audio`
- `backend = espeak`

现场启动日志确认：

```text
External audio TTS backend: espeak
```

### 七. 为什么不再用 `aplay` 直打 USB 硬件

现场已经确认：

- `pulseaudio` 正在接管 USB 声卡
- 默认 sink 已经是 USB 设备

现场结果：

```text
Default Sink: alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
```

同时：

```text
/dev/snd/pcmC2D0p  被 pulseaudio 占用
```

因此：

- 不能稳定地再用 `aplay -D plughw:CARD=audio,DEV=0` 抢设备
- 更稳的做法是让 `espeak` 走系统默认 Pulse 输出
- 而系统默认 Pulse 输出已经是外接 USB 声卡

### 八. 当前机器人后台运行状态

本轮联调结束时，机器人后台 OM1 已启动。

当时进程号：

```text
OM1 PID: 76878
```

日志文件：

```text
/tmp/om1_g1_external_eth0.log
```

如需停止：

```bash
kill 76878
```

### 九. 当前推荐测试方式

#### 1. 先确保 OM1 以 `eth0` 运行

```bash
cd /home/unitree/HongTu/OM1
UNITREE_ETHERNET=eth0 uv run --no-sync src/run.py unitree_g1_text_arm_led_external_audio_gemini
```

或后台方式：

```bash
cd /home/unitree/HongTu/OM1
UNITREE_ETHERNET=eth0 nohup uv run --no-sync src/run.py unitree_g1_text_arm_led_external_audio_gemini >/tmp/om1_g1_external_eth0.log 2>&1 &
```

#### 2. 再启动桥接

```bash
cd /home/unitree/HongTu/OM1
/home/unitree/miniforge3/envs/wakeword-clean/bin/python scripts/wakeword_adaptive_to_om1.py \
  --enable-local-tts \
  --local-reply-backend external \
  --wakeword 笨笨同学 \
  --wakeword 笨笨 \
  --wakeword Benben \
  --interrupt-phrase 先别说了 \
  --interrupt-phrase 等一下 \
  --interrupt-phrase 停一下 \
  --interrupt-phrase 暂停
```

#### 3. 观察 OM1 日志

```bash
tail -f /tmp/om1_g1_external_eth0.log
```

### 十. 明天继续时优先级

已经不用再排查：

- `MockInput` 端口是否存在
- `LED` connector 是否可用
- `arm` connector 是否可用
- 外接 USB 声卡是否存在

明天继续时只需要收口这两个点：

1. 语音桥接识别质量是否足够稳定
   - 比如“把灯变成蓝色”是否总能整句识别，而不是被切成“把。”、“灯变成蓝色。”

2. 打断是否能真正抢占当前播报
   - 也就是：
   - `笨笨同学，先别说了`
   - 是否能让当前 OM1 播报被及时打断

## 2026-04-16 补充修正二

### 十一. `400 Bad Request` 日志的来源

现场多次出现：

```text
connection rejected (400 Bad Request)
```

这不是 OM1 主体故障，也不是 websocket 服务坏了。

这是桥接层之前在转发前做了一个普通 TCP 探测，命中了 websocket 服务端的“非握手连接”日志。

结论：

- 这些 `400 Bad Request` 日志本身不是主故障
- 它们只是噪音

### 十二. 当前新的主要问题是“语音碎片化”

现场日志已经说明：

```text
Received message: 播报一下。
Received message: 在行圳天气。
Received message: 同学。
Received message: 把灯变为蓝色。
```

这说明桥接层把一条完整指令切成了多段 ASR 碎片，并且都直接送给了 OM1。

直接后果：

- OM1 收到大量不完整短句
- LLM 行为变得不稳定
- 动作、LED、播报触发率下降

### 十三. 已增加桥接层“碎片合并”

桥接脚本已经新增：

1. 对话态 follow-up 短句缓存
2. 静默后再合并转发
3. 唤醒词残片过滤

例如：

```text
播报一下。
深圳的天气。
```

现在会先缓存，再合并成：

```text
播报一下。深圳的天气。
```

而像：

```text
同学。
笨笨同学。
```

会被当作唤醒词残片直接丢弃，不再送进 OM1。

### 十四. 当前桥接新增参数

桥接脚本现在支持：

```text
--followup-flush-timeout
--min-forward-chars
```

默认策略：

- `followup_flush_timeout = 0.8s`
- `min_forward_chars = 4`
- `chunk_duration = 0.8s`

作用：

- 等待短时间，把连续识别片段拼起来
- 过短垃圾短句不往 OM1 发
- 明显的短控制命令直接立即 flush，不再傻等

### 十五. 现在的测试重点

下一轮不必再重点看：

- `400 Bad Request`

下一轮重点改看：

1. 桥接日志里是否出现：

```text
buffered_followup=...
merged_followup=...
drop_residue=...
```

2. OM1 是否收到更完整的句子，例如：

```text
播报一下深圳的天气。
把灯变成蓝色。
```

而不是继续收到：

```text
播报一下。
同学。
把针据。
```

如果机器人外放和拾音物理隔离不好，打断词容易被机器人自己播报回灌。

### 3. 会话态太长会误触发

所以对话态必须有超时退出，不应无限常驻。

## 结论

今天已经确认：

```text
机器人侧“只迁移打断功能”的正确接入点
不是 OM1 主体
而是 g1-wakeword -> *_to_om1.py 这层桥接逻辑
```

后续继续推进时，优先做：

1. 对话态状态机
2. 打断词检测
3. 打断后固定确认话术
4. 保持下一轮对话能力

不要先去重构 OM1。

## 2026-04-17 现场推进补充

当前机器人现场已经确认：

- 二阶段会话麦克风输入已通
- `user_input_transcribed` 能持续看到
- `agent_state_changed: listening -> speaking` 能看到
- `console audio compat output callback` 也能看到 `rendered>0`

但 USB 音频外放链路仍不稳定，现场表现为“模型已经开始说话，但人听不到”。

为保证机器人必须能听到回复，`interrupt/src/agent.py` 已增加兜底策略：

- 监听 `conversation_item_added`
- 当 item 为 `assistant` 且有文本内容时
- 直接调用 OM1 本地 `g1_watchdog_feedback.py --mode speak`
- 这样即使 PortAudio/LiveKit 控制台播放链临时失效，机器人仍会把回复播出来

默认开关：

```text
INTERRUPT_MIRROR_ASSISTANT_SPEECH_TO_OM1=1
```

如后续 USB 会话外放已经完全稳定，需要关闭双播报，可显式设置：

```text
INTERRUPT_MIRROR_ASSISTANT_SPEECH_TO_OM1=0
```

下一轮现场验证，不再只盯 `rendered=`，而是同时看：

```text
conversation_item_added: role=assistant ...
OM1 本地播报 assistant 回复成功 ...
```

只要这两行出现，就算 USB 会话播报没响，机器人也应当能通过 OM1 本地 TTS 把回复说出来。

## 2026-04-17 收尾状态

今天现场已经确认过的事实：

- 二阶段会话输入是通的
- `user_input_transcribed`、`speech_handle item_added`、`conversation_item_added`
  都已经能看到
- OM1 本地播报兜底已经能把 assistant 回复说出来

今天后半段为排障加入过几项实验性改动：

- 默认禁用 session speaker
- 默认把 `user_away_timeout` 改成 60 秒
- assistant 文本播报前做额外空格清洗
- 动作工具增加基于最近转写的硬校验

由于现场表现开始反复，以上实验性运行时改动已先回退，避免继续在机器人上叠加变量。

当前建议的停点：

- 保留最基础的 console audio compat 输入兼容补丁
- 保留 OM1 本地播报兜底和调试日志
- 其余运行时策略明天再重新逐项验证，不在今天继续混改
