from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.openapi_tags import TAG_RECENT_ACTIVITY
from services.recent_records_service import get_recent_records, log_recent_record
from utils.deps import get_current_user
from .route_utils import log_and_json_response

router = APIRouter(tags=[TAG_RECENT_ACTIVITY])


class RecentRecordLog(BaseModel):
    record_id: str
    record_type: str
    title: str
    status: str
    created_on: datetime
    sub_type: Optional[str] = None
    pending_at: Optional[str] = None


@router.get("/recent-activity")
async def recent_activity(user: dict = Depends(get_current_user)):
    """Get the top 5 recently accessed records for the current user."""
    try:
        records = await get_recent_records(user["staff_id"])
        data = [
            {
                "type": r.record_type,
                "name": r.title,
                "sub_type": r.sub_type,
                "id": r.record_id,
                "status": r.status,
                "created_on": r.created_on.isoformat() if r.created_on else None,
                "pending_at": r.pending_at,
                "last_accessed_on": (
                    r.last_accessed_on.isoformat() if r.last_accessed_on else None
                ),
            }
            for r in records
        ]
        return JSONResponse(content={"data": data}, status_code=200)
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {},
            "/recent-activity",
            "GET",
            500,
            {"error": "Error loading recent activity", "details": str(e)},
        )


@router.post("/recent-activity")
async def log_recent_activity(
    payload: RecentRecordLog,
    user: dict = Depends(get_current_user),
):
    """Manually log a record as recently accessed."""
    try:
        await log_recent_record(
            user_id=user["staff_id"],
            record_id=payload.record_id,
            record_type=payload.record_type,
            title=payload.title,
            status=payload.status,
            created_on=payload.created_on,
            sub_type=payload.sub_type,
            pending_at=payload.pending_at,
        )
        return JSONResponse(content={"status": "success"}, status_code=200)
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            payload.model_dump(),
            "/recent-activity",
            "POST",
            500,
            {"error": "Error logging recent activity", "details": str(e)},
        )
