# 三语唤醒对话体验优化执行文档

> 更新时间：2026-06-05
> 范围：`interrupt` 前门唤醒 + 房间会话主链
> 目标设备：本地仓库 `/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt`
> 机器人部署目录：`/data/HongTu/interrupt`
> 当前机器人运行模式确认日期：2026-06-05

---

## 1. 文档目标

本文用于把以下四个需求收口成一份可执行实施方案：

1. 唤醒后立即拉起对话房间
2. 房间就绪后只播报同语言引导语
3. 增加显式前缀看门狗，避免自听自答/误入模
4. 大模型输出按标点切分并流式推送 TTS

本文重点回答：

- 当前仓库和机器人实际上是怎么跑的
- 四个需求分别落在哪些文件上
- 哪些需求可以直接在现有架构上改
- 哪些需求如果沿用当前线上配置将无法严格验收
- 需要改哪些文件、加哪些文件、加哪些环境变量
- 推荐实施顺序、风险点和验收办法

---

## 2. 结论先行

## 2.1 总体可行性结论

这四个需求整体可做，但不能只改文案或只改 `.env.local`。

必须同时调整三层：

- 前门唤醒层
- 房间接入/本地转写层
- room-agent 回复与播报层

## 2.2 关键架构判断

当前机器人 `/data/HongTu/interrupt/.env.local` 已确认仍在使用：

- `INTERRUPT_AGENT_BACKEND=gemini_realtime`
- `INTERRUPT_AGENT_RUNTIME_MODE=online_full`
- `INTERRUPT_FRONTGATE_ENABLE_WAKE_ACK=1`
- `INTERRUPT_FRONTGATE_ENABLE_WAKE_INTRO=1`
- `INTERRUPT_RTC_TRANSCRIBE_ENABLED=1`

这意味着：

- 需求一、二可以在当前主链上直接实现
- 需求三如果要“只有带前缀才允许进大模型”，仅靠现有 `gemini_realtime` 事件过滤不够稳，必须在 `rtc_endpoint -> room data` 这一层新增显式准入看门狗
- 需求四如果要“按标点切割后逐段 TTS”，不建议继续完全依赖 `gemini_realtime` 自带语音输出；最稳妥方案是切到 `local_text_*` 房间后端，或新增“文本流 -> 分段 TTS”自管层

## 2.3 推荐收口方案

建议分两阶段实施：

### 阶段 A：先完成需求一、二、三

保留现有房间体系：

- `tools/wakeword_session_frontgate.py`
- `tools/frontgate_room_session.py`
- `src/rtc_endpoint.py`
- `src/agent.py`

阶段 A 目标：

- 唤醒即并发拉房间
- 保留唤醒自我介绍，但不阻塞房间初始化
- 房间 ready 后只播报一条同语言引导语
- 用户发言必须带显式前缀才允许送进 room-agent

### 阶段 B：单独完成需求四

如果验收要求是“严格按标点切段并逐段 TTS，首个切割点即播”，建议把房间后端切到：

- `INTERRUPT_AGENT_BACKEND=local_text_ollama`
  或
- `INTERRUPT_AGENT_BACKEND=local_text_openai_compatible`

原因：

- 当前 `gemini_realtime` 是黑盒式实时音频输出，更适合“整体实时语音对话”
- 但不适合做“我们自己完全控制标点切段、队列、逐段 TTS 合成”的强验收

如果必须保留 `gemini_realtime`，则需求四只能做到“近似流式”，很难做到你定义的那种完全可控验收。

---

## 3. 当前实际运行链路

## 3.1 前门入口

机器人当前前门入口：

- `run_robot_frontgate_session.sh`
- systemd 入口通常指向 `run_robot_frontgate_session.sh`
- 前门唤醒进程主脚本：`tools/wakeword_session_frontgate.py`

职责：

- 等待唤醒词
- 播放 wake ack / wake intro
- 设置 LED
- 拉起房间会话命令

关键代码位置：

