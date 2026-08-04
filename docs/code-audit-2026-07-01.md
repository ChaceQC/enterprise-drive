# 代码审计记录：复用成熟库与开放协议

## 审计背景

本次审计依据 `AGENT.md` 中新增的约束执行：

- 功能实现优先复用成熟库、标准工具、开放协议、框架能力或可信开源实现。
- 不默认引入或直接依赖云厂商专有 SDK。
- 临时自研实现必须记录原因、适用范围、已知限制和替换触发条件。
- 实验性功能在鲁棒性、可扩展性和可维护性前提下保持最小可行实现。

审计范围覆盖当前后端依赖、对象存储适配、Redis 限流、分页游标、文件名校验、上传 hash、认证安全、outbox 重试和文件树辅助逻辑。

## 高优先级问题

### 1. 对象存储直接依赖云厂商 SDK（已整改）

涉及位置：

- `backend/pyproject.toml:15`
- `backend/app/infrastructure/storage/s3.py:9`
- `backend/app/infrastructure/storage/s3.py:26`
- `backend/app/api/deps.py:61`
- `backend/app/workers/upload_tasks.py:9`
- `企业网盘开发者技术计划书.md:267`
- `企业网盘开发者技术计划书.md:798`

发现：

- 当前项目直接依赖 `boto3>=1.34`，并在 `S3StorageAdapter` 内创建 `boto3.client("s3")`。
- 业务模块已经通过 `StorageAdapter` 协议隔离对象存储调用，这一点是正确的；但依赖层仍直接绑定 AWS SDK，与“不默认引入或直接依赖云厂商专有 SDK”的新规则冲突。
- 完整技术计划书仍把 `boto3` 写入依赖基线，并把它作为默认实现讨论，文档与最新规则不一致。

风险：

- 后续如果继续以 boto3 为默认适配，会把 S3 兼容能力绑定到 AWS SDK 的行为、配置和兼容差异上。
- 当前适配器可替换性较好，但依赖基线和默认实例化会使新功能自然继续扩展 boto3，而不是优先选择开放协议或开源可替换客户端。
- boto3 为同步 SDK，当前已通过 `asyncio.to_thread` 包装，避免直接阻塞 event loop；但线程池包装不是长期批量对象操作方案。

建议：

- 优先替换为 S3 兼容、非云厂商专有的开源客户端适配器，例如 MinIO Python SDK，或评估基于标准 HTTP/SigV4 的轻量开源实现。
- 新适配器仍保持 `StorageAdapter` 协议边界，业务模块、上传服务、下载服务和清理任务不直接 import 具体对象存储客户端。
- 替换时同步修改 `backend/pyproject.toml`、`uv.lock`、`backend/app/infrastructure/storage/s3.py`、`backend/app/api/deps.py`、`backend/app/workers/upload_tasks.py`、README、后端 README、PROJECT_PLAN 和完整技术计划书。
- 若短期必须保留 boto3，应在对象存储 README 或进度文档中明确标注为临时方案、限定只存在于 `infrastructure` 适配层，并写明替换计划和验收条件。

整改结果：

- 已移除 `boto3/botocore` 直接依赖，改用 MinIO Python SDK 作为默认对象存储适配实现。
- `S3StorageAdapter` 仍通过 `StorageAdapter` 协议向业务层暴露能力，上传、下载和清理任务不直接依赖具体 SDK。
- 完整技术计划书、README、后端 README 和执行计划已同步改为 MinIO Python SDK 与开放 S3 兼容客户端路线。
- 2026-07-01 审计时 MinIO Python SDK 的 multipart create/complete/abort 仍在适配层调用客户端私有方法；2026-08-03 已改为公共预签名 API + 标准 S3 HTTP/XML 控制面，并由真实 MinIO 门禁锁定行为。

参考依据：

- MinIO Python SDK 文档说明其面向 MinIO 或其他 S3 兼容对象存储，并提供 Python SDK 安装与 API 文档：https://docs.min.io/aistor/developers/sdk/python/
- MinIO Python Client API 文档说明 `Minio` client 在 Python threading 场景下线程安全，但不应跨 multiprocessing 共享：https://docs.min.io/aistor/developers/sdk/python/api/
- minio-py 仓库标注 Apache V2 License，可作为许可证评估候选：https://github.com/minio/minio-py

