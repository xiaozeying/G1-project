# interrupt WebRTC 全双工迁移分析

更新时间：2026-04-21

## 1. 文档目标

本文档用于回答以下工程问题：

1. 当前机器人语音链路到底是什么架构。
2. 如果迁移到 WebRTC 全双工实时通讯，目标架构应该长什么样。
3. 哪些模块应保留，哪些模块需要替换。
4. 迁移的可行性、风险、成本、收益分别是什么。
5. 推荐的工程实施顺序是什么。

本文档不是概念性讨论，而是面向当前项目代码与真机现状的工程迁移分析文档。

---

## 2. 当前实际架构

### 2.1 当前主链路

当前真机主链路不是浏览器 WebRTC，也不是 LiveKit 房间式媒体传输，而是：

```text
用户
  -> 机器人麦克风 / USB 声卡
  -> 前门唤醒层
     - tools/wakeword_session_frontgate.py
     - src/om1_wakeword_gate.py
     - 外部 wakeword_adaptive.py
  -> 本地会话拉起
     - run_robot_frontgate_session.sh
     - run_local_voice_agent.sh
     - python -m src.agent console
  -> LiveKit Agents console mode
     - src/console_audio_compat.py
     - AgentSession
     - Gemini Live Realtime
  -> 工具层
     - src/g1_om1_adapter.py
     - 本地天气工具
     - LED / 动作 / 本地 TTS
  -> 机器人扬声器 / OM1 本地播报
```

### 2.2 当前模块分层

```text
A. 唤醒前门层
  - tools/wakeword_session_frontgate.py
  - src/om1_wakeword_gate.py
  - 外部三语言唤醒脚本

B. 会话媒体层
  - run_local_voice_agent.sh
  - python -m src.agent console
  - src/console_audio_compat.py
  - PortAudio / 本机音频设备

C. Agent 编排层
  - src/agent.py
  - turn handling
  - interruption / user_away / LED 状态

D. 工具执行层
  - src/g1_om1_adapter.py
  - 天气工具
  - LED / 动作 / 直接命令

E. 反馈呈现层
  - OM1 本地 TTS 镜像
  - G1 LED
  - G1 动作
```

### 2.3 当前架构的工程特征

- 音频采集与播放完全在机器人本机完成。
- `src.agent` 通过 LiveKit Agents `console mode` 运行单机会话。
- 实时模型是 Gemini Live，但媒体层不是浏览器 WebRTC。
- 语音回复主链路实际上有两套：
  - LiveKit console 输出链路
  - OM1 本地 TTS 镜像兜底链路
- 稳定性瓶颈主要集中在：
  - `console_audio_compat` 输入流停摆
  - 会话中途打断导致回答未完整播出
  - 模型工具调用被取消或串台

---

## 3. 当前架构的问题边界

### 3.1 当前已经能做的事

- 唤醒前门可工作。
- 唤醒后可进入实时会话。
- 灯光控制、动作控制已接入本地执行层。
- 部分实时天气查询已通过本地工具恢复。
- LED 状态反馈、away 超时回蓝等逻辑已基本成型。

### 3.2 当前持续存在的问题

- `console mode` 本地音频输入流有概率停摆，导致多轮后漏收音。
- 回声消除能力不如浏览器/WebRTC 成熟。
- 回答在生成或播报阶段被打断时，现场可能“日志有结果，用户没听到”。
- 媒体层、业务层、机器人本地反馈层耦合偏深，后续扩展成本高。
- 想接网页端、远程调试、多端旁听时，当前链路不够自然。

### 3.3 当前问题是否意味着必须立刻切 WebRTC

不是。

当前系统的问题主要出在“本地 console 音频层的稳定性”，不代表工具层、唤醒层、Agent 编排层本身都要重做。  
因此迁移策略必须是“替换媒体层”，不是“重写整个系统”。

### 3.4 当前收口中的语言策略

在 2026-04-24 这一轮收口里，`src.agent` 新增了一条“自适应多语言回答”策略，目标不是让机器人固定说某一种语言，而是尽量跟随用户最近一次输入的语言回答：

