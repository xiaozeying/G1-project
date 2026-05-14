# G1 语音-视觉-安全中间层-动作融合架构建议

更新时间：2026-05-12

这份文档基于以下四类材料收口：

- 本地现状：
  - `interrupt/docs/VOICE_CHAIN_ONE_SHOT_RESTORE_2026-05-11.md`
  - `interrupt/docs/WEBRTC_FULL_DUPLEX_MIGRATION_ANALYSIS_2026-04-21.md`
  - `interrupt/src/agent.py`
  - `interrupt/src/vision_chat.py`
  - `interrupt/src/g1_om1_adapter.py`
- 外部深度分析：
  - `/home/zz/下载/robot_voice_arch_deep_analysis.md`
- 外部项目：
  - RAI
  - g1pilot
  - OttoGuide

目标不是再写一份概念报告，而是形成适合我们当前 `interrupt + OM1 + g1-wakeword + G1` 组合的最终上层架构，并补出离线模型替换的测试路线。

## 1. 当前代码现状

当前仓库已经具备四个重要基础能力：

1. 三语言唤醒前门已存在，前门拉起实时语音会话的主入口已经稳定。
2. LiveKit Agent 会话已接好打断、多语言跟随、视觉工具和本地工具。
3. 视觉链路已经是“一次抓帧 + 调 VLM”的清晰边界。
4. 动作、LED、导航已经被封装到 `G1Om1Adapter` 一层。

但也有一个决定性缺口：

- 现在动作工具仍然是 `InterruptAssistant -> function_tool -> _execute_*_local -> G1Om1Adapter`。
- 中间只有“最近用户意图匹配”和少量 fastpath 去重，没有独立的安全裁决层。
- 这意味着 LLM 仍然离底层执行太近，动作策略、动作许可、动作互斥、人体接近、执行窗口、速率限制都没有成为独立模块。

换句话说，我们已经有了“可用的语音/视觉/动作系统”，但还没有真正拥有“可上线的安全语音机器人架构”。

## 2. 三个外部项目的横向结论

## 2.1 RAI

RAI 最值得借的是“多 Agent + 多模态 + ROS2 Connector”思路。

- 优点：
  - 语音、视觉、工具调用、ROS2 接口抽象完整。
  - ASR/TTS 已经被拆成独立 Agent，天然适合多模态编排。
  - 适合做上层感知和推理编排框架。
- 不足：
  - 对 G1 这种具身平台的动作安全约束不够强。
  - Tool call 到 ROS2 执行之间缺少强制安全闸门。
  - 更像“能力框架”，不是“机器人安全执行框架”。

对我们的启发：

- 把 RAI 的价值放在上层：
  - 语音理解
  - 视觉理解
  - 任务规划
  - 多 Agent 协调
- 不要照搬成“LLM 直接打 ROS2/SDK”。

## 2.2 g1pilot

g1pilot 最值得借的是“物理隔离 + 控制分层”。

- 优点：
  - 明确保留 Unitree 原生下肢/步态控制。
  - 对上肢提供 joint/cartesian 两种可控接口。
  - 运行时切换控制模式，接口清晰。
  - 有持续状态反馈，适合做闭环监控。
- 不足：
  - 没有语音、视觉、LLM 编排。
  - 没有任务状态机和打断恢复。

对我们的启发：

- 下肢和平衡不应该暴露给上层大模型。
- 语音和视觉只应该触发：
  - 上肢预定义动作
  - 经过授权的导航
  - 有边界的灯光/播报
- g1pilot 的价值应成为“底层安全执行边界”。

## 2.3 OttoGuide

OttoGuide 最值得借的是“状态机先于自由对话”。

- 优点：
  - 导航类任务边界清楚。
  - 异步状态机对导览场景很稳。
  - 把“什么状态能接什么命令”说清楚了。
- 不足：
  - 开放域能力弱。
  - 没有视觉推理和操作能力。
  - 不适合直接承担复杂多模态上层。

对我们的启发：

