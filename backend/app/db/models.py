from __future__ import annotations

from app.modules.audit import models as audit_models
from app.modules.auth import models as auth_models
from app.modules.file import models as file_models
from app.modules.org import models as org_models
from app.modules.permission import models as permission_models
from app.modules.quota import models as quota_models
from app.modules.space import models as space_models
from app.modules.upload import models as upload_models

__all__ = [
    "audit_models",
    "auth_models",
    "file_models",
    "org_models",
    "permission_models",
    "quota_models",
    "space_models",
    "upload_models",
]