- 用户说普通话：默认用普通话回答
- 用户说粤语：默认用粤语口语回答
- 用户说英语：默认用英语回答
- 用户明确说“之后都用粤语 / 普通话 / 英语回答”时，进入显式锁定模式
- 用户再说“恢复自动”时，切回自动跟随

这一层目前仍然属于 `Agent 编排层` 的策略，而不是媒体层能力，因此和 WebRTC 全双工迁移并不冲突。

当前实现方式是：

- 在 `user_input_transcribed` / `conversation_item_added` 时做轻量语言判断
- 用最近一次用户语言作为回复偏好
- 本地工具前置播报（动作、灯光、新闻、天气）也尽量跟随该语言

需要注意的现实边界：

- 普通话 / 英语切换通常比较稳
- 粤语的难点不在“能不能切过去”，而在“是否足够地道”
- 因此粤语体验仍可能需要后续继续补提示词和 rewrite 规则

---

## 4. 目标架构：WebRTC 全双工

### 4.1 目标架构图

```text
用户
  -> 机器人麦克风 / 机器人音频终端
  -> WebRTC 上行音频
  -> LiveKit Room
  -> Agent Runtime
     - Gemini Live Realtime
     - Tool Routing
     - Session State
  -> LiveKit Room
  -> WebRTC 下行音频
  -> 机器人扬声器 / 远程客户端
```

### 4.2 更完整的目标分层

```text
A. 唤醒前门层
  - 保留

B. 机器人 RTC 终端层
  - 采集机器人麦克风
  - 播放下行语音
  - 加入 LiveKit Room
  - 负责 publish / subscribe

C. LiveKit 房间媒体层
  - WebRTC signaling
  - 上下行媒体流
  - 抖动缓冲 / 重传 / 网络适配

D. Agent 编排层
  - src.agent
  - Gemini Live
  - turn handling
  - tools

E. 工具执行层
  - G1 / OM1 adapter
  - 天气 / 新闻 / 搜索
  - 机器人动作 / 灯光

F. 反馈层
  - 房间主播报
  - LED 状态
  - OM1 本地 TTS 兜底或短提示
```

---

## 5. 当前架构与目标架构的核心差异

### 5.1 媒体层差异

当前：

```text
本机麦克风
  -> PortAudio
  -> console audio compat
  -> AgentSession
  -> PortAudio
  -> 本机扬声器
```

目标：

```text
本机麦克风
  -> WebRTC Publisher
  -> LiveKit Room
  -> Agent
  -> LiveKit Room
  -> WebRTC Subscriber
  -> 本机扬声器
```

### 5.2 职责差异

当前 `console_audio_compat.py` 实际承担了：

- 输入流兼容
- 输出流兼容
- AEC 相关处理
- watchdog 重启
- 将音频帧接入 `AgentSession`

目标架构中，这些职责将被重新拆到：

- 机器人 WebRTC 终端
- LiveKit 房间媒体层
- WebRTC 原生音频栈

### 5.3 会话控制差异

当前：

- 唤醒命中后拉起 `run_local_voice_agent.sh`
- `python -m src.agent console`
- 会话结束后前门回待机

目标：

- 唤醒命中后：
  - 拉起机器人 RTC endpoint，或
  - 通知常驻 endpoint 入房，或
  - 唤醒 agent / room session
- 会话结束后：
  - endpoint 退房，或
  - endpoint 常驻但房间空闲

也就是说，迁移后“会话开始/结束”控制策略必须重做。

---

## 6. 哪些模块应该保留

这些模块属于“业务资产”，不应在媒体迁移时推倒重来。

### 6.1 唤醒前门层保留

- `tools/wakeword_session_frontgate.py`
- `src/om1_wakeword_gate.py`
- 现有唤醒回待机状态机

原因：

- 这层与 WebRTC 无强绑定。
- 它的职责是“是否进入会话”，不是“音频如何传输”。

### 6.2 Agent 业务规则保留

- `src/agent.py` 中的：
  - LED 状态逻辑
  - away timeout
  - fastpath
  - tool guard
  - 本地确认播报
  - 本地天气工具接入

原因：

- 这些是业务层逻辑，与媒体层替换无关。
- 如果迁移时把这些一起改，会极大扩大故障面。

### 6.3 工具执行层保留

