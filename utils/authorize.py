from db.models.helpdesk import User
from db.db_manager import db_manager

HELPDESK_ADMIN_FLAGS = (
    "is_master_admin",
    "is_query_lead",
    "is_complaint_lead",
    "is_cobce_coi_gift_lead",
    "is_knowledge_hub_admin",
    "is_cheif_compliance_officer",
)


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if isinstance(value, (int, float)):
        return value == 1
    return False


def is_helpdesk_admin_from_user(user: dict) -> bool:
    return any(as_bool(user.get(flag, False)) for flag in HELPDESK_ADMIN_FLAGS)


def is_active_helpdesk_admin(user: User) -> bool:
    if user.status != "active":
        return False
    return any(getattr(user, flag, False) for flag in HELPDESK_ADMIN_FLAGS)


async def is_helpdesk_admin(user: dict) -> bool:
    if is_helpdesk_admin_from_user(user):
        return True

    staff_id = user.get("staff_id")
    if not staff_id:
        return False

    db_user = await db_manager.get(User, staff_id)
    if not db_user:
        return False
    return is_active_helpdesk_admin(db_user)


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

