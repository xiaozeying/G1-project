# Voice Stack Robot Deployment Validation 2026-06-08

## 1. Scope

本文档只记录 `interrupt` 语音容器链在真实机器人上的一次打通验证，范围限定为：

- `wakeword-frontgate`
- `online-brain`
- `offline-brain`
- `ollama`
- `scripts/mode.sh`
- `scripts/recover.sh`
- `deploy_robot_voice_stack_over_ssh.sh`

本次现场结论重点是：

- `online` 链路可按最小集启动
- `offline` 入口仍保留，但不应宣称已完成生产化
- 机器人首次构建容器镜像时存在明显耗时

## 2. Final Deployment Shape

本次验证后，统一 `voice-stack` 运行面的固定口径如下：

- `online`
  - 只启动 `online-brain + wakeword-frontgate`
  - 不再被 `ollama` 和 `offline-brain` 启动失败阻塞
- `offline`
  - 启动 `ollama + offline-brain + wakeword-frontgate`
  - 仍视为实验链

对应入口：

```bash
./scripts/recover.sh online
./scripts/mode.sh online
./scripts/mode.sh offline
```

## 3. Field Problems Found

### 3.1 Docker daemon stale proxy

机器人 Docker daemon 初始带有失效代理：

```text
HTTP_PROXY=http://192.168.100.13:7897
HTTPS_PROXY=http://192.168.100.13:7897
```

直接表现为：

- `ollama/ollama:latest` 拉取失败
- `python:3.10-slim` 拉取失败
- `voice-stack` 首次 `up -d --build` 无法完成

现场排查命令：

```bash
systemctl show docker --property=Environment --no-pager
systemctl cat docker --no-pager | sed -n '1,220p'
```

现场修复命令：

```bash
/usr/bin/sudo rm -f /etc/systemd/system/docker.service.d/http-proxy.conf
/usr/bin/sudo systemctl daemon-reload
/usr/bin/sudo systemctl restart docker
```

注意：现场 shell 中 `sudo` 可能被 `/home/unitree/bin/sudo` 覆盖，因此应优先显式使用 `/usr/bin/sudo`。

### 3.2 Docker Hub direct access timeout

即使移除坏代理，机器人直连 `registry-1.docker.io` 仍可能超时。

现场验证结论：

- `registry-1.docker.io` 不稳定
- `docker.m.daocloud.io` 可达

因此本次收口增加了：

- `Dockerfile` 支持 `PYTHON_BASE_IMAGE`
- `env.voice-stack.example` 默认写入：

```text
HOST_INTERRUPT_RUNTIME_BASE_IMAGE=docker.m.daocloud.io/library/python:3.10-slim
```

### 3.3 Robot Docker bridge iptables limitation

机器人在默认 Docker build 网络下会触发：

```text
iptables raw table does not exist
```

因此统一 compose 中对 runtime image build 增加：

```yaml
build:
  network: host
```

避免首次 build 被 `bridge/raw` 规则卡死。

### 3.4 First build latency is expected

首次构建 `hongtu/interrupt-runtime` 时，`apt-get install` 会拉取大量依赖包，现场耗时很长是正常现象。

本次看到的典型量级：

- 新装约 290 个包
- 归档体积约 211 MB

所以第一次部署不能只看 `compose ps` 空表就判断失败，需要结合 build 日志一起看。

## 4. Changes Kept After Validation

本次真机验证后保留的工程改动包括：

1. `scripts/mode.sh`
   - `online` 只拉起 `online-brain + wakeword-frontgate`
   - `offline` 才拉起 `ollama + offline-brain + wakeword-frontgate`

2. `scripts/recover.sh`
   - 与 `mode.sh` 使用同一套最小启动口径
   - 支持从 `.env.local` 读取当前模式并恢复对应服务

3. `deploy/systemd/user/interrupt-voice-stack-compose.service`
   - `ExecStart` 改为调用 `scripts/recover.sh`
   - 避免 systemd 服务与 CLI 入口出现两套不同的启动口径

4. `deploy_robot_voice_stack_over_ssh.sh`
   - 会同步下发 `scripts/mode.sh` 和 `scripts/recover.sh`
   - 会创建机器人端 `scripts/` 目录
   - 会补齐 `HOST_INTERRUPT_RUNTIME_BASE_IMAGE`

5. `Dockerfile` / `docker-compose.voice-stack.yaml`
   - 支持替换 Python 基础镜像源
   - build 使用 `network: host`

## 5. Recommended Robot Acceptance Flow

### 5.1 Fresh deploy

```bash
cd /data/HongTu/interrupt
bash ./scripts/recover.sh online
```

### 5.2 Mode switch

```bash
cd /data/HongTu/interrupt
bash ./scripts/mode.sh online
bash ./scripts/mode.sh status
```

### 5.3 Runtime checks

```bash
/data/HongTu/interrupt/deploy/compose/composectl.sh \
  --env-file /data/HongTu/interrupt/deploy/compose/env.voice-stack \
  -f /data/HongTu/interrupt/deploy/compose/docker-compose.voice-stack.yaml \
  ps
```

```bash
tail -f /data/HongTu/interrupt/logs/robot-frontgate.log
```

```bash
docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}' \
  | grep -E 'hongtu/interrupt-runtime|docker.m.daocloud.io/library/python|REPOSITORY'
```

## 6. Current Boundary

当前仍然需要明确保留以下边界：

- `offline` 链仍未完成产品化
- `OM1` 依赖仍然是宿主机 bind mount，不是完整容器内封装
- 首次部署对现场网络质量仍较敏感
- `ollama` 仍不应成为 `online` 语音链路的硬阻塞条件

## 7. Practical Summary

这次真机验证后，统一 `voice-stack` 的正确理解应该是：

- 它已经可以作为语音链的一键部署与恢复入口
- 但必须按模式最小启动，不能把 `online` 和 `offline` 强绑在一起
- 机器人环境问题优先排查顺序应固定为：
  - Docker proxy
  - base image mirror reachability
  - Docker build network mode
  - first-build time budget