- `src/g1_om1_adapter.py`
- G1 / OM1 动作 / 灯光 / speak
- 天气工具

原因：

- 这些能力在媒体迁移后仍然要用。
- 不应该因为切 WebRTC 就重写机器人控制层。

### 6.4 反馈层部分保留

- LED 反馈保留
- OM1 本地短确认播报保留

但要注意，完整回答的主播报路径在未来应重新定义。

---

## 7. 哪些模块需要替换或重构

### 7.1 会话入口脚本需要改造

当前：

- `run_local_voice_agent.sh`
- `python -m src.agent console`

目标：

- 新的 RTC 入口脚本
- room / rtc 模式启动 agent
- 机器人音频终端单独进程

### 7.2 console 音频兼容层将不再是主路径

当前：

- `src/console_audio_compat.py` 是核心补丁

目标：

- 它应降级为“开发调试模式补丁”
- 正式真机链路不再依赖它作为主媒体层

### 7.3 机器人音频终端需要新增

当前缺少以下独立模块：

- 机器人 WebRTC 客户端
- 音频发布/订阅模块
- 房间生命周期管理模块

这些在迁移中必须新增。

---

## 8. 更工程化的迁移图

### 8.1 总体迁移路线

```text
阶段0：稳定当前 console 方案
  - 不改架构
  - 继续修业务稳定性

阶段1：抽象媒体传输接口
  - 从业务代码里抽离 console 特性

阶段2：引入 LiveKit Room 版 Agent
  - 先让 Agent 不依赖 console mode

阶段3：实现机器人 RTC endpoint
  - 真正替换本机 console 音频

阶段4：统一主播报路径
  - 决定主播报走 WebRTC 还是 OM1 本地

阶段5：正式切换
  - 真机链路改为 WebRTC 主路径
  - console 降为调试模式
```

### 8.2 阶段 0：稳定当前 console 方案

```text
保持:
  唤醒前门
  console agent
  工具层
  LED / 动作 / 本地播报

目标:
  在迁移前把业务问题收敛到“媒体层问题”
```

为什么必须先做这一步：

- 如果当前业务层本身不稳，迁移后无法判断是新媒体层问题，还是旧业务问题。
- 迁移必须建立在“动作、灯光、天气、状态机大体可信”之上。

### 8.3 阶段 1：抽象媒体传输接口

建议新增抽象：

```text
Transport Layer
  - ConsoleTransport
  - RoomTransport
```

目标：

- 让 `src.agent` 的业务层不直接假设“我一定跑在 console mode”
- 将 console 专属代码尽量下沉

建议抽象职责：

- 会话建立
- 音频输入接入
- 音频输出接入
- transcript 接入
- session 生命周期事件

### 8.4 阶段 2：引入 Room 版 Agent

这一阶段不要先改机器人音频，只改 agent 运行形态：

```text
Agent
  从:
    python -m src.agent console
  改成:
    room / rtc 模式
```

目标：

- 验证在 LiveKit Room 中：
  - 打断逻辑是否还成立
  - tool routing 是否一致
  - LED 状态机是否仍可工作
  - away / timeout 机制是否需要重映射

交付物：

- 新启动脚本
- Room 模式 agent 入口
- 基础联调方式

### 8.5 阶段 3：实现机器人 RTC Endpoint

这一阶段才是真正替换媒体层。

建议新增模块：

```text
robot_rtc_endpoint/
  - capture.py
  - playback.py
  - room_client.py
  - session_controller.py
```

职责：

- 采集机器人麦克风
- 加入房间并发布音频
- 订阅 agent 下行音频
- 回放到机器人扬声器
- 向前门暴露“加入/退出会话”的控制接口

### 8.6 阶段 4：统一播报路径

这是迁移中非常关键的一步。

必须明确以下策略之一：

#### 方案 A：主播报走 WebRTC

```text
Agent回答
  -> LiveKit Room
  -> Robot RTC endpoint
  -> 机器人扬声器

OM1 本地 TTS
  -> 仅用于短确认 / 唤醒提示 / 兜底
```

优点：

- 主媒体链统一
- 时序更清晰
- 更接近标准语音通话系统

缺点：

- 机器人端 WebRTC 回放要稳定
- OM1 本地 speak 的价值缩小

