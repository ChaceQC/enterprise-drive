# BE-030 安全测试与修复

## 范围

本文保留 `BE-030` 的历史安全门禁，并同步 Sprint 11 / `0.8.0` 当前攻击面。OIDC、LDAP、Web 身份页面和 Rust 设备会话均已实现，必须与本地账号、Cookie Session、CSRF 和租户权限一起进入安全矩阵。检查范围包括：

- 未认证入口：登录、外链访问、外链下载、健康检查和 gateway。
- 已认证入口：文件、上传、下载、搜索、分享、权限和管理员审计。
- Cookie Session、CSRF、会话轮换与复用检测。
- 登录失败窗口、阶梯延迟、验证码、账号锁定/解锁、密码策略、强制改密和浏览器/桌面全会话吊销。
- OIDC provider/discovery/JWKS、PKCE、state/nonce、账号绑定、回调、开放重定向和登出。
- LDAP 目录源、secret 引用、连接测试、dry-run/full/incremental、稳定 external ID、成员 claim、冲突、禁用和离职。
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

## 2026-08-01 路由、租户与对抗输入矩阵

### 全路由身份与 CSRF

`tests/security_route_matrix.py` 登记运行时 OpenAPI 的全部 36 个 `/api/v1` method + path，并记录最小合法请求、公开/会话/管理员模式、租户范围、CSRF 模式和资源授权策略。矩阵集合与 `create_app(settings).openapi()["paths"]` 必须完全一致，避免新增 route 未进入安全审计。

- 全部受保护 route 的匿名请求返回 `401/AUTH_REQUIRED`。
- 登录保持统一 `AUTH_INVALID_CREDENTIALS`；无 Cookie 登出幂等成功；ping 和外链入口保持公开。
- 20 个副作用 route 在有效 Cookie Session 但缺失 CSRF 时统一返回 `403/CSRF_TOKEN_INVALID`。
- 普通用户访问管理员审计 route 返回 `403/ADMIN_REQUIRED`。

### 真实跨租户与撤权

测试建立第二租户的真实用户、空间、根目录、活动/回收站节点、文件版本、ACL、外链和上传会话，再由默认租户管理员访问：

- 26 个内部资源 route 全部返回 404，不泄露外租户资源类型、状态或标识。
- 默认租户空间列表不包含外租户空间，管理员审计查询不返回外租户日志。
- 外链仍按 `tenant_slug + raw_token` 的公开能力模型工作，不错误绑定内部 Cookie Session。
- 已登录成员的空间关系被删除后，原 Cookie Session 立即失去空间列表和写权限，不需要重新登录。

### 对抗输入与传输边界

- 伪装成 PNG 的损坏内容进入终态 `image_decode_failed`，不生成预览工件。
- 超过 `preview_max_source_bytes` 的图片在读取/解码前标记 `file_too_large`。
- Office 扩展名命令注入、路径穿越、反斜杠和 NUL 文件名被拒绝。
- `Range` 请求头不能绕过下载权限；返回的预签名 URL 不包含 Cookie、CSRF 或 URL userinfo。
- 外链攻击者轮换不同原始 token 时，访问和下载仍受来源 IP 总量窗口限制，达到门槛后返回 `429/RATE_LIMITED`。

新增矩阵与对抗输入测试本地结果为 `53 passed`。

### Host、CORS 与真实 Nginx 原始 HTTP

- Trusted Host 测试确认未知 Host 在业务 route dispatch 前返回 400，响应不反射攻击者 Host。
- CORS 预检只为显式配置的 origin 返回 `Access-Control-Allow-Origin` 与 credentials，未配置 origin 返回 400 且不带允许头。
- `scripts/smoke_gateway_security_docker.py` 使用仓库正式 `default.conf.template` 和本地 Nginx 镜像，固定 `--pull never`、`0.25 CPU / 128m / 64 PIDs`、只读根文件系统与 `no-new-privileges`。
- 原始 TCP 结果：健康检查 200，冲突 `Content-Length + Transfer-Encoding` 400，重复冲突 `Content-Length` 400，API Host 在 1 KiB 门槛下拒绝 2 KiB 请求并返回 413，storage Host 对同一长度返回 `100 Continue`。
- smoke 只创建一个随机命名 Nginx 容器，结束后强制删除并确认无残留。
- CI 先显式拉取 Nginx/Certbot，再以 `--pull never` 执行模板校验和 raw HTTP smoke，镜像下载与安全验证保持分离。

### 验证闭环

- 完整 `uv lock --check`、Ruff、格式、Bandit、pip-audit、Mypy 和 pytest 门禁全部通过；最终本地测试收集 247 个用例，结果为 `243 passed, 4 skipped`。
- route/租户批次提交 `94ed1d4` 对应 GitHub Actions run `30680735602`，5 个 job 全部成功。
- 网络层提交 `65ab794` 对应 run `30681448854`，backend、Windows 部署、镜像策略和两个 MinIO supply-chain job 全部成功；backend job 实际执行 Nginx 模板校验和 raw HTTP security smoke。
- 原供应链报告步骤虽然配置 `fail-build: false`，但仍以 Grype `--fail-on critical` 生成报告，已知基线会产生误导性的“Failed minimum severity”警告；真正的新增 Critical 判定由后续基线脚本负责。
- 提交 `ff00542` 改为先安装固定版本 Grype，再不带 `--fail-on` 生成完整 JSON 报告，后续基线脚本继续只阻断新增 Critical。对应 run `30681696299` 的 5 个 job 全部成功，完整日志中上述假失败文本和 GitHub error/warning 注解命中数为 0。

## 现有有效边界