- `tools/wakeword_session_frontgate.py`
- `run_robot_frontgate_session.sh`

## 3.2 房间启动层

当前房间启动层脚本：

- `tools/frontgate_room_session.py`

职责：

- 拉起 `room-agent`
- 拉起 `rtc-endpoint`
- `ensure_room_ready()`
- 等待 `room-agent` 和机器人 RTC participant ready
- room ready 后播放 `room_ready_ack`

关键代码位置：

- `tools/frontgate_room_session.py`

## 3.3 本地麦克风与转写层

当前机器人麦克风和本地转写层：

- `src/rtc_endpoint.py`
- `tools/local_funasr_worker.py`
- `run_robot_rtc_endpoint.sh`

职责：

- 接 USB 麦音频
- 做本地分段录音
- 调本地 ASR worker
- 将转写结果发到房间

关键事实：

- `src/rtc_endpoint.py` 当前会把本地转写结果发布到
  - LiveKit transcription
  - `interrupt/local_text/transcript` data topic

## 3.4 room-agent 层

当前房间 agent：

- `src/agent.py`
- `run_room_agent.sh`

职责：

- 实时会话
- 接 room transcription / room data
- 决定是否回复
- 执行动作/导航/视觉等能力
- 输出语音回复

关键事实：

- 当前 `.env.local` 确认是 `gemini_realtime`
- `src/agent.py` 已有大量“回声抑制”和“低价值文本丢弃”逻辑
- 但还没有“必须带三语显式前缀才放行”的强看门狗

---

## 4. 四个需求的现状与可行性

## 4.1 需求一：唤醒后立即拉起对话房间

### 现状

当前 `tools/wakeword_session_frontgate.py` 中：

- `_local_wake_ack()` 会在唤醒后先播报
- 如果 `INTERRUPT_FRONTGATE_ENABLE_WAKE_INTRO=1`，会播完整自我介绍
- 然后才进入 `_launch_session()`

也就是当前链路是：

`wake_detected -> 本地播报 -> launch session`

### 当前阻塞点

文件：

- `tools/wakeword_session_frontgate.py`

现状逻辑：

- `active_led_proc = _local_wake_ack(adapter, event)`
- `returncode = _launch_session(...)`

说明：

- 会话启动在 wake ack 之后
- 即使 wake ack 很短，也会形成用户可感知空窗
- 如果是 wake intro，自然更慢

### 可行性

完全可行。

推荐改法：

- `_launch_session()` 先启动
- `_local_wake_ack()` 改为并发异步播报，甚至默认关闭
- 默认禁用 `wake_intro`

### 推荐收口

推荐收口为：

- 唤醒后立即拉起房间
- 自我介绍继续播报，但改为并发执行
- room ready 引导语必须等自我介绍结束后再播

也就是说，不再是“先自我介绍，后拉房间”，而是“先拉房间，自我介绍与初始化并发”。

---

## 4.2 需求二：房间就绪后播报引导语

### 现状

当前 `tools/frontgate_room_session.py` 已有 room ready 播报：

- `_speak_room_ready()`
- `_queue_room_ready_via_rtc()`

当前默认文案是：

- `现在可以了`

并且现有逻辑还区分：

- 粤语本地播报
- 非粤语通过 RTC relay 或本地 fallback

### 问题

现有实现不满足你的验收标准，因为：

1. 前门自我介绍还存在，而且当前会阻塞拉房间
2. room ready 文案不是目标引导语
3. 没有严格限制“只有这一句，别的都不播”

### 可行性

完全可行。

只需要：

- 不再让 wake intro 阻塞房间启动
- 将 room ready ack 文案改为三语引导语映射
- 强制 room ready 阶段只播这一句

### 推荐引导语映射

- `zh-CN` -> `请问您有什么需求呢`
- `zh-YUE` -> `請問您有咩需求呢`
- `en` -> `How can I help you?`

---

## 4.3 需求三：看门狗机制（防自听自答）

### 现状

当前仓库已经有两类“弱防护”：

