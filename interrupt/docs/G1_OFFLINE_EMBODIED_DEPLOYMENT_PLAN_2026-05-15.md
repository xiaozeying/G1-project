2# G1 离线具身智能部署方案与最终目标

更新时间：2026-05-15

## 1. 这份方案解决什么问题

目标不是把一个大模型“塞进机器人”，而是给 `Unitree G1 Edu + Dex3 + Jetson Orin NX 16GB` 落一套真正能运行、能验收、能逐步扩离线比例的具身智能部署方案。

这套方案同时满足四个约束：

- 必须保住当前在线完整版能力，不因本地化倒退。
- 必须允许机器人在断网时维持一个安全、可验证、边界清晰的单机离线能力集。
- 必须把视觉理解、工具调用、导航、动作、安全控制分层，而不是让 VLM 直接碰底层控制。
- 必须以当前仓库已经存在的本地化进度为基础推进，而不是另起炉灶。

---

## 2. 当前现实状态

结合 `2026-05-14/15` 几份文档和当前仓库实现，现状可以明确分成三层：

### 2.1 已经具备的部分

- `online_full / offline_singlebox` 双模式已经在代码里落地。
- 离线白名单能力已经在 `interrupt/src/agent.py` 实现。
- 本地文本脑已经落地：
  - `interrupt/src/local_text_brain.py`
  - `interrupt/run_local_text_brain_smoke.sh`
  - `interrupt/run_robot_text_brain_smoke.sh`
- 本地离线 VLM 验证链已经落地：
  - `interrupt/run_local_offline_vlm_validation.sh`
  - `interrupt/run_robot_offline_vlm_validation.sh`
  - `interrupt/tools/resolve_vlm_runtime.py`
- 启动和巡检已经能打印：
  - `INTERRUPT_AGENT_RUNTIME_MODE`
  - `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE`

### 2.2 已验证到的阶段

- 本机离线 VLM 已可作为本地化视觉基线。
- G1 已可通过局域网访问开发机 Ollama。
- G1 上本地文本脑 smoke 已能返回：
  - `perform_body_action`
  - `ask_camera_vision`
- 正式房间 agent 已具备“Gemini 实时语音壳 + 本地文本工具决策”的混合接入基础。

### 2.3 仍然没有完成的部分

- 正式主会话仍未完全切到纯离线语音主链。
- VLM、文本脑、导航、动作、安全网关还没有收成一套统一的“离线具身运行面”。
- 一些脚本/探针的表述已经落后于主代码进度。
  - 例如 `interrupt/tools/agent_backend_probe.py` 仍把 `local_text_ollama` 标成 `room_agent_not_integrated`，但 `interrupt/src/agent.py` 已经有本地文本脑分流逻辑。

结论：现在不是“从零开始设计”，而是“把已有离线能力收口成正式部署面，并明确终态边界”。

---

## 3. 最终目标

最终目标不是“全离线全能机器人”，而是两个模式并存、可切换、各自边界清晰。

### 3.1 目标一：在线完整版 `online_full`

在线完整版必须继续保留：

- 三语言自适应：普通话、粤语、英语
- 稳定普通对话
- 视觉问答
- 动作执行
- 导航执行
- 打断与恢复
- RTC 单路播报链
- 在线增强问答：天气、新闻、开放知识

本地化后也不能退化：

- 不能漂移成底层模型身份
- 不能明显降低普通聊天质量
- 不能破坏打断体验
- 不能引入明显重复播报或自听回环

### 3.2 目标二：单机离线版 `offline_singlebox`

单机离线版只开放低风险、强结构化、可验证能力：

- 唤醒与基础会话
- 上半身动作
- 灯光控制
- 视觉问句
- 查询已保存地点
- 导航到已保存地点
- 记住当前位置

离线版必须明确禁止：

- 开放式闲聊主回复
- 天气、新闻等外部实时数据能力
- 高自由度开放推理
- 长上下文自由对话
- 未通过白名单约束的动作/导航/工具调用

