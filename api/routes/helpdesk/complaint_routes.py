from fastapi import UploadFile, File, Form, APIRouter, Depends
from typing import List
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo
from utils.deps import get_current_user
from db.db_manager import db_manager
from db.models.helpdesk import Complaints
from db.validators.comp_help import QueryType
from storage.storage_ops import upload_files, init_json
from utils.helpers import validate_word_limit
from .route_utils import log_and_json_response

router = APIRouter()

# Complaint endpoints for raising complaints.

@router.post("/complaint")
async def raise_complaint(
    complaintType: QueryType = Form(...),
    complaintDetails: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Raise a new complaint with optional supporting files."""
    try:
        if len(files) > 6:
            return log_and_json_response(
                user["staff_id"],
                {"complaintType": complaintType.value, "complaintDetails": complaintDetails},
                "/complaint",
                "POST",
                400,
                {"error": "Max 6 files allowed"},
            )

        try:
            validate_word_limit(complaintDetails, 500)
        except ValueError as e:
            return log_and_json_response(
                user["staff_id"],
                {"complaintType": complaintType.value, "complaintDetails": complaintDetails},
                "/complaint",
                "POST",
                400,
                {"error": str(e)},
            )

        complaint_id = f"CMP-{uuid4()}"
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        file_paths = await upload_files(complaint_id, "user", files)

        json_data = {
            "id": complaint_id,
            "conversation": [
                {
                    "actor": "User",
                    "actorId": user["staff_id"],
                    "dateTime": now.isoformat(),
                    "data": {
                        "complaintType": complaintType.value,
                        "complaintDetails": complaintDetails,
                    },
                    "files": file_paths,
                }
            ],
        }

        json_path = await init_json(complaint_id, json_data)

        await db_manager.create(
            Complaints,
            {
                "ComplaintId": complaint_id,
                "ComplaintType": complaintType.value,
                "ComplaintDetails": complaintDetails,
                "CreatedOn": now,
                "CreatedBy": user["staff_id"],
                "OverallStatus": "Pending",
                "PendingAt": 1,
                "ResponseJsonPath": json_path,
            },
        )

        return log_and_json_response(
            user["staff_id"],
            {"complaint_id": complaint_id},
            "/complaint",
            "POST",
            201,
            {"details": f"Complaint has been created with complaint_id: {complaint_id}", "status": "Pending"},
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"complaintType": complaintType.value, "complaintDetails": complaintDetails},
            "/complaint",
            "POST",
            500,
            {"error": "Error creating complaint", "details": str(e)},
        )
