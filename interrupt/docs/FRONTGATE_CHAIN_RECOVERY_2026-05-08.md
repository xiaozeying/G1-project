# G1 Frontgate Chain Recovery Runbook

更新时间：2026-05-11

补充说明：

- `2026-05-11` 之后的“一步到位恢复”口径见：
  - `interrupt/docs/VOICE_CHAIN_ONE_SHOT_RESTORE_2026-05-11.md`
- 本文档更偏 `2026-05-07` 到 `2026-05-08` 的现场恢复过程
- 新文档额外补了：
  - 中英 USB TTS 最终方案
  - `external_usb_tts.sh` 快照回仓
  - 当前回灌 / AEC 边界说明

本文档记录 2026-05-07 到 2026-05-08 这一轮 Ubuntu 22.04.5 刷机后的前门主链恢复过程，目标是避免再次出现“刷机后知道能力做出来过，但无法完整恢复”的情况。

## 本次要保住的链路

- 三语言唤醒
- 三语言自适应对话
- 打断
- 语音触发上身动作和 LED
- idle 超时回前门
- 房间内三语回复统一从外接 USB 音频设备出声

当前不在本轮恢复硬目标内：

- VLM 视觉问答

## 当前仓库与外部依赖边界

本次真正收口的代码主链在：

- `interrupt/`
- `g1-wakeword/`

同时必须依赖一个外部大仓：

- `OM1/`

注意：

- `OM1/` 当前是一个独立 git 仓库，不是 `G1` 主仓里的普通目录
- 本地 `OM1/` 体量约 `2.8G`
- 其当前本地仓状态不是干净基线，不能简单当作这次 `G1` 主仓提交的一部分来理解
- 所以本次先把 `interrupt + g1-wakeword + 恢复文档` 收进 `G1`
- `OM1/` 仍需单独归档或单独推它自己的仓

当前本地 OM1 标识：

- 仓库：`OM1/.git`
- 分支：`main`
- HEAD：`057a2d0e`

## 机器人当前真实口径

