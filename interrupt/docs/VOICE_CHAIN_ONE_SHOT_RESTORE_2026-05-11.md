# G1 语音链一步到位恢复指南

更新时间：2026-05-11

补充更新：2026-05-27

补充更新：2026-05-29

这份文档记录当前已经在机器人 `192.168.100.30` 上跑通的整条语音链恢复口径，目标是下次刷机或迁移时，不再靠现场回忆逐段补。

## 2026-05-29 最新恢复结论

截至 `2026-05-29`，当前建议直接按下面的目标态恢复，不要再回到多路本地播报混用的旧口径：

- 前门负责唤醒
- 唤醒后前门释放 USB 麦
- 房间 `rtc-endpoint` 接管输入输出
- `room-agent` 通过 RTC 播报 `现在可以了`
- 房间内回复统一优先走 RTC 单路播报
- `offline_singlebox` 下支持三语自适应基础对答、动作、灯光、视觉
- 短插话 `Yeah / I. / OK / 嗯 / 好` 默认忽略，不触发新回复
- 人设统一为：
  - 中文：`笨笨同学`
  - 粤语：`笨笨同學`
  - 英文：`BenBen`
- 任何身份类回复都不应再出现：
  - `Qwen`
  - `通义`
  - `阿里云`
  - `language model`

当前推荐的一键落地顺序是：

1. 把仓库恢复到 `/data/HongTu`
2. 建好兼容软链 `/home/unitree/HongTu -> /data/HongTu`
3. 运行：

```bash
cd /data/HongTu/interrupt
python3 deploy_fix.py
```

如果是机器人本机刚刷好、还没装完环境，则先运行：

```bash
cd /data/HongTu/interrupt
./restore_robot_voice_chain.sh
```

恢复完成后再用 `deploy_fix.py` 做一次增量同步和服务重启。

## 恢复覆盖边界说明

本文档与一键脚本 `restore_robot_voice_chain.sh` 的覆盖范围是：

- 恢复 `interrupt/.env.local`
- 恢复 OM1 关键脚本
- 重建 `interrupt/.venv`
- 安装并重启 `interrupt-frontgate.service`
- 安装并重启 `interrupt-livekit.service`（本地 LiveKit 常驻）
- 验证前门日志、LiveKit 端口、服务状态
- 通过 `deploy_fix.py` 把当前仓库内的关键运行文件同步到机器人

**不在本文档覆盖范围内：**

- Gemini Live 外网握手（依赖外网连通性与 API Key 有效性）
- 房间会话内的 agent 侧逻辑（由 `frontgate_room_session.py` 负责）

现场曾出现的典型卡点：按文档恢复后前门唤醒链正常，但房间会话推进时卡住——根因是本地 LiveKit 未常驻（`127.0.0.1:7880` 未监听）。补充 `interrupt-livekit.service` 后已解决。Gemini Live 外网握手超时属于更上游问题，不在本地恢复链范围内。

2026-05-29 新增的两个高频卡点：

- 前门没有先释放 USB 麦，导致房间 `rtc-endpoint` 起不来
- 播报链混用了 RTC 和 OM1，本地麦又把扬声器听回去，表现成“自己跟自己说话”

当前这两个问题的收口口径已经固定：

- 前门唤醒后必须先 handoff 再释放设备
- 房间 reply 必须以 RTC 单路播报为主

## 目标能力

- 三语言唤醒
- 三语言自适应对话
- 打断
- 语音触发上身动作与 LED
- 视觉问答
- 导航执行
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

本轮现场新增收口结论：

- 不能只恢复“语音能说话”这一条窄链路
- 下次刷机后要一次性恢复的是 `online_full` 在线完整版能力面
- 至少包括：
  - 三语言自适应
  - 稳定普通对话
  - 视觉问答
  - 动作执行
  - 导航执行
  - 打断与恢复
  - RTC 单路播报链
- 在线增强问答：天气、新闻、开放知识

补充说明：

