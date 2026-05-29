# interrupt 测试指令手册

更新时间：2026-04-20

## 1. 系统架构

```text
用户
  -> 麦克风
  -> 前门唤醒层
     - tools/wakeword_session_frontgate.py
     - src/om1_wakeword_gate.py
  -> 本地实时会话层
     - run_local_voice_agent.sh
     - src/agent.py
     - src/console_audio_compat.py
  -> 执行层
     - src/g1_om1_adapter.py
     - OM1 本地播报
     - G1 LED
     - G1 动作
  -> 可选外部工具层
     - src/integrations.py
     - MCP stdio / MCP HTTP
```

当前说明：

- 灯光 / 动作控制：已接上本地执行层
- 天气 / 新闻实时查询：当前未接入外部实时数据工具
- 因此天气 / 新闻目前不能视为“已收口能力”

## 2. 本地静态检查

### 2.1 Python 编译检查

```bash
cd /home/zz/HongTu/interrupt
python3 -m py_compile src/agent.py
python3 -m py_compile src/console_audio_compat.py
python3 -m py_compile src/integrations.py
python3 -m py_compile src/om1_wakeword_gate.py
python3 -m py_compile tools/wakeword_session_frontgate.py
```

### 2.1.1 恢复后必须核验三语言自适应没有退化

快照目录内有完整三语言自适应实现，但恢复完成后必须再看 active `agent.py`，防止机器人运行代码退化成固定普通话。

本地快照参考实现检查：

```bash
cd /home/zz/HongTu
grep -n 'def _extract_explicit_language_tag\|def _detect_reply_language\|def _detect_forced_reply_language\|def _preferred_reply_language' \
  robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/src/agent.py
```

当前主线 active 代码检查：

```bash
cd /home/zz/HongTu
grep -n 'def _detect_reply_language\|def _detect_forced_reply_language\|def _preferred_reply_language' \
  interrupt/src/agent.py
```

如果主线仍是这类退化实现，就不能算恢复完成：

```python
def _detect_reply_language(text: str) -> str:
    return REPLY_LANGUAGE_MANDARIN

def _detect_forced_reply_language(text: str) -> str | None:
    return None
```

### 2.2 环境检查

```bash
cd /home/zz/HongTu/interrupt
source .venv/bin/activate
python tools/check_env.py
```

## 3. 模块级最小验证

### 3.1 前门回归

```bash
cd /home/zz/HongTu/interrupt
python tools/frontgate_smoke_test.py
python tools/frontgate_regression_test.py
```

### 3.2 G1 / OM1 适配器最小验证

```bash
cd /home/zz/HongTu/interrupt
python tools/g1_om1_cli.py check
python tools/g1_om1_cli.py speak "我在，请说"
python tools/g1_om1_cli.py direct "把LED灯变为红色"
python tools/g1_om1_cli.py direct "向我挥手"
```

### 3.3 本地 console 设备枚举

```bash
cd /home/zz/HongTu/interrupt
source .venv/bin/activate
python -m src.agent console --list-devices
```

## 4. 真机联调指令

### 4.1 登录机器人

```bash
ssh <robot-user>@<robot-ip>
```

### 4.2 杀旧进程

```bash
cd /home/unitree/HongTu/interrupt
pkill -f 'tools/wakeword_session_frontgate.py' || true
pkill -f 'python -m src.agent console' || true
pkill -f 'run_local_voice_agent.sh' || true
pkill -f '^arecord ' || true
```

### 4.3 启动真机前门