1. `src/speech_loop_guard.py`
   - 基于最近播报内容做自回声文本相似度过滤
2. `src/agent.py` / `src/rtc_endpoint.py`
   - 低信息量文本丢弃
   - 最近 assistant reply echo 丢弃
   - 本地播放 guard 期间的 backchannel 丢弃

这些能挡一部分问题，但不等于你的需求。

### 为什么现在不满足需求

你的需求是：

- 只有显式前缀命中才允许进大模型
- 未命中前缀要静默丢弃
- 只说前缀则进入等待追问态

而当前实现仍会：

- 把不少普通用户文本直接交给 `src.agent`
- 只要文本不被 echo/noise 规则拦截，就可能被回复

### 可行性

可行，但必须新增显式准入层。

### 最佳落点

推荐把看门狗放在 `src/rtc_endpoint.py` 本地转写发布前。

原因：

- 这是“ASR 完成 -> 文本进房间”的最窄门
- 在这里挡掉最干净
- 可以避免未命中前缀的文本进入 room-agent、进入 LLM、进入日志侧干扰

### 不推荐只放在 `src/agent.py`

因为如果只在 `agent` 里拦：

- 文本已经进房间
- 仍会污染 room transcription / data channel
- 仍会干扰中断状态与会话态判断

### 推荐行为

新增专门的 watchdog 模块，例如：

- `src/frontgate_watchdog.py`

负责：

- 三语前缀配置
- 文本归一化
- 模糊匹配
- 前缀剥离
- 返回分类结果

输出分类建议：

- `drop`
- `prefix_only`
- `accepted`

### 推荐前缀

- 普通话：`你好，机器人`
- 粤语：`你好，機器人`
- 英语：`Hello, Robot`

同时建议加入少量鲁棒别名，不宜过宽：

- `你好机器人`
- `你好 機器人`
- `hello robot`
- `hello,robot`

### prefix-only 行为

“仅前缀无后续内容”建议实现为：

- `rtc_endpoint` 不立即把空文本发进 LLM
- 在本地记一个短时 `await_followup` 状态
- 下一段用户语音如果在窗口期内到达，则直接作为真实需求文本送入房间

建议新增状态文件或内存态：

- 内存优先即可
- 无需先做跨进程状态

建议窗口：

- `4s ~ 8s`

---

## 4.4 需求四：大模型输出 TTS 流式分段播报

### 现状

当前有两种回复路径：

1. `gemini_realtime`
   - `src/agent.py` 中 `_build_session()` 直接构造 `google.realtime.RealtimeModel`
   - 语音输出主要由 realtime 会话自身控制
2. `local_text_*`
   - `src/agent.py` 中 `AgentSession(llm=None, stt=None, tts=None, turn_detection="manual")`
   - 由本地转写文本驱动，再通过 `session.say()` 或本地 fallback 播报

### 为什么当前线上配置不适合严格实现需求四

当前机器人线上 `.env.local` 是：

- `INTERRUPT_AGENT_BACKEND=gemini_realtime`

这条链更像：

- 用户语音 -> realtime LLM -> realtime voice output

问题在于：

- 我们不能稳定拿到“可完全控制的增量文本片段”
- 也不能稳定保证“按我们定义的标点切割规则进入 TTS FIFO”

所以如果强行在当前 `gemini_realtime` 上承诺需求四，会有验收风险。

### 可行性判断

需求四本身可行，但推荐改后端形态。

### 推荐实现路线

将 room-agent 回复模式切换到“文本生成 + 我方自管 TTS 队列”。

推荐后端：

- `local_text_ollama`
  或
- `local_text_openai_compatible`

然后新增一个流式播报模块，例如：

- `src/streaming_tts_segmenter.py`

负责：

- 接 LLM stream token/text chunk
- 维护 buffer
- 按标点切段
- 最小字符阈值控制
- FIFO 队列
- 串行 TTS 合成/播放

### 切割规则建议

切割符：

- `，`
- `。`
- `,`
- `.`
- `？`
- `?`
- `！`
- `!`
- `；`
- `;`