- 机器人 IP：`192.168.100.30`
- 用户：`unitree`
- `interrupt` 路径：`/home/unitree/HongTu/interrupt`
- `OM1` 路径：`/home/unitree/HongTu/OM1`
- `g1-wakeword` 路径：`/home/unitree/HongTu/g1-wakeword`
- 兼容旧路径：`/home/unitree/g1-wakeword`
- 前门 service：`interrupt-frontgate.service`
- 前门 Python：`/home/unitree/miniforge3/envs/wakeword-clean/bin/python`
- OM1 动作/灯光 Python：`/home/unitree/HongTu/OM1/.venv-g1/bin/python`
- 当前有效 Unitree 接口：`enP8p1s0`
- 当前外接 USB 音频：
  - ALSA card：`mvsilicon B1 usb audio`
  - Pulse source：`alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
  - Pulse sink：`alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`

## 当前推荐恢复顺序

1. 恢复 `interrupt/`
2. 恢复 `g1-wakeword/`
3. 恢复 `OM1/`
4. 恢复 `interrupt/.env.local`
5. 恢复 `interrupt-frontgate.service`
6. 重建 `interrupt/.venv`、`wakeword-clean`、`OM1/.venv-g1`
7. 最后再做音频、动作、房间链验证

## 当前稳定配置结论

### 1. 前门唤醒与房间回复的音频策略

当前最终目标不是混合播放，而是：

- 前门提示语可以本地播
- 房间内 assistant 三语回复统一从外接 USB 音频设备出声
- 不要同时走 transport 回放和本地镜像，避免双播

如果要统一三语都从外接 USB 音频出声，当前推荐口径是：

- `INTERRUPT_ASSISTANT_AUDIO_MODE=om1_mirror`
- `INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=om1_mirror`
- `INTERRUPT_RTC_SUBSCRIBE_AUDIO=0`
- `PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`

解释：

- `om1_mirror` 说的是播放触发链路，不等于机身喇叭
- 只要 `PULSE_SINK` 指向外接 USB，OM1 本地播放最终物理输出仍然是外接 USB 音频
- 关闭 `INTERRUPT_RTC_SUBSCRIBE_AUDIO` 的目的，是避免房间回复同时走 RTC 回放和本地镜像，造成双播

### 2. 前门房间实时参数

当前机器人恢复后，房间态默认推荐：

- `INTERRUPT_FRONTGATE_MIN_INTERRUPTION_DURATION_MS=80`
- `INTERRUPT_FRONTGATE_FALSE_INTERRUPTION_TIMEOUT_MS=500`
- `INTERRUPT_FRONTGATE_REALTIME_START_SENSITIVITY=HIGH`
- `INTERRUPT_FRONTGATE_REALTIME_END_SENSITIVITY=HIGH`
- `INTERRUPT_FRONTGATE_MIN_ENDPOINTING_DELAY_MS=150`
- `INTERRUPT_FRONTGATE_MAX_ENDPOINTING_DELAY_MS=600`
- `INTERRUPT_FRONTGATE_REALTIME_PREFIX_PADDING_MS=200`

### 3. 超时退出

当前默认：

- `INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS=180000`

说明：

- 这是房间 idle 超时回前门的时间
- 它不是“只能对话三次”的根因
- 真实问题通常是后续几轮被识别成 `noise_only` 或转写质量差

## 本轮踩坑清单

### 1. `known_hosts` 旧指纹导致 SSH 失败

表现：

- SSH 突然报主机指纹冲突

处理：

- 删除 `~/.ssh/known_hosts` 里 `192.168.100.30` 对应那一整行

### 2. 仓库里没有 `g1-wakeword/` 本体

表现：

- `interrupt/src/om1_wakeword_gate.py` 指向 `/home/unitree/g1-wakeword/wakeword_adaptive.py`
- 仓库里只有桥接脚本，没有本体

处理：

- 额外恢复 `g1-wakeword/`
- 同时兼容 `/home/unitree/HongTu/g1-wakeword` 和 `/home/unitree/g1-wakeword`

### 3. 真实前门工厂静默 fallback 到 mock

表现：

- `frontgate.log` 里出现 fallback 到 `src.mock_wakeword:factory`

本轮真实踩中的原因有两个：

- `src.om1_wakeword_gate` 动态加载时缺 `sys.modules` 注册
- `wakeword_adaptive.py` 和 `om1_wakeword_gate.py` 都曾缺过 `import os`

处理：

- 修动态加载注册
- 补齐 `import os`

### 4. `eth1` 已失效，真实接口变成 `enP8p1s0`

表现：

- 动作和 LED 默认调用 DDS 层 abort

处理：

- G1 接口统一切到 `enP8p1s0`

### 5. DDS 默认链到了错误的系统库

表现：

- OM1 动作和灯光脚本默认 abort

根因：

- `cyclonedds` 实际链到了 ROS Humble 的 `libddsc.so.0`
- 不是之前已验证的 `/usr/local/lib/libddsc.so.0`

处理：

- 在 G1/OM1 运行链上优先补 `/usr/local/lib`

### 6. USB 音频设备一度根本没枚举出来

表现：

- 设备有供电，但 `lsusb`、`arecord -l`、`pactl` 都看不到

根因：

- 设备在 Hub / Type-C 扩展坞链路上只供电，没有稳定枚举

处理：

- 重新插拔
- 确认真正出现：
  - `lsusb` 中的 `MV-SILICON`
  - `/proc/asound/cards` 中的 `card 2: audio`

### 7. 房间回复一会儿本地，一会儿 transport

表现：

- 第一条有声音，后面很多条没声音
- 或者双播

根因：

- `transport_only` 下普通 assistant 回复会跳过本地播报
- 但粤语专用 TTS 仍可能本地播一次
- 如果再打开 `om1_mirror` 且 RTC 远端音频回放还开着，就会双播

处理：

- 如果目标是“三语都统一从外接 USB 音频单路出声”
- 用：
  - `INTERRUPT_ASSISTANT_AUDIO_MODE=om1_mirror`
  - `INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=om1_mirror`
  - `INTERRUPT_RTC_SUBSCRIBE_AUDIO=0`

### 8. `frontgate_room_session.py` 用了现场不存在的方法

表现：

- 进入房间直接 traceback
- 报 `G1Om1Adapter.from_environment()`

处理：

- 改回现场稳定可用的 `G1Om1Adapter()`

### 9. `run_robot_frontgate_session.sh` 热修时容易被 shell 提前展开

表现：

- `export: /run_room_agent.sh: not a valid identifier`
- `unbound variable`

根因：

- 远程热修时把 `${...}` 提前在本地 shell 展开掉了

处理：

- 复杂 shell 字面量改动尽量在机器人交互 shell 内直接修
- 不要通过多层 shell 引号转发复杂 `${...}` 模板

## 当前建议保留到仓库里的关键文件

- `interrupt/run_robot_frontgate_session.sh`
- `interrupt/run_frontgate_session.sh`
- `interrupt/tools/wakeword_session_frontgate.py`
- `interrupt/tools/frontgate_room_session.py`
- `interrupt/src/om1_wakeword_gate.py`
- `interrupt/src/g1_om1_adapter.py`
- `interrupt/src/agent.py`
- `interrupt/tools/check_env.py`
- `interrupt/tools/frontgate_regression_test.py`
- `interrupt/README.md`
- `interrupt/PROJECT_PROGRESS.md`
- `interrupt/BOARD_UPGRADE_RESTORE_2026-04-30.md`
- `interrupt/docs/ROBOT_TEST_READY_2026-05-07.md`
- `g1-wakeword/`

## 当前建议的机器人核验命令

前门服务：

```bash
systemctl --user --no-pager --full status interrupt-frontgate.service
```

前门日志：

```bash
tail -f /home/unitree/HongTu/interrupt/logs/frontgate.log
```

房间 agent：

```bash
tail -f /home/unitree/HongTu/interrupt/logs/room-agent.log
```

RTC 端点：

```bash
tail -f /home/unitree/HongTu/interrupt/logs/robot-rtc-endpoint.log
```

看房间回复是否真正走本地 USB 出声：

```bash
grep -aE 'OM1 本地播报 assistant 回复成功|专用粤语 TTS 播报成功|跳过 assistant 本地播报' /home/unitree/HongTu/interrupt/logs/room-agent.log | tail -n 80
```

## 当前最重要的恢复判断标准

恢复不是只看 service 活着，而是至少同时满足：

- `interrupt-frontgate.service` 为 `active (running)`
- 唤醒能命中
- 前门能播报 `我在，请稍等一下吧`
- 房间 ready 能播报 `现在可以了`
- 房间内三语回复都能从外接 USB 音频设备稳定出声
- 动作 / LED 正常
- idle 超时后能回前门