```bash
cd /home/unitree/HongTu/interrupt
nohup env \
  INTERRUPT_INPUT_DEVICE=0 \
  INTERRUPT_OUTPUT_DEVICE=0 \
  INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_SUBSTRING='mvsilicon B1 usb audio' \
  INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_TIMEOUT=5 \
  INTERRUPT_FRONTGATE_INPUT_DEVICE_PROBE_MS=800 \
  INTERRUPT_FRONTGATE_INPUT_DEVICE_MIN_CALLBACKS=5 \
  INTERRUPT_FRONTGATE_INPUT_DEVICE_READY_DELAY=0.5 \
  INTERRUPT_REALTIME_PREFIX_PADDING_MS=500 \
  INTERRUPT_MIRROR_ASSISTANT_SPEECH_TO_OM1=1 \
  INTERRUPT_USER_AWAY_TIMEOUT_MS=300000 \
  INTERRUPT_ACTIVE_LISTEN_LED_RESTORE_DELAY_S=1.5 \
  INTERRUPT_ACTIVE_LISTEN_LED_COLOR=green \
  INTERRUPT_ACTION_BUSY_LED_COLOR=purple \
  INTERRUPT_ACTION_BUSY_HOLD_S=6.0 \
  INTERRUPT_ENABLE_LOCAL_TOOL_PRE_ACK=1 \
  ./run_robot_frontgate_session.sh \
  >/home/unitree/HongTu/interrupt/logs/robot-frontgate.log 2>&1 &
```

### 4.4 真机快速状态检查

```bash
ps -ef | grep -E 'wakeword_session_frontgate|python -m src.agent|arecord' | grep -v grep
```

## 5. 查看日志命令

### 5.1 前门日志

```bash
tail -F /home/unitree/HongTu/interrupt/logs/robot-frontgate.log
```

看这些关键字：

- `wake_detected`
- `wake_ack`
- `session_cmd`
- `session_exit`
- `audio_level`
- `[zh]` / `[yue]`

### 5.2 会话日志

```bash
tail -F /home/unitree/HongTu/interrupt/logs/agent.log
```

看这些关键字：

- `conversation_item_added: role=user`
- `function_tools_executed`
- `agent_state_changed`
- `user_state_changed`
- `console audio compat restarting input stream`
- `server cancelled tool calls`
- `idle LED set`

### 5.3 精准筛关键行

```bash
grep -nE 'wake_detected|wake_ack|session_cmd|session_exit|audio_level|\[zh\]|\[yue\]' /home/unitree/HongTu/interrupt/logs/robot-frontgate.log | tail -n 120
grep -nE 'conversation_item_added: role=user|function_tools_executed|agent_state_changed|user_state_changed|server cancelled tool calls|restarting input stream|idle LED set' /home/unitree/HongTu/interrupt/logs/agent.log | tail -n 200
```

### 5.4 恢复后机器人 active 配置核验

先看 RTC 主播报默认值是否还在：

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "grep -n '^INTERRUPT_ASSISTANT_AUDIO_MODE=\\|^INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=\\|^INTERRUPT_RTC_SUBSCRIBE_AUDIO=\\|^INTERRUPT_RTC_OUTPUT_DEVICE=\\|^PULSE_SINK=' /home/unitree/HongTu/interrupt/.env.local"
```

再看机器人当前 `agent.py` 是否仍保留三语言自适应逻辑：

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "grep -n 'def _detect_reply_language\\|def _detect_forced_reply_language\\|def _preferred_reply_language\\|reply language mode updated\\|reply language detected' /home/unitree/HongTu/interrupt/src/agent.py"
```

最后直接查最近语言检测日志：

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "grep -aE 'reply language mode updated|reply language detected|assistant reply language aligned|assistant reply language mismatch' /home/unitree/HongTu/interrupt/logs/room-agent.log | tail -n 80"
```

### 5.5 恢复后视觉问答入口与文件目录核验

先看 active `agent.py` 是否仍挂着视觉问答入口：

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "grep -n 'ask_camera_vision\\|camera vision query succeeded\\|VisionChatConfig\\|ask_camera_question' /home/unitree/HongTu/interrupt/src/agent.py"
```