## 中优先级问题

### 2. Redis 固定窗口限流为手写实现，且递增与过期非原子（已整改）

涉及位置：

- `backend/app/infrastructure/rate_limit/redis.py:31`
- `backend/app/infrastructure/rate_limit/redis.py:42`
- `backend/app/infrastructure/rate_limit/redis.py:45`
- `backend/app/api/deps.py:73`
- `backend/app/modules/upload/router.py:89`
- `backend/app/modules/file/router.py:178`

发现：

- 当前 `RedisFixedWindowRateLimiter` 自行实现固定窗口限流。
- `_increment` 中先执行 `INCR`，当计数为 1 时再执行 `EXPIRE`。如果进程、网络或 Redis 客户端在两条命令之间失败，可能留下没有 TTL 的限流 key。
- 项目已经通过 `RateLimiter` 协议隔离限流实现，这是正确边界；问题集中在 Redis 适配内部的鲁棒性。

风险：

- 无 TTL 的限流 key 会导致某个租户、用户、节点或 IP 在窗口结束后仍持续被限流。
- 当前功能刚覆盖上传初始化、分片签名和下载预签名；如果继续扩展到登录失败、外链访问、搜索和管理接口，非原子实现的影响面会扩大。

建议：

- 优先评估成熟 Python 限流库，例如 `limits`。该库支持多种限流策略和 Redis、Memcached、MongoDB 等后端，并提供同步和异步 API。
- 如果为了保持依赖体量暂时保留本地实现，应改为 Redis Lua 脚本，将 `INCR` 和条件 `EXPIRE` 放在一次 `EVAL` 中原子执行，并补真实 Redis 测试覆盖 TTL 行为。
- 保留本地实现时需在 `PROJECT_PROGRESS.md` 中说明：适用范围仅限固定窗口基础限流；一旦新增滑动窗口、令牌桶、多层级规则、分布式策略复用或管理端动态规则，应切换成熟库。

整改结果：

- `RedisFixedWindowRateLimiter` 已改为 Redis Lua 脚本，在一次 `EVAL` 中完成 `INCR`、首次 `EXPIRE` 和 `TTL` 读取。
- 如果发现已有 key 缺失 TTL，Lua 脚本会重新设置窗口 TTL，避免长期误限流。
- 当前仍保留固定窗口策略，仅作为上传初始化、分片签名和下载预签名的基础保护；后续若需要滑动窗口、令牌桶、多层级动态规则或管理端配置，应切换成熟限流库。

参考依据：

- Redis 官方 `INCR` 文档说明，可将 `INCR` 与可选 `EXPIRE` 放入 Lua 脚本通过 `EVAL` 执行：https://redis.io/docs/latest/commands/incr/
- Redis rate limiter 教程明确指出 Lua 脚本可避免分离读写导致的并发竞态，并把递增和过期原子化：https://redis.io/tutorials/howtos/ratelimiting/
- `limits` 文档说明其是 Python 限流库，支持常见存储后端和多种策略：https://limits.readthedocs.io/

## 可暂时保留的轻量实现

### 1. 签名分页游标

涉及位置：

- `backend/app/core/pagination.py`
- `backend/app/modules/space/service.py`
- `backend/app/modules/file/service.py`

判断：

- 当前实现只做 `created_at + id` 的不透明游标，使用标准库 `hmac`、`hashlib`、`base64` 和 `json` 签名防篡改。
- 逻辑小、边界清楚、测试成本低，暂不需要引入额外库。

已知限制：

- 当前游标未包含版本号、过期时间、查询条件摘要或租户/用户上下文。

替换触发条件：

- 如果列表查询增加复杂筛选、跨版本兼容、游标过期、安全上下文绑定或前后端契约演进，应评估 `itsdangerous` 或框架级签名工具，并补契约测试。

### 2. 文件名校验

涉及位置：

- `backend/app/modules/file/validators.py`

判断：

- 当前实现使用标准库 `unicodedata.normalize("NFC", ...)`，并校验空名、路径穿越片段、路径分隔符、NUL、控制字符和长度。
- 规则与项目当前元数据存储边界匹配，暂不需要引入通用文件名库。

已知限制：

- 尚未覆盖 Windows 保留设备名、尾随点/空格、大小写折叠冲突、Unicode 混淆字符策略和租户级命名策略。

