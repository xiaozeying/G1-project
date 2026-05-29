# G1 容器化与一键换机部署

更新时间：2026-05-20

## 1. 目标

这套收口以“完整版能力不退化”为前提：

- 普通话 / 粤语 / 英语三语言自适应
- 稳定普通对话
- 视觉问答
- 动作执行
- 导航执行
- 打断与恢复
- RTC 单路播报链
- 在线增强问答：天气、新闻、开放知识

因此，策略不是把所有东西硬塞进一个容器，而是：

- 能容器化的服务统一改成镜像 + `docker compose`
- 必须直连硬件 / 用户态音频 / 现场设备的部分，通过 compose 显式透传
- 保留 `interrupt/.env.local` 作为现场配置真源

## 2. 新增内容

开发机：

- `deploy/compose/docker-compose.local.yaml`
  - `livekit`
  - `room-agent`
  - 可选 `ollama` profile

机器人：

- `deploy/compose/docker-compose.robot.yaml`
  - `robot-frontgate`
  - 显式挂载：
    - `/dev/snd`
    - `/dev/video2`
    - Pulse socket / cookie
    - `OM1`
    - `g1-wakeword`

通用：

- `deploy/compose/Dockerfile`
- `deploy/compose/composectl.sh`
- `deploy/compose/ensure_docker_compose.sh`
- `deploy/compose/backup_robot_over_ssh.sh`
- `deploy/compose/deploy_robot_over_ssh.sh`
- `deploy/systemd/user/interrupt-frontgate-compose.service`

## 3. 为什么这样不会破坏完整版能力

完整版依赖的关键链路仍然保留：

- `Gemini realtime` 仍是主语音壳
- `LiveKit` 仍承担 RTC 房间与单路播报
- `room-agent` 仍走 `interrupt/src/agent.py`
- `robot-frontgate` 仍走现有 `run_robot_frontgate_session.sh`
- 本地文本脑仍可通过 `INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=prefer_tools`
- 视觉、动作、导航仍复用现有 `OM1 / camera / G1Nav2D`

变化只是：

- Python 运行环境从“必须依赖宿主机 `.venv`”改成“可由镜像自带解释器运行”
- 启动方式从手工 `run_*.sh` / `systemd` 收口到 compose

## 4. 开发机部署

准备：

```bash
cd interrupt
cp deploy/compose/env.local.example deploy/compose/env.local
```

按现场 IP 修改：

- `LIVEKIT_NODE_IP`
- `LIVEKIT_RTC_NODE_IP_IPV4`
- `HOST_REPO_ROOT`
- `HOST_INTERRUPT_DIR`

启动：

```bash
./deploy/compose/composectl.sh \
  --env-file deploy/compose/env.local \
  -f deploy/compose/docker-compose.local.yaml \
  up -d --build
```

如果要连同 Ollama 一起起：

```bash
./deploy/compose/composectl.sh \
  --env-file deploy/compose/env.local \
  -f deploy/compose/docker-compose.local.yaml \
  --profile ollama \
  up -d --build
```

## 5. 机器人部署

先把 compose 文件推到机器人：

```bash
cd interrupt
./deploy/compose/deploy_robot_over_ssh.sh
```

这一步默认只做 `stage`，不会立刻切走当前现场前门。

机器人首轮仅需编辑一次：

```bash
cp deploy/compose/env.robot.example deploy/compose/env.robot
```

确认这些路径：

- `HOST_REPO_ROOT=/home/unitree/HongTu`
- `HOST_INTERRUPT_DIR=/home/unitree/HongTu/interrupt`
- `HOST_OM1_DIR=/home/unitree/HongTu/OM1`
- `HOST_WAKEWORD_DIR=/home/unitree/g1-wakeword`
- `HOST_WAKEWORD_ENV_DIR=/home/unitree/miniforge3/envs/wakeword-clean`
- `HOST_XDG_RUNTIME_DIR=/run/user/1000`
- `HOST_PULSE_COOKIE=/home/unitree/.config/pulse/cookie`
- `HOST_CAMERA_DEVICE=/dev/video2`

手工启动：

```bash
cd /home/unitree/HongTu/interrupt
./deploy/compose/ensure_docker_compose.sh
./deploy/compose/composectl.sh \
  --env-file deploy/compose/env.robot \
  -f deploy/compose/docker-compose.robot.yaml \
  up -d --build robot-frontgate
```

如果确认要从本机直接切换，也可以：

```bash
./deploy/compose/deploy_robot_over_ssh.sh --activate
```

`--activate` 会先自动执行一次 `ensure_docker_compose.sh`。

开机自启：

```bash
systemctl --user daemon-reload
systemctl --user enable interrupt-frontgate-compose.service
systemctl --user start interrupt-frontgate-compose.service
```

## 6. 备份与换机

从本机发起机器人备份：

```bash
cd interrupt
./deploy/compose/backup_robot_over_ssh.sh
```

会备份：

- `interrupt/.env.local`
- 现有 `systemd --user` service
- `interrupt/backups/private/<stamp>`
- Docker 容器 / 镜像清单
- 一份 `switch-machine-bundle.tgz`

换机时最小步骤：

1. 恢复仓库到新机器。
2. 恢复 `OM1`、`g1-wakeword`、`interrupt/.env.local`。
3. 复制 `deploy/compose/env.robot`。
4. 如需沿用统一恢复入口，执行 `./restore_robot_voice_chain.sh --enable-compose`。
5. 或手工执行 compose `up -d --build`。
6. 启用 `interrupt-frontgate-compose.service`。

## 7. 当前边界

已经容器化：

- `LiveKit`
- `interrupt room-agent`
- `interrupt robot-frontgate` 运行面

仍保留宿主机透传：

- Pulse / USB 音频
- `/dev/video*`
- `OM1`
- `g1-wakeword`
- 现场 `.env.local`

这是为了先保证完整版能力不掉线；等 `wakeword` 与 `OM1` 自身也完全镜像化后，再继续把宿主机依赖缩小。

## 8. 2026-05-20 补充说明

### 8.1 默认模式说明

当前无论是 systemd 运行面还是 compose 运行面，都不能默认理解成“开机自动离线”。

当前真实口径仍然是：

- 默认主路径：`online_full`
- 离线验收模式：`offline_singlebox`

也就是说：

- compose 化不等于自动离线
- 断网也不等于当前版本会自动优雅切到完整离线主链

如果现场要验离线，必须显式切模式，再按专项文档验收：

- `interrupt/docs/OFFLINE_ACCEPTANCE_PLAN_2026-05-20.md`

### 8.2 机器人前门启动音频自愈

本轮 robot frontgate 运行面已补：

- Pulse sink/source readiness wait
- USB 默认输出自愈
- 启动无声 TTS 预热
- 失败自动重试一次
- 健康日志：
  - `logs/audio-startup-health.log`

因此后续现场若出现“开机首播无声”，优先先看：

```bash
tail -n 20 /home/unitree/HongTu/interrupt/logs/audio-startup-health.log
```

期望出现：

```text
status=ok
```
