# 离线 VLM 支线验证说明

更新时间：2026-05-12

目标：

- 保留在线主线不变：
  - LiveKit + Gemini Live 继续作为实时语音主链
  - 默认视觉仍可继续走 Gemini OpenAI 兼容接口
- 新增离线支线：
  - 本地 OpenAI 兼容服务承接视觉问答验证
  - 先验证 Qwen / Gemma / GLM 这类离线 VLM
  - 暂不替换实时语音链

## 0. 当前收口状态

截至 2026-05-12，本地第 1 步已经基本收口：

- 本地文本动作链已验证通过：
  - `offline_eval` 可通过本机 Ollama `qwen2.5:7b` 完成 `MockInput -> LLM -> 动作评测链`
- 本地视觉支线已验证通过：
  - `interrupt/run_local_offline_vlm_validation.sh` 已使用
    - `INTERRUPT_VLM_PROVIDER=ollama_native`
    - `INTERRUPT_VLM_MODEL=gemma3:latest`
    - 静态图 `OM1/system_hw_test/front_image.jpg`
  - 成功返回视觉回答：`这张图里有轮子和一些黑色的框架。`
- 在线主线仍保持不变：
  - LiveKit + Gemini Live 未被替换
  - 离线 VLM 仅作为视觉支线验证

这意味着第 1 步“先在本地打通离线支线”已经达到可切换到真机验证的标准。

截至 2026-05-13，真机侧第 2 步也已经完成首轮烟测：

- 机器人：`unitree@192.168.100.30`
- 相机输入：`/dev/video2`
- 离线视觉后端：
  - `INTERRUPT_VLM_PROVIDER=openai_compatible`
  - `INTERRUPT_VLM_BASE_URL=http://192.168.100.48:11434/v1`
  - `INTERRUPT_VLM_MODEL=gemma3:latest`
- 验证脚本：
  - `run_robot_offline_vlm_validation.sh "你前面有什么？" --language zh-CN`
- 结果：
  - `status: OK`
  - `model_found: yes`
  - `camera_device: /dev/video2`
  - `answer: 我可以看到一个黑色的物体，还有一个白色的物体，但是看不清具体是什么。`

这说明“真机相机 -> interrupt 视觉工具链 -> 局域网离线 VLM 后端 -> 中文回答”已经打通。

同一天还完成了 `ask_camera_vision` 工具层的真机会话烟测：

- 新增脚本：
  - `tools/vision_tool_session_smoke.py`
- 目的：
  - 模拟“最近一条用户输入就是视觉问题”
  - 直接走 `InterruptAssistant.ask_camera_vision()` 的守卫和工具逻辑
- 验证命令：

```bash
cd /home/unitree/HongTu/interrupt
export INTERRUPT_VLM_ENABLED=1
export INTERRUPT_VLM_PROVIDER=openai_compatible
export INTERRUPT_VLM_BASE_URL=http://192.168.100.48:11434/v1
export INTERRUPT_VLM_MODEL=gemma3:latest
./.venv/bin/python tools/vision_tool_session_smoke.py "你前面有什么？" --language zh-CN
```

- 返回结果：
  - `preferred_reply_language: zh-CN`
  - `image_path: <camera>`
  - `answer: 我能看到一些阴影和黑色的物体。看不清具体的形状。`

这说明“会话内视觉工具守卫 -> 真机相机抓帧 -> 局域网离线 VLM -> 中文回答”也已经打通。

随后又完成了真实文本会话里的三语言触发验证：

- 启动方式：
  - 机器人上运行 `run_local_text_agent.sh`
  - 仍走真实 Gemini `AgentSession`
  - 只把视觉工具后端切到局域网离线 VLM
- 已验证问法：
  - 普通话：`你前面有什么？`
  - 英语：`What do you see in front of you?`
  - 粤语：`你而家睇到啲乜？`
- 实测结论：
  - 三种问法都会在真实 session 中触发 `ask_camera_vision`
  - `function_tools_executed` 日志里能看到 `name='ask_camera_vision'`
  - 普通话最终回复保持普通话
  - 英语最终回复保持英语
  - 粤语最终回复保持粤语

这说明“用户自然问法 -> LLM 选择视觉工具 -> 工具执行 -> 多语言自然回复”已经在真机真实 session 中跑通。

同一天还完成了结构化 observation 的本地与真机验证：

