# 在线完整版 / 单机离线降级版清单

更新时间：2026-05-15

## 1. 目标

这套清单用于把机器人能力明确分成两档：

- `online_full`
  - 保留当前在线完整版能力，不允许因为本地化而回退。
- `offline_singlebox`
  - 允许在单机离线状态下继续工作，但只开放低风险、强结构化、可验证的能力。

原则：

- 本地化只能做增量替换，不能破坏原在线链路。
- 离线模式不能假装自己“全能”。
- 超出离线能力边界时，必须明确提示用户切换在线模式。

## 2. 离线版能力清单

模式：`offline_singlebox`

### 2.1 允许的能力

- 唤醒、进入会话
- 基础语音交互流程
- 上半身动作
  - 例如：挥手、举手、打招呼
- 灯光控制
  - 例如：红灯、蓝灯、关闭灯光
- 视觉问句
  - 例如：前面有什么、帮我看看眼前场景
- 已保存地点查询
  - 例如：有哪些已保存地点
- 导航到已保存地点
  - 例如：带我去前台
- 记住当前位置
  - 例如：把这里记成会议室

### 2.2 不允许直接放开的能力

- 普通闲聊主回复
- 开放式知识问答
- 天气、新闻等依赖外部实时数据的能力
- 高自由度复杂推理
- 长上下文开放对话
- 任何当前本地模型无法稳定约束身份、人设、语言风格的回复

### 2.3 验收标准

- 能力必须在断外网情况下可执行
- 响应结果必须可重复验证
- 不允许因为本地模型误判而触发错误动作
- 不允许因本地闲聊回复导致人设漂移

## 3. 在线版能力清单

模式：`online_full`

### 3.1 必须保留的能力

- 三语言自适应
  - 普通话、粤语、英语
- 稳定普通对话
- 视觉问答
- 动作执行
- 导航执行
- 打断与恢复
- AEC 所在的 RTC 单路播报链
- 在线增强型问答
  - 天气、新闻、开放式知识

### 3.2 本地化后仍不能退化的点

- 人设不能漂移成底层模型身份
- 不允许重复播报
- 不允许显著增加自听回环
- 不允许把普通对话质量明显降到离线小模型水平
- 不允许破坏原有打断体验

## 4. 意图分流规则

### 4.1 `online_full`

- 动作、导航、视觉问句：可以优先尝试本地结构化决策
- 普通闲聊主回复：继续由在线主链负责
- 本地链异常时：自动回退在线链

### 4.2 `offline_singlebox`

- 只允许这些本地工具类意图：
  - `perform_body_action`
  - `set_led_color`
  - `ask_camera_vision`
  - `list_saved_locations`
  - `navigate_to_saved_location`
  - `remember_current_location`
- 如果本地决策结果不在白名单里：
  - 不执行
  - 不转成普通闲聊
  - 直接播报离线超界提示
- 如果本地模型不可用或请求失败：
  - 不假装成功
  - 直接播报离线不可用提示

## 5. 超界播报文案

### 5.1 离线超界提示

普通话：

`当前是单机离线模式，这个请求超出了离线能力范围。请打开在线增强模式后再试。`

粤语：

`而家係單機離線模式，呢個請求超出咗離線能力範圍。請打開在線增強模式之後再試。`

英语：

`The robot is in single-box offline mode. This request is outside the offline capability set. Please enable online mode and try again.`

### 5.2 离线能力暂不可用提示

普通话：

`当前是单机离线模式，但本地能力暂时不可用。请稍后重试，或切回在线增强模式。`

粤语：

`而家係單機離線模式，但本地能力暫時不可用。請稍後再試，或者切回在線增強模式。`

英语：

`The robot is in single-box offline mode, but the local capability path is temporarily unavailable. Please try again later or switch back to online mode.`

## 6. 配置开关

### 6.1 主开关

- `INTERRUPT_AGENT_RUNTIME_MODE`
  - `online_full`
  - `offline_singlebox`

### 6.2 本地文本决策开关

- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE`
  - `disabled`
  - `shadow`
  - `prefer_tools`
  - `prefer_all`

建议：

- `online_full` 搭配 `prefer_tools`
- `offline_singlebox` 搭配 `prefer_tools`
- 暂不建议在真机默认链路使用 `prefer_all`

## 7. 代码落点

### 7.1 配置读取

- [interrupt/src/settings.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/src/settings.py:24)
  - `AgentConfig.runtime_mode`
  - `INTERRUPT_AGENT_RUNTIME_MODE`

### 7.2 主决策分流

- [interrupt/src/agent.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/src/agent.py:572)
  - `_is_offline_singlebox_mode`
  - `_offline_singlebox_limit_reply`
  - `_offline_singlebox_unavailable_reply`
- [interrupt/src/agent.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/src/agent.py:2001)
  - `_try_handle_local_text_decision`
  - 离线白名单过滤
  - 超界提示和不可用提示

### 7.3 本地文本脑提示词

- [interrupt/src/local_text_brain.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/src/local_text_brain.py:24)
  - 增加“不自称底层模型厂商”的约束

### 7.4 启动与巡检

- [interrupt/run_room_agent.sh](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/run_room_agent.sh:95)
  - 启动时打印 `runtime_mode`
- [interrupt/tools/check_env.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/tools/check_env.py:84)
  - 巡检时打印 `INTERRUPT_AGENT_RUNTIME_MODE`

## 8. 当前建议默认值

真机默认：

- `INTERRUPT_AGENT_RUNTIME_MODE=online_full`
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools`

原因：

- 保住现有在线完整版能力
- 继续灰度本地结构化能力
- 避免 `prefer_all` 带来的身份漂移、闲聊降级和播报链回退问题

## 9. 下一步建议

### 9.1 先做

- 按这份清单做断网验收表
- 验证 `offline_singlebox` 下：
  - 动作
  - 灯光
  - 视觉问句
  - 已保存地点导航
  - 记住当前位置

### 9.2 后做

- 再决定是否放开更多离线能力
- 如果要放开，必须逐项通过“不回退在线能力”的验收标准
