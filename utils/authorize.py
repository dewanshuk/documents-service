from db.models.helpdesk import User
from db.db_manager import db_manager

HELPDESK_ADMIN_FLAGS = (
    "is_master_admin",
    "is_query_lead",
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


RECORD_TYPE_LEAD_FLAG = {
    "query": "is_query_lead",
    "cobce": "is_cobce_coi_gift_lead",
    "coi": "is_cobce_coi_gift_lead",
}


def is_lead_for_type(user: dict, record_type: str) -> bool:
    """True only when the user has the type-specific lead flag (no master/CCO bypass)."""
    flag = RECORD_TYPE_LEAD_FLAG.get(record_type)
    return as_bool(user.get(flag)) if flag else False


ALL_HELPDESK_TYPES = {"Query", "Self Declaration"}

# Dashboard admin scope per lead/role flag only. CCO / master admin are not
# included — they see own records unless they also hold a matching lead flag.
# Annual Declaration is always own-scoped in dashboard_service.
DASHBOARD_ROLE_SECTIONS = {
    "is_policy_hub_admin": {"Self Declaration", "Query"},
    "is_query_lead": {"Query"},
    "is_cobce_coi_gift_lead": {"Self Declaration"},
}


def get_dashboard_type_scope(user: dict) -> tuple[set[str], set[str]]:
    """Return (visible_types, admin_types) for helpdesk dashboard sections.

    - visible_types: always ALL_HELPDESK_TYPES so every user keeps their own
      records across Query / Self Declaration.
    - admin_types: role-granted types where org-wide admin records are added
      on top of the user's own records; remaining types stay own-scoped.

    CCO / master admin / knowledge hub without a matching lead/role flag are
    treated as normal users (own records only). Users with none of the
    DASHBOARD_ROLE_SECTIONS flags see every section, own-scoped.
    """
    granted: set[str] = set()
    for flag, sections in DASHBOARD_ROLE_SECTIONS.items():
        if as_bool(user.get(flag)):
            granted |= sections

    return set(ALL_HELPDESK_TYPES), granted


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