- `src/vision_chat.py` 已支持：
  - `structured=False`：保留原自然语言回答
  - `structured=True`：同一次视觉请求返回 `natural_answer + observation JSON`
- observation 当前标准字段：
  - `natural_answer`
  - `person_detected`
  - `person_count_estimate`
  - `distance_band`
  - `obstacle_near_arms`
  - `free_space_front`
  - `human_attention`
  - `scene_visibility`
- 新增脚本能力：
  - `tools/vlm_smoke_test.py --structured`
  - `tools/vision_tool_session_smoke.py --structured`
- Agent 侧新增工具：
  - `observe_camera_scene`
  - 用于返回结构化 JSON，给后续安全裁决层消费

真机实测口径：

```bash
cd /home/unitree/HongTu/interrupt
export INTERRUPT_VLM_ENABLED=1
export INTERRUPT_VLM_PROVIDER=openai_compatible
export INTERRUPT_VLM_BASE_URL=http://192.168.100.48:11434/v1
export INTERRUPT_VLM_MODEL=gemma3:latest
./.venv/bin/python tools/vlm_smoke_test.py "你前面有什么？" --language zh-CN --structured
```

一次通过时的关键结果示例：

- `camera_device: /dev/video2`
- `answer: 我前面有黑暗的物体，无法清晰辨认。`
- `scene_visibility: dark`
- `free_space_front: blocked`
- `obstacle_near_arms: yes`

说明结构化结果已经可以开始服务“安全中间层只读判断”，而不只是做自然语言看图问答。

随后又完成了安全中间层原型的首轮真机闭环：

- 新增模块：
  - `src/safe_action_gateway.py`
- 当前原型规则：
  - `scene_visibility in {dark, occluded}` 时拒绝上身动作
  - `obstacle_near_arms == yes` 时拒绝上身动作
  - `free_space_front == blocked` 且动作属于 `front_reach / wide_gesture` 时拒绝
  - `person_detected == yes && distance_band == near` 且动作属于 `front_reach / wide_gesture` 时拒绝
- 当前动作家族：
  - `high five / shake hand` -> `front_reach`
  - `high wave` -> `wide_gesture`
  - `clap / heart` -> `compact_gesture`
- Agent 集成：
  - 新增 `check_action_safety` 工具
  - 当环境变量 `INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY=1` 时，`perform_body_action` 会先做视觉安全裁决，再决定是否执行
- 新增脚本：
  - `tools/safe_action_gateway_smoke.py`
  - `tools/action_tool_session_smoke.py`

真机验证结果：

1. `safe_action_gateway_smoke.py` 已在机器人相机上返回结构化拒绝结果：
   - `action: high wave`
   - `allowed: false`
   - `reason_code: obstacle_near_arms`

2. `action_tool_session_smoke.py` 已在 `INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY=1` 下真正拦住动作工具：

```json
{
  "action": "high wave",
  "result": "我前方靠近手臂活动范围的位置像是有遮挡物，我先不做这个动作。"
}
```

这说明“视觉 observation -> 安全裁决 -> 动作拒绝”已经形成第一版真机闭环。

这轮还顺手修复了一个粤语守卫缺口：

- 问法 `你而家睇到啲乜？` 最初会被 `_looks_like_vision_query()` 误判为非视觉问题
- 已在 `src/agent.py` 中补入：
  - `你而家睇到啲咩 / 你而家睇到啲乜`
  - `你依家睇到啲咩 / 你依家睇到啲乜`
  - `你見到啲咩 / 你見到啲乜`
  - 以及对应的 `你而家 / 你依家` 组合
- 修复后，粤语问法已在真实 session 中验证通过

截至 2026-05-13，语音导航链也完成了“可诊断收口”，但还没有完成真机可执行闭环：

- `navigate_to_saved_location`、`list_saved_locations`、`remember_current_location` 三个工具口已经在 `interrupt` 侧接好
- 视觉安全中间层也已经扩到了导航启动前判断：
  - `check_navigation_safety`
  - `evaluate_navigation_safety`
- 真机上新增了排障脚本：
  - `tools/navigation_backend_probe.py`

机器人现场探针结果已经明确：

- `INTERRUPT_G1_NAV_BASE_URL=http://localhost:5000`
- `socket_probe`: `Connection refused`
- `http_probe`: `/healthz` 不可达
- `cli_probe`: `g1_nav_command.py list --compact` 返回
  - `error=request_failed`
  - `detail=HTTPConnectionPool(host='localhost', port=5000)... Connection refused`