### 3.3 目标三：形成“具身智能分层系统”而不是“单模型统治”

终态架构不是一个模型包办全部，而是：

- 感知层：相机、深度、OCR、检测、跟踪
- 语义层：轻量/中量 VLM 做观察、解释、工具选择
- 编排层：Agent + MCP/本地工具 schema
- 执行层：导航、动作、记忆、视觉工具
- 安全层：动作限幅、白名单、干运行、失败回退
- 控制层：ROS/Unitree SDK/Dex3 驱动

---

## 4. 推荐终态架构

### 4.1 主架构

```text
用户语音/文本
  -> 实时会话壳（当前保留 Gemini Realtime）
  -> 本地文本脑 / 本地 VLM 决策
  -> 工具编排层（本地 schema，后续可扩 MCP）
  -> 安全网关
  -> G1 / Dex3 / Nav / Vision 执行器
```

### 4.2 关键分工

- `Gemini realtime`
  - 负责当前最稳的实时语音壳、打断、在线增强回答
- `local_text_brain`
  - 负责离线工具意图识别、工具调用选择、离线超界拒答
- `offline VLM`
  - 负责视觉观察和图像问答
- `safe_action_gateway`
  - 负责动作白名单、限幅、干运行、失败拒绝
- `G1Nav2D / 位置记忆`
  - 负责地点查询、记忆、导航执行

### 4.3 模型路线建议

按当前选型目标，模型路线应明确分成 `首选方案 / 生产方案 / 长期演进方案`，而不是把“当前能跑的临时基线”和“最终主线”混写。

#### 首选方案：`MiniCPM-V 4.6`

定位：

- 板端优先验证的一体化边缘多模态 VLM
- 视觉理解 + 工具调用一体化候选
- 离线 MCP/工具链最值得优先验证的模型

原因：

- 截至 `2026-05-15`，它是当前方案里最强调“边缘多模态 + 工具调用”的候选。
- 参数量仅 `1B`，对 `Jetson Orin NX 16GB` 资源压力最小。
- `Apache-2.0` 许可，对后续项目化落地更友好。
- 按候选报告结论，可通过 `vLLM + qwen3_coder parser` 接出完整工具调用链。

适合承担：

- 离线视觉问答
- 结构化工具选择
- 轻量板端 agent-vlm 验证

注意：

- 这里的“首选”是指模型选型优先级，不等于当前仓库已经完成 MiniCPM-V 正式接入。
- 真正上默认链路前，仍必须通过本地工具评测、格式稳定性评测和机器人侧长稳验证。

#### 生产方案：`Qwen2.5-VL-3B + Qwen3.5-4B` 分离架构

定位：

- 当前最适合作为工程生产形态的双模型架构
- 视觉理解与工具调用解耦

分工：

- `Qwen2.5-VL-3B`
  - 负责图像理解、前视观察、OCR/场景问答
- `Qwen3.5-4B`
  - 负责文本推理、工具选择、结构化输出

原因：

- 这条路线更符合“感知层 / 决策层”解耦思路。
- 按你给出的基准结论，`Qwen3.5-4B` 在独立测试中以 `97.5%` 准确率超过更大模型，更适合承担工具调用核心脑。
- 对当前仓库也更友好：
  - 视觉链已有 `VLM` 接入面
  - 文本链已有 `local_text_brain` 接入面

这条路线的工程意义是：

- 不强迫一个小 VLM 同时把视觉、对话、工具调用全部做到最优
- 先把“视觉可解释”和“工具调用可控”分别做稳
- 更容易灰度替换某一侧模型

#### 长期演进：`NVIDIA Cosmos Reason2 2B`

定位：

- 物理 AI / 空间推理增强模型
- 面向 NVIDIA 生态深度整合的长期方向

适合作为：

- 空间关系理解增强器
- 物理场景解释器
- 与 `Isaac / GR00T` 体系联动的长期演进模块

