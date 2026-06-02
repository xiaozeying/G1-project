# G1 Offline Single-Box Field Stabilization

更新时间：2026-06-02

## 1. 本文档用途

这份文档记录 `2026-06-02` 这一轮“先收口到可现场测试”的真实状态，重点回答四件事：

1. 当前机器人已经稳定到哪一步
2. 这一步实际改了什么
3. 刷机或代码回退后，如何恢复到当前状态
4. 下一步为什么要推进 GPU 加速

本文档对应的现场目标不是“所有能力都完美”，而是：

- 前门可稳定唤醒
- 唤醒后可进入房间对话
- `offline_singlebox` 可进行本地问答与白名单能力调用
- 中英 TTS 已对齐文档基线
- 粤语专用 TTS 已恢复可用
- 自播回灌和自问自答风险已显著收敛

## 2. 当前稳定口径

截至 `2026-06-02`，机器人 `192.168.100.30` 当前建议固定为：

- 运行模式：`offline_singlebox`
- 本地脑后端：`local_text_ollama`
- 决策模式：`prefer_tools`
- 前门入口：`interrupt-frontgate.service`
- 前门 Python：`/home/unitree/miniforge3/envs/wakeword-clean/bin/python`
- 房间 agent：`/home/unitree/HongTu/interrupt/run_room_agent.sh`
- 房间音频接管：`run_frontgate_room_session.sh`
- 本地 LiveKit：`ws://127.0.0.1:7880`
- 本地 LLM：`http://127.0.0.1:11434`

当前 TTS 口径固定为：

- 普通话：`zh-CN-XiaoxiaoNeural`
- 英文：`en-US-JennyNeural`
- 粤语：`zh-HK-HiuGaaiNeural`

当前播报分流固定为：

- 普通话 / 英文：`OM1/scripts/external_usb_tts.sh`
- 粤语：`interrupt/src/cantonese_tts.py` 单独 `edge-tts` 分支

## 3. 本轮实际收口内容

### 3.1 前门与房间接管

本轮继续保住的主链是：

```text
前门唤醒
  -> interrupt-frontgate.service
  -> 前门释放 USB 麦
  -> room-agent + rtc-endpoint 接管
  -> 本地脑在 offline_singlebox 下处理文本
  -> 本地 TTS 播报
```

相关文件：

- `interrupt/run_frontgate_session.sh`
- `interrupt/run_robot_frontgate_session.sh`
- `interrupt/run_frontgate_room_session.sh`
- `interrupt/tools/wakeword_session_frontgate.py`
- `interrupt/tools/frontgate_room_session.py`

### 3.2 自播回灌 / 自问自答收敛

本轮在 `interrupt/src/agent.py` 和 `interrupt/src/speech_loop_guard.py` 补了几层抑制：

- 短碎片过滤，不让 `Yeah / I. / OK / 嗯 / 好` 触发新回复
- 最近 assistant 回复回灌过滤
- 本地播报期间的 transcript guard
- 低信息量 transcript 过滤
- 播报后短时乱码 / 残片过滤
- 本地回复内容记忆，抑制刚播出的文本被再次当成新用户输入

当前已经明确解决过的现场问题包括：

- “我会回答你的问题...” 被再次识别成新用户输入
- `I.`、`.`、`So.` 这类碎片触发新一轮本地脑
- 英文 / 中文播报后被自己再次听回去

### 3.3 本地回复清洗

本轮在 `interrupt/src/agent.py` 内补了本地回复清洗，主要包括：

- 去掉工具决策元话术
- 去掉“下面是一个简短的自然语言回复”这类模板噪声
- 保留英文单词之间必要空格
- 去掉中英文之间影响 TTS 的异常空格
- 防止工具 payload 文本直接被读出来

这一步解决的是：

- “把空格播报出来”
- “把规则解释读出来”
- “把 JSON / payload / 工具提示词读出来”

### 3.4 中英 TTS 对齐恢复基线

本轮已把中英文房间回复重新对齐回文档基线：

- 默认走 `external_usb_tts.sh`
- 通过 `paplay` 明确落到 USB sink
- 中文推荐 `zh-CN-XiaoxiaoNeural`
- 英文推荐 `en-US-JennyNeural`

关键修复点：

- `OM1/scripts/external_usb_tts.sh`
- `interrupt/restore_assets/om1/external_usb_tts.sh`

实际修复内容：

- 修正 `INTERRUPT_ROOT` / Python 解析错误
- 避免静默退回 `espeak`
- 让恢复资产和机器人 active 脚本保持一致

### 3.5 粤语链路收口

本轮粤语链路分成两步收：

第一步，先让粤语问题能进入回复：

- `依家几点？`
- `你可以做到啲咩嘢？`
- `你係邊個？`

不再被误判成 `brief backchannel`。

第二步，修复粤语专用 TTS 在房间事件循环里的崩溃：

- 之前错误：`asyncio.run() cannot be called from a running event loop`
- 现在改为：
  - 无事件循环时直接 `asyncio.run`
  - 有事件循环时转到子线程合成

相关文件：

- `interrupt/src/cantonese_tts.py`
- `interrupt/src/speech_feedback.py`
- `interrupt/src/agent.py`

