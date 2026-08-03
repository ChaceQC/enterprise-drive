from __future__ import annotations

from app.modules.admin import models as admin_models
from app.modules.audit import models as audit_models
from app.modules.auth import models as auth_models
from app.modules.device import models as device_models
from app.modules.file import models as file_models
from app.modules.file_security import models as file_security_models
from app.modules.org import models as org_models
from app.modules.permission import models as permission_models
from app.modules.preview import models as preview_models
from app.modules.quota import models as quota_models
from app.modules.share import models as share_models
from app.modules.space import models as space_models
from app.modules.sync import models as sync_models
from app.modules.upload import models as upload_models

__all__ = [
    "admin_models",
    "audit_models",
    "auth_models",
    "device_models",
    "file_models",
    "file_security_models",
    "org_models",
    "permission_models",
    "preview_models",
    "quota_models",
    "share_models",
    "space_models",
    "sync_models",
    "upload_models",
]
