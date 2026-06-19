# docker-compose-manager

一个用于自动化管理 Docker Compose 项目的 Bash 脚本，支持重启、更新、构建、查看状态与日志，并针对自动化运行（cron / systemd timer）做了安全与鲁棒性强化。

## 特性

- **安全**：使用 `mktemp` 生成临时文件、`set -euo pipefail` 严格模式、变量全引号、容器名校验、镜像清理需显式开启。
- **鲁棒性**：运行前检查 `docker` 与 `docker compose`、检查 `docker-compose.yml`、用轮询替代固定 `sleep`、命令失败立即退出。
- **功能丰富**：支持 `restart` / `hard-restart` / `update` / `build` / `status` / `logs` 命令，可限定服务或容器。
- **UI/UX**：`--quiet` 静默模式、`--dry-run` 试运行、彩色错误/警告输出、完善的帮助信息。

## 安装

```bash
chmod +x docker-compose-manager
# 建议放到 PATH 中，例如
sudo cp docker-compose-manager /usr/local/bin/
```

## 用法

```bash
docker-compose-manager [全局选项] <命令> <路径> [参数...]
```

### 全局选项

| 选项 | 说明 |
|------|------|
| `-q`, `--quiet` | 静默模式，日志照常写入文件，但不在终端输出 |
| `--dry-run` | 只打印将要执行的命令，不真正调用 docker |
| `--no-color` | 禁用颜色输出 |

### 命令

> 说明：**所有命令在不指定服务/容器名时，默认作用于整个 `docker-compose.yml` 中定义的所有服务。**

| 命令 | 作用 | 示例 |
|------|------|------|
| `restart` | 普通重启运行中的容器 | `docker-compose-manager restart /path/to/project [容器名...]` |
| `hard-restart` | 硬重启：先停止/删除容器，再重新拉起 | `docker-compose-manager hard-restart /path/to/project [服务名...]` |
| `update` | 拉取镜像并执行 `up -d` | `docker-compose-manager update /path/to/project [服务名...]` |
| `build` | 构建镜像 | `docker-compose-manager build /path/to/project [服务名...]` |
| `status` | 查看容器状态 | `docker-compose-manager status /path/to/project` |
| `logs` | 查看日志（默认 tail 100） | `docker-compose-manager logs /path/to/project [服务名...]` |

```bash
# 作用于所有服务
docker-compose-manager update /path/to/project

# 只作用于指定服务
docker-compose-manager update /path/to/project app worker

# 硬重启所有服务（先 down 再 up -d）
docker-compose-manager hard-restart /path/to/project

# 硬重启指定服务
docker-compose-manager hard-restart /path/to/project web
```

## 自动化示例

### 1. Cron

每分钟检查一次更新：

```cron
# /etc/cron.d/docker-compose-manager
* * * * * root /usr/local/bin/docker-compose-manager -q update /opt/my-project
```

每天凌晨 3 点重启并清理旧镜像：

```cron
0 3 * * * root DOCKER_COMPOSE_PRUNE=1 /usr/local/bin/docker-compose-manager -q update /opt/my-project
```

> 使用 `-q` 避免 cron 产生邮件；脚本会自己写日志到 `~/.cache/docker-compose-manager/docker-compose-manager.log`。

### 2. Systemd Timer

创建三个文件：

**`/etc/systemd/system/docker-compose-manager@.service`**

```ini
[Unit]
Description=Manage Docker Compose project at %i

[Service]
Type=oneshot
ExecStart=/usr/local/bin/docker-compose-manager -q update %i
User=root
```

**`/etc/systemd/system/docker-compose-manager@.timer`**

```ini
[Unit]
Description=Run docker-compose-manager for %i every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

启用并启动（假设项目路径为 `/opt/my-project`）：

```bash
systemctl daemon-reload
systemctl enable --now docker-compose-manager@/opt/my-project.timer
systemctl list-timers docker-compose-manager@\*.timer
```

> 路径中的 `/` 在 systemd 实例名里会被转义为 `-`，实际使用时可能需要把路径做成软链或改用 `@` 后面的实例名规则。更简单的做法是不使用模板，直接为每个项目写独立的 service/timer 文件。

### 3. 为单个项目写独立的 Systemd 单元

**`/etc/systemd/system/my-project-update.service`**

```ini
[Unit]
Description=Update my-project via docker-compose-manager

[Service]
Type=oneshot
ExecStart=/usr/local/bin/docker-compose-manager -q update /opt/my-project
User=root
```

**`/etc/systemd/system/my-project-update.timer`**

```ini
[Unit]
Description=Run my-project update every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now my-project-update.timer
systemctl list-timers my-project-update.timer
```

### 4. Systemd Timer 时间写法

`[Timer]` 段常用指令：

| 指令 | 说明 | 示例 |
|------|------|------|
| `OnBootSec=` | 系统启动后多久首次触发 | `OnBootSec=1min` / `OnBootSec=5min` / `OnBootSec=0` |
| `OnUnitActiveSec=` | 上一次任务执行完成后多久再次触发 | `OnUnitActiveSec=5min` / `OnUnitActiveSec=1h` |
| `OnCalendar=` | 按日历时间触发（类似 cron） | `OnCalendar=*-*-* 03:00:00` |

常见配置示例：

```ini
# 每 5 分钟执行一次
[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
```

```ini
# 每小时执行一次
[Timer]
OnBootSec=1min
OnUnitActiveSec=1h
```

```ini
# 每天凌晨 3 点执行（类似 cron 0 3 * * *）
[Timer]
OnCalendar=*-*-* 03:00:00
```

```ini
# 每周一凌晨 2 点执行
[Timer]
OnCalendar=Mon *-*-* 02:00:00
```

```ini
# 每 3 小时执行一次，且系统启动 5 分钟后首次执行
[Timer]
OnBootSec=5min
OnUnitActiveSec=3h
```

> 使用 `OnCalendar` 时不需要 `OnUnitActiveSec`。可以用 `systemd-analyze calendar '*-*-* 03:00:00'` 验证时间语法。

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DOCKER_COMPOSE_LOG` | 日志文件路径 | `~/.cache/docker-compose-manager/docker-compose-manager.log` |
| `DOCKER_COMPOSE_PRUNE=1` | 更新后执行 `docker image prune -f` | 不执行 |
| `DOCKER_COMPOSE_LOGS_TAIL` | `logs` 命令默认 tail 行数 | `100` |
| `DOCKER_COMPOSE_WAIT_TIMEOUT` | 等待容器就绪超时（秒） | `30` |
| `DOCKER_COMPOSE_WAIT_INTERVAL` | 等待容器就绪检查间隔（秒） | `2` |

## 日志

默认日志位置：

```text
~/.cache/docker-compose-manager/docker-compose-manager.log
```

可通过 `DOCKER_COMPOSE_LOG` 覆盖，例如：

```bash
DOCKER_COMPOSE_LOG=/var/log/dcm.log docker-compose-manager update /opt/my-project
```

## 注意事项

- 脚本默认不执行 `docker image prune -f`，如需清理请设置 `DOCKER_COMPOSE_PRUNE=1`。
- `update` 命令现在直接执行 `docker compose up -d`，由 Docker 自行决定是否需要重建容器，不再先 `down`。
- 在自动化环境中建议始终使用 `-q` 避免终端输出噪音。
- 使用 `--dry-run` 可在不实际执行的情况下预览将要运行的命令。
