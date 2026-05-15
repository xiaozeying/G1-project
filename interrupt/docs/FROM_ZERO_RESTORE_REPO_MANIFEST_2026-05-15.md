# 从 0 恢复仓库清单

更新时间：2026-05-15

## 1. 结论

当前仓库已经包含“从 0 恢复整条 G1 interrupt 主链”所需的大部分代码与恢复素材，但恢复成功仍然依赖：

- 正确的机器人环境变量
- 机器人侧 Python 环境
- `systemd --user` 服务安装
- 音频/相机/网络设备状态

更准确地说：

- `interrupt` 主链：仓库内基本齐全
- `OM1`：仓库内已存在
- `g1-wakeword`：仓库内已存在
- `G1Nav2D/src` 导航源码：仓库内已存在
- 地图/地点基础资产：仓库内已存在一批样例与现有地图
- 机器人现场环境：仍然需要按恢复文档落地

## 2. 仓库内已包含的恢复要素

### 2.1 `interrupt` 主链

目录：

- [interrupt](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt)

包含：

- 前门会话脚本
- 房间 agent
- RTC endpoint
- 本地文本脑
- 本地 VLM 探针与 smoke
- 在线/离线模式切换
- 巡检工具

### 2.2 `OM1` 仓库

目录：

- [OM1](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1)

包含：

- G1 相关脚本
- 动作/灯光/播报脚本
- preflight / smoke / fallback 脚本
- 现有 Python 环境目录占位

关键脚本示例：

- [g1_direct_command_fallback.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1/scripts/g1_direct_command_fallback.py)
- [g1_watchdog_feedback.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1/scripts/g1_watchdog_feedback.py)
- [external_usb_tts.sh](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1/scripts/external_usb_tts.sh)

### 2.3 `g1-wakeword`

目录：

- [g1-wakeword](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/g1-wakeword)

说明：

- 仓库内已有这套唤醒词目录，不再只是外部依赖口头约定。
- 恢复脚本和资产打包脚本也已经考虑了它。

### 2.4 `G1Nav2D/src` 导航源码

目录：

- [G1Nav2D/src](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/G1Nav2D/src)
- [G1Nav2D/bridge](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/G1Nav2D/bridge)
- [run_nav_bridge.sh](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/G1Nav2D/run_nav_bridge.sh)

说明：

- 导航源码和 HTTP bridge 都在仓库内。
- 但 `build/`、`devel/` 属于本地构建结果，不应当作为“源码恢复成功”的判据。

### 2.5 地图 / 地点 / 配置资产

地图样例：

- [G1Nav2D/src/ros_map_edit/maps](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/G1Nav2D/src/ros_map_edit/maps)

地点配置样例：

- [g1_locations.example.json](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/config/g1_locations.example.json)

VLM 配置样例：

- [vlm_server_profiles.example.env](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/config/vlm_server_profiles.example.env)

### 2.6 环境模板

模板文件：

- [.env.example](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/.env.example)

现已包含：

- `INTERRUPT_AGENT_RUNTIME_MODE`
- `INTERRUPT_AGENT_BACKEND`
- `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE`
- 本地文本脑 URL / model
- 机器人离线 VLM URL / model
- 播报链默认值

### 2.7 `systemd --user` 服务

服务文件：

- [interrupt-frontgate.service](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/deploy/systemd/user/interrupt-frontgate.service)

说明：

- 前门服务模板已经在仓库里。
- 恢复脚本会优先从这里安装。

### 2.8 恢复手册

已有文档：

- [VOICE_CHAIN_ONE_SHOT_RESTORE_2026-05-11.md](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/docs/VOICE_CHAIN_ONE_SHOT_RESTORE_2026-05-11.md)
- [LOCAL_TO_G1_DEPLOY_PLAYBOOK_2026-05-14.md](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/docs/LOCAL_TO_G1_DEPLOY_PLAYBOOK_2026-05-14.md)
- [G1_OFFLINE_EMBODIED_DEPLOYMENT_PLAN_2026-05-15.md](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/docs/G1_OFFLINE_EMBODIED_DEPLOYMENT_PLAN_2026-05-15.md)
- [OFFLINE_ONLINE_CAPABILITY_CHECKLIST_2026-05-15.md](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/docs/OFFLINE_ONLINE_CAPABILITY_CHECKLIST_2026-05-15.md)

### 2.9 一键打包 / 备份 / 恢复脚本

脚本：

- [prepare_robot_wipe_bundle.sh](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/prepare_robot_wipe_bundle.sh)
- [package_robot_voice_assets.sh](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/package_robot_voice_assets.sh)
- [backup_robot_voice_chain.sh](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/backup_robot_voice_chain.sh)
- [restore_robot_voice_chain.sh](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/restore_robot_voice_chain.sh)

## 3. 仓库内仍然不是“自动完整恢复”的部分

这些不是代码缺失，而是恢复时仍需现场条件配合：

- 机器人真实 `.env.local`
  - API key
  - 局域网 IP
  - 音频设备名
- Python 虚拟环境重建
  - `interrupt/.venv`
  - `OM1/.venv-g1`
  - `wakeword-clean`
- LiveKit / Gemini / Ollama 服务可达性
- USB 麦、Pulse source/sink、相机设备枚举
- 导航构建产物是否需要现编

## 4. 对“能不能只靠标签从 0 恢复”的准确口径

### 4.1 可以说“仓库里有”

- 主链代码
- 恢复脚本
- 环境模板
- service 文件
- 导航源码
- OM1
- g1-wakeword
- 基础地图/配置资产

### 4.2 还不能说“完全不依赖现场环境”

因为以下仍不是纯代码问题：

- 机器人设备枚举
- 在线服务地址
- 私有密钥
- Python 依赖实际安装
- 导航是否需要重编译

## 5. 当前建议恢复顺序

1. 检出恢复标签
2. 按 [VOICE_CHAIN_ONE_SHOT_RESTORE_2026-05-11.md](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/docs/VOICE_CHAIN_ONE_SHOT_RESTORE_2026-05-11.md) 恢复主链
3. 用 [.env.example](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/.env.example) 生成机器人 `.env.local`
4. 跑 [restore_robot_voice_chain.sh](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/restore_robot_voice_chain.sh)
5. 再按 [FROM_ZERO_RESTORE_REPO_MANIFEST_2026-05-15.md](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/docs/FROM_ZERO_RESTORE_REPO_MANIFEST_2026-05-15.md) 逐项核对

## 6. 当前最准确的结论

当前仓库已经具备：

- `从标签恢复 interrupt 主链`
- `恢复 OM1 / g1-wakeword / 前门 service`
- `恢复本地化/离线化主线代码`

但如果目标是：

`拿标签 -> 新机器完全空白 -> 一次性恢复到现场演示状态`

那么仍然需要把现场环境变量、依赖安装和设备状态一起恢复到位。