- `offline_singlebox` 下允许基础问答
- 但天气、新闻这类联网能力是否可用，取决于本地脑与联网后端是否真实可达
- 对于身份类问题，不再允许回答成底层模型身份，必须固定回到笨笨同学口径

## 2026-05-29 恢复后现场必查项

### 1. 服务与端口

```bash
systemctl --user is-active interrupt-livekit.service
systemctl --user is-active interrupt-frontgate.service
ss -ltn | grep ':7880 '
```

### 2. 前门与房间日志

```bash
tail -f /data/HongTu/interrupt/logs/robot-frontgate.log
tail -f /data/HongTu/interrupt/logs/room-agent.log
tail -f /data/HongTu/interrupt/logs/robot-rtc-endpoint.log
```

### 3. 期望看到的关键日志

- 前门唤醒后：
  - `room_ready_ack queued reply=现在可以了 mode=room_agent_rtc`
- 房间里：
  - `frontgate ready prompt relay: ok=True text='现在可以了'`
- 短插话过滤：
  - `user_input_transcribed ignored brief backchannel`
- 不再出现：
  - `我叫Qwen`
  - `My name is Qwen`
  - `The robot is in single-box offline mode...` 被无条件反复播报

### 4. 现场最小验收口令

- `你是谁`
- `你可以做什么`
- `你会说什么语言`
- `Can you introduce yourself?`
- `挥挥手`
- `把灯变成蓝色`
- `你前面有什么`

期望结果：

- 身份类回答统一为笨笨同学三语口径
- 动作和灯光可直接执行
- 视觉问题有本地回答
- 不再出现双声道自对话

说明：

- `OM1/` 整仓目前仍是外部大仓，不能直接指望主仓完整带走。
- 但这次真正影响“中英从 USB 出声”的关键资产，其实就是这份脚本。
- 所以主仓里额外保留了：
  - `interrupt/restore_assets/om1/external_usb_tts.sh`

迁移时至少要把这份脚本同步到：

- `/home/unitree/HongTu/OM1/scripts/external_usb_tts.sh`

## 机器人最终稳定口径

- G1 Jetson 大空间目录：`/data`
- 当前推荐项目真实落点：`/data/HongTu`
- 兼容软链：`/home/unitree/HongTu -> /data/HongTu`
- 机器人：`192.168.100.30`
- 用户：`unitree`
- `interrupt`：`/home/unitree/HongTu/interrupt`
- `OM1`：`/home/unitree/HongTu/OM1`
- `g1-wakeword`：`/home/unitree/HongTu/g1-wakeword`
- 前门 service：`interrupt-frontgate.service`
- 前门 Python：`/home/unitree/miniforge3/envs/wakeword-clean/bin/python`
- OM1 动作灯光 Python：`/home/unitree/HongTu/OM1/.venv-g1/bin/python`
- 如果刷机后 `OM1/.venv-g1` 损坏，恢复脚本现在会自动补：
  - `/home/unitree/HongTu/OM1/.venv-g1-runtime/bin/python`
- 当前有效网卡：`enP8p1s0`
- 外接 USB 声卡：
  - ALSA card：`mvsilicon B1 usb audio`
  - sink：`alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
  - source：`alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`

## `/data` 迁移原则

这轮现场新增一个必须写死的迁移结论：

- G1 Jetson 的 `/` 分区已经不算宽裕，现场看到约 `67%` 已用
- `/data` 分区空间很大，现场仅约 `1%` 已用
- 后续刷机恢复、重新部署、拷模型、拷日志、做旁路验证，都应默认放到 `/data`

推荐落点：

- 工作区真实目录：`/data/HongTu`
- 兼容软链：`ln -sfn /data/HongTu /home/unitree/HongTu`

这样做的好处是：

- 旧脚本、旧 service、旧文档里大量写死的 `~/HongTu/...` 不用全部重写
- 现场迁移时仍然可以逐步把真实数据面收敛到 `/data`
- 刷机后恢复时，只要先恢复软链，大部分历史命令还能直接复用

建议恢复第一步就先做：

```bash
sudo mkdir -p /data/HongTu
sudo chown -R unitree:unitree /data/HongTu
ln -sfn /data/HongTu /home/unitree/HongTu
```

## 最终推荐的语音输出设计

### 房间主播报

恢复后的默认口径统一改为 RTC 主播报：

```text
Gemini / agent assistant reply
  -> LiveKit room downstream audio
  -> robot rtc endpoint playback
  -> Pulse USB sink
