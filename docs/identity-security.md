# Sprint 11 身份与账号安全

> 适用项目版本：`v0.8.0`
>
> migration head：`20260804_0024`

本文说明 Sprint 11 `BE-040` 至 `BE-043`、`FE-010` 至 `FE-011` 的当前实现、部署参数、安全边界和验收入口。身份提供商或目录只负责认证与目录数据来源；本地 PostgreSQL 用户、租户、权限、会话和审计仍是业务事实。

## 1. 能力范围

### 本地账号

- 来源 IP 与规范化账号哈希的 Redis 固定窗口限流。
- PostgreSQL 用户行锁内的失败次数、失败窗口、阶梯延迟、验证码阈值和临时锁定。
- `423 ACCOUNT_LOCKED`、`Retry-After`、锁定期限和管理员乐观解锁。
- 服务端密码策略、用户改密、管理员重置、首次登录强制改密。
- 浏览器会话列表、本人会话吊销、浏览器与桌面设备全会话吊销。

### OIDC/OAuth 2.1

- OIDC provider 创建、更新、启停、列表和连接测试。
- Authorization Code + PKCE S256、一次性 state/nonce。
- discovery、issuer、JWKS、RS256/ES256、issuer/audience/exp/iat/azp 校验。
- 本地账号绑定、解除绑定、单点登录和 RP-Initiated Logout。
- 回调完成后签发本项目 opaque Cookie Session，不向浏览器持久化 provider token。

### LDAP

- LDAP Source 创建、更新、启停、列表和连接测试。
- dry-run、full、incremental 三种 run。
- 用户、部门、用户组稳定 external ID 映射。
- 部门/组成员 claim、手工成员保留和多 Source 声明边界。
- 禁用、全量缺失离职、冲突报告、浏览器/桌面会话吊销。
- Celery maintenance Worker 异步执行 `identity.sync_ldap`。

### Web

- 登录页显示验证码、锁定反馈和 OIDC provider。
- 强制首次改密壳、密码策略、用户改密、浏览器会话管理。
- OIDC 登录回调、账号绑定和解除。
- 管理员账号解锁、密码重置。
- OIDC provider、LDAP Source、连接测试、LDAP run 和冲突页面。

## 2. 数据模型

`20260804_0024` 在既有认证表上增加：

- `users.local_password_enabled`
- `users.failed_login_attempts`
- `users.last_failed_login_at`
- `users.locked_until`
- `users.lock_reason`
- `users.password_changed_at`
- `auth_sessions.ip`
- `auth_sessions.user_agent`
- `auth_sessions.auth_method`
- `auth_sessions.oidc_provider_id`
- `auth_sessions.last_seen_at`
- `idx_auth_sessions_user_active`

身份表：

- `oidc_providers`：租户内 provider 配置和版本。
- `oidc_flows`：一次性登录/绑定 flow，保存 state/nonce 哈希、PKCE verifier、回调和到期时间。
- `oidc_identity_links`：`tenant + issuer + subject` 到本地用户的稳定绑定。
- `ldap_sources`：目录端点、查询范围、属性映射、secret 引用、cursor 和版本。
- `ldap_sync_runs`：queued/running/succeeded/failed run、模式、cursor、统计和错误。
- `ldap_object_bindings`：Source、对象类型、external ID 与本地对象 ID 的稳定映射。
- `ldap_sync_conflicts`：用户、部门、组和成员冲突。
- `ldap_membership_relations`：LDAP 声明对应的核心成员边及其所有权。
- `ldap_membership_claims`：每个 Source 对成员关系的声明和最后出现 run。

外部标识建立后不得因用户名、邮箱、DN、部门路径或组名变化而重新绑定。名称冲突进入 `ldap_sync_conflicts`，不自动接管已有本地对象。

## 3. 本地账号安全

### 3.1 配置