- 安全中间层必须吸收 OttoGuide 的状态机思想。
- 特别是在：
  - 导航中
  - 播报中
  - 动作执行中
  - 人靠近机器人时
  - 需要回 idle/frontgate 时
  都应该由中间层而不是 LLM 自己决定允许哪些动作。

## 2.4 最终归纳

三个项目最适合我们的组合方式不是三选一，而是：

- 上层感知与推理：借 RAI
- 底层运动与物理边界：借 g1pilot
- 任务状态与执行许可：借 OttoGuide

## 3. 建议的最终架构

```text
用户
  -> 三语言唤醒前门
  -> LiveKit 准实时语音会话
  -> 上层感知与推理层
     - ASR / VAD / interruption
     - 多语言对话 Agent
     - 视觉问答 / 场景理解 / 任务规划
  -> 安全中间层
     - 意图规范化
     - 状态机
     - 动作白名单
     - 互斥和速率限制
     - 人体/距离/空间校验
     - 执行授权与降级
  -> 执行适配层
     - G1 upper-body action adapter
     - LED adapter
     - nav adapter
     - speak adapter
  -> 底层控制
     - g1pilot / OM1 / Unitree native loco
```

核心原则只有一句：

- 语音和视觉在上层负责“理解世界”和“提出动作意图”。
- 安全中间层负责“决定是否允许执行、执行到什么粒度、何时打断和如何恢复”。
- 底层执行层只负责“可靠执行已经被批准的指令”。

## 4. 分层职责

## 4.1 上层语音与视觉

这一层保留现在 `interrupt` 的主方向，但要进一步去业务直连。

建议保留：

- 三语言唤醒前门
- LiveKit Agent 会话与打断
- 多语言跟随回复
- `ask_camera_vision` 这种“一次视觉观察”工具

建议增强：

- 让视觉不仅回答“看到了什么”，还输出结构化 observation：
  - `person_detected`
  - `distance_band`
  - `obstacle_near_arms`
  - `free_space_front`
  - `human_attention`
- 语音层不仅输出自然语言，还输出结构化 intent：
  - `speak`
  - `gesture`
  - `navigate`
  - `led`
  - `vision_query`
  - `cancel`
  - `pause`

这层的输出不应是“直接执行命令”，而应是“候选意图 + 置信度 + 参数”。

## 4.2 安全中间层

这是最终架构的核心新增层。

建议新增一个独立域层，而不是继续把逻辑塞进 `agent.py`：

- `src/safe_action_gateway.py`
- `src/action_policy.py`
- `src/robot_state_guard.py`
- `src/execution_fsm.py`

这一层至少要做六件事：

1. 意图白名单化
   - 只允许预定义动作、预定义 LED、预定义导航。
   - 禁止自由文本直接映射到底层 SDK。
2. 状态机裁决
   - `idle`
   - `listening`
   - `speaking`
   - `navigating`
   - `gesture_running`
   - `vision_busy`
   - `human_too_close`
   - `error_recovery`
3. 互斥规则
   - 导航中禁止大幅上肢动作。
   - 手臂动作执行中禁止再次下发另一组手臂动作。
   - 播报打断优先级高于普通回复。
4. 速率限制
   - 同类动作冷却时间。
   - 高频灯光命令去抖。
   - 重复导航命令抑制。
5. 空间与人体安全
   - 人体近距离时只允许小幅动作或完全禁止。
   - 视觉检测到前方拥挤时禁止挥手/击掌这类外扩动作。
6. 降级与恢复
   - 不满足安全条件时回复解释，不执行动作。
   - 执行失败时回到可恢复状态，不让 Agent 自行乱补动作。

## 4.3 执行适配层

这一层应该尽量“笨”，不做策略判断。

建议保留现有适配边界：

- `G1Om1Adapter.speak()`
- `G1Om1Adapter.set_led()`
- `G1Om1Adapter.execute_direct_text()`
- 导航桥接

但建议收紧入口：

