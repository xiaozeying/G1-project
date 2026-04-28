# 2026-04-27 机器人 USB 对话链路调试交接

## 当前收尾状态

- 机器人测试进程已清理：
  - `python -m src.agent start` 已停
  - `python -m src.rtc_endpoint` 已停
  - `wakeword_session_frontgate.py` / `run_frontgate_session.sh` 已停
- 机器人前门 user service 已停：
  - `systemctl --user stop interrupt-frontgate.service`
  - 当前状态：`inactive (dead)`
- 当前没有进程占用 `plughw:CARD=audio,DEV=0`

## 2026-04-28 继续推进结果

- 已重新连接机器人并确认：
  - `interrupt-frontgate.service` 会在重启后自动恢复为 `active (running)`
  - 它仍然是当前前门自启入口
- 已修复一个前门崩溃点：
  - 文件：`src/om1_wakeword_gate.py`
  - 问题：ASR 初始化失败时会触发
    - `AttributeError: 'FrontGateAdaptiveWakeWordSystem' object has no attribute 'asr_model'`
  - 处理：改为在 `asr_model` 缺失时抛出可恢复的 `RuntimeError`
  - 作用：前门会走现有重试路径，而不是直接把进程炸掉交给 systemd 重启
- 已把修复同步到机器人：
  - `/home/unitree/HongTu/interrupt/src/om1_wakeword_gate.py`
- 已把前门默认输出收口到 USB：
  - 同步更新了机器人侧 `run_robot_frontgate_session.sh`
  - 机器人侧 `.env.local` 也改成：
    - `INTERRUPT_RTC_OUTPUT_DEVICE="pulse"`
    - `PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
    - `PULSE_SOURCE=alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
- 当前机器人前门日志已确认：
  - `robot pulse sink` 为 USB sink
  - `robot rtc output device` 为 `pulse`
  - `robot rtc endpoint command` 已带 `INTERRUPT_RTC_OUTPUT_DEVICE=pulse`

## 2026-04-28 当前机器人状态

- `interrupt-frontgate.service`：`active (running)`
- 前门仍在监听 USB 麦：
  - `wakeword_session_frontgate.py`
  - `arecord -D plughw:CARD=audio,DEV=0`
- 目前未看到新的 `asr_model` 缺失崩溃再次出现
- 下一步更偏向真机行为验证：
  - 前门真实唤醒是否稳定命中
  - 命中后是否顺利进入 `run_frontgate_room_session.sh`
  - 进入房间会话后 USB 输入/输出是否都保持在正确设备

## 2026-04-28 后续新增结论

- 已修复开机后 USB 外接音频音量可能为 0 的问题：
  - `run_robot_frontgate_session.sh` 现在会在前门启动时主动：
    - `set-default-sink`
    - `set-sink-mute 0`
    - `set-sink-volume 100%`
  - 当前真机验证结果：
    - `Mute: no`
    - `Volume: 100%`
- 已修复前门“进程活着但日志不再更新”的卡死点：
  - 根因：`src/om1_wakeword_gate.py` 使用阻塞式大块 `read()` 读取 `arecord` 管道
  - 表现：`wakeword_session_frontgate.py` 还在、`arecord` 也在，但 `frontgate.log` 停止增长
  - 处理：改为非缓冲小块 `os.read()` 累积，避免卡在 `pipe_read`
- 房间会话“无响应后退出”的排查结论：
  - 至少有一轮前门进入房间后，`room-agent` 已成功收到用户语音并执行动作：
    - 例子：`揮手。`
    - agent 已返回：`已完成动作。`
  - 因此前面感知到的“无响应”很可能有一部分来自：
    - USB 外接音频开机音量为 0
- “然后退出”则来自当前前门房间会话的 idle 超时：
  - 当前已调为 `INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS=180000`
  - 3 分钟无有效输入后会写 `user_input_idle` 并退出回到前门待机
- 已修复“超时退出房间后自动再次唤醒”的问题：
  - 根因：前门回待机时复用了同一个 wake gate，上一轮识别历史仍保留在内存里
  - 处理：`tools/wakeword_session_frontgate.py` 在 session 结束后显式销毁当前 gate，并在下一轮重新创建
  - 目的：回到前门后必须等待新的真实唤醒词，不允许沿用旧历史直接再命中

## 今晚确认过的关键结论

- 机器人上存在 `systemd --user` 服务 `interrupt-frontgate.service`，它会自动重启前门链路。
- 这个前门 service 会拉起：
  - `wakeword_session_frontgate.py`
  - `run_robot_frontgate_session.sh`
  - `run_frontgate_session.sh`
  - `arecord -D plughw:CARD=audio,DEV=0`