#### 方案 B：主回答仍走 OM1 本地 TTS

```text
Agent回答文本
  -> OM1 本地镜像 TTS

WebRTC
  -> 主要用于上行收音 / 远程监控
```

优点：

- 复用当前 OM1 本地播报路径
- 回答文本可控

缺点：

- 两套播报链并存
- 时序更复杂
- 更容易出现重复播报、抢占、回声问题

工程上更推荐方案 A。

### 8.7 阶段 5：正式切换

正式切换后的主链路：

```text
Wake Gate
  -> Robot RTC Endpoint
  -> LiveKit Room
  -> Agent
  -> Tools
  -> LiveKit Room
  -> Robot RTC Endpoint
```

此时：

- `console_audio_compat.py` 退出真机主链路
- `run_local_voice_agent.sh` 保留给开发自测
- 真机联调以房间模式为主

---

## 9. 可行性分析

## 9.1 技术可行性

结论：可行，而且技术路径清晰。

理由：

- 当前系统已经完成了：
  - 唤醒前门
  - Agent 业务规则
  - 工具层
  - 反馈层
- 真正未标准化的是“媒体层”
- LiveKit 本身就是为 WebRTC 房间媒体传输设计的

因此，本项目并不是“从零做 WebRTC 机器人”，而是“把已有业务系统的媒体层替换成 WebRTC”

这在工程上是可行的。

## 9.2 架构可行性

结论：高可行，但必须分阶段。

理由：

- 当前业务层和工具层已成型
- 唤醒层与媒体层耦合有限
- 可以先保留前门，再逐步替换会话音频层

但如果试图“一步切换为 WebRTC 正式主链路”，风险会很高。

## 9.3 真机落地可行性

结论：中高可行，但受机器人端 WebRTC 客户端实现方式影响很大。

要落地，必须明确：

1. 机器人端用什么作为 WebRTC 终端  
   - 浏览器壳
   - Python LiveKit SDK
   - 自定义原生进程

2. 音频设备由谁控制  
   - 机器人 endpoint 直接控制
   - 还是继续由 OM1 音频侧控制

3. 主播报走哪条链  
   - WebRTC
   - OM1 本地 TTS

如果这三点不先定，迁移会陷入反复试错。

---

## 10. 收益分析

### 10.1 迁移到 WebRTC 后的主要收益

- 更成熟的全双工音频链路
- 更标准的音频会话架构
- 更易接入远程网页端 / 监控端
- 更适合旁听、录音、调试、可视化
- 有助于摆脱 `console_audio_compat` 这类本地补丁依赖

### 10.2 迁移后最有价值的改善点

结合当前痛点，收益最大的是：

- 降低输入流静默停摆概率
- 降低回答中途“看起来生成了但现场没播出来”的问题
- 提升打断、回声消除、双向说话时的整体稳定性

---

## 11. 风险分析

### 11.1 风险一：会话生命周期重新定义

当前前门的心智模型是：

```text
wake -> 拉本地 session -> session 结束 -> 回蓝灯
```

迁移后，可能变成：

```text
wake -> endpoint 入房 -> 房间保持 / 退房 -> 回蓝灯
```

这会影响：

- LED 状态切换
- away timeout
- 会话退出条件

### 11.2 风险二：双播报冲突

如果 WebRTC 下行和 OM1 本地 TTS 同时保留主播报能力：

- 可能重复播报
- 可能互相打断
- 可能引入额外回声

### 11.3 风险三：排障复杂度上升

当前排障大多集中在：

- 本机声卡
- console 输入流
- agent 状态机

迁移后会增加：

- 房间连接
- publish / subscribe
- track 丢失
- 网络时延
- peer 重连

### 11.4 风险四：真机端音频终端实现成本

这是迁移里最大的新增成本。

如果没有一个稳定的机器人 WebRTC endpoint，迁移就无法真正落地。

---

## 12. 成本分析

### 12.1 低成本部分

- 保留唤醒前门
- 保留工具层
- 保留 Agent 业务规则
- 保留 LED / 动作反馈逻辑

### 12.2 高成本部分

- 机器人 RTC endpoint 新实现
- 房间生命周期控制
- 主播报路径统一
- 端到端真机调试

