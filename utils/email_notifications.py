"""Fire-and-forget email notification helpers for compliance events.

Each public function fetches recipients, builds the HTML, and sends the
email.  Call them with ``asyncio.create_task(notify_...)`` so the HTTP
response is not delayed.
"""

import logging
from db.db_manager import db_manager

from utils.email_manager import send_email
from utils.email_templates import (
    record_created,
    record_assigned,
    record_responded,
    record_closed,
    annual_declaration_assigned,
)


RECORD_TYPE_LABELS = {
    "query": "Query",
    "complaint": "Complaint",
    "gift": "Gift Declaration",
    "cobce": "Self Declaration (COBCE)",
    "coi": "Self Declaration (COI)",
    "r518": "Self Declaration (R5.18)",
}

LEAD_FLAG_FOR_TYPE = {
    "query": "is_query_lead",
    "complaint": "is_complaint_lead",
    "gift": "is_cobce_coi_gift_lead",
    "cobce": "is_cobce_coi_gift_lead",
    "coi": "is_cobce_coi_gift_lead",
    "r518": "is_cobce_coi_gift_lead",
}


async def _get_user_details(staff_id: str) -> dict:
    rows = await db_manager.raw(
        """
        SELECT staff_id, username, email,
               department, division, organization_vertical
        FROM users.users
        WHERE staff_id = :sid
        """,
        {"sid": staff_id},
    )
    if rows:
        r = rows[0]
        return {
            "staff_id": r["staff_id"],
            "name": r.get("username") or r["staff_id"],
            "email": r.get("email", ""),
            "department": r.get("department") or "",
            "division": r.get("division") or "",
            "vertical": r.get("organization_vertical") or "",
        }
    return {
        "staff_id": staff_id,
        "name": staff_id,
        "email": "",
        "department": "",
        "division": "",
        "vertical": "",
    }


async def _get_lead_staff_ids(record_type: str) -> list[str]:
    flag = LEAD_FLAG_FOR_TYPE.get(record_type)
    if not flag:
        return []
    rows = await db_manager.raw(
        f"""
        SELECT staff_id
        FROM users.users
        WHERE status = 'active' AND {flag} = true
        """,
    )
    return [r["staff_id"] for r in rows]


# =====================================================
# RECORD CREATED
# =====================================================

async def notify_record_created(
    record_type: str,
    record_id: str,
    creator_staff_id: str,
    title: str = "",
) -> None:
    try:
        label = RECORD_TYPE_LABELS.get(record_type, record_type)
        user = await _get_user_details(creator_staff_id)
        leads = await _get_lead_staff_ids(record_type)

        html = record_created(
            record_type=label,
            record_id=record_id,
            requester_name=user["name"],
            requester_staff_id=user["staff_id"],
            requester_vertical=user["vertical"],
            requester_division=user["division"],
            requester_department=user["department"],
            title_text=title,
            raw_record_type=record_type,
        )

        recipients = list(
            dict.fromkeys([creator_staff_id] + leads)
        )

        await send_email(
            recipients=recipients,
            subject=f"New {label} Created — {record_id}",
            html_body=html,
        )
    except Exception:
        logging.exception(
            "notify_record_created failed for %s", record_id
        )


# =====================================================
# RECORD ASSIGNED
# =====================================================

async def notify_record_assigned(
    record_type: str,
    record_id: str,
    assigned_to_staff_id: str,
    assigned_by_staff_id: str,
    creator_staff_id: str,
    title: str = "",
) -> None:
    try:
        label = RECORD_TYPE_LABELS.get(record_type, record_type)
        creator = await _get_user_details(creator_staff_id)
        assignee = await _get_user_details(assigned_to_staff_id)

        html = record_assigned(
            record_type=label,
            record_id=record_id,
            assigned_to_name=assignee["name"],
            requester_name=creator["name"],
            requester_staff_id=creator["staff_id"],
            requester_vertical=creator["vertical"],
            requester_division=creator["division"],
            requester_department=creator["department"],
            title_text=title,
            raw_record_type=record_type,
        )

        await send_email(
            recipients=[assigned_to_staff_id],
            subject=f"{label} Assigned — {record_id}",
            html_body=html,
            cc=[assigned_by_staff_id],
        )
    except Exception:
        logging.exception(
            "notify_record_assigned failed for %s", record_id
        )


