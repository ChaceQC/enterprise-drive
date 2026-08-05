# 维护任务监控与告警

## 1. 范围

`BE-035` 复用现有 Celery beat 和 `maintenance` 队列，不新增第二套调度器。当前纳入统一健康状态的周期任务：

- `upload.expire_sessions`
- `file.cleanup_expired_trash`
- `share.expire_shares`
- `preview.cleanup_artifacts`
- `file.process_tree_operations`
- `file.cleanup_unreferenced_blobs`
- `file.cleanup_orphaned_objects`
- `quota.reconcile_space_usage`
- `admin.cleanup_expired_exports`
- `audit.ensure_partitions`
- `audit.archive_retention`
- `governance.process_permission_rebuilds`

Beat 只负责按 UTC 周期投递，任务业务事实仍以 PostgreSQL、审计日志和对象存储状态为准。

## 2. 连续失败状态

maintenance Worker 在 Celery `task_postrun` signal 中记录最终状态，不修改十二个任务的业务函数。状态写入 Redis：

```text
maintenance_health:{task_name}
```

每个 hash 保存：

- `consecutive_failures`
- `alert_active`
- `last_status`
- `last_finished_at`
- `last_success_at`
- `last_failure_at`

成功会把连续失败归零；其他最终状态会原子递增失败次数。达到 `DRIVE_MAINTENANCE_ALERT_CONSECUTIVE_FAILURES` 时：

1. 写入结构化 `maintenance.alert` 错误日志。
2. 把 `maintenance_task_alert_active{task}` 设置为 `1`。
3. 由 `deploy/monitoring/maintenance-alerts.yml` 触发 Prometheus 告警。

`file.process_tree_operations` 和 `governance.process_permission_rebuilds` 的 Celery task 本身可以成功结束但报告个别 operation 失败，因此规则会单独监控相应 `maintenance_task_result_total{metric="failed"}`；排障后通过大目录或权限重算 retry API 恢复。显式 `governance.run_lifecycle_policy` 使用 `admin_jobs` 保存 pending/running/succeeded/failed，不进入周期 stale 计算。

Redis 状态只用于运行监控，不替代数据库和审计事实。Redis 暂时不可用时，维护任务原结果不被反向判定为失败；Worker 会记录状态写入错误，后续执行继续尝试。

## 3. Worker 指标

`worker-maintenance:9100/metrics` 新增：

| 指标 | 含义 |
| --- | --- |
| `maintenance_task_consecutive_failures{task}` | 当前连续失败次数 |
| `maintenance_task_alert_active{task}` | 是否达到连续失败阈值 |
| `maintenance_task_stale{task}` | 是否超过多个预期调度周期未完成 |
| `maintenance_task_last_finished_timestamp_seconds{task}` | 最近完成时间 |
| `maintenance_task_last_success_timestamp_seconds{task}` | 最近成功时间 |
| `maintenance_task_last_failure_timestamp_seconds{task}` | 最近失败时间 |
| `maintenance_task_result_total{task,metric}` | 任务返回计数的累计值 |

`maintenance_task_result_total` 只采集返回字典中的非负数值字段，例如 `scanned`、`cleaned`、`storage_errors`、`snapshot_drifts` 和 `ledger_drifts`；游标、ID、路径、错误文本和列表不会进入 label。

Worker 主进程每隔 `DRIVE_MAINTENANCE_HEALTH_REFRESH_SECONDS` 从 Redis 刷新 Gauge，因此 Worker 子进程轮换或重启后仍能恢复连续失败状态。stale 阈值为：

```text
任务调度间隔 × DRIVE_MAINTENANCE_ALERT_STALE_INTERVALS
```

从未完成过的任务保持 timestamp `0`，不立即标记 stale；部署监控还应单独检查 Celery beat 和 maintenance Worker 的 `up` 状态。

## 4. 配置