推荐优先级：

- 主切口：`，` `。` `,` `.`
- 次切口：`？` `?` `！` `!` `；` `;`

最小字符阈值建议：

- 中文按 `>= 5` 字
- 英文按 `>= 8` 字符或 `>= 2` 词

### 现有可复用能力

可以复用：

- `src/speech_feedback.py`
- `src/cantonese_tts.py`
- `restore_assets/om1/external_usb_tts.sh`

但要新增：

- 分段队列
- 正在播放时的串行锁
- 末尾 flush 逻辑

---

## 5. 推荐改动清单

## 5.1 必改文件

### 1. `tools/wakeword_session_frontgate.py`

用途：

- 实现需求一
- 将 wake intro 改成并发播放

建议修改：

- 将 `_launch_session()` 提前到 wake 后立即执行
- 将 `_local_wake_ack()` 改为：
  - 默认禁用
  - 或放到后台线程
- 默认关闭 `INTERRUPT_FRONTGATE_ENABLE_WAKE_INTRO`

### 2. `tools/frontgate_room_session.py`

用途：

- 实现需求二

建议修改：

- 增加三语引导语映射函数
- 将 `room_ready_reply` 从 `现在可以了` 改为按唤醒语言选择
- 严格约束 room ready 阶段只允许播这一句
- 删除“ready 后再补播别的 ack”的分支空间

### 3. `src/rtc_endpoint.py`

用途：

- 实现需求三的最佳入口

建议修改：

- 在 `LocalTranscriber._drain_results()` 里，发布 transcription/data 之前接入 watchdog
- 对转写文本做：
  - 前缀识别
  - 前缀剥离
  - prefix-only 等待态
  - 未命中静默丢弃

### 4. `src/agent.py`

用途：

- 实现需求二的 relay 配合
- 为需求三提供 prefix-only 等待追问兜底
- 为需求四预留统一 TTS 分段播报入口

建议修改：

- 若保留 `interrupt/frontgate/room_ready_ack`，确保只播引导语
- 对 watchdog 放行文本和普通 room transcription 做更清晰区分
- 如进入阶段 B，实现统一的“文本流 -> 分段 TTS”调度接口

### 5. `run_robot_frontgate_session.sh`

用途：

- 固定机器人运行口径

建议修改：

- 默认关闭：
  - `INTERRUPT_FRONTGATE_ENABLE_WAKE_ACK`
  - `INTERRUPT_FRONTGATE_ENABLE_WAKE_INTRO`
- 增加：
  - 看门狗开关默认值
  - 引导语文案默认值

### 6. `.env.example`

用途：

- 补齐新配置说明

建议修改：

- 加入新的前门看门狗与引导语配置
- 明确需求四若启用，推荐 `local_text_*` 后端

### 7. `README.md`

用途：

- 记录新链路口径和 env 说明

建议修改：

- 前门体验优化说明
- 三语引导语配置
- 看门狗前缀配置
- 流式分段 TTS 的后端限制说明

---

## 5.2 建议新增文件

### 1. `src/frontgate_watchdog.py`

建议新增。

职责：

- 文本归一化
- 三语前缀配置
- 前缀模糊匹配
- 剥离前缀
- 分类结果结构化输出

建议暴露接口：

```python
@dataclass
class WatchdogDecision:
    action: str          # drop / prefix_only / accepted
    language: str
    prefix: str
    content: str

def evaluate_frontgate_text(
    text: str,
    *,
    default_language: str = "",
) -> WatchdogDecision:
    ...
```

### 2. `src/frontgate_followup_state.py`

可选新增。

如果不想把 prefix-only 等待态直接塞进 `rtc_endpoint.py`，可以拆小模块。

职责：

- 记录“刚收到前缀但无正文”
- 判断下一条转写是否可视为 follow-up
- 处理超时

### 3. `src/streaming_tts_segmenter.py`

建议在阶段 B 新增。

职责：