不建议短期直接把它定义成主生产脑，原因是：

- 当前仓库工具链、脚本链和验证链更接近通用 OpenAI-compatible / Ollama 路线
- Cosmos 更适合作为中长期“物理推理增强层”，而不是现在立刻替换所有现有链路

#### 当前仓库落地基线

虽然上面的选型优先级如上，但当前仓库已经验证到的现实基线仍是：

- 本地文本脑：`qwen2.5:7b` over Ollama
- 本地视觉链：`Qwen2.5-VL` / `gemma3` 路线已有脚本与 probe

因此正确推进顺序是：

1. 先用当前基线把链路做稳。
2. 再把 `MiniCPM-V 4.6` 接入为一体化候选主线。
3. 并行保留 `Qwen2.5-VL-3B + Qwen3.5-4B` 作为生产分离架构。
4. 最后把 `Cosmos Reason2 2B` 作为物理 AI 增强路线引入。

原则：

- Orin NX 16GB 上不追求大模型全能。
- 先保证工具调用稳定，再追求更强开放能力。
- 模型只做高层决策，不直接下发底层控制。

---

## 5. 推荐部署策略

## 5.1 总体策略

采用“三层部署”：

- `第 1 层：开发机`
  - 跑本地 VLM / 本地文本脑 / 评测 / 日志
- `第 2 层：G1 机载 Orin NX`
  - 跑正式会话、采集、执行、安全网关、导航桥
- `第 3 层：可选离线局域网 GPU 主机`
  - 需要更大 VLM 时再接入，不作为第一阶段前提

这样做的原因：

- 当前仓库已证明“G1 消费开发机上的离线模型服务”是最现实路径。
- 不把 Orin NX 直接压成“大模型 + 视觉 + 控制”一锅煮。
- 有利于先把链路跑稳，再考虑把更多模型收回机载。

## 5.2 近期正式推荐模式

### 模式 A：生产推荐

- `INTERRUPT_AGENT_RUNTIME_MODE=online_full`
- `INTERRUPT_AGENT_BACKEND=gemini_realtime`
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools`
- `INTERRUPT_VLM_PROVIDER=openai_compatible` 或已验证离线路径

用途：

- 保住在线会话质量
- 让动作/视觉/导航等结构化能力优先走本地化
- 发生异常时可回退在线链

### 模式 B：离线验收模式

- `INTERRUPT_AGENT_RUNTIME_MODE=offline_singlebox`
- `INTERRUPT_AGENT_BACKEND=gemini_realtime` 或后续本地语音壳
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools`
- `INTERRUPT_VLM_*` 指向强制离线可达服务

用途：

- 断网验收
- 验证离线白名单能力
- 不允许越界到开放式聊天

### 模式 C：灰度扩大本地化比例

