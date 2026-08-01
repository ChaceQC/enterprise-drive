# BE-029 性能基准

## 目标

性能基准只测已经启动的 API/Compose 环境，不在压测命令里隐式构建、拉取或启动服务。当前工具使用项目 dev 依赖中的 Locust，报告同时保留 Locust CSV/HTML 和项目自己的 `report.json`。

技术计划书中的目标阈值为：

| 场景 | 目标 |
| --- | --- |
| 文件列表与批量权限评估 | P95 < 500 ms |
| 初始化上传 | P95 < 300 ms |
| 完成上传（不含对象存储合并） | P95 < 800 ms |
| 搜索 | P95 < 800 ms |
| 审计查询 | P95 < 1 s |

当前第一版覆盖登录、`/auth/me`、文件列表/批量权限评估、DTP/1 初始化上传、搜索和管理员审计查询。multipart complete、对象存储合并、10,000 文件、100 万索引和 1,000 万审计数据由后续 target 数据准备任务扩展，不能把 smoke 结果误报为目标规模验收。

登录和 `/auth/me` 当前记录请求量、错误率、P95/P99，但技术计划书尚未为其定义性能验收阈值，因此不会用临时编造的延迟目标阻断报告；正式门槛需要结合 Argon2id 参数、账号安全策略和生产 CPU 预算另行确定。

## Profile 与资源边界

| profile | fixture 子目录 | 用户数 | 时长 | 默认用途 |
| --- | ---: | ---: | ---: | --- |
| `smoke` | 100 | 2 | 20s | 本机真实 Docker 快速回归 |
| `baseline` | 1,000 | 10 | 60s | 单机基准 |
| `target` | 10,000 | 50 | 300s | 显式目标规模演练，默认不执行 |

`target` 只表示 API fixture 规模档位，不代表已经完成计划书中的 100 万索引或 1,000 万审计数据验收。运行前必须确认 Docker Desktop 资源、数据库容量、MinIO/OpenSearch 磁盘和清理窗口。

## 目标规模数据生成器

`performance.target_data` 负责准备、检查和清理 BE-029 的大规模基准数据，不会构建、拉取或启动任何服务。它把 OpenSearch 文档和审计日志分成独立阶段，使用确定性 ID、专属 `be029-*` index、专属审计 action、批量 checkpoint 和原子 state JSON，进程中断后可从上一个批次继续。

`performance.runner --scenario upload_complete` 会真实执行初始化、part presign、无 Cookie 的预签名 MinIO PUT、complete 和节点清理。测试环境请求带 `X-Drive-Benchmark: BE-029` 时，complete 响应增加 `Server-Timing` 的 `storage_complete`、`hash_validation` 和 `final_object` 分段；报告中的 `upload_complete_api_without_storage_merge` 为端到端响应时间扣除对象存储合并段后的指标。预签名数据面使用 `trust_env=false`，并把每个用户的首个连接 warm-up 单独记录，避免把冷启动误算为稳态传输。

先用小批次验证连接和清理路径：

```powershell
uv run python -X utf8 -m performance.target_data `
  --state tmp\performance\target\state.json `
  --opensearch-docs 1000 `
  --audit-rows 1000 `
  --max-batches 1 `
  prepare
uv run python -X utf8 -m performance.target_data `
  --state tmp\performance\target\state.json status
uv run python -X utf8 -m performance.target_data `
  --state tmp\performance\target\state.json `
  cleanup `
  --confirm-run-id <state.run_id>
```

正式目标必须显式确认并分阶段执行；`--max-batches` 默认值为 `1`，显式传 `0` 才表示本次不限批次，避免误操作时一次性占满 CPU、内存或磁盘：

```powershell
uv run python -X utf8 -m performance.target_data `
  --state tmp\performance\target\state.json `
  --opensearch-docs 1000000 `
  --audit-rows 10000000 `
  --confirm-large-target `
  --max-batches 100 `
  --throttle-seconds 0.05 `
  prepare
```