- 废弃“自由文本执行”为默认路径。
- 把 `execute_direct_text` 改成仅供安全层内部兜底，不再直接暴露给 LLM。
- LLM 默认只能发：
  - `perform_body_action(action_id)`
  - `set_led_color(color_id)`
  - `navigate_to_saved_location(location_id)`
  - `speak(text, mode)`

## 4.4 底层控制

底层控制应坚持 g1pilot 的哲学：

- 下肢和平衡由 Unitree 原生控制保持主导。
- 上肢控制暴露有限接口。
- 导航是高层目标，不是逐步位移文本命令。
- 所有危险自由度都不直接给 LLM。

## 5. 对现有代码的直接改造建议

## 5.1 `interrupt/src/agent.py`

现状：

- 已经有工具层。
- 已经有打断、多语言、视觉工具。
- 已经有本地 fastpath 和最近意图保护。

建议：

- 保留 Agent 作为“交互编排层”。
- 让 tool 只调用 `SafeActionGateway`，不再直接进 `G1Om1Adapter`。
- `perform_body_action`、`navigate_to_saved_location`、`set_led_color` 全部先过安全层。

## 5.2 `interrupt/src/vision_chat.py`

现状：

- 当前实现已经是清晰的单帧抓图 + OpenAI 兼容接口调用。
- 但内部函数名和鉴权逻辑还是 Gemini 绑定。

建议：

- 把 `_request_gemini_vision()` 抽象成 provider：
  - `openai_compatible`
  - `gemini_openai_compat`
  - `vllm`
  - `sglang`
- 让视觉层天然支持本地 VLM 替换。

## 5.3 `interrupt/src/g1_om1_adapter.py`

现状：

- 已经把播报、LED、动作、导航入口收口到一处。

建议：

- 继续保留这一层，不要让安全策略反向污染到底层适配器。
- 适配器只关心：
  - 参数是否合法
  - 命令是否发出
  - 返回码和 stdout/stderr

## 6. 离线大模型替换在线 API 的现实边界

这里要明确分成两件事，不要混在一起：

## 6.1 视觉/文本模型替换

这个最容易做，因为当前 `vision_chat.py` 已经在调 OpenAI 兼容接口。

所以第一阶段最适合替换的是：

- 视觉问答 VLM
- 非实时文本规划模型
- 结构化意图抽取模型

## 6.2 实时语音对话模型替换

这个难得多，因为当前实时会话依赖：

- LiveKit Agents
- `livekit.plugins.google`
- Gemini Live 原生实时音频能力

所以“离线替换在线 API”不应一上来就替换整条实时链，而应该分阶段：

1. 先替换视觉 VLM
2. 再替换文本推理/规划模型
3. 最后再评估是否替换原生实时语音模型

否则会同时碰：

- VAD
- 流式 ASR
- 流式对话
- 流式 TTS
- 打断恢复

工程风险会陡增。

## 7. 离线模型测试建议

## 7.1 先做 OpenAI 兼容本地服务

建议统一采用本地 OpenAI 兼容入口，优先选：

- `vllm`
- `sglang`
- 必要时 `ollama` 只用于轻量文本实验

这样可以最大化复用现有 `vision_chat.py` 的调用方式。

## 7.2 候选模型分工

截至 2026-05-12，我能核对到的公开开源多模态候选里，建议这样分：

- 视觉主测：
  - Qwen2.5-VL
  - Gemma 3
  - GLM-4.1V 或 GLM-4.5V
- 轻量文本/意图抽取：
  - Gemma 3 4B/12B
  - Qwen 系列小模型

说明：

- 你提到的 `GLM-5V` 我这次没有核对到明确的公开官方 VLM 发布口径。
- 当前能核对到的公开 GLM 视觉线更接近 `GLM-4.1V` / `GLM-4.5V`。
- 所以若我们现在做离线对比，GLM 分支建议先落到 `GLM-4.1V` 或 `GLM-4.5V`，除非你们内部已经有 `GLM-5V` 可用服务。

## 7.3 测试分三层

### A. 单模型离线能力测试

目标：

- 不连机器人，只验证模型本身。

测试项：

