"""Email HTML templates used across the app.

Provide small helper functions that return ready-to-send HTML strings
so all emails have a consistent look and feel.
"""
from typing import List, Tuple
from core.constants import BASE_URL


import base64
import os


def _get_base64_image(filename: str) -> str:
    path = os.path.join("assests", filename)
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return ""

def _base_html(
    title: str,
    preface: str,
    details: List[Tuple[str, str]],
    footer_note: str = "",
    action_url: str = "",
    action_text: str = "Click here to access",
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
        f""" <span style="color: #000000;">To view more details, please visit <a href="{action_url}" style="color: #2E5BEA; text-decoration: underline; font-weight: 700;">Compliance Connect</a>.</span>"""
        if action_url
        else ""
    )

    logo_left_b64 = _get_base64_image("pinterest-logo-png-2011.png")
    logo_right_b64 = _get_base64_image("pinterest-logo-png-2011 - Copy.png")

    img_left = (
        f'<img src="data:image/png;base64,{logo_left_b64}" alt="Logo Left" '
        f'style="display:block; border:none; outline:none; text-decoration:none;">'
        if logo_left_b64
        else ""
    )
    img_right = (
        f'<img src="data:image/png;base64,{logo_right_b64}" alt="Logo Right" '
        f'style="display:block; border:none; outline:none; text-decoration:none;">'
        if logo_right_b64
        else ""
    )

    return f"""
<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <!--[if mso]>
    <xml>
      <o:OfficeDocumentSettings>
        <o:AllowPNG/>
        <o:PixelsPerInch>96</o:PixelsPerInch>
      </o:OfficeDocumentSettings>
    </xml>
    <![endif]-->
</head>
<body style="
    margin:0;
    padding:0;
    width:100% !important;
    background:#F3F5F7;
    font-family:'Segoe UI',Arial,sans-serif;
    -webkit-text-size-adjust:100%;
    -ms-text-size-adjust:100%;
">

<table
    role="presentation"
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="background:#F3F5F7; width:100%;"
>
<tr>
<td align="center" style="padding:0;">

    <table
        role="presentation"
        width="100%"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="
            width:100%;
            background:#FFFFFF;
            border:none;
        "
    >

        <tr>
            <td style="background:#FFFFFF; padding:16px 24px 12px 24px;">
                <table width="100%" border="0" cellspacing="0" cellpadding="0">
                    <tr>
                        <td align="left" valign="middle">
                            {img_left}
                        </td>
                        <td align="right" valign="middle">
                            {img_right}
                        </td>
                    </tr>
                </table>
            </td>
        </tr>

        <tr>
            <td style="
                background:#0F4C81;
                padding:20px 24px;
            ">
                <div style="
                    color:#FFFFFF;
                    font-size:26px;
                    font-weight:700;
                    line-height:1.3;
                ">
                    {title}
                </div>
            </td>
        </tr>

        <tr>
            <td style="padding:20px;">

                <div style="
                    background:#F5F7FA;
                    border-left:6px solid #2E5BEA;
                    padding:16px;
                    margin-bottom:20px;
                ">
                    <div style="
                        color:#000000;
                        font-size:15px;
                        line-height:1.6;
                    ">
                        {preface}{action_html}
                    </div>
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

                    {details_html}

                </table>

                {footer_html}

            </td>
        </tr>
    <tr>
        <td style="
        padding:20px 30px;
        border-top:1px solid #e5e7eb;">
 
            <div style="
            font-size:14px;
            font-weight:700;
            color:#0f4c81;
            font-family:'Segoe UI',Arial,sans-serif;
            margin-bottom:4px;">
                Thanks &amp; Regards,<br>
                Compliance Team
            </div>
 
            <div style="
            font-size:12px;
            line-height:1.5;
            color:#6b7280;
            font-family:'Segoe UI',Arial,sans-serif;">
                Supporting governance, risk management,
                compliance excellence and continuous audit improvement.
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
        ("Requester", f"{requester_name} ({requester_staff_id})"),
        ("Vertical/Division/Deptt", f"{requester_vertical or '-'}/{requester_division or '-'}/{requester_department or '-'}"),
        ("Status", "Pending"),
    ]
    if title_text:
        if len(title_text) > 100:
            title_text = title_text[:97] + "..."
        details.insert(1, ("Title", title_text))
    
    url_type = raw_record_type or record_type.lower()
    return _base_html(title, preface, details, action_url=f"{BASE_URL}/{url_type}/{record_id}", action_text="Click here to access")


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
        ("Assigned To", assigned_to_name),
        ("Requester", f"{requester_name} ({requester_staff_id})"),
        ("Vertical/Division/Deptt", f"{requester_vertical or '-'}/{requester_division or '-'}/{requester_department or '-'}"),
    ]
    if title_text:
        if len(title_text) > 100:
            title_text = title_text[:97] + "..."
        details.insert(1, ("Title", title_text))
        
    url_type = raw_record_type or record_type.lower()
    return _base_html(
        title,
        preface,
        details,
        footer_note="Please review and take action on the assigned record.",
        action_url=f"{BASE_URL}/{url_type}/{record_id}",
        action_text="Click here to access"
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
        ("Responded By", responder_name),
        ("Requester", f"{requester_name} ({requester_staff_id})"),
        ("Vertical/Division/Deptt", f"{requester_vertical or '-'}/{requester_division or '-'}/{requester_department or '-'}"),
    ]
    if title_text:
        if len(title_text) > 100:
            title_text = title_text[:97] + "..."
        details.insert(1, ("Title", title_text))
    if response_text:
        details.append(("Response", response_text))

    url_type = raw_record_type or record_type.lower()
    return _base_html(title, preface, details, action_url=f"{BASE_URL}/{url_type}/{record_id}", action_text="Click here to access")


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
        ("Closed By", closed_by_name),
        ("Requester", f"{requester_name} ({requester_staff_id})"),
        ("Vertical/Division/Deptt", f"{requester_vertical or '-'}/{requester_division or '-'}/{requester_department or '-'}"),
        ("Status", "Closed"),
    ]
    if title_text:
        if len(title_text) > 100:
            title_text = title_text[:97] + "..."
        details.insert(1, ("Title", title_text))

    url_type = raw_record_type or record_type.lower()
    return _base_html(title, preface, details, action_url=f"{BASE_URL}/{url_type}/{record_id}", action_text="Click here to access")


def annual_declaration_assigned(
    declaration_name: str,
    financial_year: str,
    due_date: str,
    action_url: str = "",
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
    ]
    return _base_html(
        title,
        preface,
        details,
        footer_note=(
            "Please complete and submit your declaration before "
            "the due date."
        ),
        action_url=action_url,
    )