再看视觉 / 本地决策相关文件是否都落在正确目录：

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "cd /home/unitree/HongTu/interrupt && ls src/agent.py src/settings.py src/vision_chat.py src/local_text_brain.py src/navigation_intents.py src/safe_action_gateway.py src/safe_action_middleware.py src/cantonese_tts.py src/tts_mute_state.py tools/resolve_vlm_runtime.py tools/vlm_smoke_test.py"
```

如果误看到这些文件出现在根目录：

```text
/home/unitree/HongTu/interrupt/agent.py
/home/unitree/HongTu/interrupt/vision_chat.py
/home/unitree/HongTu/interrupt/settings.py
/home/unitree/HongTu/interrupt/vlm_smoke_test.py
```

就说明同步目标写错了，service 即使能启动，也不能算恢复完成。

## 6. 联调测试清单

### 6.1 唤醒链路

步骤：

1. 蓝灯待机
2. 说 `笨笨同学`
3. 观察 `wake_detected`
4. 观察机器人播报 `我在，请说`

通过标准：

- 日志出现 `wake_detected`
- 机器人有唤醒应答
- 会话启动

### 6.2 动作链路

步骤：

1. 唤醒
2. 说 `挥手`
3. 动作结束前后继续说 `握手`

通过标准：

- 第一条动作命令进入 `conversation_item_added: role=user`
- 本地动作执行成功
- 如输入流停摆，日志应出现 `console audio compat restarting input stream`
- 第二条命令能继续进入 `conversation_item_added: role=user`

### 6.3 灯光链路

步骤：

1. 唤醒
2. 说 `把灯变成红色`
3. 再说 `变成紫色`

通过标准：

- 灯光实际变化
- 日志里出现本地或工具执行成功
- 不出现长期卡死

### 6.4 会话超时与回蓝

步骤：

1. 唤醒
2. 不再说话
3. 等待超过 `5 分钟`

通过标准：

- 日志出现 `user_state_changed: listening -> away`
- 日志出现 `idle LED set: reason=user_away`
- 灯回蓝
- 之后可再次唤醒

### 6.5 三语言自适应回归

步骤：

1. 唤醒并说普通话问题，例如 `你现在在哪`
2. 再说英语，例如 `What can you do`
3. 再说粤语，例如 `你可唔可以介绍下自己`
4. 再说 `之后都用英语回答`
5. 再说中文问题，确认仍用英语答
6. 最后说 `恢复自动` 或 `跟着我说的话回答`
7. 再说普通话问题，确认切回普通话

通过标准：

- 普通话输入默认普通话回答
- 英语输入默认英语回答
- 粤语输入默认粤语回答
- 显式锁定语言后，后续回答服从锁定
- 恢复自动后，重新跟随用户当前输入语言

### 6.6 视觉问答回归

步骤：

1. 唤醒后说 `你前面有什么`
2. 再说 `What do you see in front of you`
3. 再说 `你可唔可以睇下前面有咩`

通过标准：

- 三句都能进入视觉问答链
- 日志能看到 `ask_camera_vision` 或 `camera vision query succeeded`
- 不会退化成普通闲聊回复
- 不会因为恢复时误用瘦版 `agent.py` 导致视觉入口缺失

## 7. 当前已知限制

### 7.1 天气 / 新闻

当前限制：

- 当前没有接入 weather/news MCP 或 HTTP 实时工具
- 所以天气 / 新闻不会稳定返回实时信息

检查当前配置：

```bash
grep -n 'mcp_' /home/unitree/HongTu/interrupt/config.yaml
```

当前如果为空：

```yaml
mcp_stdio_command: ""
mcp_http_urls: []
```

就说明这条能力还没有真正接上。

### 7.2 远端 tool-call 取消

如果日志出现：

```text
server cancelled tool calls
```

说明：

- 用户语音已进会话
- 但远端模型工具调用被取消
- 当前应优先依赖本地控制快路收口灯光/动作

## 8. 下一次接着推进时的建议顺序

1. 先跑 `前门回归 + 编译检查`
2. 再跑真机 `唤醒 -> 动作 -> 第二轮动作`
3. 再确认 `5 分钟 away -> 蓝灯 -> 可再次唤醒`
4. 最后才接 weather/news 外部工具链
