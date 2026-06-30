from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GlobalStatsResponse(BaseModel):
    total_programs: int
    active_programs: int
    inactive_programs: int
    running_scans: int
    pending_scans: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_programs": 12,
                "active_programs": 9,
                "inactive_programs": 3,
                "running_scans": 2,
                "pending_scans": 1,
            }
        },
    )
