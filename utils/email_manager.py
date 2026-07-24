import logging
import asyncio
from azure.communication.email import EmailClient
from core.constants import GENERIC_EMAIL
from db.db_manager import db_manager
from utils.azure_secrets import get_secret_sync


# =====================================================
# INITIALIZE ONCE
# =====================================================

ACS_CONNECTION_STRING = get_secret_sync(
    "ACS-CONNECTION-STRING"
)

SENDER_EMAIL = GENERIC_EMAIL

EMAIL_CLIENT = EmailClient.from_connection_string(
    ACS_CONNECTION_STRING
)



async def send_email(
    recipients: list[str],
    subject: str,
    html_body: str,
    cc: list[str] | None = None,
) -> dict:
    """
    Recipients can contain:
    - Staff IDs
    - Email IDs

    If a staff ID is not found in DB,
    fallback email will be:
        {staff_id}@abc.com
    """

    try:
        # ==========================================
        # NORMALIZE INPUT
        # ==========================================

        normalized = []

        for recipient in recipients:

            if not recipient:
                continue

            if isinstance(recipient, (list, tuple, set)):
                normalized.extend(
                    str(r).strip()
                    for r in recipient
                    if r
                )
            else:
                normalized.append(
                    str(recipient).strip()
                )

        normalized = list(dict.fromkeys(normalized))

        direct_emails = []
        staff_ids = []

        for recipient in normalized:

            if "@" in recipient:
                direct_emails.append(recipient.lower())
            else:
                staff_ids.append(recipient)

        resolved_recipients = direct_emails.copy()

        # ==========================================
        # RESOLVE STAFF IDS IN ONE QUERY
        # ==========================================

        if staff_ids:

            placeholders = ", ".join(
                f":staff_id_{idx}"
                for idx in range(len(staff_ids))
            )

            sql = f"""
                SELECT
                    staff_id,
                    email
                FROM users.users
                WHERE staff_id IN ({placeholders})
            """

            params = {
                f"staff_id_{idx}": staff_id
                for idx, staff_id in enumerate(staff_ids)
            }

            rows = await db_manager.raw(
                sql,
                params
            )

            email_map = {
                row["staff_id"]: row["email"]
                for row in rows
                if row.get("email")
            }

            for staff_id in staff_ids:

                resolved_recipients.append(
                    email_map.get(
                        staff_id,
                        f"{staff_id}@abc.com"
                    )
                )

        # ==========================================
        # REMOVE DUPLICATES
        # ==========================================

        resolved_recipients = list(
            dict.fromkeys(resolved_recipients)
        )

        if not resolved_recipients:

            return {
                "success": False,
                "error": "No valid recipients found"
            }

        # ==========================================
        # RESOLVE CC
        # ==========================================

        resolved_cc = []

        if cc:
            cc_normalized = []
            for r in cc:
                if r:
                    cc_normalized.append(str(r).strip())

            cc_emails = [
                e.lower() for e in cc_normalized if "@" in e
            ]
            cc_staff = [
                e for e in cc_normalized if "@" not in e
            ]

            resolved_cc = cc_emails.copy()

            if cc_staff:
                cc_placeholders = ", ".join(
                    f":cc_{i}" for i in range(len(cc_staff))
                )
                cc_sql = f"""
                    SELECT staff_id, email
                    FROM users.users
                    WHERE staff_id IN ({cc_placeholders})
                """
                cc_params = {
                    f"cc_{i}": sid
                    for i, sid in enumerate(cc_staff)
                }
                cc_rows = await db_manager.raw(
                    cc_sql, cc_params
                )
                cc_map = {
                    r["staff_id"]: r["email"]
                    for r in cc_rows if r.get("email")
                }
                for sid in cc_staff:
                    resolved_cc.append(
                        cc_map.get(sid, f"{sid}@abc.com")
                    )

            resolved_cc = [
                e for e in dict.fromkeys(resolved_cc)
                if e not in resolved_recipients
            ]

        # ==========================================
        # SEND EMAIL
        # ==========================================

        recipients_payload = {
            "to": [
                {"address": email}
                for email in resolved_recipients
            ]
        }

        if resolved_cc:
            recipients_payload["cc"] = [
                {"address": email}
                for email in resolved_cc
            ]

        message = {
            "senderAddress": SENDER_EMAIL,
            "recipients": recipients_payload,
            "content": {
                "subject": subject,
                "html": html_body
            }
        }

        poller = await asyncio.to_thread(
            EMAIL_CLIENT.begin_send,
            message
        )

        result = await asyncio.to_thread(
            poller.result
        )

        logging.info(
            f"Email sent to "
            f"{len(resolved_recipients)} recipient(s)"
        )

        return {
            "success": True,
            "recipient_count": len(
                resolved_recipients
            ),
            "result": str(result)
        }

    except Exception as ex:

        logging.exception(
            "Email sending failed"
        )

        return {
            "success": False,
            "error": str(ex)
        }