### 12.3 最容易低估的成本

- 音频设备兼容性
- 回声与打断时序
- 真机网络环境下的媒体稳定性

---

## 13. 推荐迁移策略

推荐采用“保业务、换媒体”的策略：

### 13.1 原则

- 不改唤醒前门
- 不改工具层
- 不改大部分 `src.agent` 业务规则
- 只替换媒体层

### 13.2 推荐实施顺序

1. 继续把当前 console 方案收稳到可控状态
2. 抽象 transport 层
3. 先做 room mode agent
4. 再做 robot RTC endpoint
5. 最后统一主播报路径

### 13.3 不推荐的方式

不推荐直接：

- 一次性重写为 WebRTC 正式链路
- 同时改唤醒层、工具层、播报层、媒体层
- 在当前业务未稳的状态下强切

原因很简单：故障面会失控。

---

## 14. 建议的最终工程图

```text
[Wake Gate]
  wakeword detect
  idle/awake LED
  session start/stop

        |
        v

[Robot RTC Endpoint]
  mic capture
  speaker playback
  room join/leave
  publish/subscribe

        |
        v

[LiveKit Room]
  WebRTC signaling
  media routing
  stream lifecycle

        |
        v

[Agent Runtime]
  Gemini realtime
  interruption logic
  turn handling
  tool routing
  session state machine

        |
        v

[Tool Layer]
  G1 / OM1 actions
  LED
  weather
  news
  search

        |
        v

[Feedback Layer]
  LED feedback
  optional local fallback TTS
  logs / traces / monitoring
```

---

## 15. 当前结论

### 15.1 结论摘要

- 当前真机主链路不是 WebRTC 全双工，而是本地 console mode 音频链路。
- 项目迁移到 WebRTC 全双工在技术上可行。
- 迁移重点不在工具层，而在媒体层替换。
- 最稳妥的路线是：
  - 保留唤醒前门
  - 保留 Agent 业务规则
  - 保留工具层
  - 逐步替换 `console audio I/O` 为 `WebRTC room transport`

### 15.2 工程判断

如果目标是短期把机器人本机助手做稳，当前 console 路线仍应继续收口。  
如果目标是中长期构建“更像电话/通话系统”的全双工实时语音能力，WebRTC 迁移值得做，而且应尽早进入架构抽象阶段。

---

## 15.3 截至 2026-04-23 的真实进展

- `src/rtc_endpoint.py` 已具备真机房间接入所需的最小能力：
  - 设备名解析失败时回退到 `default/pulse`
  - 多声道输入混单声道
  - 上行轨显式以 `SOURCE_MICROPHONE` 发布
  - 真机侧增加上下行电平日志，便于现场排障
- `src/agent.py` 已在房间模式下把输入 participant 固定到 `robot-rtc-endpoint`，避免误绑到旧 agent participant。
- 真机已经验证过：
  - 房间 worker 可注册
  - 机器人 RTC endpoint 可入房
  - 用户语音可被房间模式 agent 转写
  - agent 可生成文字回复
- 2026-04-22 现场日志已证明：
  - `user_input_transcribed` 正常产生
  - `conversation_item_added: role=assistant` 正常出现
  - 机器人端可收到 agent 下行转写

### 15.4 2026-04-23 复测新增结论

- 今日首个阻塞不是机器人链路，而是开发机上的 `livekit-server --dev` 默认只监听 `127.0.0.1`。
- 对真机 / 局域网联调，必须显式使用：
  - `LIVEKIT_BIND_ADDRESS=0.0.0.0`
  - `LIVEKIT_NODE_IP=<开发机局域网 IP>`
- 今日复测重新确认：
  - room worker 可再次注册
  - 手动 dispatch 后 agent 可再次接单
  - 机器人 endpoint 可再次订阅 agent 下行音轨
- 今日尚未完全自动化验证“下行可听播报”，因为：
  - 房间文本流在 participant 绑定后不能直接等价替代真实语音输入
  - 当前最可靠的最终确认方式仍是现场说一句并听外接 USB 输出