这说明当前语音导航没有卡在 LLM 触发或工具封装，而是卡在“机器人导航 HTTP bridge 没有运行”。

更进一步的环境核对结果：

- 机器人当前默认运行时是 `ROS 2 humble`
- 现场存在的导航工作区位于：
  - `/home/unitree/g1_3d_nav/HongTu/G1Nav2D`
- 但当前 `interrupt` 侧桥接方案依赖的是：
  - `rospy`
  - `actionlib`
  - `move_base`
  - 也就是 ROS1 风格的 `g1_nav_bridge.py`
- 在机器人现场直接验证：
  - `import rospy` 失败
  - `ModuleNotFoundError: No module named 'rospy'`

所以当前状态要如实描述为：

- `语音视觉问答`：已真机打通
- `语音视觉 + 动作安全拦截`：已真机打通
- `语音导航安全预检查`：已打通到只读/拒绝层
- `语音导航实际启动导航`：尚未打通

当前阻塞根因不是语音层，而是“导航桥方案与现场导航运行时还未真正对接”。

同一天也完成了导航替代接法的第一轮落地：

- 保留原 `http_bridge` 方案不动
- 新增 `ros2_goal_pose` 支线：
  - `INTERRUPT_G1_NAV_PROVIDER=ros2_goal_pose`
  - 默认脚本：`OM1/scripts/g1_nav_goal_pose.py`
  - 默认动作：直接向现场 ROS2 `/goal_pose` 发布 `geometry_msgs/msg/PoseStamped`
- 已补示例地点文件：
  - `interrupt/config/g1_locations.example.json`

设计意图：

- 复用现场已经存在的 ROS2 订阅者：
  - `/goal_pose`
  - subscriber: `ik_fcl_ompl_planner`
- 避开当前现场缺失的：
  - `localhost:5000` HTTP bridge
  - `rospy/actionlib/move_base` 运行时
  - `zenoh` 动态库现场导入问题

已完成的机器人侧非运动验证：

```bash
cd /home/unitree/HongTu/OM1
INTERRUPT_G1_NAV_PROVIDER=ros2_goal_pose \
INTERRUPT_G1_NAV_LOCATIONS_FILE=/home/unitree/HongTu/interrupt/config/g1_locations.example.json \
./.venv-g1/bin/python scripts/g1_nav_goal_pose.py list --compact
```

结果：

- `ok: true`
- `locations: ["前台"]`

再对一个不存在的目标地点做了非运动验证：

```bash
cd /home/unitree/HongTu/OM1
INTERRUPT_G1_NAV_PROVIDER=ros2_goal_pose \
INTERRUPT_G1_NAV_LOCATIONS_FILE=/home/unitree/HongTu/interrupt/config/g1_locations.example.json \
./.venv-g1/bin/python scripts/g1_nav_goal_pose.py navigate 茶水间
```

结果：

- `ok: false`
- `error: location_not_found`
- `available: ["前台"]`

这说明 `interrupt -> adapter -> ros2_goal_pose CLI` 这条替代导航支线已经接好了命令面和地点解析面。

本轮刻意没有在真机上对真实点位执行 `/goal_pose` 发布，因为当前示例文件不是现场真实保存点位，直接发布存在误动作风险。下一步要做的是把现场真实地点文件接进来，再选一个安全时段做单次真机 `/goal_pose` 放行验证。

截至 2026-05-13 下午，对 `HongTu` 现场导航运行时又补了一轮核对，结论比之前更明确：

- 机器人当前有两个导航相关运行面：
  - `3d_nav_g1` 容器
  - `uniflexai/tinynav:latest` 容器
- `3d_nav_g1` 容器内当前实际在跑的是：
  - `livox_ros_driver2_node`
  - `fastlio_mapping`
  - `global_localization_node`
- 也就是说，现场当前更像是“定位 / 地图 / 感知链路在运行”，不等于“目标导航执行链已闭环”。

同一时间从机器人 ROS2 侧看到：

- `/global_map` 存在
- `/planner_map` 存在
- `/slam_info` 存在
- `/unitree_slam/waypoints` 存在
- `/goal_pose` 也可能出现

但关键事实是：

- `ros2 topic info -v /goal_pose`
  - `Publisher count: 1`
  - `Node name: rviz`
  - `Subscription count: 0`