state 不保存数据库密码；清理只接受 state 中完全匹配的 `run_id`，只删除其专属 OpenSearch index 和带有精确 benchmark action 的审计行。完成数据生成后仍需执行真实 multipart complete 压测和 target profile，不能把“数据已准备”误报为完整性能验收。

2026-08-01 已使用本地固定镜像和两个受限临时容器完成 `1,000/1,000` 小规模闭环：默认参数先生成 `100/100` 并保存 checkpoint，显式 `--max-batches 0` 后恢复到 `1,000/1,000`；清理后审计 action 真实剩余 `0`，专属 OpenSearch index 返回 `404`，本轮容器剩余 `0`。PostgreSQL 限制为 `0.75 CPU / 768 MiB / 128 PIDs`，OpenSearch 限制为 `1 CPU / 1536 MiB / 256 PIDs`，运行阶段均使用 `--pull never`。这只验证生成器的恢复和清理闭环，不代表目标规模性能验收。

真实 Compose 的 `upload_complete` smoke 需要把 project 名传给 runner，以生成完整环境证据：

```powershell
uv run python -X utf8 -m performance.runner `
  --base-url http://localhost:<gateway-port> `
  --profile smoke `
  --scenario upload_complete `
  --docker-compose-project <compose-project> `
  --output-dir tmp\performance\multipart-report
```

报告 `report.json` 使用 `BE-029/2`，包含 `summary`（请求/失败/错误率）、每个指标的平均值、最小值、最大值、p50/p95/p99，以及 `environment.host`、`environment.docker`、`environment.compose`、`environment.database`、`environment.opensearch` 和 `environment.target_data`。容器环境采集只读取 compose project 标签下的容器，不读取或写入容器环境变量中的密码。

## 运行步骤

### 1. 启动已构建的真实环境

```powershell
# 先按 AGENT.md 单独完成镜像构建和 Compose 配置校验
.\deploy\windows\manage.ps1 up -EnvFile .env.windows
```

压测工具不会调用 `up -Build`，也不会自动拉取镜像。压测完成后单独停止：

```powershell
.\deploy\windows\manage.ps1 down -EnvFile .env.windows
```

容量基准通常需要在隔离环境把 `DRIVE_RATE_LIMIT_ENABLED=false`，否则同一测试账号和来源 IP 会先命中业务限流，测到的是保护策略而不是后端容量。根 `compose.windows.yml` 已把该变量传入 API/Worker，默认仍为 `true`；报告通过 `PERF_RATE_LIMIT_MODE` 记录本次模式。生产限流本身需要单独保留正向和触发 429 的功能测试。

### 2. 准备 smoke fixture

`prepare` 从当前登录用户可见的第一个空间解析真实 root node，在其下先创建一个带随机前缀的 fixture 根目录，再把 profile 对应数量的子目录全部放入该根目录。fixture 文件记录稳定的上传父目录、`fixture_root_id` 和子目录 ID，但不保存密码。文件列表场景访问 fixture 根目录以真实评估 100/1,000/10,000 项目录页；上传初始化继续使用稳定父目录，避免已取消 upload session 的外键阻塞 fixture 根目录清理。

```powershell
Set-Location backend
$env:PERF_PASSWORD = "<管理员密码>"
$env:PERF_RATE_LIMIT_MODE = "disabled-isolated-benchmark"
uv run python -X utf8 -m performance.fixture prepare `
  --base-url http://localhost:18080 `
  --profile smoke `
  --output tmp\performance\smoke\fixture.json
```

如果要固定空间和根节点，可显式传 `--space-id` 与 `--parent-id`。目标规模必须显式指定 `--profile target`，并先确认清理策略。

隔离测试环境没有空间时可显式传 `--create-space`。fixture 清理会先把本次 fixture 根目录及全部子目录移入回收站，再对根目录执行一次 purge；当前 API 没有删除空间入口，因此持久环境会保留一个空的性能空间，只有在随后删除整个隔离 Compose project volumes 时才使用 `--create-space`。

### 3. 运行基准

