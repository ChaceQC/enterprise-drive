# 维护任务监控与告警

## 1. 范围

`BE-035` 复用现有 Celery beat 和 `maintenance` 队列，不新增第二套调度器。当前纳入统一健康状态的周期任务：

- `upload.expire_sessions`
- `file.cleanup_expired_trash`
- `file.cleanup_unreferenced_blobs`
- `file.cleanup_orphaned_objects`
- `quota.reconcile_space_usage`

Beat 只负责按 UTC 周期投递，任务业务事实仍以 PostgreSQL、审计日志和对象存储状态为准。

## 2. 连续失败状态

maintenance Worker 在 Celery `task_postrun` signal 中记录最终状态，不修改五个任务的业务函数。状态写入 Redis：

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
```

- 连续失败阈值不得小于 1。
- stale 周期倍数不得小于 2，避免单次调度延迟造成误报。
- Redis 状态默认保留 30 天。
- Redis 连接超时保持短值，监控写入不得长时间阻塞任务收尾。

## 5. Prometheus 规则

规则文件：

```text
deploy/monitoring/maintenance-alerts.yml
```

包含：

- 连续失败 Critical。
- 多周期未完成 Warning。
- 对象存储清理错误 Warning。
- 容量快照或账本漂移 Warning。

根 Compose 当前不内置 Prometheus Server 或 Alertmanager。生产监控系统必须：

1. 把 `worker-maintenance:9100` 配置为独立 scrape target。
2. 加载上述 rule 文件。
3. 把告警路由到企业现有 Alertmanager、邮件、短信或 IM 值班系统。
4. 保留 `service`、`task`、环境和部署实例标签，禁止把 tenant、用户、文件 ID 或 storage key 作为 Prometheus label。

## 6. 排障顺序

1. 检查 `beat` 和 `worker-maintenance` 容器状态。
2. 检查 `worker_tasks_total` 的 task/status 与最近错误日志。
3. 检查 Redis、PostgreSQL、MinIO 和 Docker Desktop 资源状态。
4. 根据 `maintenance_task_result_total` 判断是扫描积压、对象存储错误还是容量漂移。
5. 修复依赖后等待下一次周期任务；成功执行会自动清零连续失败告警。
