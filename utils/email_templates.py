"""Email HTML templates used across the app.

Provide small helper functions that return ready-to-send HTML strings
so all emails have a consistent look and feel.
"""
from typing import List, Tuple
from core.constants import BASE_URL


def _base_html(
    title: str,
    preface: str,
    details: List[Tuple[str, str]],
    footer_note: str = "",
    action_url: str = "",
    action_text: str = "View Dashboard",
) -> str:

    details_html = "".join(
        f"""
        <tr>
            <td style="
                width:35%;
                padding:16px 18px;
                border-bottom:1px solid #DCE6F0;
                color:#000000;
                font-size:13px;
                font-weight:700;
                text-transform:uppercase;
            ">
                {label}
            </td>

            <td style="
                padding:16px 18px;
                border-bottom:1px solid #DCE6F0;
                color:#0F4C81;
                font-size:14px;
                font-weight:500;
            ">
                {value}
            </td>
        </tr>
        """
        for label, value in details
    )

    footer_html = (
        f"""
        <div style="
            margin-top:10px;
            border:1px solid #DCE6F0;
            background:#F8FAFD;
            padding:12px;
        ">
            <div style="
                color:#D32F2F;
                font-size:14px;
                font-weight:700;
                margin-bottom:6px;
            ">
                ► Action Required
            </div>

            <div style="
                color:#000000;
                font-size:13px;
                line-height:1.5;
            ">
                {footer_note}
            </div>

        </div>
        """
        if footer_note
        else ""
    )

    action_html = (
        f"""
        <div style="margin-top:20px; text-align:center;">
            <a href="{action_url}" style="
                display:inline-block;
                background:#2E5BEA;
                color:#FFFFFF;
                font-size:14px;
                font-weight:700;
                text-decoration:none;
                padding:12px 24px;
                border-radius:4px;
            ">
                {action_text}
            </a>
        </div>
        """
        if action_url
        else ""
    )

    return f"""
<html>

<body style="
    margin:0;
    padding:0;
    background:#F3F5F7;
    font-family:'Segoe UI',Arial,sans-serif;
">

<table
    role="presentation"
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="background:#F3F5F7;"
>
<tr>
<td align="center" style="padding:25px;">

    <table
        role="presentation"
        width="550"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="
            width:550px;
            background:#FFFFFF;
            border:1px solid #DCE6F0;
            border-radius:6px;
            overflow:hidden;
        "
    >

        <tr>
            <td style="
                background:#0F4C81;
                padding:24px;
            ">
                <div style="
                    color:#FFFFFF;
                    font-size:26px;
                    font-weight:700;
                    line-height:1.3;
                    margin-bottom:6px;
                ">
                    {title}
                </div>

                <div style="
                    color:#D7E6F7;
                    font-size:12px;
                ">
                    Audit Management Notification
                </div>
            </td>
        </tr>

        <tr>
            <td style="padding:20px;">

                <div style="
                    background:#F5F7FA;
                    border-left:6px solid #2E5BEA;
                    padding:16px;
                    margin-bottom:15px;
                ">
                    <div style="
                        color:#000000;
                        font-size:14px;
                        line-height:1.6;
                    ">
                        {preface}
                    </div>
                </div>

                <div style="
                    color:#0F4C81;
                    font-size:16px;
                    font-weight:700;
                    margin-bottom:8px;
                ">
                    Audit Details
                </div>

                <table
                    width="100%"
                    cellpadding="0"
                    cellspacing="0"
                    border="0"
                    style="
                        border-collapse:collapse;
                        border:1px solid #DCE6F0;
                    "
                >

                    <tr>

                        <th style="
                            background:#2E5BEA;
                            color:#FFFFFF;
                            text-align:left;
                            padding:12px;
                            font-size:13px;
                        ">
                            Field
                        </th>

                        <th style="
                            background:#2E5BEA;
                            color:#FFFFFF;
                            text-align:left;
                            padding:12px;
                            font-size:13px;
                        ">
                            Details
                        </th>

                    </tr>

                    {details_html}

                </table>

                {action_html}

                {footer_html}

                <div style="
                    margin-top:8px;
                    padding-top:8px;
                    border-top:1px solid #DCE6F0;
                ">

                    <div style="
                        color:#0F4C81;
                        font-size:14px;
                        font-weight:700;
                        margin-bottom:4px;
                    ">
                        Audit &amp; Compliance Team
                    </div>

                    <div style="
                        color:#000000;
                        font-size:12px;
                        line-height:1.5;
                    ">
                        Supporting governance, risk management,
                        compliance excellence and continuous audit improvement.
                    </div>

                </div>

            </td>
        </tr>

    </table>

</td>
</tr>
</table>

</body>
</html>
"""


def audit_created_draft(audit_id: str, name: str, department: str, start_date, end_date) -> str:
    title = f"Draft Audit Created — {audit_id}"
    preface = "A draft audit has been created. You are receiving this because you are listed as an auditor for this audit."
    details = [
        ("Audit Name", name),
        ("Department", department),
        ("Start Date", str(start_date)),
        ("End Date", str(end_date)),
        ("Status", "Draft"),
    ]
    return _base_html(title, preface, details)