- 2026-04-23 晚些时候已完成进一步收口：
  - 真机现场再次确认外接 USB 声卡可听到播报
  - `src/rtc_endpoint.py` 已增加 agent 断线后的自动 redispatch 守护
  - 这让 `away -> session.shutdown()` 之后不再依赖人工补 dispatch 才能恢复房间会话
  - 机器人前门默认第二阶段命令已切换为房间 wrapper，而不是旧 `run_local_voice_agent.sh`
  - 前门唤醒后会优先确保 `room agent + rtc endpoint + dispatch` 可用，再等待房间会话自然结束
- 2026-04-23 现场暴露“自打断”后，已把 endpoint 从单纯能量门控推进到参考信号 AEC：
  - `OutputPlayback.push_frame()` 会把 agent 下行音频喂给 LiveKit `AudioProcessingModule.process_reverse_stream()`
  - `MicrophonePublisher._pump()` 会对上行麦克风帧执行 `process_stream()` 后再 publish
  - 默认开启 `INTERRUPT_RTC_AEC_ENABLED=1`
  - 为保留轻声真人插话，当前未开启 noise suppression，只启用 echo cancellation + high pass filter
  - AEC 不可用时才回退到临时 ducking，避免功能硬失败
- 2026-04-23 第二轮现场修复：
  - 修正真机 `OutputPlayback.push_frame()` 下行参考帧重复喂入 AEC 的问题，避免 reverse stream 时间轴走快导致回声消除失真
  - 在 AEC 之后增加保守的 residual echo gate：只有播放活跃、raw_rms 较高、clean_rms 很低且 clean/raw 比例很小时才抑制残余回声
  - `src.agent` 的动作/灯光意图缓存从单槽改为按 payload 保留多个候选，避免连续说“挥手、鼓掌、天气”时，较早动作被后一句天气意图覆盖
  - 真机重启验证：`src/agent.py`、`src/rtc_endpoint.py` 编译通过，room agent 与 `robot-rtc-endpoint` 均重新入房，房间保持单 agent
- 2026-04-23 第三轮现场低延迟修复：
  - 动作 fastpath 从只等 `conversation_item_added final` 改为可在 partial transcript 中提前触发，命中后后台执行动作并保留 dedupe 标记，防止 final/工具调用重复执行
  - `get_news` / `get_weather` 增加最近用户意图门禁，避免 `<noise>`、数字或误转写触发新闻/天气工具
  - `INTERRUPT_MIN_ENDPOINTING_DELAY_MS=150`、`INTERRUPT_MAX_ENDPOINTING_DELAY_MS=700`、`INTERRUPT_REALTIME_PREFIX_PADDING_MS=250` 已用于真机低延迟测试
  - `INTERRUPT_RTC_PLAYBACK_PREBUFFER_MS=80` 已用于真机，启动日志确认 playback prebuffer 降到 `7056` bytes
- 同轮测试确认不要再写死 `hw:2,0`：
  - PortAudio / ALSA 卡号会漂移，`hw:2,0` 曾解析到 Jetson APE，导致麦克风 raw_rms 长时间为 0
  - 机器人 RTC 输入输出应优先用 `pulse`
  - Pulse 默认 source/sink 必须固定到外接 USB 声卡
- 2026-04-23 第四轮现场打断手感回调：
  - 不引入固定“打断词”快路径，避免把自然插话体验做窄
  - 保留 AEC、residual echo gate、新闻/天气意图门禁、动作 partial fastpath、关闭本地 query pre-ack 等已验证修复
  - 将真机 `INTERRUPT_MIN_INTERRUPTION_DURATION_MS` 从过度保守的 `180` 回拨到基线 `80`
  - 将真机 `INTERRUPT_FALSE_INTERRUPTION_TIMEOUT_MS` 从 `700` 回拨到基线 `500`
  - 将 realtime start sensitivity 从 `LOW` 恢复为 `HIGH`，让真人插话更接近前一轮好用的手感
  - 重启后日志确认：`min_interrupt=80ms false_interrupt_timeout=500ms`，房间内保持单 `robot-rtc-endpoint` + 单 agent
