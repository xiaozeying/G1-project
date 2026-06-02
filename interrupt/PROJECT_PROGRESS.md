# interrupt 项目进展记录

最后更新时间：2026-06-02

## 2026-06-02 offline_singlebox 现场收口

本轮目标不是继续扩能力，而是先把机器人收口到“可以正式现场测试”的状态。

当前已经新增并确认的收口结论：

- `offline_singlebox + local_text_ollama + prefer_tools` 已作为本轮机器人现场主口径固定
- 前门 `interrupt-frontgate.service` 已恢复为当前唯一推荐入口
- 中英文房间回复已重新对齐到 `external_usb_tts.sh -> USB sink`
- 英文推荐声线固定为 `en-US-JennyNeural`
- 中文推荐声线固定为 `zh-CN-XiaoxiaoNeural`
- 粤语继续保留单独 `edge-tts` 分支，推荐声线 `zh-HK-HiuGaaiNeural`
- 本地短碎片过滤、回灌抑制、自播保护已补强，明显减少“自己跟自己说话”
- 粤语专用 TTS 在房间事件循环里直接崩溃的问题已修复，不再触发：
  - `asyncio.run() cannot be called from a running event loop`

当前最准确的状态是：

- 主链已经能现场演示
- 但回复时延仍偏大
- 下一步最高优先级应转向“机器人本地回复 GPU 加速”

本轮单独收口说明、恢复口径与下一步建议见：

- `interrupt/docs/OFFLINE_SINGLEBOX_FIELD_STABILIZATION_2026-06-02.md`

## 2026-05-29 单机三语链路与前门接管收口

本轮把“现场能不能直接开机、唤醒、进入会话、稳定对答”这件事继续往可恢复包收紧了。

当前新增确定下来的收口点有五个：

- 前门唤醒后先释放 USB 麦，再交给房间 `rtc-endpoint` 接管
- 房间进入成功后的 `现在可以了` 不再走 OM1 本地直放，统一改成 room-agent 通过 RTC 播报
- `offline_singlebox` 下对短插话做过滤，不让 `Yeah / I. / OK / 嗯 / 好` 这类碎片触发新回复或把语言模式切成英文
- 本地问答 persona 统一成“笨笨同学 / BenBen”，不再允许回复里冒出 `Qwen`、`通义`、`阿里云` 之类底层模型名
- 运行模式与恢复口径已经固定为“RTC 单路播报优先，OM1 不再作为主回复播报链”

现场最重要的链路现已收成：

```text
前门唤醒
  -> 前门进程释放 USB 麦
  -> room-agent + rtc-endpoint 接管
  -> room-agent 通过 RTC 播报“现在可以了”
  -> 用户进入三语自适应对答 / 动作 / 灯光 / 视觉
  -> idle 超时退出房间
  -> 回到前门待机
```

本轮同时新增了仓库内可追踪的机器人部署脚本：

- `interrupt/deploy_fix.py`

用途是：

- 把当前仓库里的关键语音链文件直接推到 `192.168.100.30`
- 自动写入现场推荐 `.env.local`
- 远端编译检查
- 重启 `interrupt-livekit.service` 和 `interrupt-frontgate.service`

因此下次换机或重新恢复时，不再需要只靠聊天记录逐条敲命令。

## 当前状态

当前机器人主路径已经收口为：

```text
前门唤醒
  -> interrupt-frontgate.service
  -> 房间会话 / realtime agent
  -> Gemini Live
  -> G1 / OM1 工具与本地反馈
  -> idle 超时后回到前门待机
```

网页端与本地 Playground 仍保留，但已经不是当前真机联调主线。

## 2026-05-20 离线验收口径与音频启动收口

本轮补了两个很关键的收尾结论。

第一，已经明确“当前测试通过”主要仍是在线主链通过，不应直接写成“离线能力已完成验收”。

当前真实口径是：

- 默认模式仍是 `online_full`
- `offline_singlebox` 需要显式切换
- 当前没有正式收口成“断网自动切到离线模式”

因此后续必须把以下两件事分开：

- 在线主路稳定性测试
- 离线白名单能力验收

第二，已经把“开机后首播偶发没声音”从现场手动问题收成了前门启动自愈逻辑。

当前 `run_robot_frontgate_session.sh` 已新增：

- Pulse source/sink readiness wait
- 默认 USB sink/source 自愈
- `external_usb_tts.sh` 无声预热
- 预热失败自动重试一次
- 健康日志落盘：
  - `logs/audio-startup-health.log`

截至 `2026-05-20` 现场实测：

- `interrupt-frontgate.service` 可正常拉起
- 启动时能看到：
  - `robot pulse source ready`
  - `robot pulse sink ready`
  - `robot audio startup preflight: ok`
- `audio-startup-health.log` 已出现：
  - `status=ok`

这意味着“开机首播无声”已经不再依赖人工干预，而是进入启动阶段自动自愈。

## 2026-05-20 语音导航接口层收口

本轮把“导航不是 `interrupt` 的工作”这个工程边界正式收紧了。

当前明确：