# =====================================================
# RECORD RESPONDED
# =====================================================

async def notify_record_responded(
    record_type: str,
    record_id: str,
    responder_staff_id: str,
    creator_staff_id: str,
    title: str = "",
    response_text: str = "",
) -> None:
    try:
        label = RECORD_TYPE_LABELS.get(record_type, record_type)
        creator = await _get_user_details(creator_staff_id)
        responder = await _get_user_details(responder_staff_id)

        html = record_responded(
            record_type=label,
            record_id=record_id,
            responder_name=responder["name"],
            requester_name=creator["name"],
            requester_staff_id=creator["staff_id"],
            requester_vertical=creator["vertical"],
            requester_division=creator["division"],
            requester_department=creator["department"],
            title_text=title,
            response_text=response_text,
            raw_record_type=record_type,
        )

        recipients = list(
            dict.fromkeys([creator_staff_id, responder_staff_id])
        )

        await send_email(
            recipients=recipients,
            subject=f"{label} Response — {record_id}",
            html_body=html,
        )
    except Exception:
        logging.exception(
            "notify_record_responded failed for %s", record_id
        )


# =====================================================
# RECORD CLOSED
# =====================================================

async def notify_record_closed(
    record_type: str,
    record_id: str,
    closed_by_staff_id: str,
    creator_staff_id: str,
    title: str = "",
) -> None:
    try:
        label = RECORD_TYPE_LABELS.get(record_type, record_type)
        creator = await _get_user_details(creator_staff_id)
        closer = await _get_user_details(closed_by_staff_id)

        html = record_closed(
            record_type=label,
            record_id=record_id,
            closed_by_name=closer["name"],
            requester_name=creator["name"],
            requester_staff_id=creator["staff_id"],
            requester_vertical=creator["vertical"],
            requester_division=creator["division"],
            requester_department=creator["department"],
            title_text=title,
            raw_record_type=record_type,
        )

        recipients = list(
            dict.fromkeys([creator_staff_id, closed_by_staff_id])
        )

        await send_email(
            recipients=recipients,
            subject=f"{label} Closed — {record_id}",
            html_body=html,
        )
    except Exception:
        logging.exception(
            "notify_record_closed failed for %s", record_id
        )


# =====================================================
# ANNUAL DECLARATION — USERS ASSIGNED
# =====================================================

async def notify_annual_declaration_users(
    declaration_id: str,
    declaration_name: str,
    financial_year: str,
    due_date: str,
) -> None:
    try:
        rows = await db_manager.raw(
            """
            SELECT uds.staff_id
            FROM annual_declarations.user_declaration_status uds
            WHERE uds.declaration_id = :did
              AND uds.notify = true
            """,
            {"did": declaration_id},
        )

        staff_ids = [r["staff_id"] for r in rows]
        if not staff_ids:
            return

        for staff_id in staff_ids:
            try:
                user = await _get_user_details(staff_id)
                html = annual_declaration_assigned(
                    declaration_name=declaration_name,
                    financial_year=financial_year,
                    due_date=due_date,
                    employee_name=user["name"],
                    employee_staff_id=user["staff_id"],
                )
                await send_email(
                    recipients=[staff_id],
                    subject=(
                        f"Annual Declaration Assigned — "
                        f"{declaration_name} ({financial_year})"
                    ),
                    html_body=html,
                )
            except Exception:
                logging.exception(
                    "Failed to email %s for declaration %s",
                    staff_id, declaration_id,
                )
    except Exception:
        logging.exception(
            "notify_annual_declaration_users failed for %s",
            declaration_id,
        )
