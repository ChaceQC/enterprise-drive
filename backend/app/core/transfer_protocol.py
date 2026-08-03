from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

DRIVE_TRANSFER_PROTOCOL_HEADER = "X-Drive-Transfer-Protocol"
DRIVE_TRANSFER_PROTOCOL_V1: Literal["DTP/1"] = "DTP/1"


class DriveTransferProtocolResponse(BaseModel):
    protocol_version: Literal["DTP/1"] = DRIVE_TRANSFER_PROTOCOL_V1
    client_operation_id: str | None = None