- 单图问答
- 中文/英语/粤语输出稳定性
- 物体计数
- 人/障碍物/桌面物体识别
- “看不清就承认看不清”的服从性
- 输出是否天然简短

## B. `interrupt` 集成测试

目标：

- 验证本地模型能否无缝接进现有工具链。

测试项：

- `tools/vlm_smoke_test.py` 跑通
- `ask_camera_vision` 跑通
- 超时重试是否合理
- 失败时回退话术是否稳定

## C. 真机任务测试

目标：

- 看模型是否真的适合机器人任务，而不是只会答题。

测试项：

- “前面有人吗”
- “桌上有什么”
- “我可以挥手吗”
- “前面空间够不够做击掌动作”
- “导航前方是否拥堵”

这一层必须和安全中间层联调，因为最终关心的是“视觉是否足够支持动作许可判断”。

## 7.4 建议测试矩阵

| 维度 | Gemini 在线基线 | Qwen2.5-VL | Gemma 3 | GLM-4.1V/4.5V |
|---|---|---|---|---|
| 单图识别准确率 | 基线 | 对比 | 对比 | 对比 |
| 中文口语回答 | 基线 | 对比 | 对比 | 对比 |
| 英语回答 | 基线 | 对比 | 对比 | 对比 |
| 粤语回答 | 基线 | 对比 | 对比 | 对比 |
| 响应延迟 | 基线 | 记录 | 记录 | 记录 |
| GPU 占用 | 基线 | 记录 | 记录 | 记录 |
| “看不清”服从性 | 基线 | 记录 | 记录 | 记录 |
| 动作安全判断辅助价值 | 基线 | 记录 | 记录 | 记录 |

## 7.5 最低实现改造

如果只为了先开始测试，不需要先重构整套系统，最小改造可以只有两步：

1. 给 `vision_chat.py` 增加 provider 抽象和本地 base_url 配置。
2. 给 `config.yaml` 增加本地模型配置组：
   - `provider`
   - `base_url`
   - `model`
   - `api_key`
   - `timeout`

这样我们就能在不碰实时语音主链的情况下，先完成离线 VLM 替换测试。

当前仓库里对应的最小落地入口已经补成：

- `interrupt/tools/vlm_backend_probe.py`
- `interrupt/tools/vlm_smoke_test.py`
- `interrupt/run_offline_vlm_smoke.sh`
- `interrupt/run_robot_offline_vlm_validation.sh`
- `interrupt/docs/OFFLINE_VLM_BRANCH_VALIDATION_2026-05-12.md`

## 8. 推荐实施顺序

建议按下面的顺序推进：

1. 先把“安全中间层”从 `agent.py` 中独立出来。
2. 把视觉调用从 Gemini 绑定改成 provider 抽象。
3. 先做本地 VLM 替换测试，不动实时语音主链。
4. 用视觉结果参与动作许可判断，形成“视觉辅助安全”闭环。
5. 再评估是否替换实时语音模型。

## 9. 最终建议

最终推荐架构不是“一个超大 Agent 直接管所有东西”，而是：

- `interrupt` 继续做上层实时交互壳
- 视觉和语言模型继续做感知与推理
- 新增独立安全中间层做动作裁决
- 底层动作保持 g1pilot/OM1/Unitree 的硬边界

一句话总结：

- RAI 负责聪明
- OttoGuide 负责有序
- g1pilot 负责不摔
- 我们新增的安全中间层负责不乱动

## 10. 参考链接

- RAI GitHub: https://github.com/RobotecAI/rai
- RAI Voice Interface: https://robotecai.github.io/rai/tutorials/voice_interface/
- RAI ASR Agent: https://robotecai.github.io/rai/speech_to_speech/agents/asr/
- RAI TTS Agent: https://robotecai.github.io/rai/speech_to_speech/agents/tts/
- g1pilot: https://github.com/hucebot/g1pilot
- OttoGuide: https://github.com/LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU
- 本地深度分析：`/home/zz/下载/robot_voice_arch_deep_analysis.md`
