# interrupt 项目进展记录

最后更新时间：2026-04-27

## 当前状态

当前主路径已经收口为：

```text
唤醒前门
  -> 拉起 LiveKit Agents console realtime session
  -> Gemini Live
  -> G1 / OM1 工具与本地反馈
```

网页端与 LiveKit 房间模式仍保留，但已经不是本轮机器人联调主线。

## 已完成

- `tools/wakeword_session_frontgate.py`
  - 前台门已改为 PTY 拉起 `python -m src.agent console`
  - 避免 console mode 在无终端子进程场景下退化成 `(none) -> AgentSession -> (none)`
  - 会话退出后恢复待机态 LED
- `src/g1_om1_adapter.py`
  - 默认 OM1 路径已按机器人优先级修正
  - G1 默认接口已统一为 `eth1`
- `run_robot_frontgate_session.sh`
  - 第二阶段 console session 默认输入设备固定为 `0`
  - 第二阶段 console session 默认输出设备固定为 `0`
- `src/om1_wakeword_gate.py`
  - 三语言唤醒前门已支持常见误识别归一
  - 默认分块时长已收口到 `0.8s`
  - 前门增加基础音量门限，减少静音和噪声误触发
- `src/agent.py`
  - 已接入 G1 / OM1 LED、动作、直接命令工具
  - 会话日志里已补充实时转写和打断调试钩子
  - assistant 文本可镜像到 OM1 本地播报
- `tools/frontgate_smoke_test.py`
  - 已有前台门编排自测
- `tools/frontgate_regression_test.py`
  - 新增最小回归检查，覆盖唤醒别名归一、会话态状态机、`eth1` 默认口径

## 2026-04-20 新增收口

- 当前前台门新增“工厂回退”逻辑：
  - 当机器人默认真实唤醒工厂不可用时
  - 会自动回退到 `src.mock_wakeword:factory`
  - 这样机器人环境缺少 `WAKEWORD_SCRIPT` 或脚本路径失效时，不会直接把整条前门启动链路炸掉

## 当前仍需现场验证

- 真机确认第二阶段 `INTERRUPT_INPUT_DEVICE=0` 的 follow-up 语音稳定进入 realtime session
- 真机确认 assistant 播报、用户插话、动作 / LED 执行三者同时存在时，现场体感延迟是否已稳定可接受
- 如果后续要继续收口“抢占旧播报”，需要在 OM1 侧确认是否存在显式 stop 接口，而不是只依赖新文本覆盖旧播报

## 2026-04-27 调试交接

- 新增机器人 USB 对话联调交接记录：
  - `docs/HANDOFF_2026-04-27_ROBOT_USB_DIALOG.md`
- 本轮已确认：
  - `interrupt-frontgate.service` 会自动重启前门并抢占 USB 麦
  - 直连房间测试时必须先停前门 service
  - USB 输出可稳定走外接 USB 设备
  - USB 输入在前门不抢占时可恢复正常回调

## 2026-04-28 新进展

- 已修复前门 ASR 未初始化时的崩溃路径：
  - `src/om1_wakeword_gate.py`
  - 从不可恢复的 `AttributeError` 改为可重试的 `RuntimeError`
- 已把机器人前门默认播放出口收口到 USB：
  - `run_robot_frontgate_session.sh` 默认 `PULSE_SINK` 改为 USB sink
  - 默认 `OM1_CONSOLE_OUTPUT_DEVICE` 改为 `pulse`
  - 默认 `INTERRUPT_RTC_OUTPUT_DEVICE` 改为 `pulse`
- 已在机器人侧 `.env.local` 对齐：
  - `INTERRUPT_RTC_OUTPUT_DEVICE="pulse"`
  - `PULSE_SINK=...usb...`
  - `PULSE_SOURCE=...usb...`
- 已修复前门读取 `arecord` 管道时的假活着卡死：
  - `src/om1_wakeword_gate.py`
  - 改为 `os.read()` 小块累积，避免卡在 `pipe_read`
- 已修复开机后 USB sink 音量可能为 0 的问题：
  - `run_robot_frontgate_session.sh`
  - 前门启动时会主动 unmute 并拉到目标音量
- 已修复房间 idle 退出后前门自动再唤醒的问题：
  - `tools/wakeword_session_frontgate.py`
  - session 结束后销毁旧 wake gate，下一轮重新建 gate 回待机
- 机器人前门房间 idle 超时已调为 3 分钟：
  - `run_robot_frontgate_session.sh`
  - 当前 `INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS=180000`