| 变量 | 默认值 | 说明 |
| --- | ---: | --- |
| `DRIVE_LOGIN_IP_RATE_LIMIT_COUNT` | `30` | 每个来源 IP 的登录窗口次数 |
| `DRIVE_LOGIN_ACCOUNT_RATE_LIMIT_COUNT` | `10` | 每个规范化租户/账号哈希的窗口次数 |
| `DRIVE_LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `60` | Redis 固定窗口 |
| `DRIVE_LOGIN_FAILURE_LOCK_THRESHOLD` | `5` | 用户失败次数达到该值后锁定 |
| `DRIVE_LOGIN_FAILURE_WINDOW_SECONDS` | `900` | 用户失败次数滚动窗口 |
| `DRIVE_LOGIN_LOCK_SECONDS` | `900` | 临时锁定时长 |
| `DRIVE_LOGIN_DELAY_BASE_SECONDS` | `0.25` | 首次失败基础延迟 |
| `DRIVE_LOGIN_DELAY_MAX_SECONDS` | `4.0` | 阶梯延迟上限 |
| `DRIVE_LOGIN_CAPTCHA_AFTER_FAILURES` | `3` | 达到该失败次数后要求验证码；`0` 表示不按次数触发 |
| `DRIVE_PASSWORD_MIN_LENGTH` | `12` | 密码最小长度 |
| `DRIVE_PASSWORD_REQUIRE_UPPERCASE` | `true` | 要求大写字母 |
| `DRIVE_PASSWORD_REQUIRE_LOWERCASE` | `true` | 要求小写字母 |
| `DRIVE_PASSWORD_REQUIRE_DIGIT` | `true` | 要求数字 |
| `DRIVE_PASSWORD_REQUIRE_SPECIAL` | `true` | 要求特殊字符 |

Redis IP/账号窗口先限制请求速率；找到活动本地用户后，再在用户行锁内维护失败状态。不存在租户/用户、停用用户或关闭本地密码时仍执行 Argon2id dummy/真实哈希校验，并返回统一认证错误。

### 3.2 验证码

`CaptchaVerifier` 是异步协议，输入只有挑战 token 和受控上下文。默认 `DisabledCaptchaVerifier` 不启用挑战；部署接入真实验证码时应实现基础设施适配器并通过依赖注入替换，禁止把 token 写入：

- 日志；
- 审计 metadata；
- Prometheus label；
- URL；
- 数据库身份表。

verifier 不可用返回 `CAPTCHA_UNAVAILABLE`；达到阈值但 token 缺失或无效返回 `CAPTCHA_REQUIRED`。只有 provider 验证通过后才继续校验密码。

### 3.3 密码和强制改密

接口：

- `GET /api/v1/auth/password/policy`
- `POST /api/v1/auth/password/change`
- `POST /api/v1/admin/users/{user_id}/password-reset`
- `POST /api/v1/admin/users/{user_id}/unlock`

规则：

- 管理员创建用户、管理员重置和用户改密使用同一服务端密码策略。
- 用户改密要求当前密码正确，新密码不能与当前密码相同。
- 管理员重置使用 `expected_version`，设置 `must_change_password=true`，清除失败/锁定状态并吊销全部会话。
- seed 管理员默认要求首次改密。
- `must_change_password=true` 时，服务端只允许读取 `/auth/me`、提交 `/auth/password/change` 和执行不依赖当前用户依赖的退出流程；其他业务入口返回 `PASSWORD_CHANGE_REQUIRED`。
- 改密成功后当前 Cookie 也被吊销，响应清除 Cookie，用户必须重新认证。

### 3.4 会话

接口：

- `GET /api/v1/auth/sessions`
- `DELETE /api/v1/auth/sessions/{session_id}`

列表只返回当前租户、当前用户、未撤销、未过期且未被轮换替换的浏览器会话，并标记当前会话、认证方式、OIDC provider、IP、User-Agent、创建/最近活动/过期时间。

吊销按 session family 执行：

- 用户只能访问和吊销自己的会话。
- 吊销当前 family 时响应清除 Cookie。
- 用户改密、管理员重置、用户停用和 LDAP 离职同时更新 `auth_sessions` 与 `device_sessions`。
- 旧轮换 token 被复用时，继续按既有规则吊销整个 family。

## 4. OIDC/OAuth 2.1 + PKCE

### 4.1 管理接口

- `GET /api/v1/admin/identity/oidc/providers`
- `POST /api/v1/admin/identity/oidc/providers`
- `PATCH /api/v1/admin/identity/oidc/providers/{provider_id}`
- `POST /api/v1/admin/identity/oidc/providers/{provider_id}/test`

provider 按租户隔离，slug 租户内唯一，更新使用 `expected_version`。读取响应返回 `client_secret_configured`，不返回 secret 明文。

当前 secret resolver 只接受：

```text
env:VARIABLE_NAME
```

例如数据库保存 `env:OIDC_CLIENT_SECRET`，真实值由 API 容器环境变量 `OIDC_CLIENT_SECRET` 提供。空字符串、变量缺失或未知引用格式按凭据不可用/引用不合法处理。

### 4.2 用户接口

- `GET /api/v1/auth/oidc/providers`
- `GET /api/v1/auth/oidc/{provider_slug}/start`
- `POST /api/v1/auth/oidc/{provider_slug}/bind/start`
- `GET /api/v1/auth/oidc/{provider_slug}/callback`
- `POST /api/v1/auth/oidc/{provider_slug}/logout`
- `GET /api/v1/auth/identity-links`
- `DELETE /api/v1/auth/identity-links/{link_id}`

登录 flow 只接受启用 provider。绑定 flow 还绑定当前租户和当前本地用户。

### 4.3 流程和校验

1. 服务端生成随机 state、nonce、code verifier。
2. 数据库只保存 state/nonce 哈希；code verifier 仅保存在短期 flow 中。
3. provider authorization URL 使用 PKCE `S256`。
4. 回调先原子消费 flow 并提交，使同一 state 不能重放。
5. 服务端用 code verifier 交换 token。
6. discovery issuer 必须与配置 issuer 精确匹配。
7. ID token 只允许 RS256/ES256，通过 JWKS 校验签名，并验证 issuer、audience、exp、iat；多 audience 时验证 azp。
8. ID token nonce 哈希必须与 flow 匹配。
9. 登录只接受已绑定的 `tenant + issuer + subject`；不会按 email 自动绑定本地账号。
10. 成功后只签发本项目 Cookie Session，并记录 `auth_method=oidc` 与 provider ID。

非回环 provider endpoint 必须使用 HTTPS；HTTP 只允许 `localhost`、`127.0.0.1`、`::1` 测试端点。HTTP client 禁止自动跟随重定向。

`DRIVE_IDENTITY_ALLOWED_REDIRECT_PATHS` 是回调后的站内路径 allowlist。完整 URL、scheme-relative URL、反斜杠和未登记路径应被拒绝，防止开放重定向。

同一 `tenant + issuer + subject` 只能绑定一个本地用户；同一用户对同一 provider 只能保留一个 link。关闭本地密码的用户解除最后一个 OIDC link 时返回 `OIDC_LAST_LOGIN_METHOD`。

### 4.4 登出

若 discovery 声明 `end_session_endpoint`，服务端返回 provider logout URL；无该端点时 `logout_url=null`。无论 provider 是否支持 RP logout，本地 session family 都会被吊销并清除 Cookie。

## 5. LDAP 只读目录同步

### 5.1 管理接口

- `GET /api/v1/admin/identity/ldap/sources`
- `POST /api/v1/admin/identity/ldap/sources`
- `PATCH /api/v1/admin/identity/ldap/sources/{source_id}`
- `POST /api/v1/admin/identity/ldap/sources/{source_id}/test`
- `POST /api/v1/admin/identity/ldap/sources/{source_id}/sync`
- `GET /api/v1/admin/identity/ldap/runs`
- `GET /api/v1/admin/identity/ldap/runs/{run_id}/conflicts`

Source 配置包括：

- `server_url`、`base_dn`、`bind_dn`、`bind_password_ref`；
- user/department/group base DN 与 filter；
- 属性映射；
- enabled、version、sync cursor、最近成功时间。

`bind_password_ref` 与 OIDC secret 一样只支持 `env:VARIABLE_NAME`。API 连接测试和 maintenance Worker 同步都需要解析该引用，因此两个容器必须注入同一真实值。

生产优先使用 `ldaps://` 并验证目录证书链。连接测试只证明当前配置可连接和 Base DN 可发现，不代表同步变更已经安全。

