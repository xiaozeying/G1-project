# Wakeword + Online Split Containers

日期：2026-06-05

## 1. 范围

本阶段只固定两块：

- `wakeword-frontgate`
- `online-brain`

暂不把 `offline_singlebox` 并入这套新容器拓扑。

## 2. 目标

- 保留真实唤醒词链路
- 保留当前稳定在线链路
- 把“唤醒”和“在线会话”拆成两个独立容器
- 不重写现有 `frontgate room session` 主逻辑

## 3. 拓扑

```text
wakeword-frontgate
  -> 真实唤醒词
  -> 本地唤醒播报 / 灯效
  -> HTTP 通知
  -> online-brain

online-brain
  -> frontgate_online_bridge
  -> run_frontgate_room_session.sh
  -> room-agent
  -> rtc-endpoint
  -> LiveKit / Gemini realtime
```

## 4. 为什么先不用第三个离线容器

当前离线链还没开发完整。

因此本阶段明确只做：

- 生产可用的在线链固定
- 唤醒与在线链路边界拆分

离线链后续再单独并入：

- `offline-brain`
- `ollama` sidecar

## 5. 关键实现

### 5.1 wakeword 容器

仍复用：

- `run_robot_frontgate_session.sh`
- `run_frontgate_session.sh`
- `tools/wakeword_session_frontgate.py`

区别是：

- `INTERRUPT_FRONTGATE_SESSION_COMMAND` 不再直接指向 `run_frontgate_room_session.sh`
- 而是改为 `scripts/frontgate_notify_online_bridge.sh`

### 5.2 online 容器

新增：

- `run_frontgate_online_bridge.sh`
- `tools/frontgate_online_bridge.py`

行为：

- 在本机 `127.0.0.1:8787` 提供一个极小 HTTP 服务
- 接收唤醒容器发来的 wake event
- 在容器内部继续调用现有 `run_frontgate_room_session.sh`

这意味着：

- 现有 `room-agent + rtc-endpoint + room_ready_ack + watchdog` 全部沿用
- 只在唤醒和在线会话之间插入一个容器边界

### 5.3 跨容器 intro-done 信号

新增共享目录：

- `${HOST_INTERRUPT_DIR}/volumes/frontgate_shared`

用途：

- `wakeword-frontgate` 写入 intro 完成信号
- `online-brain` 读取同一路径，继续执行 room ready ack 时序

## 6. 文件

新增文件：

- `deploy/compose/docker-compose.robot.wakeword-online.yaml`
- `deploy/compose/env.robot.wakeword-online.example`
- `deploy/compose/deploy_robot_wakeword_online_over_ssh.sh`
- `deploy/systemd/user/interrupt-frontgate-wakeword-online-compose.service`
- `run_frontgate_online_bridge.sh`
- `tools/frontgate_online_bridge.py`
- `scripts/frontgate_notify_online_bridge.sh`
- `scripts/recover_wakeword_online_split.sh`

## 7. 机器人部署

推送：

```bash
./deploy/compose/deploy_robot_wakeword_online_over_ssh.sh
```

推送并激活：

```bash
./deploy/compose/deploy_robot_wakeword_online_over_ssh.sh --activate
```

机器人本地恢复：

```bash
./scripts/recover_wakeword_online_split.sh
```

## 8. 当前结论

这套方案适合现在就落地，因为它：

- 不要求先完成离线链
- 不破坏当前稳定在线主链
- 让唤醒和在线链路可以独立重启、独立替换

后续如果要接离线容器，建议新增：

- `offline-brain`
- `ollama`

但不要回头改这阶段的 `wakeword-frontgate -> online-brain` 基本边界。