- 缓冲 token / chunk
- 按标点切段
- 最小长度过滤
- flush 尾段
- 顺序播放

### 4. `tools/frontgate_watchdog_smoke.py`

建议新增测试工具。

用途：

- 离线喂文本验证三语前缀命中、剥离和 prefix-only 行为

---

## 6. 推荐新增环境变量

以下环境变量建议加入 `.env.example`，并在机器人 `/data/HongTu/interrupt/.env.local` 显式配置。

## 6.1 需求一、二相关

```env
INTERRUPT_FRONTGATE_ENABLE_WAKE_ACK=0
INTERRUPT_FRONTGATE_ENABLE_WAKE_INTRO=0
INTERRUPT_FRONTGATE_ROOM_READY_ACK_TEXT_ZH=请问您有什么需求呢
INTERRUPT_FRONTGATE_ROOM_READY_ACK_TEXT_YUE=請問您有咩需求呢
INTERRUPT_FRONTGATE_ROOM_READY_ACK_TEXT_EN=How can I help you?
INTERRUPT_FRONTGATE_ROOM_READY_ACK_MODE=room_agent_rtc
```

## 6.2 需求三相关

```env
INTERRUPT_FRONTGATE_WATCHDOG_ENABLED=1
INTERRUPT_FRONTGATE_WATCHDOG_PREFIX_ZH=你好，机器人|你好机器人|机器人，你好|机器人你好
INTERRUPT_FRONTGATE_WATCHDOG_PREFIX_YUE=你好，機器人|你好機器人|機器人，你好|機器人你好
INTERRUPT_FRONTGATE_WATCHDOG_PREFIX_EN=Hello, Robot|Hello Robot|Hi, Robot|Hi Robot|Hey, Robot|Hey Robot|Oh, Robot|Oh Robot
INTERRUPT_FRONTGATE_WATCHDOG_PENDING_PREFIX_ZH=你好
INTERRUPT_FRONTGATE_WATCHDOG_PENDING_PREFIX_YUE=你好
INTERRUPT_FRONTGATE_WATCHDOG_PENDING_PREFIX_EN=Hello|Hi|Hey|Oh
INTERRUPT_FRONTGATE_WATCHDOG_ROBOT_TERM_ZH=机器人
INTERRUPT_FRONTGATE_WATCHDOG_ROBOT_TERM_YUE=機器人
INTERRUPT_FRONTGATE_WATCHDOG_ROBOT_TERM_EN=Robot
INTERRUPT_FRONTGATE_WATCHDOG_FOLLOWUP_WINDOW_S=6
INTERRUPT_FRONTGATE_WATCHDOG_PENDING_PREFIX_WINDOW_S=1.6
INTERRUPT_RTC_TRANSCRIBE_SILENCE_S=1.1
INTERRUPT_RTC_TRANSCRIBE_MIN_AUDIO_S=0.6
```

## 6.3 需求四相关

```env
INTERRUPT_STREAMING_TTS_ENABLED=1
INTERRUPT_STREAMING_TTS_MIN_CHARS_CJK=5
INTERRUPT_STREAMING_TTS_MIN_CHARS_LATIN=8
INTERRUPT_STREAMING_TTS_PUNCTUATION=，。, .？?！!；;
INTERRUPT_STREAMING_TTS_FLUSH_TIMEOUT_MS=350
```

如果阶段 B 采用本地文本后端，还建议：

```env
INTERRUPT_AGENT_BACKEND=local_text_openai_compatible
```

或

```env
INTERRUPT_AGENT_BACKEND=local_text_ollama
```

---

## 7. 详细实施方案

## 7.1 阶段 A：先改需求一、二、三

### 步骤 1：改成并发自我介绍，不阻塞拉房间

修改文件：

- `tools/wakeword_session_frontgate.py`
- `run_robot_frontgate_session.sh`
- `/data/HongTu/interrupt/.env.local`

实施内容：

