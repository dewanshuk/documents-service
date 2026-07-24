import asyncio

from fastapi import UploadFile, File, Form, APIRouter, Depends
from typing import List

from utils.deps import get_current_user
from utils.helpers import now_ist, db_timestamp_now
from utils.record_ids import next_gift_id
from utils.email_notifications import notify_record_created
from db.db_manager import db_manager
from db.models.helpdesk import GiftDeclarations
from storage.storage_ops import upload_files, init_json
from .route_utils import log_and_json_response

from core.openapi_tags import TAG_GIFT

router = APIRouter(tags=[TAG_GIFT])

# Gift declaration endpoints for raising gift declarations.

@router.post("/gift")
async def raise_gift(
    status: str = Form(...),
    person: str = Form(...),
    organization: str = Form(...),
    approxValueINR: float = Form(...),
    portalApprovalTaken: str = Form(...),
    portalNumber: str = Form(None),
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Raise a gift declaration, optionally including approval portal details and files."""
    try:
        if portalApprovalTaken.lower() == "yes" and not portalNumber:
            return log_and_json_response(
                user["staff_id"],
                {
                    "status": status,
                    "person": person,
                    "organization": organization,
                },
                "/gift",
                "POST",
                400,
                {"error": "Portal number required if approval taken"},
            )

        if len(files) > 6:
            return log_and_json_response(
                user["staff_id"],
                {"status": status, "person": person, "organization": organization},
                "/gift",
                "POST",
                400,
                {"error": "Max 6 files allowed"},
            )

        staff_id = user["staff_id"]
        gift_id = await next_gift_id(staff_id)
        now = now_ist()
        created_on = db_timestamp_now()
        file_paths = await upload_files(gift_id, "user", files)

        json_data = {
            "id": gift_id,
            "conversation": [
                {
                    "actor": "User",
                    "actorId": staff_id,
                    "dateTime": now.isoformat(),
                    "data": {
                        "status": status,
                        "person": person,
                        "organization": organization,
                        "approxValueINR": approxValueINR,
                        "portalApprovalTaken": portalApprovalTaken,
                        "portalNumber": portalNumber,
                    },
                    "files": file_paths,
                }
            ],
        }

        json_path = await init_json(gift_id, json_data)

        await db_manager.create(
            GiftDeclarations,
            {
                "GiftId": gift_id,
                "Status": status,
                "Person": person,
                "Organization": organization,
                "ApproxValueINR": approxValueINR,
                "PortalApprovalTaken": portalApprovalTaken,
                "PortalNumber": portalNumber,
                "CreatedOn": created_on,
                "CreatedBy": staff_id,
                "OverallStatus": "Pending",
                "PendingAt": 1,
                "ResponseJsonPath": json_path,
            },
        )

        asyncio.create_task(notify_record_created(
            "gift", gift_id, staff_id,
        ))

        return log_and_json_response(
            staff_id,
            {"gift_id": gift_id},
            "/gift",
            "POST",
            201,
            {
                "details": f"Gift declaration created with id: {gift_id}",
                "status": "Pending",
                "gift_id": gift_id,
            },
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"status": status, "person": person, "organization": organization},
            "/gift",
            "POST",
            500,
            {"error": "Error creating gift declaration", "details": str(e)},
        )
