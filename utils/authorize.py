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


ALL_HELPDESK_TYPES = {"Query", "Complaint", "Gift Declaration", "Self Declaration"}

# Dashboard section visibility per lead/role flag (Annual Declaration is excluded
# here: its own visibility rules are handled separately in dashboard_service, based
# on is_master_admin / is_cheif_compliance_officer).
DASHBOARD_ROLE_SECTIONS = {
    "is_cheif_compliance_officer": ALL_HELPDESK_TYPES,
    "is_policy_hub_admin": {"Self Declaration", "Complaint", "Query"},
    "is_query_lead": {"Query"},
    "is_complaint_lead": {"Complaint"},
    "is_cobce_coi_gift_lead": {"Self Declaration", "Gift Declaration"},
}


def get_dashboard_type_scope(user: dict) -> tuple[set[str], set[str]]:
    """Return (visible_types, admin_types) for helpdesk dashboard sections.

    - visible_types: which of ALL_HELPDESK_TYPES should appear for this user.
    - admin_types: subset of visible_types where records are shown org-wide
      (all staff); the remaining visible types are scoped to the user's own records.

    is_master_admin / is_knowledge_hub_admin keep full unrestricted access (unaffected
    by the new role-based scoping). Users with none of the DASHBOARD_ROLE_SECTIONS
    flags see every section, scoped to their own records only.
    """
    if as_bool(user.get("is_master_admin")) or as_bool(user.get("is_knowledge_hub_admin")):
        return set(ALL_HELPDESK_TYPES), set(ALL_HELPDESK_TYPES)

    granted: set[str] = set()
    for flag, sections in DASHBOARD_ROLE_SECTIONS.items():
        if as_bool(user.get(flag)):
            granted |= sections

    if granted:
        return granted, granted

    return set(ALL_HELPDESK_TYPES), set()


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

