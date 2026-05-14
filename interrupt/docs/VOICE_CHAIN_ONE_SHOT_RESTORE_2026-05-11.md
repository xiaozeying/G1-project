# G1 语音链一步到位恢复指南

更新时间：2026-05-11

这份文档记录当前已经在机器人 `192.168.100.30` 上跑通的整条语音链恢复口径，目标是下次刷机或迁移时，不再靠现场回忆逐段补。

## 目标能力

- 三语言唤醒
- 三语言自适应对话
- 打断
- 语音触发上身动作与 LED
- idle 超时回前门
- 房间内普通话、英语、粤语都能正常播报
- 普通话、英语统一从外接 USB 音频设备播报
- 粤语保留单独 TTS 口径

## 这次最终收口的代码边界

- 主仓内必须保住：
  - `interrupt/`
  - `g1-wakeword/`
- 外部依赖但本次必须快照关键入口：
  - `OM1/scripts/external_usb_tts.sh`

说明：

- `OM1/` 整仓目前仍是外部大仓，不能直接指望主仓完整带走。
- 但这次真正影响“中英从 USB 出声”的关键资产，其实就是这份脚本。
- 所以主仓里额外保留了：
  - `interrupt/restore_assets/om1/external_usb_tts.sh`

迁移时至少要把这份脚本同步到：

- `/home/unitree/HongTu/OM1/scripts/external_usb_tts.sh`

## 机器人最终稳定口径

- 机器人：`192.168.100.30`
- 用户：`unitree`
- `interrupt`：`/home/unitree/HongTu/interrupt`
- `OM1`：`/home/unitree/HongTu/OM1`
- `g1-wakeword`：`/home/unitree/HongTu/g1-wakeword`
- 前门 service：`interrupt-frontgate.service`
- 前门 Python：`/home/unitree/miniforge3/envs/wakeword-clean/bin/python`
- OM1 动作灯光 Python：`/home/unitree/HongTu/OM1/.venv-g1/bin/python`
- 当前有效网卡：`enP8p1s0`
- 外接 USB 声卡：
  - ALSA card：`mvsilicon B1 usb audio`
  - sink：`alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
  - source：`alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`

## 最终推荐的语音输出设计

### 普通话与英语

普通话和英语现在不再依赖 Unitree 本地 `TtsMaker` 直接出声，而是走：

```text
interrupt -> G1Om1Adapter.speak()
          -> INTERRUPT_G1_SPEAK_SCRIPT
          -> OM1/scripts/external_usb_tts.sh
          -> edge-tts
          -> 外接 USB 音频设备
```

当前稳定 voice：

- 中文：`zh-CN-XiaoxiaoNeural`
- 英文：`en-US-JennyNeural`

对应环境变量：

```bash
INTERRUPT_G1_SPEAK_SCRIPT=/home/unitree/HongTu/OM1/scripts/external_usb_tts.sh
OM1_EDGE_TTS_ZH_VOICE=zh-CN-XiaoxiaoNeural
OM1_EDGE_TTS_EN_VOICE=en-US-JennyNeural
```

### 粤语

粤语保留单独链路，不和中英混用：

```text
speech_feedback.py
  -> cantonese_tts.py
  -> edge-tts
  -> zh-HK-HiuGaaiNeural
```

这条链已经是原设计的一部分，当前不建议和中英再强行统一。

## 为什么最后没有继续走 Unitree 本地 TTS + USB 路由

这次现场已经实测确认：

- `g1_watchdog_feedback.py --mode speak`
- `audio_client.TtsMaker(...)`

在当前这台 Ubuntu 22.04 机器人上，返回成功不代表走进了 Pulse。

现场证据是：

- `pactl list short sink-inputs` 没有对应播放流
- 即使 `PULSE_SINK` 已经指向 USB，声音也仍然会从机身扬声器走

所以当前最稳结论是：

- 想稳定锁到 USB，就走 `external_usb_tts.sh`
- 不要把主恢复方案押在 `TtsMaker` 重新路由到 USB 上

## 一步到位恢复顺序

1. 恢复 `interrupt/`
2. 恢复 `g1-wakeword/`
3. 恢复 `OM1/`
4. 把 `interrupt/restore_assets/om1/external_usb_tts.sh` 同步到机器人 `OM1/scripts/`
5. 恢复 `interrupt/.env.local`
6. 恢复 `interrupt-frontgate.service`
7. 重建：
   - `interrupt/.venv`
   - `wakeword-clean`
   - `OM1/.venv-g1`
8. 重启前门并验证

## 推荐恢复形态

这套链路不建议强行做成“单容器包打天下”。

原因：

- 前门入口直接依赖 `systemd --user`
- 音频强依赖 Pulse、USB 声卡枚举、`pactl` 默认 sink/source
- 唤醒词链路依赖独立的 `wakeword-clean` Python 环境
- 动作和灯光依赖机器人本机 `OM1/.venv-g1` 与 Unitree 侧运行环境

因此当前更稳的方案是：

- `interrupt/` 与恢复资产放在主仓
- `OM1/`、`g1-wakeword/` 保持本机工作区
- 用一键恢复脚本把环境、service 和关键资产恢复到位

当前主仓已提供：

```bash
./prepare_robot_wipe_bundle.sh
./package_robot_voice_assets.sh
./backup_robot_voice_chain.sh
./restore_robot_voice_chain.sh
```

建议顺序：

1. 刷盘前先运行 `./prepare_robot_wipe_bundle.sh`
2. 把生成的备份目录整体带走
3. 刷盘后恢复代码
4. 在机器人上运行 `./restore_robot_voice_chain.sh`

脚本会自动尝试：

- 总入口脚本会顺序调用：
  - `package_robot_voice_assets.sh`
  - `backup_robot_voice_chain.sh`
- 关键资产打包脚本会导出：
  - `om1-voice-assets.tar.gz`
  - `g1-wakeword-assets.tar.gz`
  - `asset-manifest.txt`
- 备份脚本会导出 `.env.local`、service、三个 Python 环境 freeze、设备快照
- 恢复 `interrupt/.env.local`
- 如果工作区缺失，自动从打包产物恢复 `OM1/` 和 `g1-wakeword/` 的关键入口文件
- 同步 `external_usb_tts.sh` 到 `OM1/scripts/`
- 安装 `interrupt-frontgate.service`
- 重建 `interrupt/.venv`
- 检查或恢复 `wakeword-clean`
- `systemctl --user restart interrupt-frontgate.service`

恢复脚本还支持：

```bash
./prepare_robot_wipe_bundle.sh --verify-only
./restore_robot_voice_chain.sh --verify-only
./restore_robot_voice_chain.sh --skip-bootstrap
```

适用目标：

- 刷盘后把机器人恢复到“开机后可直接唤醒”的状态
- 避免现场再手动补 service、env、OM1 关键脚本和前门入口

## 迁移后最关键的环境变量

至少确认这些值成立：

```bash
INTERRUPT_G1_INTERFACE=enP8p1s0
INTERRUPT_G1_SPEAK_SCRIPT=/home/unitree/HongTu/OM1/scripts/external_usb_tts.sh
OM1_EDGE_TTS_ZH_VOICE=zh-CN-XiaoxiaoNeural
OM1_EDGE_TTS_EN_VOICE=en-US-JennyNeural
PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
PULSE_SOURCE=alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
INTERRUPT_ASSISTANT_AUDIO_MODE=om1_mirror
INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=om1_mirror
INTERRUPT_RTC_SUBSCRIBE_AUDIO=0
```

## 最小验证命令

### 1. 服务状态

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 'systemctl --user status interrupt-frontgate.service --no-pager'
```