- `interrupt` 只负责语音导航接口层
- 不负责导航算法、地图、定位、规划器、Nav2、move_base 的运行时
- 语音侧只稳定交付三类工具口：
  - `list_saved_locations`
  - `navigate_to_saved_location`
  - `remember_current_location`

当前 `interrupt` 已支持：

- `INTERRUPT_G1_NAV_PROVIDER=g1_3d_nav`
- 统一导航适配层 `src/g1_om1_adapter.py`
- 兼容导航桥入口：
  - `run_g1_3d_nav_bridge.sh`
  - `bridge/g1_3d_nav_bridge.py`

同时已确认机器人现有导航工作区口径是：

- `/home/unitree/g1_3d_nav`
- 点位主数据面：`/home/unitree/g1_3d_nav/maps/waypoints.yaml`

因此后续若出现：

- `nav2_msgs` 缺失
- overlay 失效
- `localhost:5000` 未监听
- 导航环境未编译完整

这些都归类为“导航后端运行时问题”，不再视为 `interrupt` 主链未收口。

接口契约文档见：

- `interrupt/docs/VOICE_NAVIGATION_INTERFACE_CONTRACT_2026-05-20.md`

## 2026-05-11 语音链恢复收口

本轮把“刷机后可一步恢复”的最小闭环又补齐了一层，当前已经明确：

- 前门 `wake_ack` 与房间 `room_ready_ack` 都可正常出声
- 普通话房间回复已经稳定走外接 USB 播报
- 英语房间回复已经稳定走外接 USB 播报，当前推荐女声是 `en-US-JennyNeural`
- 粤语仍保留单独 `edge-tts` 链
- `G1Om1Adapter.speak()` 已支持通过 `INTERRUPT_G1_SPEAK_SCRIPT` 分流到外部 USB TTS 脚本

当前最终推荐：

- 中文：`zh-CN-XiaoxiaoNeural`
- 英文：`en-US-JennyNeural`
- 粤语：`zh-HK-HiuGaaiNeural`

同时，本轮还确认了一个重要工程边界：

- 这台 Ubuntu 22.04 机器人上的 `g1_watchdog_feedback.py -> TtsMaker()` 不能稳定通过 `PULSE_SINK` 改路由到 USB
- 因此当前最稳恢复方案不是继续押注 Unitree 本地 TTS 出 USB
- 而是保住 `external_usb_tts.sh` 这条可恢复、可验证、可显式指定 USB sink 的路径

本轮已将关键脚本快照补进主仓：

- `interrupt/restore_assets/om1/external_usb_tts.sh`

完整恢复步骤见：

- `interrupt/docs/VOICE_CHAIN_ONE_SHOT_RESTORE_2026-05-11.md`

## 2026-05-07 Ubuntu 22.04 恢复补记

本轮在刷机后的 G1 Ubuntu 22.04.5 环境上，已经把前门主链重新恢复到可运行状态，并确认：

- `interrupt-frontgate.service` 可正常自启，当前主入口仍成立
- 缺失的 `g1-wakeword/` 已补回仓库，并能在 `wakeword-clean` 环境下真实加载
- `src.om1_wakeword_gate:factory` 已修复动态加载模块注册问题，不再无声回退到 mock
- 机器人当前真实可用 Unitree 接口不是 `eth1`，而是 `enP8p1s0`
- `run_frontgate_room_session.sh` 已验证可拉起 `room-agent` 和 `rtc-endpoint`
- 当前为优先保证主链稳定，机器人侧暂时关闭视觉入口：
  - `INTERRUPT_VISION_CHAT_ENABLED=0`
  - `INTERRUPT_VLM_ENABLED=0`

本轮额外确认的机器人口径：

- 板卡系统：Ubuntu 22.04.5
- 前门唤醒 Python：`/home/unitree/miniforge3/envs/wakeword-clean/bin/python`
- OM1 动作 / 灯光 Python：`/home/unitree/HongTu/OM1/.venv-g1/bin/python`
- 推荐恢复顺序：`interrupt/` -> `OM1/` -> `g1-wakeword/` -> 私有 `.env.local` -> `interrupt-frontgate.service`

## 2026-04-30 已验证状态

本轮已形成可恢复的真机快照，已验证链路为：

- 前门唤醒词可命中
- 命中后可进入房间
- 可进行三语言自适应对话
- assistant 回复支持被用户插话打断
- 会话 idle 超时后可退回前门待机
- VLM 单帧视觉问答可工作

当前真机唯一推荐主入口：

```bash
systemctl --user restart interrupt-frontgate.service
```

对应 service 文件：

```text
interrupt/deploy/systemd/user/interrupt-frontgate.service
```

## 当前已完成

- `tools/wakeword_session_frontgate.py`
  - 前门已改为 PTY 拉起 session，避免 console mode 退化为无音频 `(none) -> AgentSession -> (none)`
  - 会话退出后会销毁旧 wake gate，并恢复待机态 LED
  - 支持真实唤醒工厂不可用时回退到 `src.mock_wakeword:factory`