### 5.2 run 模式

| 模式 | 读取 | 核心写入 | 缺失处理 | cursor |
| --- | --- | --- | --- | --- |
| `dry_run` | 全量快照 | 不写 | 只统计 | 不前移 |
| `full` | 全量快照 | 写 | 处理当前 Source 中未出现的 LDAP 绑定 | 成功后前移 |
| `incremental` | 从已有 cursor 读取变化 | 写 | 只处理 adapter 明确返回的 tombstone/变化 | 成功后前移 |

同步 HTTP 请求只创建 queued run 并返回 202；`identity.sync_ldap` 在 maintenance Worker 中执行。run 记录固定 Source version，防止配置变化后使用不一致参数。

目录读取、分页和规范化在核心 apply 前完成。网络失败、凭据失败、分页不完整、重复 external ID 或快照引用不完整时，run 失败，不进入“未出现即离职”处理。

### 5.3 稳定映射与冲突

external ID 应使用 `entryUUID`、`objectGUID` 等稳定属性。映射建立后：

- DN 变化只更新诊断/属性，不创建新本地对象。
- 用户名、email、部门路径或组 slug 与未绑定本地对象冲突时记录 conflict。
- 不自动猜测或接管本地对象。
- LDAP 创建的用户关闭本地密码，使用随机不可用密码哈希，默认不是超级管理员。
- 当前 v0.8.0 由 LDAP Source 创建的绑定均标记为 `authoritative=true`；full 缺失处理按当前 Source 的绑定集合执行。