```

对应环境变量：

```bash
INTERRUPT_ASSISTANT_AUDIO_MODE=transport_only
INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=transport_only
INTERRUPT_RTC_SUBSCRIBE_AUDIO=1
INTERRUPT_RTC_OUTPUT_DEVICE=pulse
PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
```

这样做的原因是：

- 播报主链固定走 RTC 下行，不再每次恢复后手工切换
- `rtc_endpoint` 能拿到播放参考音，更利于 AEC 收口
- 避免 `OM1` 本地播报被麦克风再次听回，触发“自己跟自己说话 / 自己重复动作”

### 恢复完成后仍必须校验的两件事

这一步必须写死进恢复流程，不能只看快照目录里的历史代码。

1. 机器人当前生效的 `interrupt/.env.local` 必须仍是 RTC 主播报默认值：

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "grep -n '^INTERRUPT_ASSISTANT_AUDIO_MODE=\\|^INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=\\|^INTERRUPT_RTC_SUBSCRIBE_AUDIO=\\|^INTERRUPT_RTC_OUTPUT_DEVICE=\\|^PULSE_SINK=' /home/unitree/HongTu/interrupt/.env.local"
```

预期至少看到：

- `INTERRUPT_ASSISTANT_AUDIO_MODE=transport_only`
- `INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=transport_only`
- `INTERRUPT_RTC_SUBSCRIBE_AUDIO=1`

2. 机器人当前正在跑的 `interrupt/src/agent.py` 必须保住三语言自适应逻辑，而不是退化成“永远普通话”：

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "grep -n 'def _detect_reply_language\\|def _detect_forced_reply_language\\|def _preferred_reply_language\\|reply language mode updated\\|reply language detected' /home/unitree/HongTu/interrupt/src/agent.py"
```

如果恢复后机器人活跃代码里只剩这类退化实现：

```python
def _detect_reply_language(text: str) -> str:
    return REPLY_LANGUAGE_MANDARIN

def _detect_forced_reply_language(text: str) -> str | None:
    return None
```

就说明恢复还没有真正收口，虽然快照目录里有实现，机器人当前运行代码却没有跟上。

快照里的正确参考实现位于：

- `robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/src/agent.py`
- 关键入口：`_extract_explicit_language_tag` / `_detect_reply_language` / `_detect_forced_reply_language` / `_preferred_reply_language`

### 恢复完成后还必须校验的第三件事

机器人当前 active `agent.py` 必须已经挂回视觉问答入口，而不是只剩动作 / 灯光 / 普通对话。

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "grep -n 'ask_camera_vision\\|camera vision query succeeded\\|VisionChatConfig\\|ask_camera_question' /home/unitree/HongTu/interrupt/src/agent.py"
```

预期至少能看到：

- `ask_camera_vision`
- `camera vision query succeeded`
- `VisionChatConfig`

如果这条检查为空，通常不是视觉文件完全丢了，而是：

- 恢复时把“瘦版 / 精简版 `agent.py`”覆盖到了机器人
- 导致视觉模块还在磁盘上，但主会话入口没有真正接回去

这类情况不能算恢复完成。

### 恢复同步时必须保证文件落在正确目录

这次现场踩过一个高频坑：

- 文件虽然同步到了机器人
- 但如果 `agent.py`、`vision_chat.py`、`settings.py`、`vlm_smoke_test.py` 之类落在了 `interrupt/` 根目录
- 而不是 `interrupt/src/`、`interrupt/tools/`
- 前门 service 仍然可能启动
- 但运行时吃到的依旧是旧代码