- `INTERRUPT_AGENT_RUNTIME_MODE=online_full`
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_all`

用途：

- 小范围验证本地文本脑是否能接住更多非工具类回复

前提：

- 必须先通过 `prefer_tools` 长稳测试
- 必须证明不会引入身份漂移、闲聊降级、播报问题

---

## 6. 分阶段部署方案

## 6.1 第一阶段：收口当前已完成能力

目标：把“能 smoke”收成“能复现”。

要做的事：

- 固化开发机局域网模型服务入口
  - `interrupt/run_lan_ollama_serve.sh`
- 固化 G1 侧本地文本脑探针
  - `interrupt/run_robot_text_brain_smoke.sh`
- 固化本机/机器人离线 VLM 验证
  - `interrupt/run_local_offline_vlm_validation.sh`
  - `interrupt/run_robot_offline_vlm_validation.sh`
- 统一巡检入口
  - `interrupt/tools/check_env.py`

通过标准：

- G1 能稳定访问开发机上的本地模型服务
- 动作/视觉两个 smoke 至少连续通过
- 离线 VLM 在本机和 G1 侧都能明确区分“通过 / 失败”，不假通过

## 6.2 第二阶段：做成混合生产链

目标：形成可对外演示、可日常联调的稳定默认形态。

配置建议：

- `runtime_mode=online_full`
- `backend=gemini_realtime`
- `local_text_decision_mode=prefer_tools`

要做的事：

- 把动作、视觉、导航、地点记忆全部纳入本地文本脑工具判定
- 把离线白名单和超界播报作为默认守门逻辑
- 打通以下链路：
  - 用户说动作 -> 本地工具调用 -> 安全网关 -> 执行
  - 用户问前方 -> 本地文本脑 -> `ask_camera_vision`
  - 用户说去前台 -> 地点表查询 -> 导航桥 -> 执行

通过标准：

- 在线对话质量不退化
- 结构化能力优先走本地链
- 本地链异常时能够优雅失败或回退

## 6.3 第三阶段：离线单机验收

目标：形成真正可断网演示的 `offline_singlebox`。

要做的事：

- 强制白名单工具集
- 所有超界请求统一播报拒答
- 关闭天气/新闻/开放知识
- 验证断网后仍可执行：
  - 动作
  - 灯光
  - 视觉问句
  - 地点查询
  - 地点导航
  - 位置记忆

通过标准：

- 断外网时上述能力稳定可复现
- 超界请求不误执行、不误转闲聊
- 模型不可用时明确提示不可用，不假装成功

## 6.4 第四阶段：扩展为 MCP 风格具身编排层

目标：从“本地函数调用”升级成“标准化工具层”。

要做的事：

- 将当前工具 schema 逐步抽象为 MCP 风格接口
- 最先标准化这些工具：
  - `perform_body_action`
  - `set_led_color`
  - `ask_camera_vision`
  - `list_saved_locations`
  - `navigate_to_saved_location`
  - `remember_current_location`
- 后续再扩：
  - `robot_state`
  - `motion_plan_dry_run`
  - `hand_grasp_candidates`
  - `memory/resources`

通过标准：

- 模型输出与执行层解耦
- 工具权限和审计更清晰
- 为后续接 Qwen3-VL / Gemma4 / 外置工作站留标准接口

---

## 7. 具体落地步骤

## 7.1 开发机侧

1. 启动局域网可访问的本地模型服务。

```bash
cd interrupt
bash ./run_lan_ollama_serve.sh
```

2. 做本地文本脑 smoke。

```bash
cd interrupt
bash ./run_local_text_brain_smoke.sh "挥挥手"
bash ./run_local_text_brain_smoke.sh "帮我看看前面有什么"
```

3. 做本地离线 VLM 验证。

```bash
cd interrupt
bash ./run_local_offline_vlm_validation.sh "这张图里有什么？"
```

4. 跑本地文本离线评测集。

```bash
cd interrupt
bash ./run_local_text_offline_eval.sh batch
```

## 7.2 G1 侧

1. 配置 G1 指向开发机局域网模型服务。

建议至少设置：

```bash
export INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL=http://192.168.100.48:11434
export INTERRUPT_AGENT_LOCAL_TEXT_MODEL=qwen2.5:7b
```

如果走 OpenAI-compatible VLM：

```bash
export INTERRUPT_VLM_PROVIDER=openai_compatible
export INTERRUPT_VLM_BASE_URL=http://<LAN_GPU_HOST>:8000/v1
export INTERRUPT_VLM_MODEL=Qwen2.5-VL-7B-Instruct
```

2. 跑机器人侧文本脑 smoke。

```bash
cd interrupt
bash ./run_robot_text_brain_smoke.sh "挥挥手"
bash ./run_robot_text_brain_smoke.sh "帮我看看前面有什么"
```

3. 跑机器人侧离线 VLM 验证。

```bash
cd interrupt
bash ./run_robot_offline_vlm_validation.sh "你前面有什么？"
```

4. 以生产推荐配置启动正式房间 agent。

建议：

```bash
export INTERRUPT_AGENT_RUNTIME_MODE=online_full
export INTERRUPT_AGENT_BACKEND=gemini_realtime
export INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools
```

## 7.3 断网验收

1. 切到单机离线模式。

```bash
export INTERRUPT_AGENT_RUNTIME_MODE=offline_singlebox
export INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools
```

2. 断开外网后逐项验证：

- 挥手
- 开蓝灯
- 看前面有什么
- 列出已保存地点
- 去前台
- 把这里记成会议室

3. 再验证超界拒答：

- 今天天气怎么样
- 最近新闻是什么
- 随便聊聊 AI

预期：

- 前一组应执行或返回结构化结果
- 后一组必须统一触发离线超界播报

---

## 8. 关键配置建议

### 8.1 默认生产值

```bash
INTERRUPT_AGENT_RUNTIME_MODE=online_full
INTERRUPT_AGENT_BACKEND=gemini_realtime
INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools
INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER=ollama
INTERRUPT_AGENT_LOCAL_TEXT_MODEL=qwen2.5:7b
```

### 8.2 离线验收值

```bash
INTERRUPT_AGENT_RUNTIME_MODE=offline_singlebox
INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools
INTERRUPT_VLM_ENABLED=1
```

### 8.3 不建议当前默认开启的值

```bash
INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_all
```

原因：

- 还没有足够证据证明本地文本脑能长期稳定承接普通对话
- 有身份漂移、闲聊降级、回复风格失稳风险

---

## 9. 验收口径

这套方案最终是否成功，不看“模型名字”，看这五条：

### 9.1 功能验收

- 在线完整版能力全部保住
- 离线白名单能力全部跑通

### 9.2 安全验收

- 离线超界不误执行
- 本地模型失败时不假装成功
- 不允许本地模型直接越过安全网关碰底层控制

### 9.3 稳定性验收

- 本地文本脑 smoke 可连续复现
- G1 访问开发机模型服务无偶发性拒连
- VLM 不因为 provider 误配置而静默回退到云

### 9.4 体验验收

- 在线模式下普通会话不明显变差
- 打断与恢复不退化
- 不重复播报，不显著自听回环

### 9.5 架构验收

- 文本脑、VLM、执行器、安全层职责清晰
- 可以继续往 MCP 化、外置工作站、机载小模型三条路扩展

---

## 10. 主要风险与对应处理

### 10.1 风险：误以为“离线就应该全本地全机载”

处理：

- 第一阶段坚持“开发机承载模型，G1 承载执行与会话”
- 等链路稳了再讨论更多机载化

### 10.2 风险：`prefer_all` 过早上生产

处理：

- 先长期运行 `prefer_tools`
- 只在灰度环境验证 `prefer_all`

### 10.3 风险：VLM 或本地文本脑只在 smoke 通过，正式链上失稳

处理：

- 所有 smoke 通过后，再做长时房间会话回归
- 给本地决策链增加日志、命中率、失败率统计

### 10.4 风险：脚本与真实代码状态不一致

处理：

- 优先相信 `interrupt/src/agent.py` 与当前运行结果
- 尽快修正 `agent_backend_probe.py` 这类已经落后的提示脚本

---

## 11. 最终建议

当前最合理的结论只有一句话：

**不要把目标定义成“G1 立刻纯离线全能”；要把目标定义成“在线完整版不退化 + 单机离线白名单能力可验收 + 本地文本脑和离线 VLM 逐步扩大覆盖面”。**

按当前仓库进度，推荐正式推进顺序是：

1. 先把 `online_full + prefer_tools` 做成默认稳定生产形态。
2. 再把 `offline_singlebox` 做成可断网验收形态。
3. 然后把工具层逐步 MCP 化。
4. 最后才讨论把更多主对话能力从在线链迁到本地链。

这条路线最贴合当前代码现实，也最能避免“为了离线而牺牲机器人整体可用性”。
