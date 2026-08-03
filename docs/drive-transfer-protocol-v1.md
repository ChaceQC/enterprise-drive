# Drive Transfer Protocol v1

状态：Accepted

线协议标识：`DTP/1`

生效日期：2026-07-31

## 1. 定位

Drive Transfer Protocol v1（DTP/1）是企业网盘在 HTTPS 之上的应用层文件传输契约。它定义：

- 上传初始化、秒传和 multipart 模式选择。
- 分片大小、分片编号、断点状态和签名有效期。
- 分片上传、完成、取消和幂等结果。
- 整文件大小与 SHA-256 完整性校验。
- 预签名下载和 HTTP Range 使用方式。
- 协议版本协商、错误码和兼容性规则。

DTP/1 不定义新的 TCP、UDP、TLS、QUIC、加密算法或可靠传输实现。控制面继续使用 FastAPI HTTPS API；普通文件正文通过短期预签名 HTTPS URL 直接访问 MinIO/S3，高密级或强审计场景由同一 HTTPS API 提供受控流式代理。

## 2. 规范用语

本文中的“必须”“禁止”“应”“可以”分别表示强制要求、强制禁止、推荐要求和可选能力。

## 3. 分层

### 3.1 控制面

控制面负责身份、权限、容量、审计和传输状态：

| 操作 | 当前接口 |
| --- | --- |
| 初始化上传或秒传 | `POST /api/v1/uploads/init` |
| 查询上传断点 | `GET /api/v1/uploads/{session_id}` |
| 获取单个分片签名 | `POST /api/v1/uploads/{session_id}/parts/{part_no}/presign` |
| 批量获取分片签名 | `POST /api/v1/uploads/{session_id}/parts/presign` |
| 确认服务端可见分片 | `POST /api/v1/uploads/{session_id}/parts/{part_no}/confirm` |
| 完成上传 | `POST /api/v1/uploads/{session_id}/complete` |
| 取消上传 | `POST /api/v1/uploads/{session_id}/abort` |
| 获取文件下载签名 | `GET /api/v1/files/{node_id}/download` |
| 获取指定历史版本下载签名 | `GET /api/v1/files/{node_id}/versions/{version_id}/download` |
| 受控代理下载 | `GET /api/v1/files/{node_id}/content` |
| 获取外链下载签名 | `POST /api/v1/public/shares/download` |

控制面请求不得携带大文件正文。

### 3.2 数据面

数据面使用以下两种 HTTPS 路径：

- 上传：客户端对预签名 URL 执行分片 `PUT`。
- 普通下载：客户端对预签名 URL 执行 `GET`，需要续传或并行读取时使用标准 `Range` 请求头。
- 受控下载：客户端直接请求 `/api/v1/files/{node_id}/content`，服务端重新检查权限并代理单段 Range。
- 客户端不得修改已签名的 bucket、object key、upload ID、part number 或签名查询参数。
- 签名过期后必须重新向控制面申请，不得长期缓存。

## 4. 版本协商

实现 DTP/1 的客户端应发送：

```http
X-Drive-Transfer-Protocol: DTP/1
```

为兼容已有 Web/API 调用，当前服务端允许省略该请求头；省略时按 `DTP/1` 处理。

全部上传响应、当前/历史版本文件下载签名响应和外链下载签名响应必须返回：

```json
{
  "protocol_version": "DTP/1"
}
```

代理下载返回二进制流，并通过响应头返回：

```http
X-Drive-Transfer-Protocol: DTP/1
Accept-Ranges: bytes
```

客户端声明未知版本时，服务端返回 HTTP `426`：

```json
{
  "code": "TRANSFER_PROTOCOL_UNSUPPORTED",
  "details": {
    "requested": "DTP/2",
    "supported": ["DTP/1"]
  }
}
```

同一主版本内只允许增加向后兼容字段或可选能力。删除字段、改变状态语义、改变校验规则或使既有请求失效时必须发布新协议版本。

## 5. 上传状态机