```dotenv
DRIVE_MAINTENANCE_ALERT_CONSECUTIVE_FAILURES=3
DRIVE_MAINTENANCE_ALERT_STALE_INTERVALS=3
DRIVE_MAINTENANCE_STATE_TTL_SECONDS=2592000
DRIVE_MAINTENANCE_STATE_REDIS_TIMEOUT_SECONDS=1.0
DRIVE_MAINTENANCE_HEALTH_REFRESH_SECONDS=30
DRIVE_ADMIN_EXPORT_RETENTION_DAYS=30
DRIVE_ADMIN_EXPORT_CLEANUP_INTERVAL_SECONDS=86400
DRIVE_AUDIT_PARTITION_MAINTENANCE_INTERVAL_SECONDS=86400
DRIVE_AUDIT_ARCHIVE_INTERVAL_SECONDS=86400
DRIVE_AUDIT_RETENTION_DAYS=365
```

- 连续失败阈值不得小于 1。
- stale 周期倍数不得小于 2，避免单次调度延迟造成误报。
- Redis 状态默认保留 30 天。
- Redis 连接超时保持短值，监控写入不得长时间阻塞任务收尾。
- 管理导出对象默认保留 30 天，每日清理一次。
- 审计分区默认每天检查并预建未来 6 个月；归档默认每天扫描 365 天前记录，是否删除源记录由显式配置控制。

## 5. Prometheus 规则

规则文件：

```text
deploy/monitoring/maintenance-alerts.yml
deploy/monitoring/platform-alerts.yml
```

包含：

- 连续失败 Critical。
- 多周期未完成 Warning。
- 对象存储清理错误 Warning。
- 容量快照或账本漂移 Warning。
- API/Worker scrape target down。
- API 5xx 比例和 P95 延迟。
- Outbox dead/backlog。
- Outbox 最老 pending/failed 积压超过 15 分钟。
- 权限重算批次失败和生命周期运行失败。
- 搜索索引延迟。
- Worker 失败和 Prometheus rule evaluation failure。

根 `compose.windows.yml` 已提供可选 `monitoring` profile：

- `prometheus`：抓取 API、5 个 Worker、Prometheus 和 Alertmanager，加载两组规则。
- `alertmanager`：从只读 URL 文件加载企业 webhook，并发送 resolved 通知。
- `grafana`：通过 gateway `/grafana/` 子路径访问，预置运行概览、维护治理和 Sprint 12 治理三张看板。

三项服务都只加入 Compose 内网，不发布宿主端口。Prometheus、Alertmanager 和 Grafana 的数据分别保存在独立 named volume；关闭 profile 不删除数据。

## 6. 启用监控 profile

先在未提交的 `.env.windows` 中配置：

```dotenv
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=至少16字符的独立强密码
GRAFANA_ROOT_URL=http://localhost:18080/grafana/
ALERTMANAGER_WEBHOOK_URL_FILE=D:\enterprise-drive-secrets\alertmanager-webhook-url
PROMETHEUS_RETENTION_TIME=30d
PROMETHEUS_RETENTION_SIZE=20GB
```

webhook 文件必须是 UTF-8 单行 HTTP(S) URL。正式 `up -Monitoring` 会拒绝仓库内示例文件、`change-me` Grafana 密码、localhost webhook 和不合法的 `/grafana/` root URL。公网 TLS 模式还要求：

```dotenv
GRAFANA_ROOT_URL=https://drive.example.com/grafana/
```

启用：

```powershell
.\deploy\windows\manage.ps1 config -Monitoring -EnvFile .env.windows -Quiet
.\deploy\windows\manage.ps1 up -Monitoring -EnvFile .env.windows
.\deploy\windows\manage.ps1 status -Monitoring -EnvFile .env.windows
```

同时启用公网 TLS：

```powershell
.\deploy\windows\manage.ps1 up -Tls -Monitoring -EnvFile .env.windows
```

访问：

```text
http://localhost:18080/grafana/
https://drive.example.com/grafana/
```

