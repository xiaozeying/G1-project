# HongTu Voice Runtime

本仓库当前 README 仅描述 G1 机器人语音主链相关内容。

不在本文档收口范围内：

- 导航链路
- 公司介绍、招聘、宣传信息
- 与当前语音运行时无关的历史实验说明

## 1. 当前目标

当前仓库的语音方向目标是：

- 在同型号 G1 机器上恢复并运行三语语音主链
- 固定稳定在线链路
- 保留离线链入口，但明确其尚未完整开发
- 支持前门唤醒、房间会话、RTC 音频、三语看门狗与同语言回复

当前默认推荐口径：

- `online` = 稳定生产链路
- `offline` = 实验链路，不视为等价生产能力

## 2. 语音主链范围

本次收口只关注以下目录和链路：

- `interrupt/`
  - 前门唤醒
  - room-agent
  - rtc-endpoint
  - 在线/离线模式切换
  - room ready 引导语
  - 前门看门狗
- `g1-wakeword/`
  - 真实唤醒词脚本与安装入口

当前不纳入本次收口：

- `G1Nav2D/`
- 各类导航桥接与地图资产
- 其他历史语音/视觉实验目录

## 3. 同机型刷机前准备入口

如果设备还没刷机，建议先从仓库根目录准备语音恢复包：

```bash
cd ~/HongTu
./prepare_same_model_g1_voice_bundle.sh
```

只检查准备条件，不实际打包：

```bash
./prepare_same_model_g1_voice_bundle.sh --verify-only
```

这个入口会委托：

- `interrupt/prepare_robot_wipe_bundle.sh`
- `interrupt/package_robot_voice_assets.sh`
- `interrupt/backup_robot_voice_chain.sh`

输出目录默认位于：

```text
interrupt/backups/private/<stamp>/
```

关键产物包括：

- `robot-interrupt.env.local`
- `om1-voice-assets.tar.gz`
- `g1-wakeword-assets.tar.gz`
- Python 环境 freeze 清单
- 设备快照
- `switch-machine-bundle.tgz`

## 4. 同机型刷机恢复入口

如果目标是把同型号、刚刷机的 G1 机器尽快拉回当前语音主链，统一从仓库根目录执行：

```bash
cd ~/HongTu
./restore_same_model_g1.sh
```

只做体检不启动服务：

```bash
./restore_same_model_g1.sh --verify-only
```

如果现场明确要启用 compose 运行面：

```bash
./restore_same_model_g1.sh --enable-compose
```

这个入口会：

- 统一 repo root / `interrupt/` / `g1-wakeword/` / `OM1/` 路径
- 自动校正 `~/HongTu` 软链
- 检查恢复边界
- 委托 `interrupt/restore_robot_voice_chain.sh` 完成语音主链恢复

## 5. 当前恢复边界

当前能跟随 git 恢复的主要语音资产：

- `interrupt/`
- `g1-wakeword/`
- 仓库根恢复入口 `restore_same_model_g1.sh`

当前还不能只靠 `git clone` 自动完整恢复的部分：

- `OM1/`
  - 当前没有完整纳入 git 跟踪
- 私有现场配置
  - `interrupt/.env.local`
- 本地 Python 运行环境
  - `interrupt/.venv`
  - `OM1/.venv-g1`
  - `wakeword-clean`
- 机器人现场设备状态
  - USB 音频
  - Pulse source/sink
  - 相机
  - 在线服务可达性

如果缺少 `OM1/`，恢复入口会明确中止，并要求提供：

1. 本地 `OM1/` 目录
2. 或 `interrupt/backups/private/<stamp>/om1-voice-assets.tar.gz`

## 6. 当前推荐恢复顺序

推荐按下面的闭环顺序执行：

1. 刷机前先执行：

```bash
./prepare_same_model_g1_voice_bundle.sh
```

2. 把仓库恢复到目标机器，例如 `/data/HongTu`
3. 建兼容软链：

```bash
ln -sfn /data/HongTu ~/HongTu
```

4. 确认以下目录存在：
   - `interrupt/`
   - `g1-wakeword/`
   - `OM1/` 或对应备份包
5. 执行：

```bash
./restore_same_model_g1.sh
```

6. 恢复后检查：

```bash
systemctl --user status interrupt-frontgate.service --no-pager
tail -n 80 interrupt/logs/frontgate.log
```

## 7. 日常切换入口

当前现场统一通过下面的脚本切换语音模式，不建议手改 `.env.local`：

```bash
cd interrupt
./robot_dialogue_mode.sh online
./robot_dialogue_mode.sh offline
./robot_dialogue_mode.sh status
```

当前固定口径：

- `online`
  - `INTERRUPT_AGENT_RUNTIME_MODE=online_full`
  - `INTERRUPT_AGENT_BACKEND=gemini_realtime`
  - `INTERRUPT_DIALOGUE_MODE_STABILITY=production_fixed`
- `offline`
  - `INTERRUPT_AGENT_RUNTIME_MODE=offline_singlebox`
  - `INTERRUPT_AGENT_BACKEND=local_text_ollama`
  - `INTERRUPT_DIALOGUE_MODE_STABILITY=experimental_incomplete`

## 8. 前门三语优化现状

当前仓库已经固定了前门三语优化的一期收口：

- 唤醒后并发拉房
- 自我介绍保留，但不阻塞房间初始化
- room ready 后只播报一条同语言引导语
- 用户发言需命中显式前缀看门狗后才允许进入 room-agent
- 问什么语言，优先按什么语言回复

对应文档：

- `interrupt/docs/TRILINGUAL_FRONTGATE_DIALOG_OPTIMIZATION_EXECUTION_PLAN_2026-06-05.md`

## 9. 一期 split container 现状

当前 split container 只收口语音链的一期方案：

- `wakeword-frontgate`
- `online-brain`

这套方案的目标是先固定：

- 真实唤醒词运行面
- 稳定在线语音主链

而不是一次性把未完成的离线链也并进去。

对应文档：

- `interrupt/docs/WAKEWORD_ONLINE_SPLIT_CONTAINERS_2026-06-05.md`

## 10. 关键入口文件

语音主链的主要入口：

- `prepare_same_model_g1_voice_bundle.sh`
- `restore_same_model_g1.sh`
- `interrupt/restore_robot_voice_chain.sh`
- `interrupt/run_robot_frontgate_session.sh`
- `interrupt/run_frontgate_room_session.sh`
- `interrupt/run_robot_rtc_endpoint.sh`
- `interrupt/run_room_agent.sh`
- `interrupt/robot_dialogue_mode.sh`

## 11. 最小技术结论

当前仓库已经可以作为同机型 G1 语音主链恢复的统一代码入口，但它还不是完全自包含的纯源码镜像。

最准确的说法是：

- 语音主链代码、刷机前准备脚本和恢复脚本已经收口
- 真实现场恢复仍依赖 `OM1/`、私有配置、虚拟环境和设备状态
- 导航链路不在当前 README 的技术说明范围内