冲突类型包括：

- `username_conflict`
- `path_conflict`
- `slug_conflict`
- `local_object_missing`
- `last_super_admin`
- snapshot/external ID/membership 相关冲突

冲突不会让 run 整体伪装失败；run 统计 `conflicts`，管理员通过冲突接口查看明细。

### 5.4 禁用、离职和会话

- 目录显式 `enabled=false` 会停用对应用户/部门/组。
- full 模式中当前 Source 未出现的已绑定用户标记为 missing 并停用。
- 停用用户递增版本并吊销浏览器/桌面全部会话。
- 最后一个活动超级管理员保护继续生效；LDAP 不默认写入超级管理员权限。
- incremental 模式不会因为快照中未包含对象就推断离职。

### 5.5 成员关系

LDAP membership claim 与核心 `department_members` / `user_group_members` 边分离：

- claim 出现时确保核心成员边存在。
- 若核心边原本由管理员手工建立，relation 标记为非 LDAP 独占。
- claim 消失时先删除 claim。
- 只有核心边由 LDAP 管理且没有其他 Source claim 时才删除核心边。
- 手工成员关系不得因目录同步消失。

成员和组织状态变化继续触发租户权限版本、权限缓存失效和分享接收人重算语义。

## 6. 前端行为

### 用户端

- `CAPTCHA_REQUIRED` 时显示挑战 token 输入。
- `ACCOUNT_LOCKED` 时显示服务端 `locked_until`。
- OIDC provider 列表来自服务端，按钮跳转服务端生成的 authorization URL。
- OIDC callback 页面只刷新本项目 Cookie Session，不读取 provider token。
- `must_change_password` 时应用壳只显示改密和退出。
- 账号安全页显示密码策略、浏览器会话和 OIDC links。

### 管理端

- 账号安全页显示失败次数、锁定期限和强制改密状态。
- 解锁、密码重置都携带用户 `expected_version`。
- OIDC/LDAP 配置只显示 secret 是否已设置。
- LDAP 支持 dry-run/full/incremental 启动、run 状态/统计和 conflict 查看。

前端校验只改善体验；密码策略、版本前置条件、租户边界、管理员权限、CSRF 和 secret 不回显均由后端执行。

## 7. 审计、指标和告警

主要审计 action：

- `auth.login`
- `auth.account.locked`
- `auth.password.changed`
- `auth.session.revoked`
- `admin.user.password_reset`
- `admin.user.unlocked`
- `identity.oidc.provider.*`
- `identity.oidc.account.bound`
- `identity.oidc.account.unlinked`
- `identity.oidc.login`
- `identity.oidc.logout.started`
- `identity.ldap.source.*`
- `identity.ldap.sync.requested`
- `identity.ldap.sync.completed`

Prometheus 指标：

- `auth_security_events_total{event,outcome}`
- `identity_provider_operations_total{provider_type,operation,outcome}`
- `ldap_sync_runs_total{mode,outcome}`

告警：

- `EnterpriseDriveAccountLocksDetected`
- `EnterpriseDriveIdentityProviderFailures`
- `EnterpriseDriveLdapSyncFailures`

标签必须保持低基数；provider slug、tenant/user ID、external ID、DN、state、nonce、token、secret 和错误原文不能成为 label。

## 8. 错误码

常见账号错误：

- `AUTH_INVALID_CREDENTIALS`
- `RATE_LIMITED`
- `CAPTCHA_REQUIRED`
- `CAPTCHA_UNAVAILABLE`
- `ACCOUNT_LOCKED`
- `PASSWORD_CHANGE_REQUIRED`
- `PASSWORD_POLICY_VIOLATION`
- `PASSWORD_REUSE_NOT_ALLOWED`
- `CURRENT_PASSWORD_INVALID`
- `AUTH_SESSION_NOT_FOUND`

