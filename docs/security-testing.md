# BE-030 安全测试与修复

## 范围

本阶段以当前默认部署、已实现 API 和攻击者可达路径为准，不把尚未实现的 OIDC、LDAP、Web 页面或 Rust 桌面端当作现有攻击面。检查范围包括：

- 未认证入口：登录、外链访问、外链下载、健康检查和 gateway。
- 已认证入口：文件、上传、下载、搜索、分享、权限和管理员审计。
- Cookie Session、CSRF、会话轮换与复用检测。
- 用户上传内容的预览、正文抽取和对象存储处理。
- PostgreSQL、Redis、OpenSearch、MinIO、Worker 与 gateway 的网络边界。
- Python 依赖、静态代码模式、镜像和既有供应链门禁。

## 自动化门禁

后端 dev 依赖固定 `bandit` 和 `pip-audit`，GitHub `backend-ci` 在 Ruff 之后执行：

```powershell
Set-Location backend
uv sync --frozen --all-extras --dev
uv run bandit -r app -ll --skip B101
uv run pip-audit --local --progress-spinner off
```

- Bandit 阻断中危和高危结果。测试断言使用仓库测试规则检查，因此扫描跳过 `B101`。
- Worker metrics 的 `0.0.0.0:9100` 只监听 Compose 内部网络，正式编排不发布宿主端口；代码只对这一行精确标注 `# nosec B104`。
- `pip-audit` 审计当前项目虚拟环境中的实际锁定包，发现已知漏洞时返回非零状态。
- MinIO Server/Client 继续使用现有 SBOM、Grype 和 Critical 基线门禁；其既有 Critical 基线没有因 Python 审计而消失。

## 2026-07-31 首轮结果

### Pillow 上传内容处理

实际环境审计了 123 个已安装包，发现的 20 条记录全部集中在 `Pillow 12.2.0`。项目预览 Worker 会对用户上传图片执行 `Image.open(...).convert(...)`，因此不是不可达的开发依赖。

处理结果：

- 生产依赖下限提升为 `pillow>=12.3.0`。
- `uv.lock` 和本地环境已更新到 `Pillow 12.3.0`。
- 加入安全工具后重新审计 145 个环境包，已知漏洞数为 0。
- 图片、PDF、Office 和 Worker 预览定向测试全部通过。

### 登录暴力猜测与时序枚举

登录入口现在同时执行两类 Redis 固定窗口：

- `auth.login.ip`：默认每个来源 IP 每 60 秒 30 次。
- `auth.login.account`：默认每个规范化租户与账号标识每 60 秒 10 次；Redis key 只保存 SHA-256 标识，不保存原始用户名。

账号维度不包含客户端 IP，用于限制分布式账号猜测；IP 维度限制单来源对 Argon2id 的 CPU 消耗。达到门槛统一返回 `RATE_LIMITED` 和剩余等待秒数。

当租户不存在、用户不存在或用户已停用时，认证服务仍执行与正常密码相同参数的 Argon2id 校验，再返回统一的 `AUTH_INVALID_CREDENTIALS`，降低账号存在性时序差异。

环境变量：

```dotenv
DRIVE_RATE_LIMIT_ENABLED=true
DRIVE_LOGIN_IP_RATE_LIMIT_COUNT=30
DRIVE_LOGIN_ACCOUNT_RATE_LIMIT_COUNT=10
DRIVE_LOGIN_RATE_LIMIT_WINDOW_SECONDS=60
```

### 敏感输入回显

422 请求校验错误不再把 Pydantic 的原始 `input` 写入响应 `details`，避免密码、外链口令、原始 token 或其他敏感字段被错误响应、代理或客户端日志重复保存。

### Production Settings fail-fast

`Settings` 现在在 `DRIVE_ENVIRONMENT=production` 时执行应用内安全自校验，不能只依赖宿主 `manage.ps1`：