这说明当前 `HongTu` 现场运行时里，`/goal_pose` 只是 RViz 或调试链在发/保留这个 topic 名称，并没有真正的导航节点在消费它。

因此，截至 2026-05-13 的最准确判断是：

- `interrupt` 侧语音导航工具口：已具备
- `ros2_goal_pose` 替代支线：已具备
- 点位 JSON 格式兼容：已具备
- `HongTu` 当前现场的“导航目标消费者”：尚未确认存在

所以当前阻塞已经进一步收敛为：

1. 没有现场真实 `*_point.json` 点位文件
2. 当前运行时没有看到真实消费 `/goal_pose` 的 planner / navigator 订阅者

这意味着下一步不是直接做语音导航放行，而是先让 `HongTu` 导航运行时进入“有目标消费者”的状态，再谈端到端导航。

## 1. 当前实现边界

本轮已新增：

- `vision.provider`
- `vision.api_key`
- `tools/vlm_smoke_test.py` 支持 provider/base_url/model/api_key 覆盖
- `tools/vlm_backend_probe.py` 支持探测 OpenAI 兼容 `/models`
- `run_offline_vlm_smoke.sh` 快捷脚本
- `run_local_offline_vlm_validation.sh` 本地静态图一键验证脚本
- `run_robot_offline_vlm_validation.sh` 真机侧一键验证脚本

默认行为仍然不变：

- `vision.provider=gemini_openai_compat`
- 在线主线继续使用 `GEMINI_API_KEY`

## 2. 本地化主线入口

为了把“在线语音主线 + 本地视觉/安全支线”固定成可重复运行的模式，当前仓库新增了两个本地化入口：

1. 本地运行 profile

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
./run_local_localized_stack.sh
```

默认会打开：

- `INTERRUPT_VLM_ENABLED=1`
- `INTERRUPT_VLM_PROVIDER=ollama_native`
- `INTERRUPT_VLM_BASE_URL=http://127.0.0.1:11434/v1`
- `INTERRUPT_VLM_MODEL=gemma3:latest`
- `INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY=1`

并继续复用原有 `run_local_voice_agent.sh`，因此：

- 在线 Gemini 语音主线仍保留
- 本地 VLM 与安全中间层自动作为支线打开

2. 本地一键健康检查

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
./run_local_localized_stack_probe.sh "这张图里有什么？" "high wave"
```

会串起：

- `check_env.py`
- `vlm_backend_probe.py`
- `vlm_smoke_test.py --structured`
- `safe_action_gateway_smoke.py`

适合在继续做本地化收口前快速确认：

- 本地 VLM 后端是否在线
- 结构化 observation 是否正常
- 安全中间层规则是否还在按预期工作

2026-05-13 本地实测已通过：

- `provider=ollama_native`
- `model=gemma3:latest`
- 静态图回答：`这张图里有一部分木地板，以及一个机器人。`
- 结构化 observation：`person_detected=no`、`free_space_front=partial`、`scene_visibility=clear`
- 动作安全烟测：`high wave -> allowed=true`

离线支线建议配置：

- `INTERRUPT_VLM_PROVIDER=openai_compatible`
- `INTERRUPT_VLM_BASE_URL=http://127.0.0.1:8000/v1`
- `INTERRUPT_VLM_MODEL=<your-local-vlm>`
- `INTERRUPT_VLM_API_KEY=` 可留空

如果本地直接用 Ollama 多模态能力，建议配置：

- `INTERRUPT_VLM_PROVIDER=ollama_native`
- `INTERRUPT_VLM_BASE_URL=http://127.0.0.1:11434/v1`
- `INTERRUPT_VLM_MODEL=gemma3:latest`

## 3. 离线大模型横向对比入口