```powershell
uv run python -X utf8 -m performance.runner `
  --profile smoke `
  --scenario mixed `
  --fixture tmp\performance\smoke\fixture.json `
  --no-prepare `
  --output-dir tmp\performance\smoke\run-01
```

也可以让 runner 自动准备并在结束时清理 fixture：

```powershell
uv run python -X utf8 -m performance.runner `
  --profile smoke `
  --scenario list `
  --create-space `
  --output-dir tmp\performance\smoke\list-01
```

输出文件：

- `stats_stats.csv`：Locust 各请求名称的总计。
- `stats_stats_history.csv`：时间序列。
- `stats_failures.csv`：失败请求。
- `stats_exceptions.csv`：Locust 用户异常。
- `report.html`：人工查看。
- `report.json`：包含 profile、fixture 数量、并发参数、P95/P99、目标阈值和 `passed`。
- `report.json` 还记录 Git SHA、Python/Locust 版本、平台、CPU 数、限流模式和 fixture 是否新建了空间。

### 4. 清理

runner 默认清理本次自动创建的 fixture 根目录及全部子目录；如果使用 `--keep-fixture` 或 `--no-prepare`，必须显式执行：

```powershell
uv run python -X utf8 -m performance.fixture cleanup `
  --fixture tmp\performance\smoke\fixture.json
```

清理失败时保留 fixture JSON，优先按其中的 `fixture_root_id` 排查；兼容旧 fixture 时才逐个使用 `folder_ids`。清理入口始终先执行普通 DELETE，再执行 purge，不执行无差别数据库或对象存储删除。

## 场景说明

- `login`：只测登录，不在 `on_start` 预登录。
- `auth_me`：测已建立 Cookie Session 的 `/auth/me`。
- `list`：测 `/api/v1/files`，返回页会触发服务端批量权限评估，名称为 `file_list_permission_batch`。
- `upload_init`：测 DTP/1 `uploads/init`，若返回 multipart 会立即调用 `abort` 清理，不上传真实对象。
- `search`：测 `/api/v1/search`，需要 fixture 前缀已进入索引或接受空结果的查询路径。
- `audit`：测管理员审计分页查询。
- `mixed`：按保守权重混合上述热点，不等价于生产流量模型；正式容量结论必须用记录过的流量比例重跑。

## 首份真实 Docker smoke

2026-07-31 使用隔离 Compose project、现有本地镜像和 `--no-build --pull never` 完成首份可复现 smoke：

- profile：100 个 fixture 子目录、2 用户、20 秒、`mixed`。
- 结果：170 次请求、0 次失败，`report.json passed=true`。
- P95：文件列表/批量权限 `32 ms`、初始化上传 `92 ms`、搜索 `71 ms`、管理员审计 `25 ms`。
- 非门禁观测：登录 `2500 ms`、`/auth/me` `12 ms`、上传 abort `64 ms`。
- 资源峰值：6 个同时运行容器，aggregate Docker CPU `162%`，容器内存 `1506.1 MiB`，Docker 相关宿主进程 working set `4471.9 MiB`。
- 清理：数据库中随机 `perf*` fixture 节点为 `0`；测试 project 的容器、网络、named volumes 和四个临时宿主端口均为 `0`。
- 工件：`backend/tmp/performance/20260731-be029-smoke-9c42e8/`。

该结果只证明受限本机 smoke 可运行且当前阈值通过，不代表目标规模容量、生产账号登录 SLO 或完整 multipart 合并性能。

## 当前缺口

- 需要独立的数据生成器，直接准备 100 万 OpenSearch 文档和 1,000 万审计日志，并记录生成耗时、索引 refresh 和磁盘占用。
- 已补真实 multipart complete 分段和 `BE-029/2` 报告字段；仍需在 100 万/1,000 万目标数据与完整 target profile 中填入最终并发、数据量、磁盘和 p50/p95/p99 证据。
- 需要在 BE-035 接入持续失败阈值、Prometheus scrape 和治理看板；本工具只负责一次性可重复基准和工件输出。