- 禁止 debug 和关闭限流。
- 关键 secret、初始管理员密码、S3 secret 与 PostgreSQL/Redis/Celery URL 密码必须达到既定长度，并拒绝示例值、开发默认值和 `$` 间接插值。
- Trusted Hosts 必须显式列出且禁止 wildcard；CORS 与 S3 公共端点必须是无凭据、无路径/query/fragment 的 HTTP(S) 根 URL。
- localhost/回环地址继续允许本机 HTTP 基线；出现任何非回环生产 Host 后，CORS 和 S3 公共端点必须使用 HTTPS、Cookie 必须启用 Secure，S3 外部端点必须使用 443。
- `hide_input_in_errors` 会阻止 Pydantic 在启动异常中回显原始配置输入。

该校验由 FastAPI、Celery Worker/beat、Alembic migration 和管理员 seed 的共同 `get_settings()` 路径触发。单元测试覆盖本机与公网正例、默认/示例 secret、无密码 URL、Wildcard、带凭据/路径端点、HTTP 公网 origin、非 443 S3、SameSite=None 和 secret 不回显。

真实 Docker 负例确认弱 production 配置在联网前以退出码 1 阻断且不回显传入 secret；正例分别通过独立 PostgreSQL/认证 Redis/API/Worker 可观测性 smoke，以及根 Compose migration、seed、minio-init 和 API healthy 依赖链。两次隔离验证结束后相关容器、网络和卷均为 0。

提交 `a52b4ce` 对应 GitHub Actions run `30661668693`，backend、Windows 部署、镜像策略和两个 MinIO supply-chain job 全部成功；CI 实际执行 188 个后端测试、新增安全扫描、observability Docker smoke 以及 runtime/preview 镜像构建。

### 首轮验证闭环

- 完整锁文件、同步、Ruff、格式、Bandit、pip-audit、Mypy 和 pytest 门禁全部通过；完整测试结果为 `172 passed, 4 skipped`。
- runtime 与 preview 镜像分别在 `1 CPU / 2 GiB`、`1 CPU / 3 GiB` BuildKit 上限下使用 `--pull=false` 串行重建，两个镜像都确认安装 `Pillow 12.3.0`。
- 隔离真实 Compose 使用已有本地镜像和 `--no-build --pull never` 启动 API 必需依赖。账号限流阈值临时设为 1 后，错误登录第一次返回 `401/AUTH_INVALID_CREDENTIALS`，第二次返回 `429/RATE_LIMITED`，动作是 `auth.login.account`。
- 真实 Compose 采样峰值为 5 个运行容器、`123.1%` aggregate Docker CPU 和 `1426.3 MiB` 容器内存；验证结束后隔离 project 的容器、网络和卷全部清理。
- 提交 `25acecf` 对应 GitHub Actions run `30660034411`，backend、Windows 部署、镜像策略和两个 MinIO supply-chain job 全部成功。

## 现有有效边界

- 浏览器认证使用服务端 opaque Cookie Session；session token 只以哈希保存。
- session cookie 为 HttpOnly，CSRF cookie 可读并要求副作用请求通过请求头回传。
- session 轮换替换旧 token；旧 token 复用会吊销整个 family。
- gateway 是唯一宿主端口入口；API、Worker、PostgreSQL、Redis、OpenSearch 和 MinIO 不发布宿主端口。
- 文件、下载、上传完成、分享、预览和授权入口均重新读取 PostgreSQL 权限事实。
- 用户可见 500 响应不返回内部异常、SQL、对象 key 或栈信息。

## 后续审计

- 对 34 个 API route 建立未认证、普通用户、跨租户、撤权并发和管理员矩阵。
- 增加动态安全测试，覆盖 Host/CORS/CSRF、请求走私边界、超大请求、恶意图片/文档、Range、预签名 URL 和外链穷举。
- Sprint 11 再实现阶梯延迟、临时锁定、管理员解锁、验证码和登录安全告警；当前固定窗口不替代完整账号安全治理。
- 正式上线前处理 MinIO Server/Client 既有 Critical 基线，并完成真实公网 DNS、受信 TLS、外部扫描和恢复演练。