为了避免每接一颗本地模型就手工改脚本，当前仓库新增了统一横评入口：

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
./run_local_vlm_compare.sh
```

默认读取：

- `config/vlm_eval_matrix.local_baseline.json`

多模型占位矩阵示例：

- `config/vlm_eval_matrix.example.json`

矩阵文件里可以同时定义：

- `questions`
- `candidates`
- 每个 candidate 的 `provider / base_url / model / structured`

输出特点：

- 复用同一个 `vision_chat.py`
- 同一张图、同一组问题横向比较多颗 VLM
- 同时保留自然语言 `answer`
- 同时落盘结构化 `observation`
- 默认结果文件：
  - `tmp/vlm_compare_last.json`

推荐用法：

1. 默认先本地跑 `gemma3`
2. 再把 `Qwen-VL` 的 OpenAI 兼容服务挂到 `:8000`
3. 再把 `GLM` 的 OpenAI 兼容服务挂到 `:9000`
4. 用 `config/vlm_eval_matrix.example.json` 这类多模型矩阵直接比较

2026-05-13 当前已完成的基线能力：

- `tools/vlm_compare_matrix.py`
- `run_local_vlm_compare.sh`
- `config/vlm_eval_matrix.example.json`
- `config/vlm_eval_matrix.local_baseline.json`

这意味着下一步离线模型测试已经不需要再改代码，只需要：

- 起模型服务
- 改矩阵配置
- 直接跑横评脚本

2026-05-13 当前本机实测状态：

- `gemma3:latest @ 127.0.0.1:11434` 已在线并通过默认横评
- `Qwen-VL` 预留端口 `127.0.0.1:8000` 当前 `Connection refused`
- `GLM-V` 预留端口 `127.0.0.1:9000` 当前 `Connection refused`
- `vlm_compare_matrix.py` 已增加预探测，未起服务的候选会立即报错，不再按每题长时间重试

为了把下一步“起多模型服务”也收进口径，当前仓库又补了两类启动模板：

- `run_local_vllm_vision_server.sh`
- `run_local_sglang_vision_server.sh`
- `run_local_qwen25_vl_vllm.sh`
- `config/vlm_server_profiles.example.env`
- `config/vlm_eval_matrix.qwen_vs_gemma.json`
- `docs/QWEN_VL_VLLM_BRINGUP_2026-05-13.md`

建议口径：

1. `Qwen-VL` 优先走 `vLLM`
2. `GLM-V` 优先走 `SGLang` 或你们现成的 OpenAI 兼容服务
3. 起好服务后直接复用：

```bash
./run_local_vlm_compare.sh config/vlm_eval_matrix.example.json
```

当前这台开发机的环境核对结果：

- `vllm` 未安装
- `sglang` 未安装
- `transformers` 未安装
- `nvidia-smi` 当前未返回有效驱动信息

所以当前代码侧已经收口到“可接”，但真正开始 `Qwen-VL / GLM` 横评，还需要切到一台已具备 GPU 驱动和对应推理环境的机器，或先在本机补装相应环境。

说明：

- 如果后端是 `vLLM / SGLang / LM Studio / 自建 OpenAI 兼容服务`，优先使用 `openai_compatible`
- 如果后端是本机 `Ollama` 多模态，优先使用 `ollama_native`
- 当前第 1 步本地闭环是通过 `ollama_native` 打通的，不建议把 `Ollama` 当作首选 `openai_compatible` 图像后端来做第一轮验证

## 2. 推荐验证形态

### 2.1 在线主线

不改现有机器人主链。

### 2.2 离线支线

只让 `ask_camera_vision` 和 `tools/vlm_smoke_test.py` 切到本地服务。

这样做的好处：

- 不影响实时语音
- 不影响三语言唤醒
- 不影响打断
- 只替换视觉后端，便于和 Gemini 做 A/B 对比

## 3. 最小环境变量

示例：

```bash
export INTERRUPT_VLM_ENABLED=1
export INTERRUPT_VLM_PROVIDER=openai_compatible
export INTERRUPT_VLM_BASE_URL=http://127.0.0.1:8000/v1
export INTERRUPT_VLM_MODEL=Qwen2.5-VL-7B-Instruct
export INTERRUPT_VLM_API_KEY=
```

如果本地服务要求 token，也可以设置：

```bash
export INTERRUPT_VLM_API_KEY=local-test-key
```

## 4. 最小验证命令

### 4.1 环境检查

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
python tools/check_env.py
```

重点确认：

- `INTERRUPT_VLM_PROVIDER`
- `INTERRUPT_VLM_BASE_URL`
- `INTERRUPT_VLM_MODEL`

### 4.2 离线 VLM 烟测

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
./run_offline_vlm_smoke.sh "你前面有什么？" --language zh-CN
```

或者直接覆盖参数：

```bash
python tools/vlm_smoke_test.py \
  "桌上有什么？" \
  --language zh-CN \
  --provider openai_compatible \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen2.5-VL-7B-Instruct
```

### 4.3 后端探针

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
python tools/vlm_backend_probe.py --require-model
```

用途：