```text
init
  ├─ instant ───────────────> completed
  └─ multipart
       initiated -> uploading -> completing -> completed
             └───────────────> aborted
             └───────────────> expired
             └───────────────> failed
```

终态包括：

- `completed`
- `aborted`
- `expired`
- `failed`

终态会话禁止继续签发上传分片。重复 complete 或 abort 必须返回已有终态结果，不得重复创建版本或重复扣减容量。

## 6. 初始化

客户端提交：

- 目标空间和父目录。
- 文件展示名。
- 文件总字节数。
- `sha256` 内容哈希。
- 可选 MIME。
- 冲突策略。

服务端必须重新校验：

- 当前用户和节点级 `upload` 权限。
- 文件名和同目录冲突。
- 空间容量。
- hash 算法与格式。
- 同租户可复用 blob 状态。

### 6.1 秒传模式

命中同租户、同算法、同 hash、同大小且状态为 `active` 的 blob 时，服务端可以返回 `mode=instant`，但仍必须：

- 创建新的文件节点和版本。
- 增加 blob 引用计数。
- 扣减或预留容量。
- 写入审计、搜索和预览事件。

### 6.2 Multipart 模式

未命中可复用 blob 时，服务端返回：

- `session_id`
- `part_size_bytes`
- `total_parts`
- `max_parallelism`
- `checksum_algorithm=sha256`
- `expires_at`
- `protocol_version`
- `client_operation_id`

`part_size_bytes` 和 `total_parts` 由服务端决定，客户端不得自行改变同一会话的分片边界。

## 7. 分片上传与断点恢复

1. 客户端先查询上传状态，取得服务端确认的 `uploaded_parts`。
2. 只为缺失分片申请预签名 URL；单次批量签名最多 32 个分片。
3. 按服务端返回的 `part_size_bytes` 切分文件。
4. 每个分片 PUT 成功后调用确认接口，提交 ETag 和实际分片字节数；只有对象存储 stat 与会话边界一致的分片才进入 `uploaded_parts`。
5. 每个分片失败时仅重试该分片，并遵守错误中的 `retry_after_seconds`。
6. 签名过期时重新申请签名，不重新创建上传会话。
7. 客户端退出前把本地文件标识、session ID、分片大小和已确认状态写入 Rust 本地传输队列；本地记录不是服务端完成状态的事实来源。

客户端可以并行上传多个分片，但必须支持：

- 用户配置的并发限制。
- 带宽限制。
- 暂停、继续和取消。
- 指数退避与抖动。
- 文件在传输期间发生变化时停止 complete。

首个 Rust 客户端应从保守并发开始，并依据真实 PostgreSQL、MinIO、磁盘、网关和网络基准调整；协议不把固定并发数写死。
服务端通过 `max_parallelism` 返回当前并发上限提示，客户端可以使用更低值，但不得超过该提示。

## 8. Complete

客户端提交全部分片的：

- `part_no`
- `etag`
- 可选 `size_bytes`

服务端必须：

1. 校验分片编号完整、唯一且范围正确。
2. 合并对象存储 multipart upload。
3. 校验最终对象大小。
4. 服务端读取最终内容并计算整文件 SHA-256。
5. 只有大小和 hash 均匹配时才能创建 blob、node、version 和容量流水。
6. complete 结果必须幂等。
7. 对象已归档但数据库失败时由补偿和孤儿对象治理处理。

Multipart ETag 只作为对象存储分片完成参数，禁止把它当作整文件 MD5 或 DTP/1 完整性依据。

## 9. 下载

下载控制面返回：

- `node_id`
- `version_id`
- 文件名
- 字节数
- `hash_algo`
- `content_hash`
- MIME
- 短期 `download_url`
- `expires_at`
- 必要请求头
- `protocol_version`

当前版本使用 `/api/v1/files/{node_id}/download`；指定不可变历史版本使用 `/api/v1/files/{node_id}/versions/{version_id}/download`。两个入口都重新检查节点级 `download` 权限和 active blob 状态，历史版本入口不得因为该版本不是 `current_version_id` 而拒绝。版本回滚属于控制操作：服务端创建引用目标历史内容的新版本并更新当前指针，禁止改写或复用原历史版本 ID。