- 保留 `INTERRUPT_FRONTGATE_ENABLE_WAKE_INTRO=1`
- `wake_detected` 后立即执行 `_launch_session()`
- 自我介绍改为后台异步执行，不能阻塞 session launch
- room ready 提示必须等待“intro done signal + room ready”同时成立

### 步骤 2：统一 room ready 引导语

修改文件：

- `tools/frontgate_room_session.py`

实施内容：

- 基于 `INTERRUPT_WAKE_EVENT_LANGUAGE` 生成三语引导语
- 替换 `现在可以了`
- 粤语仍走粤语专用 TTS
- 中英仍优先走 RTC relay / 现有本地播报兜底

### 步骤 3：接入显式前缀看门狗

修改文件：

- 新增 `src/frontgate_watchdog.py`
- 修改 `src/rtc_endpoint.py`

实施内容：

- `LocalTranscriber._drain_results()` 中，`cleaned` 文本生成后先过 `evaluate_frontgate_text()`
- 若 `drop`：
  - 不 publish transcription
  - 不 publish `interrupt/local_text/transcript`
- 若 `prefix_only`：
  - 不发空文本到房间
  - 记录等待 follow-up 状态
- 若 `accepted`：
  - 只发剥离前缀后的真实内容

### 步骤 4：prefix-only 追问态

修改文件：

- `src/rtc_endpoint.py`
- 可选新增 `src/frontgate_followup_state.py`

实施内容：

- 用户只说 `你好，机器人`
- 进入 6 秒等待态
- 下一句若到达：
  - 直接按 follow-up 内容发进房间
- 超时则静默结束

### 步骤 5：补 smoke test

新增文件：

- `tools/frontgate_watchdog_smoke.py`

用例至少覆盖：

- `你好，机器人，介绍一下你自己`
- `你好，機器人，帶我去門口`
- `Hello, Robot, what can you do?`
- `介绍一下你自己`
- `今天天气怎么样`
- `你好，机器人`

---

## 7.2 阶段 B：实现需求四

### 方案选择

建议采用“local_text 房间后端 + 自管分段 TTS”。

修改文件：

- `src/agent.py`
- 新增 `src/streaming_tts_segmenter.py`
- 可能补 `src/speech_feedback.py`

### 实施内容

1. room-agent 从 LLM 获取流式文本 chunk
2. 交给 `streaming_tts_segmenter`
3. 在切到第一个有效片段时立即启动首段 TTS
4. 后续片段进入 FIFO
5. 播放严格串行

### 必须说明

如果继续保留 `gemini_realtime` 作为唯一回复通道，则阶段 B 不能按你的验收标准“严格闭环”。

---

## 8. 具体到文件的修改建议

## 8.1 本地仓库文件

必须修改：

- `tools/wakeword_session_frontgate.py`
- `tools/frontgate_room_session.py`
- `src/rtc_endpoint.py`
- `src/agent.py`
- `run_robot_frontgate_session.sh`
- `.env.example`
- `README.md`

建议新增：

- `src/frontgate_watchdog.py`
- `src/frontgate_followup_state.py`
- `src/streaming_tts_segmenter.py`
- `tools/frontgate_watchdog_smoke.py`

建议新增文档：

- `docs/TRILINGUAL_FRONTGATE_DIALOG_OPTIMIZATION_EXECUTION_PLAN_2026-06-05.md`

## 8.2 机器人部署目录文件

实施时需要同步到：

- `/data/HongTu/interrupt/tools/wakeword_session_frontgate.py`
- `/data/HongTu/interrupt/tools/frontgate_room_session.py`
- `/data/HongTu/interrupt/src/rtc_endpoint.py`
- `/data/HongTu/interrupt/src/agent.py`
- `/data/HongTu/interrupt/run_robot_frontgate_session.sh`
- `/data/HongTu/interrupt/.env.local`

如果阶段 B 落地，还要同步：

- `/data/HongTu/interrupt/src/frontgate_watchdog.py`
- `/data/HongTu/interrupt/src/frontgate_followup_state.py`
- `/data/HongTu/interrupt/src/streaming_tts_segmenter.py`
- `/data/HongTu/interrupt/tools/frontgate_watchdog_smoke.py`