# =====================================================
# COMPLIANCE HELPDESK TEMPLATES
# =====================================================


def record_created(
    record_type: str,
    record_id: str,
    requester_name: str,
    requester_staff_id: str,
    requester_vertical: str = "",
    requester_division: str = "",
    requester_department: str = "",
    title_text: str = "",
    raw_record_type: str = "",
) -> str:
    title = f"New {record_type} — {record_id}"
    preface = (
        f"A new {record_type} has been raised by "
        f"{requester_name} ({requester_staff_id})."
    )
    details = [
        ("Type ID", f"{record_type} - {record_id}"),
        ("Requester", f"{requester_name} ({requester_staff_id})"),
        ("Vertical/Division/Deptt", f"{requester_vertical or '-'}/{requester_division or '-'}/{requester_department or '-'}"),
        ("Status", "Pending"),
    ]
    if title_text:
        details.insert(1, ("Title", title_text))
    
    url_type = raw_record_type or record_type.lower()
    return _base_html(title, preface, details, action_url=f"{BASE_URL}/{url_type}/{record_id}", action_text="View Dashboard")


def record_assigned(
    record_type: str,
    record_id: str,
    assigned_to_name: str,
    requester_name: str,
    requester_staff_id: str,
    requester_vertical: str = "",
    requester_division: str = "",
    requester_department: str = "",
    title_text: str = "",
    raw_record_type: str = "",
) -> str:
    title = f"{record_type} Assigned — {record_id}"
    preface = (
        f"You have been assigned to {record_type} {record_id}."
    )
    details = [
        ("Type ID", f"{record_type} - {record_id}"),
        ("Assigned To", assigned_to_name),
        ("Requester", f"{requester_name} ({requester_staff_id})"),
        ("Vertical/Division/Deptt", f"{requester_vertical or '-'}/{requester_division or '-'}/{requester_department or '-'}"),
    ]
    if title_text:
        details.insert(1, ("Title", title_text))
        
    url_type = raw_record_type or record_type.lower()
    return _base_html(
        title,
        preface,
        details,
        footer_note="Please review and take action on the assigned record.",
        action_url=f"{BASE_URL}/{url_type}/{record_id}",
        action_text="View Dashboard"
    )


def record_responded(
    record_type: str,
    record_id: str,
    responder_name: str,
    requester_name: str,
    requester_staff_id: str,
    requester_vertical: str = "",
    requester_division: str = "",
    requester_department: str = "",
    title_text: str = "",
    response_text: str = "",
    raw_record_type: str = "",
) -> str:
    title = f"{record_type} Response — {record_id}"
    preface = (
        f"A new response has been added to {record_type} "
        f"{record_id} by {responder_name}."
    )
    
    if len(response_text) > 100:
        response_text = response_text[:97] + "..."

    details = [
        ("Type ID", f"{record_type} - {record_id}"),
        ("Responded By", responder_name),
        ("Requester", f"{requester_name} ({requester_staff_id})"),
        ("Vertical/Division/Deptt", f"{requester_vertical or '-'}/{requester_division or '-'}/{requester_department or '-'}"),
    ]
    if title_text:
        details.insert(1, ("Title", title_text))
    if response_text:
        details.append(("Response", response_text))

    url_type = raw_record_type or record_type.lower()
    return _base_html(title, preface, details, action_url=f"{BASE_URL}/{url_type}/{record_id}", action_text="View Dashboard")


def record_closed(
    record_type: str,
    record_id: str,
    closed_by_name: str,
    requester_name: str,
    requester_staff_id: str,
    requester_vertical: str = "",
    requester_division: str = "",
    requester_department: str = "",
    title_text: str = "",
    raw_record_type: str = "",
) -> str:
    title = f"{record_type} Closed — {record_id}"
    preface = (
        f"{record_type} {record_id} has been closed by "
        f"{closed_by_name}."
    )
    details = [
        ("Type ID", f"{record_type} - {record_id}"),
        ("Closed By", closed_by_name),
        ("Requester", f"{requester_name} ({requester_staff_id})"),
        ("Vertical/Division/Deptt", f"{requester_vertical or '-'}/{requester_division or '-'}/{requester_department or '-'}"),
        ("Status", "Closed"),
    ]
    if title_text:
        details.insert(1, ("Title", title_text))

    url_type = raw_record_type or record_type.lower()
    return _base_html(title, preface, details, action_url=f"{BASE_URL}/{url_type}/{record_id}", action_text="View Dashboard")


def annual_declaration_assigned(
    declaration_name: str,
    financial_year: str,
    due_date: str,
    employee_name: str,
    employee_staff_id: str,
) -> str:
    title = f"Annual Declaration — {declaration_name}"
    preface = (
        f"You have been assigned to complete the "
        f"{declaration_name} declaration for FY {financial_year}."
    )
    details = [
        ("Declaration", declaration_name),
        ("Financial Year", financial_year),
        ("Due Date", str(due_date)),
        ("Employee Name", employee_name),
        ("Staff ID", employee_staff_id),
    ]
    return _base_html(
        title,
        preface,
        details,
        footer_note=(
            "Please complete and submit your declaration before "
            "the due date."
        ),
    )