因此同步后必须直接核：

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "cd /home/unitree/HongTu/interrupt && ls src/agent.py src/settings.py src/vision_chat.py tools/vlm_smoke_test.py tools/resolve_vlm_runtime.py"
```

不要接受以下错误恢复状态：

- `/home/unitree/HongTu/interrupt/agent.py`
- `/home/unitree/HongTu/interrupt/vision_chat.py`
- `/home/unitree/HongTu/interrupt/vlm_smoke_test.py`

这些文件如果出现在根目录，说明同步目标写错了，必须立即挪回 `src/` / `tools/`。

### OM1 本地播报

`OM1/scripts/external_usb_tts.sh` 仍保留，但现在降级为：

- 排障链路
- 对比链路
- 特定本地直播需求时手动切换使用

## 为什么恢复默认值改成 RTC 主播报

这次现场新增结论是：

- 如果默认恢复为 `om1_mirror + RTC_SUBSCRIBE_AUDIO=0`
- 机器人会更容易把自己的本地播报再次识别成用户语音
- 进而出现“自己跟自己对话”或“自己重复挥手/鼓掌”的问题

因此恢复文档现在明确收口为：

- 恢复后默认就是 RTC 主播报
- 不再要求现场手工切换

## 为什么仍保留 `external_usb_tts.sh`

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
   - 如果 `OM1/.venv-g1` 不可用，自动补最小可运行的 `OM1/.venv-g1-runtime`
8. 重启前门并验证

### 8.1 同步在线完整版能力面所需文件

除了最小语音链，下次恢复还必须把下面这些文件一起恢复，才能一次性保住 `online_full`：

- `interrupt/src/agent.py`
- `interrupt/src/settings.py`
- `interrupt/src/vision_chat.py`
- `interrupt/src/local_text_brain.py`
- `interrupt/src/navigation_intents.py`
- `interrupt/src/safe_action_gateway.py`
- `interrupt/src/safe_action_middleware.py`
- `interrupt/src/cantonese_tts.py`
- `interrupt/src/tts_mute_state.py`
- `interrupt/src/speech_feedback.py`
- `interrupt/src/speech_loop_guard.py`
- `interrupt/tools/resolve_vlm_runtime.py`
- `interrupt/tools/vlm_smoke_test.py`
- `interrupt/tools/vlm_backend_probe.py`
- `interrupt/tools/vlm_compare_matrix.py`
- `interrupt/tools/safe_navigation_gateway_smoke.py`
- `interrupt/run_offline_vlm_smoke.sh`
- `interrupt/run_local_offline_vlm_validation.sh`
- `interrupt/run_robot_offline_vlm_validation.sh`
- `interrupt/config/vlm_server_profiles.example.env`
- `interrupt/config/vlm_eval_matrix.example.json`
- `interrupt/config/vlm_eval_matrix.local_baseline.json`
- `interrupt/config/vlm_eval_matrix.qwen_vs_gemma.json`
- `interrupt/config/vlm_eval_matrix.qwen3b_vs_gemma.json`

其中最关键的恢复原则是：

- 不要再用缺少 `ask_camera_vision` 的瘦版 `agent.py` 覆盖机器人
- 不要只同步 `src/agent.py` 却漏掉 `vision_chat.py / settings.py / local_text_brain.py`
- 不要只恢复“语音能说话”而忽略视觉 / 导航 / 本地安全中间层

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
- 同步 `bootstrap_g1_runtime_env.sh` 到 `OM1/scripts/`
- 安装 `interrupt-frontgate.service`
- 重建 `interrupt/.venv`
- 检查或恢复 `wakeword-clean`
- 校验当前 `INTERRUPT_G1_OM1_PYTHON` 能否导入 `cyclonedds + unitree_sdk2py`
- 如果失败，自动引导 `OM1/.venv-g1-runtime`
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
PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
PULSE_SOURCE=alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
INTERRUPT_ASSISTANT_AUDIO_MODE=transport_only
INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=transport_only
INTERRUPT_RTC_SUBSCRIBE_AUDIO=1
INTERRUPT_RTC_OUTPUT_DEVICE=pulse
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

建议直接改成下面这条，连 RTC 主播报默认值一起验：

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 "grep -n '^INTERRUPT_G1_SPEAK_SCRIPT\\|^OM1_EDGE_TTS_.._VOICE\\|^PULSE_SINK\\|^PULSE_SOURCE\\|^INTERRUPT_ASSISTANT_AUDIO_MODE\\|^INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE\\|^INTERRUPT_RTC_SUBSCRIBE_AUDIO\\|^INTERRUPT_RTC_OUTPUT_DEVICE' /home/unitree/HongTu/interrupt/.env.local"
```

