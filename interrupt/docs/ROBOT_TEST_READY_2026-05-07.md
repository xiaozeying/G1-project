# Robot Test Ready Checklist

更新时间：2026-05-11

本文档用于刷机到 Ubuntu 22.04.5 后，快速确认 G1 前门主链已经进入“可测试”状态。

## 当前测试范围

本轮已准备到可以现场验收以下能力：

- 三语言唤醒
- 三语言自适应对话
- assistant 回复可被用户打断
- 语音触发上身动作与 LED 灯变化
- 会话超时后自动回前门待机

当前不在本轮必测范围内：

- 视觉 VLM 问答

当前机器人上视觉入口已临时关闭：

```bash
INTERRUPT_VISION_CHAT_ENABLED=0
INTERRUPT_VLM_ENABLED=0
```

## 机器人关键口径

- 机器人 IP：`192.168.100.30`
- 用户：`unitree`
- `interrupt` 路径：`/home/unitree/HongTu/interrupt`
- `OM1` 动作/灯光 Python：`/home/unitree/HongTu/OM1/.venv-g1/bin/python`
- 前门唤醒 Python：`/home/unitree/miniforge3/envs/wakeword-clean/bin/python`
- 当前可用 Unitree 接口：`enP8p1s0`
- 前门 service：`interrupt-frontgate.service`

## 开测前检查

在机器人上执行：

```bash
systemctl --user status interrupt-frontgate.service --no-pager
```

期望：

- `active (running)`

查看前门日志：

```bash
tail -n 80 /home/unitree/HongTu/interrupt/logs/frontgate.log
```

期望：

- 能持续看到 `[FrontGate] audio_level ...`
- 能持续看到 `[yue]`、`[en]` 或中文转写片段
- 不应反复出现 fallback 到 `src.mock_wakeword:factory`

## 必要受控验证

如需确认房间链可拉起：

```bash
cd /home/unitree/HongTu/interrupt
./run_frontgate_room_session.sh --startup-timeout 25 --idle-grace 3 --max-duration 15
```

期望：

- `managed readiness room-agent=True rtc-endpoint=True`
- `dispatch requested room=interrupt-demo`
- `room session active`
- 到时后自动打印 `room session max duration reached`

## 现场口测顺序

推荐按下面顺序做：

1. 唤醒词
2. 普通对话
3. 打断
4. 动作和 LED
5. 超时回前门

### 1. 唤醒词

建议至少测：

- `笨笨同学`
- `你好笨笨`
- `hello benben`

期望：

- 机器人先播报“我在，请说”
- 待机蓝灯切换到激活态
- 日志出现 `wake_detected`

### 2. 普通对话

示例：

- `你现在可以说中文吗`
- `Can you introduce yourself in English`
- `你可唔可以用广东话答我`

期望：

- 能跟随用户语言回复
- 房间链不崩

### 3. 打断

在 assistant 正在说话时插入：

- `等一下`
- `先别说了`
- `stop`

期望：

- 当前播报被打断
- 会话继续保持可交互

### 4. 动作和 LED

示例：

- `向我挥手`
- `把LED灯变成蓝色`
- `把灯变成红色`

期望：

- 动作脚本执行成功
- 灯光状态变化成功

如需单点验证，可分别执行：

```bash
/home/unitree/HongTu/OM1/.venv-g1/bin/python /home/unitree/HongTu/OM1/scripts/g1_direct_command_fallback.py --interface enP8p1s0 '挥手'
```

```bash
/home/unitree/HongTu/OM1/.venv-g1/bin/python /home/unitree/HongTu/OM1/scripts/g1_watchdog_feedback.py --interface enP8p1s0 --mode static --color blue
```

### 5. 超时回前门

当前默认值：

```bash
INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS=180000
```

期望：

- 约 3 分钟无有效用户输入后，会话退出
- 前门恢复待机蓝灯
- 再次说唤醒词可重新进入会话

## 当前已知但不阻塞测试的问题

- `room-agent` 日志会提示 LiveKit HMAC key 过短 warning
- `robot-rtc-endpoint.log` 中仍可能看到 `reason=no_callbacks` 的麦克风重启日志
- `tools/check_env.py` 在机器人上如果没有同步最新脚本，可能仍会把前门工厂误报成 mock 默认值

这些问题目前不会阻塞本轮语音主链验收。

## 2026-05-11 修复记录

本次联调已把“开机后直接唤醒可用”所需的关键修复固定到代码和机器人持久配置中。

### 已修复

- 修复前门拉房间时 `room-agent` readiness 过早误判的问题。
  现已优先等待 `registered worker`，只在进程存活且超过保护窗口后才兜底放行，避免房间还没注册就提前 `dispatch`。
- 修复 `room-agent` 启动过重、偶发注册不上的问题。
  已将 LiveKit worker 默认空闲进程数调为 `0`，并放宽初始化超时，降低 G1 上的启动压力。
- 修复房间对话阶段 assistant 双播的问题。
  普通 assistant 回复已固定为只走 LiveKit 房间音频，不再额外走本地 `OM1` 镜像。
- 修复粤语回复在 `transport_only` 下仍偷偷走本地 TTS 的特例。
  现在粤语和中英文保持一致，只有在 `om1_mirror` 模式下才允许本地镜像播报。
- 修复动作执行时工具确认话术与房间回复双声源互相抢话的问题。
  工具确认播报也已切为只走 LiveKit 房间音频。

### 当前固定配置

机器人持久配置文件：

```bash
/home/unitree/HongTu/interrupt/.env.local
```

当前关键音频模式为：

```bash
INTERRUPT_ASSISTANT_AUDIO_MODE=transport_only
INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=transport_only
```

含义：

- 房间内 assistant 正式回复只保留一条 LiveKit 房间音频
- 动作/工具确认话术也只保留一条 LiveKit 房间音频
- 正常开关机后仍沿用这套配置，无需再次手动修链路

### 当前结论

- 当前状态可以按“开机 -> 等服务起来 -> 直接说唤醒词”使用
- 后续若未改动音频设备、`.env.local` 或相关代码，不需要重复本轮修复步骤