- `src/om1_wakeword_gate.py`
  - 三语言唤醒前门已支持常见误识别归一
  - 已修复 ASR 未初始化时的崩溃路径，从 `AttributeError` 改为可重试 `RuntimeError`
  - 已修复读取 `arecord` 管道时“进程活着但日志不再更新”的假活着卡死
  - 前门已有基础音量门限，减少静音和噪声误触发
- `src/g1_om1_adapter.py`
  - 默认 OM1 路径已按机器人优先级修正
  - G1 默认接口已统一为机器人当前真实可用口径优先
  - 已支持 `INTERRUPT_G1_SPEAK_SCRIPT` 外部分流
- `run_robot_frontgate_session.sh`
  - 已把机器人前门默认播放出口收口到 USB
  - 前门启动时会主动 `set-default-sink`、unmute 并拉到目标音量
  - 已新增启动音频预热、自愈重试与健康日志
  - 房间 idle 超时当前收口为 `INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS=180000`
- `src/agent.py`
  - 已接入 G1 / OM1 LED、动作、直接命令工具
  - 会话日志里已补充实时转写、打断调试钩子和函数工具执行日志
  - assistant 文本可镜像到 OM1 本地播报
  - 已接入天气、新闻、VLM 视觉问答能力
- `tools/frontgate_regression_test.py`
  - 已覆盖唤醒别名归一、会话态状态机、`eth1` 默认口径
- `tools/frontgate_smoke_test.py`
  - 已有前台门编排 smoke test
- `BOARD_UPGRADE_RESTORE_2026-04-30.md`
  - 已记录当前 verified robot state 的恢复流程、依赖快照与风险点

## 当前推荐参数

- `INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS=180000`
- `OM1_WAKEWORD_CHUNK_DURATION=1.6`
- `OM1_WAKEWORD_MERGE_HISTORY_CHUNKS=3`
- `OM1_AUDIO_GAIN=2.2`
- `PULSE_SINK=alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
- `PULSE_SOURCE=alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo`
- `INTERRUPT_RTC_OUTPUT_DEVICE=pulse`
- `INTERRUPT_FRONTGATE_PULSE_WAIT_TIMEOUT_S=12.0`
- 机器人前置相机当前按 `/dev/video2` 口径验证

## 当前仍未完全收口

以下问题仍属于“已知剩余收尾项”，不是主链路未打通：

- 唤醒词命中率仍需继续调优，仍存在切碎识别和误识别
- 从“我在，请说”到房间真正 ready 之间仍有空白时间
- thinking 阶段用户再次插话时，Gemini Live 仍可能触发上游 `1008 policy violation`
- 如果后续要继续收口“抢占旧播报”，仍需在 OM1 侧确认是否存在显式 stop 接口，而不是只依赖新文本覆盖旧播报
- `frontgate_smoke_test.py` 仍应继续加强，确保前门编排自测长期稳定、快速结束
- 离线能力仍未做完整专项验收；明天应按 `OFFLINE_ACCEPTANCE_PLAN_2026-05-20.md` 单独验证

## 调试交接结论

截至当前，已有这些明确结论：

- `interrupt-frontgate.service` 是当前机器人前门自启入口
- 前门 service 活着时会抢占 USB 麦
- 因此前门 service 与 rtc-endpoint 直连测试链路不能同时开
- USB 输出已确认可稳定走外接 USB 设备
- USB 输入在前门不抢占时可恢复正常回调
- 房间 idle 退出后，前门会回待机，不会沿用上一轮唤醒历史立即再次命中
- 默认模式仍是 `online_full`，不能把在线主链通过当成离线验收已完成
- 当前未正式收口成“断网自动切离线”

## 2026-04-30 快照与恢复基线

当前已留存可恢复快照，关键基线如下：

- Git 远端：`https://github.com/xiaozeying/G1`
- 分支：`g1-field-2026-04-24`
- Tag：`interrupt-frontgate-vlm-backup-2026-04-30`
- 参考基线：`interrupt-edge-cantonese-tts-2026-04-29`

当前恢复时必须一并关注：

- `interrupt/` 代码目录
- 机器人实际使用的 `OM1/` workspace
- 私有 `.env.local`
- `interrupt-frontgate.service`
- `interrupt/.venv`、wakeword env、`OM1/.venv`
- 音频卡枚举和 `/dev/videoX` 编号

详情见：

- `interrupt/BOARD_UPGRADE_RESTORE_2026-04-30.md`
- `interrupt/docs/HANDOFF_2026-04-27_ROBOT_USB_DIALOG.md`

## 下一阶段最值得继续做的事

- 继续优化唤醒词命中率与误触发率
- 压缩 wake ack 到 session ready 的空白时间
- 继续观察并定位插话时的上游 `1008 policy violation`
- 把前门 smoke test 收口成稳定自动回归
- board upgrade 后按恢复文档逐项验证 USB 音频、相机、systemd user service、代理和 OM1 环境
- 按 `interrupt/docs/OFFLINE_ACCEPTANCE_PLAN_2026-05-20.md` 做明天的离线专项验收