- 浏览器认证使用服务端 opaque Cookie Session；session token 只以哈希保存。
- session cookie 为 HttpOnly，CSRF cookie 可读并要求副作用请求通过请求头回传。
- session 轮换替换旧 token；旧 token 复用会吊销整个 family。
- 登录失败仍先受 IP/账号 Redis 窗口限制；已定位用户的失败状态在 PostgreSQL 行锁内维护，超过阈值后持久化锁定并返回 `423 ACCOUNT_LOCKED` 与 `Retry-After`。
- 用户改密、管理员重置、用户停用和 LDAP 离职会同时吊销浏览器与桌面设备会话；强制改密账号不能访问其他业务入口或注册新设备。
- OIDC 只接受 Authorization Code + PKCE，state/nonce 一次消费，provider metadata issuer 必须匹配，ID token 只允许 RS256/ES256 并校验 issuer/audience/exp/iat/azp；回调返回路径来自 allowlist。
- OIDC/LDAP secret 只通过 `env:VARIABLE_NAME` 解析，数据库和管理响应不保存或回显明文；空值、缺失值和未知引用按凭据不可用处理。
- LDAP dry-run 不写核心用户/组织/绑定/cursor；full 缺失只影响当前 Source 的 LDAP 绑定，名称冲突进入冲突记录，目录 claim 消失不会删除仍由管理员手工保留的成员边。
- gateway 是唯一宿主端口入口；API、Worker、PostgreSQL、Redis、OpenSearch 和 MinIO 不发布宿主端口。
- 文件、下载、上传完成、分享、预览和授权入口均重新读取 PostgreSQL 权限事实。
- 用户可见 500 响应不返回内部异常、SQL、对象 key 或栈信息。

## 后续审计

- 完整后端代理 Range、增强审计、水印或 DLP 继续由 `BE-034` 交付。
- Sprint 11 代码侧安全治理与本地 route matrix、OpenAPI/client、前端 E2E、migration 门禁已通过；最终远端证据为 `{{SPRINT11_COMMIT}}`、`{{SPRINT11_CI_RUN_ID}}`、`{{SPRINT11_CI_JOB_SUMMARY}}`。
- 正式试点前使用真实企业 OIDC provider 和 LDAPS 目录执行 discovery/JWKS 轮换、错误回调、RP logout、目录分页/超时/证书链、冲突和离职演练；本地 fake adapter 测试不能替代该外部证据。
- 正式上线前处理 MinIO Server/Client 既有 Critical 基线，并完成真实公网 DNS、受信 TLS、外部扫描和恢复演练。

## 2026-08-04 Sprint 11 身份与账号安全

### 本地账号与会话

- `tests/test_sprint11_account_security.py` 覆盖验证码阈值、失败次数持久化、锁定、正确密码在锁定期仍返回 423、管理员版本前置解锁、强制首次改密、业务入口阻断、用户会话隔离、本人会话吊销、管理员重置和浏览器/桌面全会话吊销。
- 账号安全专项 4 个用例已分别通过；受影响既有回归为 Auth 8 passed、登录限流 2 passed、管理员用户生命周期 1 passed、桌面设备会话 1 passed。
- 密码策略由服务端统一返回和校验；弱密码、当前密码错误、密码复用、版本冲突和跨租户用户均返回受控错误，不在响应或审计中记录密码。
- CAPTCHA 通过 `CaptchaVerifier` 协议注入；默认 verifier 关闭，生产接入真实 provider 时仍需保证 token 只进入验证适配层，不进入指标标签或结构化日志。

### OIDC/OAuth 2.1 + PKCE

- `tests/test_identity_oidc.py` 覆盖账号绑定后登录、opaque Cookie Session、一次性 state 重放拒绝、同一 issuer/subject 不可绑定两个本地用户和 redirect path allowlist。
- provider 连接测试先读取 discovery 与 JWKS；HTTP 自动重定向关闭，非回环 provider endpoint 必须使用 HTTPS。
- token endpoint 返回的 ID token 通过 Authlib 校验签名和 claims，允许算法固定为 RS256/ES256；nonce 与数据库哈希匹配后才完成绑定或登录。
- 解绑会保护最后一种可用登录方式；OIDC logout 先构建受控 provider end-session URL，再吊销本地 session family 和 Cookie。

### LDAP 只读同步

- `tests/test_identity_ldap.py` 覆盖连接测试、绑定用户禁用只递增一次版本、dry-run 零核心写入、稳定映射增量更新、手工成员保留、全量缺失用户禁用与浏览器/桌面会话吊销，以及用户名/部门路径/组 slug 冲突记录。
- 同步请求先持久化 run，再由 `identity.sync_ldap` 在 maintenance Worker 执行；run 状态为 queued/running/succeeded/failed，失败保留错误码和消息，旧 cursor 仅在成功 apply 后前移。
- dry-run 强制按全量快照读取但不更新核心对象、绑定、Source cursor 或 `last_success_at`。full 才处理当前 Source 中未出现的绑定；incremental 只应用 adapter 明确返回的变化。
- 成员 claim 与核心成员边分离：目录声明出现时确保成员边存在；声明消失时，只有该边由 LDAP 管理且不存在其他 claim 时才删除，手工成员关系继续保留。

### 最终门禁插槽

- 运行时 OpenAPI 最终统计：105 paths / 134 operations / 162 schemas。
- Sprint 11 完整本地验证：账号安全 4 项与受影响回归 12 项、OIDC/LDAP 10 项、route matrix 134 条路由及 6 项集合校验、前端三浏览器 12 场景均通过；静态、锁文件、OpenAPI/client、PostgreSQL migration、Compose、Cargo metadata 和差异检查均通过。
- 集成提交与远端 CI：`{{SPRINT11_COMMIT}}` / `{{SPRINT11_CI_RUN_ID}}` / `{{SPRINT11_CI_JOB_SUMMARY}}`。