---

## 9. 推荐验收用例

## 9.1 需求一验收

用例：

- 说出唤醒词

预期：

- 日志里先看到 `wake_detected`
- 立即进入 `session_cmd=...run_frontgate_room_session.sh`
- 不等待自我介绍结束

关注日志：

- `logs/robot-frontgate.log`
- `logs/room-agent.log`
- `logs/robot-rtc-endpoint.log`

## 9.2 需求二验收

用例：

- 普通话唤醒
- 粤语唤醒
- 英语唤醒

预期：

- 房间 ready 后只播一条引导语
- 普通话：`请问您有什么需求呢`
- 粤语：`請問您有咩需求呢`
- 英语：`How can I help you?`
- 无其他 wake ack / intro / ready ack

## 9.3 需求三验收

用例：

- 机器人自己播 TTS
- 旁人普通聊天
- 用户说 `你好，机器人`
- 用户说 `你好，机器人，介绍一下你自己`

预期：

- 自己播报回采不触发大模型
- 旁人聊天未带前缀不触发
- 仅前缀进入等待态，不报错
- 前缀加正文时，仅正文送入大模型

## 9.4 需求四验收

用例：

- 问一个能输出长回复的问题

预期：

- 第一个有效切分点到达即触发首段 TTS
- 后续分段顺序播放
- 不错序
- 不出现过短碎片

---

## 10. 风险与注意事项

## 10.1 最大风险

最大风险不是代码复杂度，而是“需求四与当前线上后端形态不匹配”。

如果不接受切到 `local_text_*`，则需求四只能做近似版。

## 10.2 看门狗前缀不要做得太宽

否则会把旁人对话误判成命中。

建议第一版宁可严格，不要贪多别名。

## 10.3 prefix-only 不要直接回问

你要求“仅前缀无后续内容 -> 进入等待追问状态，不报错”。

所以第一版建议：

- 不主动再播一句“请说”
- 只在内部开启等待窗口

这样最不容易引入新的自听自答问题。

## 10.4 需求二和需求三是耦合的

如果 room ready 引导语太长，会增加被自己回采的概率。

所以需求二的引导语必须短。

---

## 11. 推荐实施顺序

推荐顺序：

1. 先改需求一
2. 再改需求二
3. 然后改需求三
4. 做真机回归
5. 最后独立做需求四

不建议四个需求一次性一起上真机。

---

## 12. 最终建议

如果目标是“尽快显著改善现场体验”，建议本轮先收口：

- 需求一
- 需求二
- 需求三

它们都能在当前主链上稳定落地，而且用户体感会立刻明显变好。

如果目标是“严格满足分段流式 TTS 验收”，建议把需求四单列为二期，并明确接受以下技术决策之一：

- 方案 A：房间后端切到 `local_text_*`
- 方案 B：继续 `gemini_realtime`，但验收改成“近似流式”而非“严格自管切段”

---

## 13. 本轮已确认的线上事实

2026-06-05 已通过 SSH 核对机器人 `/data/HongTu/interrupt`，确认：

- 前门实际代码目录是 `/data/HongTu/interrupt`
- `/data/HongTu/interrupt/tools/wakeword_session_frontgate.py` 已与当前本地结构同构
- `/data/HongTu/interrupt/tools/frontgate_room_session.py` 已与当前本地结构同构
- `/data/HongTu/interrupt/src/agent.py` 当前支持 `gemini_realtime` 和 `local_text_*` 两类后端
- `/data/HongTu/interrupt/.env.local` 当前仍开启：
  - `INTERRUPT_FRONTGATE_ENABLE_WAKE_ACK=1`
  - `INTERRUPT_FRONTGATE_ENABLE_WAKE_INTRO=1`
  - `INTERRUPT_AGENT_BACKEND=gemini_realtime`
  - `INTERRUPT_RTC_TRANSCRIBE_ENABLED=1`

这也是本文做出上述结论的直接依据。