### 2.1 三语言自适应代码仍在 active `agent.py`

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "grep -n 'def _detect_reply_language\\|def _detect_forced_reply_language\\|def _preferred_reply_language\\|reply language mode updated\\|reply language detected' /home/unitree/HongTu/interrupt/src/agent.py"
```

预期结论：

- 不是只剩“固定普通话”的空壳函数
- 仍能识别普通话 / 粤语 / 英语
- 仍支持“用粤语回答 / 用英语回答 / 恢复自动”这类显式语言锁定与解锁

### 2.2 视觉问答入口仍在 active `agent.py`

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "grep -n 'ask_camera_vision\\|camera vision query succeeded\\|VisionChatConfig\\|ask_camera_question' /home/unitree/HongTu/interrupt/src/agent.py"
```

### 2.3 视觉 / 本地决策相关文件都在正确目录

```bash
ssh -o StrictHostKeyChecking=no unitree@192.168.100.30 \
  "cd /home/unitree/HongTu/interrupt && ls src/vision_chat.py src/local_text_brain.py src/navigation_intents.py src/safe_action_gateway.py src/safe_action_middleware.py tools/resolve_vlm_runtime.py tools/vlm_smoke_test.py"
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

建议现场同时保留这几条：

```bash
tail -f /home/unitree/HongTu/interrupt/logs/robot-frontgate.log
tail -f /home/unitree/HongTu/interrupt/logs/robot-rtc-endpoint.log
```

### 7. 前门自启状态与重启

```bash
systemctl --user status interrupt-frontgate.service --no-pager -l
systemctl --user restart interrupt-frontgate.service
```

当前 service 关键点：

- service：`interrupt-frontgate.service`
- `ExecStart=%h/HongTu/interrupt/run_robot_frontgate_session.sh`
- 由于 `%h/HongTu` 可以是指向 `/data/HongTu` 的软链，所以迁到 `/data` 后仍能沿用

### 8. USB 麦三层枚举检查

现场如果发现：

- 前门不稳定
- `arecord stalled`
- `Device or resource busy`
- 唤醒后不进房间
- 进入房间后音频链异常

不要先怀疑上层 agent，先做三层检查：

```bash
lsusb
arecord -l
pactl list short sources
pactl list short sinks
```

健康状态至少要看到：

- `lsusb` 中出现 `8888:1719 MV-SILICON`
- `arecord -l` 中出现 `card ...: audio [mvsilicon B1 usb audio]`
- Pulse 里同时出现：
  - `alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
  - `alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`

如果这三层没有同时成立，不要继续调上层房间逻辑。

## 2026-05-27 现场离线旁路收口总结

### 1. 前门要继续自启，但要接离线旁路链路

当前现场验证通过的口径不是停掉前门，而是：

- 保持 `interrupt-frontgate.service` 开机自启
- 前门继续负责唤醒与派房
- 房间 agent 运行在 `offline_singlebox` 旁路模式
- 在线主链路保留，不直接破坏

也就是说，这轮是“前门仍然在线，自启仍然保留，房间侧切到离线旁路验证”。

### 2. “进入房间后没回复”不等于收音没切换

这一轮现场最容易误判的点是：

- 看到机器人没回复，就以为前门到房间的收音切换失败了

但实际排查结论是：