- 因此前门一旦活着，就会抢占 USB 麦，导致 `rtc-endpoint` 侧出现：
  - `restarting microphone stream: reason=no_callbacks`
- 只要前门进程释放 USB 麦，`rtc-endpoint` 直连测试链路就能恢复正常麦克风回调。
- USB 输出链路可走外接 USB 音频设备：
  - `PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
  - `INTERRUPT_RTC_OUTPUT_DEVICE=pulse`
- USB 输入测试时可走：
  - `INTERRUPT_RTC_INPUT_DEVICE=plughw:CARD=audio,DEV=0`

## 本轮调试里观察到的性能问题

- 对话“慢”不完全是链路挂死，主要还有一段“停顿判定偏保守”的问题。
- 实测日志中，用户说完后，agent 往往要等 final transcript 收口才稳定回答。
- 噪声也会混进转写，例如：
  - `'<noise> 介紹一下你自己。'`
- 已尝试过一组更激进的快响应参数：
  - `INTERRUPT_MIN_ENDPOINTING_DELAY_MS=150`
  - `INTERRUPT_MAX_ENDPOINTING_DELAY_MS=600`
  - `INTERRUPT_MIN_INTERRUPTION_DURATION_MS=50`
  - `INTERRUPT_FALSE_INTERRUPTION_TIMEOUT_MS=250`
  - `INTERRUPT_REALTIME_PREFIX_PADDING_MS=200`
- 但如果前门 service 没停，这组参数不会真正生效，因为 USB 麦会再次被前门抢走。

## 关键日志时间点

- 旧会话 `AJ_zsPLRjZJyg2A` 在 `2026-04-27 17:44:35` 因 `300.3s` 无有效输入自动 shutdown。
- 新直连测试会话曾成功进入 listening：
  - `AJ_Ernv8YuGs5fH`
- 快响应模式下的新会话：
  - `AJ_agziVJqM6VRx`
  - `2026-04-27 18:10:25` 进入 `listening`
- 本轮结束前已将上述测试进程全部停掉，避免明天接手时状态混乱。

## 机器人侧重要日志位置

- 前门/房间日志目录：
  - `/home/unitree/HongTu/interrupt/logs/`
- 本轮临时输出：
  - `/tmp/interrupt-room-agent.fast2.out`
  - `/tmp/interrupt-rtc.fast3.out`
  - 以及之前的：
    - `/tmp/interrupt-room-agent.longtest2.out`
    - `/tmp/interrupt-rtc.longtest2.out`
    - `/tmp/interrupt-rtc.usb-split2.out`

## 明天继续调试的推荐顺序

1. 先确认前门 service 仍是停的：
   - `systemctl --user status interrupt-frontgate.service`
2. 再启动“直连测试模式”，只验证 USB 输入输出和响应速度。
3. 等直连模式稳定后，再处理“前门唤醒后释放 USB 麦并切到 room session”的正式集成。

## 明天直连测试的建议启动命令

```bash
systemctl --user stop interrupt-frontgate.service

env \
  INTERRUPT_ASSISTANT_AUDIO_MODE=transport_only \
  INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=transport_only \
  INTERRUPT_USER_AWAY_TIMEOUT_MS=3600000 \
  INTERRUPT_MIN_ENDPOINTING_DELAY_MS=150 \
  INTERRUPT_MAX_ENDPOINTING_DELAY_MS=600 \
  INTERRUPT_MIN_INTERRUPTION_DURATION_MS=50 \
  INTERRUPT_FALSE_INTERRUPTION_TIMEOUT_MS=250 \
  INTERRUPT_REALTIME_START_SENSITIVITY=HIGH \
  INTERRUPT_REALTIME_END_SENSITIVITY=HIGH \
  INTERRUPT_REALTIME_PREFIX_PADDING_MS=200 \
  /home/unitree/HongTu/interrupt/run_room_agent.sh
```

另开一个终端：

```bash
env \
  PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo \
  INTERRUPT_RTC_INPUT_DEVICE=plughw:CARD=audio,DEV=0 \
  INTERRUPT_RTC_OUTPUT_DEVICE=pulse \
  /home/unitree/HongTu/interrupt/run_robot_rtc_endpoint.sh
```

## 恢复前门时的提醒

- 不要直接把前门 service 和直连测试链路同时开着。
- 后续正式集成时，需要让前门唤醒命中后主动释放 `plughw:CARD=audio,DEV=0`，再把麦交给房间会话。