常见 OIDC 错误：

- `OIDC_PROVIDER_NOT_FOUND`
- `OIDC_STATE_INVALID`
- `OIDC_NONCE_INVALID`
- `OIDC_PROVIDER_ERROR`
- `OIDC_CODE_MISSING`
- `OIDC_ACCOUNT_NOT_LINKED`
- `OIDC_SUBJECT_ALREADY_BOUND`
- `OIDC_PROVIDER_ALREADY_BOUND`
- `OIDC_LAST_LOGIN_METHOD`
- `OIDC_ENDPOINT_INVALID`
- `OIDC_ISSUER_MISMATCH`
- `OIDC_DISCOVERY_FAILED`
- `OIDC_JWKS_FAILED`

常见身份 secret/LDAP 错误：

- `IDENTITY_SECRET_UNAVAILABLE`
- `IDENTITY_SECRET_REF_INVALID`
- `LDAP_SOURCE_NOT_FOUND`
- `LDAP_SOURCE_DISABLED`
- `LDAP_SYNC_ALREADY_RUNNING`
- `LDAP_SYNC_RUN_NOT_FOUND`
- `LDAP_CONNECTION_FAILED`
- `LDAP_CONNECTION_TEST_FAILED`
- `LDAP_SERVER_URL_INVALID`
- `LDAP_SEARCH_FAILED`
- `LDAP_ENTRY_INVALID`
- `LDAP_DUPLICATE_EXTERNAL_ID`
- `LDAP_ATTRIBUTE_MAPPING_INVALID`

错误响应不回显密码、provider token、client secret、bind password、state、nonce、code verifier 或目录凭据。

## 9. 验证

账号安全专项：

```powershell
Set-Location backend
uv run pytest tests/test_sprint11_account_security.py
```

OIDC/LDAP 专项：

```powershell
uv run pytest tests/test_identity_oidc.py tests/test_identity_ldap.py
```

受影响安全矩阵和契约：

```powershell
uv run pytest tests/test_route_security_matrix.py
uv run pytest tests/test_app.py tests/test_desktop_openapi_contract.py
```

前端：

```powershell
Set-Location frontend
npm run lint
npm run typecheck
npm run test:unit
npm run test:contract
npm run build
npm run api:check
```

数据库：

```powershell
Set-Location backend
uv run alembic upgrade head
uv run alembic downgrade 20260803_0023
uv run alembic upgrade 20260804_0024
```

只运行新增和受影响集合；Sprint 10、MinIO、备份恢复、性能和完整桌面历史集合在相关代码未变化时复用既有证据。

最终统计插槽：

- OpenAPI：105 paths / 134 operations / 162 schemas。
- 本地验证：账号安全 4 项与受影响回归 12 项、OIDC/LDAP 10 项、route matrix 134 条路由及 6 项集合校验、前端三浏览器 12 场景均通过；Ruff/format、Mypy、锁文件、OpenAPI/client、PostgreSQL migration、Compose config、Cargo metadata 和差异检查均通过。
- 提交：`e6b4f6d`。
- CI：run `30922718148` 成功；changes/backend 成功，7 个未受影响 job 按 scope 跳过。frontend 已在 run `30919983108` 成功，Rust/MinIO/Windows/安装包已在 run `30917345858` 成功。

## 10. 生产验收

代码侧门禁通过后，生产试点还必须完成：

1. 使用真实企业 OIDC provider 验证 discovery、JWKS、key rotation、PKCE、错误回调、绑定冲突、登录和 RP logout。
2. 使用真实 LDAPS 目录验证证书链、分页、超时、属性映射、dry-run、full、incremental、冲突、禁用和离职。
3. 确认 API 与 maintenance Worker 均能解析所需 `env:` secret，且管理响应、日志、审计、指标和诊断没有明文。
4. 验证账号锁定告警、provider failure 告警、LDAP sync failure 告警能到达真实 Alertmanager 接收端。
5. 执行跨租户、CSRF、开放重定向、state 重放、会话撤销和设备停止同步验收。
6. 保存 provider/目录配置版本、测试时间、变更审批、run ID、审计 ID 和回滚步骤。

真实身份源验收不替代既有 DNS/受信 TLS、MinIO 修复镜像、备份恢复和正式发布门禁。
