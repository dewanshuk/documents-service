from db.models.helpdesk import User
from db.db_manager import db_manager

async def is_active_query_lead(staff_id: str) -> bool:
    result = await db_manager.list(
        model=User,
        filters={
            "staff_id": staff_id,
            "status": "active",
            "is_query_lead": True,
        },
        limit=1,
        include_total=True
    )
    return result["total"] > 0

async def is_active_cobce_coi_gift_lead(staff_id:str) -> bool:
    result = await db_manager.list(
        model=User,
        filters={
            "staff_id": staff_id,
            "status": "active",
            "is_cobce_coi_gift_lead": True,
        },
        limit=1,
        include_total=True
    )
    return result["total"] > 0

async def is_active_complaint_lead(staff_id:str) -> bool:
    result = await db_manager.list(
        model=User,
        filters={
            "staff_id": staff_id,
            "status": "active",
            "is_complaint_lead": True,
        },
        limit=1,
        include_total=True
    )
    return result["total"] > 0