Rust 客户端必须：

1. 下载到同目录随机临时文件。
2. 支持 HTTP Range 续传。
3. 完成后校验长度和 SHA-256。
4. 校验成功后原子替换目标文件。
5. 目标版本变化、权限撤销或签名过期时重新进入控制面，不继续使用旧 URL。

普通文件继续使用预签名直连。高密级或强审计场景可使用 `/api/v1/files/{node_id}/content`：无 Range 返回 HTTP 200，合法单段 Range 返回 HTTP 206，并返回 `Content-Range`、`Content-Length`、ETag 和 UTF-8 文件名。多段、不可满足或超过服务端单段上限的 Range 返回 HTTP 416；水印、密级标签自动强制代理和内容 DLP 仍由后续策略接入。

## 10. 错误处理

DTP/1 客户端至少识别：

- `TRANSFER_PROTOCOL_UNSUPPORTED`
- `AUTH_REQUIRED`
- `CSRF_INVALID`
- `RATE_LIMITED`
- `DOWNLOAD_PROXY_DISABLED`
- `DOWNLOAD_RANGE_INVALID`
- `DOWNLOAD_RANGE_TOO_LARGE`
- `SPACE_NOT_FOUND`
- `PARENT_NOT_FOUND`
- `NODE_NOT_FOUND`
- `NODE_NAME_EXISTS`
- `FILE_VERSION_NOT_FOUND`
- `FILE_VERSION_CONFLICT`
- `QUOTA_EXCEEDED`
- `BLOB_DELETING`
- `UPLOAD_SESSION_NOT_FOUND`
- `UPLOAD_SESSION_EXPIRED`
- `UPLOAD_NOT_ACTIVE`
- `UPLOAD_PART_INVALID`
- `UPLOAD_PART_MISSING`
- `UPLOAD_HASH_MISMATCH`

未知错误码必须按可重试性保守处理，不得默认 complete 成功。HTTP 401/403/404、409、410、422、426、429 和 5xx 应保留各自语义。

## 11. 安全边界

- DTP/1 只运行于 HTTPS。
- 原始 session、Cookie、token、预签名 URL 和对象 key 禁止写入普通日志或诊断包。
- 对象存储 bucket 必须保持私有。
- 文件名只保存在元数据中，不进入最终对象 key。
- 服务端权限、容量、审计和 hash 校验不得由客户端状态替代。
- 客户端不得把分片成功等同于文件完成，只有 complete 响应为最终上传结果。

## 12. 当前实现与后续能力

| 能力 | 状态 |
| --- | --- |
| `DTP/1` 请求头协商 | 已实现 |
| 响应 `protocol_version` | 已实现 |
| 秒传、multipart、状态查询、单分片签名 | 已实现 |
| 幂等 complete、abort、服务端 SHA-256 | 已实现 |
| 预签名 HTTPS 下载 | 已实现 |
| 指定历史版本 DTP/1 预签名下载 | 已实现 |
| 受控流式代理与单段 HTTP Range | 已实现 |
| 批量分片签名 | `DC-006` 实现 |
| 服务端并发/带宽提示 | `DC-006` 实现 |
| Rust 持久化传输队列 | `DC-006` 实现 |
| HTTP/2、HTTP/3 透明承载与回退验证 | `BE-029` / `DC-006` 基准后决定 |
| 密级标签自动强制代理、水印或内容 DLP | 后续治理策略实现 |

## 13. 验收

DTP/1 首个桌面实现至少通过：

- 1 GB 文件上传、暂停、进程退出、恢复和完成。
- 只重传失败分片。
- 签名过期后重新签名继续。
- complete 重复调用只创建一个版本。
- 上传期间本地文件变化时拒绝完成。
- Range 下载中断后恢复。
- 下载完成后长度和 SHA-256 一致。
- 不支持的协议版本返回 HTTP 426。
- 权限撤销、容量不足、限流和会话过期形成明确状态。