- 先确认本地 OpenAI 兼容服务真的在线
- 先确认目标模型真的已经被服务加载
- 避免还没连相机就卡在后端没起好

### 4.4 真机一键验证

如果代码已经在机器人 `/home/unitree/HongTu/interrupt`，可以直接：

```bash
cd /home/unitree/HongTu/interrupt
export INTERRUPT_VLM_ENABLED=1
export INTERRUPT_VLM_PROVIDER=openai_compatible
export INTERRUPT_VLM_BASE_URL=http://192.168.100.48:11434/v1
export INTERRUPT_VLM_MODEL=gemma3:latest
./run_robot_offline_vlm_validation.sh "你前面有什么？" --language zh-CN
```

已验证通过的一组实机配置就是上面这组：

- 机器人本机不需要安装 `ollama`
- 由开发机 `192.168.100.48` 提供局域网 VLM 服务
- 机器人只负责抓前置相机并发起视觉请求

它会顺序执行：

1. `tools/check_env.py`
2. `tools/vlm_backend_probe.py --require-model`
3. `tools/vlm_smoke_test.py`

### 4.5 本地静态图一键验证

如果还没上真机，先在开发机验证整条请求链：

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
export INTERRUPT_VLM_ENABLED=1
export INTERRUPT_VLM_PROVIDER=ollama_native
export INTERRUPT_VLM_BASE_URL=http://127.0.0.1:11434/v1
export INTERRUPT_VLM_MODEL=gemma3:latest
./run_local_offline_vlm_validation.sh "这张图里有什么？" --language zh-CN
```

默认静态图路径是：

```bash
/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1/system_hw_test/front_image.jpg
```

本地已验证通过的命令形态：

```bash
cd /home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt
export INTERRUPT_VLM_ENABLED=1
export INTERRUPT_VLM_PROVIDER=ollama_native
export INTERRUPT_VLM_BASE_URL=http://127.0.0.1:11434/v1
export INTERRUPT_VLM_MODEL=gemma3:latest
./run_local_offline_vlm_validation.sh "这张图里有什么？" --language zh-CN
```

一次通过时的关键输出特征：

- `status: OK`
- `model_found: yes`
- `camera_device: image:.../front_image.jpg`
- `answer: 这张图里有轮子和一些黑色的框架。`

也可以手动覆盖：

```bash
python tools/vlm_smoke_test.py \
  "这张图里有什么？" \
  --language zh-CN \
  --provider openai_compatible \
  --base-url http://127.0.0.1:11434/v1 \
  --model <your-local-vlm> \
  --image /path/to/test.jpg
```

## 4.6 真机上线前最低检查

在真机上至少确认：

- `INTERRUPT_VLM_BASE_URL` 指向可访问的本地或局域网服务
- `INTERRUPT_VLM_MODEL` 与 `/v1/models` 返回值一致
- `UNITREE_G1_CAMERA_DEVICE` 或自动探测能找到前置相机
- 当前在线主链环境变量不要被这组支线变量覆盖掉 `GEMINI_API_KEY`

## 5. 推荐对比模型

截至 2026-05-12，建议优先验证：

- Qwen2.5-VL
- Gemma 3
- GLM-4.1V 或 GLM-4.5V

建议验证维度：

- 是否能稳定识别人、桌面物体、障碍物
- 中文回答是否简短自然
- 英语回答是否稳定
- 粤语回答是否能基本服从
- 失败时是否会诚实说看不清
- 延迟是否能接受

## 6. 当前不建议立即替换的部分

当前不建议把下面这些一起切到离线：

- LiveKit 实时语音模型
- 打断链
- 流式 TTS
- 流式 ASR

原因：

- 这些属于主链稳定性核心，耦合远高于视觉单点替换。
- 离线支线先验证视觉最划算，也最不影响现场可用性。

## 7. 下一步建议

建议按这个顺序推进：

1. 记录离线 VLM 与 Gemini 视觉在同一场景下的识别差异、延迟差异、错误模式差异。
2. 做第二轮真机提示词验证，覆盖近距障碍、人体、桌面物体、弱光场景，并重点观察 observation 字段稳定性。
3. 细化动作家族，把 `compact_gesture`、`front_reach`、`wide_gesture` 扩展成更完整的白名单。
4. 把同样的安全裁决模式扩展到导航和自由文本动作入口。
5. 等规则稳定后，再决定是否默认打开 `INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY`。