- `robot-rtc-endpoint.log` 已经能看到房间内转写到了用户的话
- 说明麦克风切换很多时候其实是成功的
- 真正出问题的往往是本地文本决策脑、视觉、或回复播报链

所以现场先看：

```bash
tail -f /home/unitree/HongTu/interrupt/logs/robot-rtc-endpoint.log
```

如果这里已经看到类似“你是谁”“你现在能看到什么”的转写，就不要再把问题误判成“房间没收音”。

### 3. “自己跟自己说话”本质上是回灌，不是单纯一句“没开 AEC”

现场现象包括：

- 机器人持续自己说话
- 出现两个声音
- 明明用户没继续说，房间里却又触发了一轮回复

这轮收口结论：

- 不是简单一句“系统完全没 AEC”
- 主要是某些本地播报链没有完整纳入当前 AEC 参考
- 再叠加双播路径没有完全收口，容易变成自说自听

这也是为什么恢复默认值统一要求：

- `INTERRUPT_ASSISTANT_AUDIO_MODE=transport_only`
- `INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE=transport_only`

尽量避免房间 assistant 再额外走本地镜像播报。

### 4. USB 麦丢失时，不要盲目回退到 APE

这轮现场踩过的坑是：

- USB 录音设备一度没枚举出来
- 如果这时强行让前门回退到 `APE/platform-sound`
- 很容易出现：
  - `Device or resource busy`
  - `arecord stalled`
  - 前门误占设备
  - 后续房间链音频状态更乱

恢复原则：

- USB 设备没枚举出来时，先修 USB 枚举本身
- 不要把“强制 APE 回退”当作默认恢复方案
- USB 回来后，再恢复 USB 优先选择

### 5. 离线单机模式当前真实能力边界

这轮最终可现场验证并跑通的最小能力，不是“完整离线大模型陪聊”，而是：

- 唤醒
- 开蓝灯
- 挥手
- 固定自我介绍
- 视觉问答保底链路

需要明确写进恢复文档的现实边界：

- 本地文本脑依赖远端/局域网 Ollama：`http://192.168.100.48:11434`
- 这个服务如果没起：
  - 动作/灯光 fastpath 仍可能可用
  - 固定自我介绍可以靠内建回复兜底
  - 视觉问答可以绕过本地文本脑直接兜底
  - 但开放式普通离线聊天会退化

所以当前“离线旁路可恢复最低演示面”是：

- 基础动作
- 灯光
- 固定介绍
- 视觉问答

不是完整开放闲聊。

### 6. 这轮补上的保底代码逻辑

这次现场为了让恢复后的旁路链路不再完全卡死在上游服务，补了几条必须同步的逻辑：

- `你是谁 / 自我介绍`：内建固定介绍词，避免依赖外部模型实时生成
- 前门唤醒播报：按唤醒语言播对应的自我介绍
- 本地文本脑失败时：
  - 视觉问答可直接走 `ask_camera_vision` 保底
  - 不再一律立刻落到“离线不可用”的统一失败话术
- 开启 `INTERRUPT_ENABLE_LOCAL_TEXT_REPLY_FALLBACK=1`
- 增加自说自听防护，避免最近播报文本被再次当成用户输入

### 7. 现场排障顺序建议

遇到“动作有了、但没播报”或“视觉失败”时，建议按这个顺序排：

1. 看前门是否正常：

```bash
tail -f /home/unitree/HongTu/interrupt/logs/frontgate.log
tail -f /home/unitree/HongTu/interrupt/logs/robot-frontgate.log
```

2. 看房间是否收到用户语音：

```bash
tail -f /home/unitree/HongTu/interrupt/logs/robot-rtc-endpoint.log
```

3. 看 agent 是否在回复链路上失败：

```bash
tail -f /home/unitree/HongTu/interrupt/logs/room-agent.log
```

4. 如果是视觉失败，先确认相机枚举和设备路径，再看 VLM 服务

5. 如果是完全自己跟自己说话，优先查双播、回灌和旧会话残留，不要先怀疑动作层

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
