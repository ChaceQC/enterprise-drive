from __future__ import annotations

ACTION_DELETE = "delete"
ACTION_DOWNLOAD = "download"
ACTION_GRANT = "grant"
ACTION_LIST = "list"
ACTION_MANAGE = "manage"
ACTION_PREVIEW = "preview"
ACTION_READ_META = "read_meta"
ACTION_RESTORE = "restore"
ACTION_SHARE = "share"
ACTION_UPDATE = "update"
ACTION_UPLOAD = "upload"

PERMISSION_ACTIONS = frozenset(
    {
        ACTION_DELETE,
        ACTION_DOWNLOAD,
        ACTION_GRANT,
        ACTION_LIST,
        ACTION_MANAGE,
        ACTION_PREVIEW,
        ACTION_READ_META,
        ACTION_RESTORE,
        ACTION_SHARE,
        ACTION_UPDATE,
        ACTION_UPLOAD,
    }
)
