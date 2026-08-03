# ADR-0001：Rust 桌面端 Sprint 7 边界

- 状态：已接受
- 日期：2026-08-03
- 目标版本：`0.5.0`

## 决策

桌面端采用 Rust stable、Cargo workspace 和 Tauri 2，Windows 11 首发。Tauri 页面只负责展示和命令调用，以下事实必须由 Rust crate 持有：

- API client 与 `Authorization: Device <opaque token>`；
- Windows Credential Manager 凭据；
- SQLite 远端节点索引、同步游标、客户端操作日志和传输任务；
- DTP/1 预签名 HTTPS 上传下载、Range、SHA-256、暂停/继续/取消；
- 同步根配置与服务端增量变更消费；
- 脱敏诊断导出。

后端设备会话与浏览器 Cookie Session 独立。设备 token 仅存 hash，短期轮换；设备列表支持单设备和全设备吊销。桌面写请求使用 `X-Client-Operation-ID`，文件重命名、移动和删除携带当前 `version_id` 前置条件。

初次同步顺序固定为：

1. 获取与租户、用户、空间、同步根绑定的签名游标锚点；
2. 使用空间/目录 API 建立 SQLite 快照；
3. 从锚点继续消费增量变更；
4. tombstone、移出同步根和权限撤销均以服务端变更为准。

## 本地数据

SQLite 保存：

- 远端 node/version、父子关系、名称和权限版本；
- 同步根、游标和本地路径；
- 客户端操作 ID、请求状态和失败码；
- 上传下载任务、已确认分片、临时文件和字节进度。

SQLite 不保存设备 token、Cookie、文件正文或权限事实。异常退出后 `running` 任务恢复为 `paused`，由用户继续或取消。

## Sprint 7 与 Sprint 8 分界

Sprint 7 提供登录、空间/目录浏览、同步目录选择、离线元数据、单向上传下载队列、托盘和诊断导出。

以下内容保留到 Sprint 8：

- 文件系统实时监听；
- 本地变更自动上送；
- 双向状态机和离线操作重放；
- 冲突副本与删除/修改冲突；
- 签名更新清单和失败回退。

这样可先验证设备会话、游标、tombstone、版本前置条件和 DTP/1，不以高频全量扫描或界面状态替代同步协议。