替换触发条件：

- 如果后续支持本地同步客户端、跨平台打包下载、WebDAV、SMB 网关或大小写不敏感目录策略，应引入成熟校验库或集中命名策略模块。

### 3. 上传 hash 规范化

涉及位置：

- `backend/app/modules/upload/hash.py`
- `backend/app/infrastructure/storage/s3.py:159`
- `backend/app/infrastructure/storage/testing.py:100`

判断：

- 当前只支持 `sha256`，本地实现仅做算法白名单和大小写规范化，复杂度很低。
- 服务端对象 hash 计算使用标准库 `hashlib` 流式处理，符合当前安全目标。

已知限制：

- 请求层仅约束 `content_hash` 长度，尚未严格校验 sha256 十六进制格式。

替换触发条件：

- 如果支持多算法、对象存储 checksum 头、客户端分片 Merkle 校验或文件类型嗅探，应引入成熟校验/检测库，并把 hash 契约写入 OpenAPI 测试。

### 4. Outbox 指数退避

涉及位置：

- `backend/app/modules/audit/dispatcher.py:91`
- `backend/app/modules/audit/repository.py`

判断：

- 当前 outbox 调度只需要简单指数退避，最大延迟 300 秒，逻辑集中且测试已覆盖状态流转。
- Celery 已承担任务运行，outbox 当前只负责数据库事件投递状态，不需要额外调度框架。

已知限制：

- 2026-07-01 审计时没有 jitter、分级错误分类、dead-letter 管理界面或指标告警；该限制已在 Sprint 12 / `0.9.0` 关闭：Outbox 现支持 transient/permanent 分类、带 jitter 的有界退避、processing 超时恢复、dead-letter 查询/详情/幂等重放和最老积压告警。

替换触发条件：

- 当前集中实现继续适用于单 PostgreSQL Outbox 与少量受控 publisher；如果未来扩展为高吞吐多目标投递、跨服务顺序保证或复杂延迟调度，再评估 `tenacity`、专用消息系统或更完整的事件投递组件。

### 5. 文件树遍历辅助函数

涉及位置：

- `backend/app/modules/file/tree.py`
- `backend/app/modules/file/service.py`

判断：

- 当前树遍历是面向 Sprint 2/3 的小规模目录同步处理，逻辑清楚，已在进度文档标注大目录后续需后台任务或冗余状态。
- 暂不需要引入图算法库。

已知限制：

- 大目录删除、恢复和彻底删除仍可能形成长事务和多次查询。

替换触发条件：

- 如果目录规模扩大、引入批量恢复、后台删除、权限继承批量重算或审计批量投递，应改为后台任务、批处理游标或数据库递归查询，并补性能边界测试。

## 已符合规则的复用点

- 认证密码哈希使用 `argon2-cffi`；浏览器认证已改为服务端 opaque session、HttpOnly Cookie 和 CSRF 校验，不使用 JWT 编解码。
- Web 框架、配置、错误响应、参数校验使用 FastAPI、Pydantic 和 Starlette 体系。
- 数据访问使用 SQLAlchemy 2.x 和 Alembic migration，没有手写 SQL 字符串拼接业务查询。
- 异步任务使用 Celery，没有自研任务队列。
- Redis 连接使用 `redis.asyncio` 客户端，没有自研协议客户端。
- 测试使用 pytest、pytest-asyncio、httpx 和测试替身适配器，符合可替换边界。

## 后续行动建议

1. 对象存储默认实现、依赖基线和相关文档已完成整改；2026-08-03 又移除 MinIO multipart 私有方法依赖，后续按 `minio 7.x` 兼容窗口和真实集成门禁管理升级风险。
2. Redis 固定窗口限流已改为 Lua 原子脚本；后续新增复杂限流策略时再评估成熟限流库。
3. 浏览器认证已改为 BFF + HttpOnly Cookie Session，后续接入 OIDC/OAuth 2.1 + PKCE 时应继续保持 BFF 会话边界。
4. 容量校准已恢复为基于 PostgreSQL 事实表和现有 SQLAlchemy 能力的维护任务，未引入额外复杂调度或自研规则引擎；后续继续推进 blob/object 垃圾回收。
5. 为暂留轻量实现补充触发条件记录；后续触发时优先使用成熟库或框架能力。