### 2. 当前语音配置

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 "grep -n '^INTERRUPT_G1_SPEAK_SCRIPT\\|^OM1_EDGE_TTS_.._VOICE\\|^PULSE_SINK\\|^PULSE_SOURCE' /home/unitree/HongTu/interrupt/.env.local"
```

### 3. USB 中文播报

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 '/home/unitree/HongTu/OM1/scripts/external_usb_tts.sh 测试中文USB播报'
```

### 4. USB 英文播报

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \"/home/unitree/HongTu/OM1/scripts/external_usb_tts.sh 'This is an English USB playback test.'\"
```

### 5. 前门日志

```bash
tail -f /home/unitree/HongTu/interrupt/logs/frontgate.log
```

### 6. 房间日志

```bash
tail -f /home/unitree/HongTu/interrupt/logs/room-agent.log
```

## 这轮新增踩坑

### 1. 中英同一个 multilingual voice 不稳定

尝试过把中英都切成：

- `zh-CN-XiaoxiaoMultilingualNeural`

现场结果：

- 中文和英文不是稳定成功
- `room_ready_ack` 出现：
  - `edge_tts.exceptions.NoAudioReceived`

结论：

- 不要把“中英同音色”当当前演示默认值
- 当前稳定口径仍是：
  - 中文 `XiaoxiaoNeural`
  - 英文 `JennyNeural`

### 2. 工具前置确认不是 bug

现场觉得“一次问题多次播报”，有一部分是设计使然：

- 工具前置确认会先播一次
- 工具执行完，assistant 正式回复还会再播一次

所以：

- 这不是新增回归
- 真正要区分的是“设计上的双播”和“回声回灌导致的自说自听”

### 3. 当前真正棘手的是回灌，不是简单没开 AEC

现象：

- 机器人刚播出去的话，会被房间态重新识别成用户输入

说明：

- 系统不是没有 AEC
- 但当前 `external_usb_tts.sh -> 播放器 -> USB sink` 这条本地播报链，没有被现有 AEC 完整兜住

当前结论：

- 不建议粗暴整段压麦，因为会伤打断
- 后续优先方向应是：
  - 最近播报文本回灌过滤
  - 或继续把本地 USB 播报链接入更完整的 AEC 参考流

### 4. `external_usb_tts.sh` 现场依赖不齐时会静默退化

这条脚本现场踩过的坑包括：

- 缺 `espeak-ng`
- locale 导致 `grep`/字符处理异常
- 播放器选择不稳定

所以迁移后第一时间要验证：

- `edge_tts` 可用
- `espeak-ng` 可用
- `mpg123`/`ffplay`/`mpv`/`gst-play-1.0`/`play` 至少有一个存在

## 下次迁移时不要遗漏的文件

- `interrupt/src/g1_om1_adapter.py`
- `interrupt/src/om1_wakeword_gate.py`
- `interrupt/tools/wakeword_session_frontgate.py`
- `interrupt/tools/frontgate_room_session.py`
- `interrupt/run_robot_frontgate_session.sh`
- `interrupt/deploy/systemd/user/interrupt-frontgate.service`
- `g1-wakeword/wakeword_adaptive.py`
- `interrupt/restore_assets/om1/external_usb_tts.sh`
- 私有 `interrupt/.env.local`

## 这次最终建议

如果目标是“下次迁移一步到位”，主仓至少要保住三件事：

1. `interrupt + g1-wakeword` 的当前稳定代码
2. `external_usb_tts.sh` 的可恢复快照
3. 这份恢复文档

这样即使 `OM1/` 大仓之后再单独封存，整条语音主链的恢复路径也不会再断。 