- 2026-04-23 第五轮前门生命周期修复：
  - 发现 `INTERRUPT_FRONTGATE_SESSION_TIMEOUT=0` 依赖房间自然退出；同时 RTC endpoint 的自动 redispatch 会让前门难以判断会话结束
  - 前门模式下启动 RTC endpoint 时临时设置 `INTERRUPT_RTC_AUTO_DISPATCH_AGENT=0` 和 `INTERRUPT_RTC_AGENT_ABSENCE_CHECK_INTERVAL_S=0`，由 frontgate wrapper 统一 dispatch
  - 前门模式下 room agent 临时设置 `INTERRUPT_USER_AWAY_TIMEOUT_MS=60000`，并增加 `INTERRUPT_FRONTGATE_ROOM_MAX_DURATION_S=180` 作为硬兜底
  - `tools/frontgate_room_session.py` 会记录自己启动的 room agent / RTC endpoint，并在会话结束、启动失败或硬超时时清理这些进程
  - 修复 room worker 尚未 registered 就 dispatch 的竞态：前门默认 `INTERRUPT_FRONTGATE_ROOM_PRE_DISPATCH_DELAY_S=12`，`INTERRUPT_FRONTGATE_ROOM_STARTUP_TIMEOUT_S=60`
  - 2026-04-24 补充收口：前门房间会话只有在 `agent + robot-rtc-endpoint` 同时进房后才判定为 `room session active`，避免 `robots=[]` 时被误判成就绪；默认 `INTERRUPT_FRONTGATE_ROOM_PRE_DISPATCH_DELAY_S` 下调到 `2s`，减少唤醒应答后前几句被启动空窗吃掉的问题
  - mock 前门回归通过：`wake_detected -> room session active -> 180s max duration reached -> stopping managed rtc-endpoint/room-agent -> idle_led blue -> wakeword>`
  - 退出后确认 LiveKit `interrupt-demo` 房间 participants 为空，无残留 agent/robot endpoint
  - 换电池后发现 Pulse 默认 source/sink 会漂移：需要重新固定到 USB source/sink，否则真实 OM1 唤醒层可能 `rms=0`
  - 今日真实 OM1 前门仍需继续调：USB 电平已恢复，但 SenseVoice 未稳定输出唤醒词转写；下一步应单独抓取唤醒音频样本调 ASR/阈值

### 15.5 当前剩余风险

- `livekit-server` 在开发模式下的监听地址需要显式配置，否则会造成“机器人完全连不上房间”的假故障。
- 机器人端当前设备解析会回退到 `default`，这依赖 Pulse 默认 source/sink 事先已指向 USB 声卡。
- AEC 刚接入，还需要继续做长播报 + 真人轻声插话回归：
  - 验证 `user_input_transcribed` 不再包含 assistant 播报内容
  - 验证真人轻声插话仍可触发打断
  - 验证 `RTC AEC capture processed` 的 clean_rms 不会把真实用户语音压没
- `RTC playback level` 仍建议保留到迁移收口阶段，用于区分：
  - agent 没有产生语音
  - 房间下行有语音但播放线程异常
  - 本地外设链路有声但人耳没听到
- 自动 redispatch 目前放在 RTC endpoint 常驻进程里，后续还要继续确认：
  - 高频断网 / 重连场景下是否会出现重复 dispatch
  - 与前门唤醒层接回后，是否需要把房间恢复策略改成由前门统一编排
- 前门当前已经能拉起房间会话，但还需要继续做真机回归：
  - 连续多轮唤醒 / 超时 / 再唤醒
  - 前门绿灯、蓝灯、wake ack 与房间会话结束时机是否完全一致
- 真实 OM1 唤醒词在换电池后仍需单独回归：
  - Pulse 默认 source/sink 可能回到 `nx_remapped_out` / 板载声卡
  - 当前已验证 USB 输入有电平，但唤醒 ASR 未稳定输出 `[zh] ...` 文本
  - 不应把 mock 前门验证等同于真实唤醒词验证

---

## 16. 后续建议

建议后续补三份配套文档：

1. `PHASE1_TRANSPORT_ABSTRACTION_PLAN.md`  
   说明如何从 `console mode` 抽 transport 层。

2. `ROBOT_RTC_ENDPOINT_DESIGN.md`  
   说明机器人 WebRTC endpoint 如何实现。

3. `ROOM_MODE_CUTOVER_TEST_PLAN.md`  
   说明迁移后的联调与回归测试方案。
