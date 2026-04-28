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