gateway 使用 Docker 内置 DNS 运行时解析 `grafana`，因此未启用 profile 时 gateway 仍可启动；访问 `/grafana/` 会返回上游不可用，而不会把 Grafana 端口直接暴露到宿主。

## 7. 管理 API

系统管理员可使用：

- `GET /api/v1/admin/maintenance/tasks`：查询十二个周期任务的连续失败、alert、stale 和时间戳。
- `POST /api/v1/admin/maintenance/runs`：创建租户范围的显式异步运行。
- `GET /api/v1/admin/maintenance/runs`：按状态/任务筛选并 cursor 分页。
- `GET /api/v1/admin/maintenance/runs/{run_id}`：查询持久化运行状态和结果。
- `GET /api/v1/admin/governance/overview`：查询权限重算、大目录任务、生命周期运行和维护告警摘要。
- `GET/PATCH /api/v1/admin/governance/lifecycle-policy`：读取或乐观更新租户生命周期策略。
- `POST/GET /api/v1/admin/governance/lifecycle-runs`：创建 dry-run/正式运行并查询持久化结果。
- `POST/GET /api/v1/admin/governance/permission-rebuilds`：创建或查询 space/node 权限重算。
- `GET/POST /api/v1/admin/governance/permission-rebuilds/{operation_id}[/retry]`：查询详情或恢复失败任务。
- `GET /api/v1/admin/audit/governance`：查询审计分区、归档、外部投递和 Outbox 摘要。
- `GET /api/v1/admin/outbox/dead-letters`：按事件/错误分类查询 dead-letter；详情只暴露 payload key 列表。
- `POST /api/v1/admin/outbox/dead-letters/{event_id}/replay`：执行租户隔离、审计和幂等重放。

显式运行默认 `dry_run=true`。会修改数据且不支持 dry-run 的任务必须提交 `dry_run=false`；容量校准修复必须使用 `dry_run=false, repair=true`。不适用的 `retention_days`、`repair` 或 `scan_all` 组合会返回 422，避免参数被静默忽略。

异步导出也使用 maintenance 队列；`admin.cleanup_expired_exports` 删除超过 `DRIVE_ADMIN_EXPORT_RETENTION_DAYS` 的私有导出对象并把 job 标记为 `expired`。

## 8. 配置与看板验证

CI 会：

1. 用 `docker compose --profile monitoring ... config` 确认三项服务存在且无宿主端口。
2. 拉取固定 digest 镜像并确认 healthcheck 使用的 `wget` 存在。
3. 使用镜像内 `promtool` 校验 Prometheus 配置和规则。
4. 使用镜像内 `amtool` 校验 Alertmanager 配置。
5. 解析所有 Grafana dashboard JSON，检查非空且 UID 唯一。

预置看板：

- `enterprise-drive-overview`：API RPS、5xx、P50/P95、Outbox、搜索延迟和 Worker 任务结果。
- `enterprise-drive-maintenance`：连续失败、alert/stale、维护返回计数和最近成功时间。
- `enterprise-drive-governance`：权限重算批次、生命周期运行、Outbox 最老积压/dead 数量和审计/治理维护告警。

保留 `service`、`task`、`queue`、环境和部署实例等有界标签；禁止把 tenant、用户、文件 ID、request ID 或 storage key 作为 Prometheus label。

## 9. 排障顺序

1. 使用 `manage.ps1 status -Monitoring` 检查 Prometheus、Alertmanager、Grafana、beat 和 worker-maintenance。
2. 检查 Prometheus targets 和 rule evaluation 状态。
3. 检查 `worker_tasks_total` 的 task/status 与最近错误日志。
4. 检查 Alertmanager route、webhook 文件路径和接收端响应。
5. 检查 Redis、PostgreSQL、SeaweedFS 和 Docker Desktop 资源状态。
6. 根据 `maintenance_task_result_total` 判断是扫描积压、对象存储错误还是容量漂移。
7. 修复依赖后等待下一次周期任务，或通过管理员维护 API 创建显式运行；成功执行会自动清零连续失败告警。