当前已在机器人上直接验证：

- `INTERRUPT_CANTONESE_TTS_ENABLED=1`
- `EdgeCantoneseTts(...).synthesize_and_play(...) == True`

### 3.6 前门采集自愈

本轮补了唤醒采集自愈逻辑：

- 当 `arecord` 报 `No such device`
- 或 `Cannot get card index`
- 或读管道假活着卡住

前门会尝试刷新 capture device 并重新绑定。

相关文件：

- `interrupt/src/om1_wakeword_gate.py`

## 4. 当前仍然存在的已知问题

### 4.1 回复延迟仍偏大

当前慢的主因已经不是前门，而是：

- `local_text_ollama` 本地脑生成耗时
- fallback 链路的 TTS 启动成本
- 发生回灌时会额外拖慢体感

当前结论：

- 主问题已经从“链路断”变成了“本地回复太慢”
- 下一步最高优先级是本地脑推理加速

### 4.2 粤语内容模板仍未完全固定

虽然粤语专用 TTS 已可工作，但当前仍可能出现：

- 用户说粤语
- 语言识别是 `zh-YUE`
- 本地脑回的文本却仍偏普通话

也就是说，当前“语言跟随”已经能走到：

- 识别语言正确
- 进入对应回复链正确
- TTS 分流正确

但“固定粤语口语模板”这件事还没有完全做完。

### 4.3 视觉能力仍依赖现场相机状态

当前视觉问题若出现：

- `camera vision query failed`
- `capture_failed`

通常不是对话主链断，而是现场相机采集未成功。

## 5. 当前建议的恢复步骤

### 5.1 机器人目标目录

建议统一恢复到：

- `/data/HongTu`

并保留兼容软链：

- `/home/unitree/HongTu -> /data/HongTu`

### 5.2 代码与资产恢复顺序

1. 恢复 `interrupt/`
2. 恢复 `g1-wakeword/`
3. 恢复 `OM1/`
4. 恢复 `interrupt/.env.local`
5. 同步 `interrupt/restore_assets/om1/external_usb_tts.sh` 到 `OM1/scripts/external_usb_tts.sh`
6. 确认 `wakeword-clean`、`interrupt/.venv`、`OM1/.venv-g1` 可用
7. 恢复 `interrupt-frontgate.service`
8. 重启并检查日志

### 5.3 关键环境变量

当前机器人侧至少应明确：

```bash
INTERRUPT_AGENT_RUNTIME_MODE=offline_singlebox
INTERRUPT_AGENT_BACKEND=local_text_ollama
INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools
INTERRUPT_G1_SPEAK_SCRIPT=/home/unitree/HongTu/OM1/scripts/external_usb_tts.sh
OM1_EDGE_TTS_PYTHON=/home/unitree/HongTu/interrupt/.venv/bin/python
OM1_EDGE_TTS_ZH_VOICE=zh-CN-XiaoxiaoNeural
OM1_EDGE_TTS_EN_VOICE=en-US-JennyNeural
INTERRUPT_CANTONESE_TTS_ENABLED=1
INTERRUPT_CANTONESE_TTS_VOICE=zh-HK-HiuGaaiNeural
PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
PULSE_SOURCE=alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo
```

### 5.4 当前唯一推荐入口

```bash
systemctl --user restart interrupt-frontgate.service
```

### 5.5 重启后建议立即检查

```bash
systemctl --user --no-pager --full status interrupt-frontgate.service
tail -n 80 /home/unitree/HongTu/interrupt/logs/frontgate.log
tail -n 120 /home/unitree/HongTu/interrupt/logs/room-agent.log
```

重点看：

- 是否正常进入 `offline_singlebox`
- 是否仍是 `local_text_ollama`
- 是否存在 `asyncio.run() cannot be called from a running event loop`
- 是否出现新的自播回灌

## 6. 当前可视为“到位”的现场测试项

当前已经可按下面口径做现场测试：

- 唤醒词命中
- `现在可以了` 正常播报
- 基础多轮问答可进入
- 白名单动作 / 灯光能力可调
- 基础视觉问答入口可触发
- 中英 TTS 走文档基线
- 粤语专用 TTS 已不再因事件循环直接崩溃

## 7. 下一步建议

下一步不建议继续优先修文案细节，而应先做：

## 7.1 机器人本地回复 GPU 加速

目标：

- 把 `local_text_ollama` 的首 token 与整句回复延迟明显压下去
- 优先解决“能用但体感太慢”

建议方向：

1. 确认机器人当前 Ollama / 本地模型实际是否已走 GPU
2. 检查 Jetson 上模型量化、上下文长度、并发和显存占用
3. 若当前 `qwen2.5:7b` 延迟过高，评估：
   - 更小模型
   - 更低量化
   - 更短 prompt
   - 更明确的固定模板 fast path
4. 必要时把高频问答做成前置本地模板，减少每次都走完整 LLM 推理

## 7.2 粤语高频问答模板固定

等 GPU 加速稳定后，再推进：

- `你係邊個？`
- `你可以做到啲咩嘢？`
- `依家几点？`

这类高频粤语问句固定成自然粤语模板，避免继续先产普通话文本再走粤语 TTS。
