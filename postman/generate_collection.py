"""Generate Postman collection + environment for Compliance APIs."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent


def make_url(path: str, query=None):
    query = query or []
    enabled = [q for q in query if not q.get("disabled")]
    qstr = ("?" + "&".join(f"{q['key']}={q['value']}" for q in enabled)) if enabled else ""
    result = {
        "raw": "{{base_url}}" + path + qstr,
        "host": ["{{base_url}}"],
        "path": [p for p in path.lstrip("/").split("/") if p],
    }
    if query:
        result["query"] = [
            {
                "key": q["key"],
                "value": q["value"],
                **({"disabled": True} if q.get("disabled") else {}),
            }
            for q in query
        ]
    return result


def auth_header():
    return {"key": "Authorization", "value": "Bearer {{auth_token}}", "type": "text"}


def req(name, method, path, *, query=None, body=None, desc="", auth=True, headers=None):
    h = []
    if auth:
        h.append(auth_header())
    if headers:
        h.extend(headers)
    item = {
        "name": name,
        "request": {
            "method": method,
            "header": h,
            "url": make_url(path, query),
            "description": desc,
        },
        "response": [],
    }
    if body is not None:
        item["request"]["body"] = body
    return item


def form_body(fields):
    formdata = []
    for f in fields:
        if f.get("type") == "file":
            entry = {
                "key": f["key"],
                "type": "file",
                "src": f.get("src", "fixtures/sample.txt"),
            }
        else:
            entry = {"key": f["key"], "value": f["value"], "type": "text"}
        if f.get("description"):
            entry["description"] = f["description"]
        formdata.append(entry)
    return {"mode": "formdata", "formdata": formdata}


def json_body(obj):
    return {
        "mode": "raw",
        "raw": json.dumps(obj, indent=2),
        "options": {"raw": {"language": "json"}},
    }


def build():
    health = [
        req("Health Check", "GET", "/api/compliance/health", auth=False),
    ]

    dashboard = [
        req(
            "Dashboard (pending)",
            "GET",
            "/api/compliance/dashboard",
            query=[
                {"key": "tab", "value": "pending"},
                {"key": "page", "value": "1"},
                {"key": "page_size", "value": "10"},
                {"key": "type", "value": "query,gift,complaint", "disabled": True},
                {"key": "search", "value": "", "disabled": True},
                {"key": "sub_type", "value": "", "disabled": True},
                {"key": "response_status", "value": "", "disabled": True},
                {"key": "overall_status", "value": "", "disabled": True},
                {"key": "updated_on_start", "value": "2026-01-01", "disabled": True},
                {"key": "updated_on_end", "value": "2026-12-31", "disabled": True},
            ],
        ),
        req(
            "Dashboard (all)",
            "GET",
            "/api/compliance/dashboard",
            query=[
                {"key": "tab", "value": "all"},
                {"key": "page", "value": "1"},
                {"key": "page_size", "value": "10"},
            ],
        ),
        req(
            "Dashboard Export",
            "GET",
            "/api/compliance/dashboard/export",
            query=[
                {"key": "tab", "value": "pending"},
                {"key": "type", "value": "query,gift", "disabled": True},
            ],
            desc="Downloads xlsx",
        ),
    ]

    recent = [
        req("Get Recent Activity", "GET", "/api/compliance/recent-activity"),
        req(
            "Log Recent Activity",
            "POST",
            "/api/compliance/recent-activity",
            body=json_body(
                {
                    "record_id": "{{query_id}}",
                    "record_type": "query",
                    "title": "Dummy recent activity title",
                    "status": "Pending",
                    "created_on": "2026-08-01T10:00:00",
                    "sub_type": "COBCE",
                    "pending_at": "Compliance Team",
                }
            ),
            headers=[{"key": "Content-Type", "value": "application/json"}],
        ),
    ]

    query = [
        req(
            "Raise Query",
            "POST",
            "/api/compliance/query",
            body=form_body(
                [
                    {
                        "key": "queryType",
                        "value": "COBCE",
                        "description": "COBCE | COI | ComplyShield | Gift | Other",
                    },
                    {"key": "title", "value": "Dummy query title for Postman"},
                    {
                        "key": "description",
                        "value": "This is a dummy description for raising a compliance query via Postman.",
                    },
                    {"key": "files", "type": "file", "src": "fixtures/sample.txt"},
                ]
            ),
            desc="Creates a new query. Copy returned query_id into env variable query_id.",
        ),
        req("View Query", "GET", "/api/compliance/query/{{query_id}}"),
        req(
            "Respond to Query",
            "POST",
            "/api/compliance/query/{{query_id}}/respond",
            body=form_body(
                [
                    {"key": "message", "value": "Dummy response comment from Postman."},
                    {"key": "files", "type": "file", "src": "fixtures/sample.txt"},
                ]
            ),
        ),
        req(
            "Close Query",
            "POST",
            "/api/compliance/query/{{query_id}}/close",
            body=form_body(
                [
                    {
                        "key": "comment",
                        "value": "Closing this query via Postman dummy payload.",
                    }
                ]
            ),
        ),
    ]

    complaint = [
        req(
            "Raise Complaint",
            "POST",
            "/api/compliance/complaint",
            body=form_body(
                [
                    {
                        "key": "complaintType",
                        "value": "Other",
                        "description": "COBCE | COI | ComplyShield | Gift | Other",
                    },
                    {
                        "key": "complaintDetails",
                        "value": "Dummy complaint details submitted from Postman collection.",
                    },
                    {"key": "files", "type": "file", "src": "fixtures/sample.txt"},
                ]
            ),
            desc="Creates complaint. Copy complaint_id into record_id if needed.",
        ),
    ]

    gift = [
        req(
            "Raise Gift Declaration",
            "POST",
            "/api/compliance/gift",
            body=form_body(
                [
                    {"key": "status", "value": "Submitted"},
                    {
                        "key": "type",
                        "value": "TO_BE_GIVEN",
                        "description": "TO_BE_GIVEN | ALREADY_GIVEN | TO_BE_RECEIVED | ALREADY_RECEIVED",
                    },
                    {"key": "title", "value": "Dummy gift declaration"},
                    {
                        "key": "description",
                        "value": "Dummy gift description for Postman testing.",
                    },
                    {"key": "person", "value": "Jane Doe"},
                    {"key": "organization", "value": "Acme Corp"},
                    {"key": "approxValueINR", "value": "2500"},
                    {"key": "portalApprovalTaken", "value": "yes"},
                    {"key": "portalNumber", "value": "PORTAL-12345"},
                    {"key": "files", "type": "file", "src": "fixtures/sample.txt"},
                ]
            ),
        ),
    ]

    cobce_rows = json.dumps(
        [
            {
                "nature_of_violation": "Dummy violation nature",
                "person_responsible": "John Smith",
            }
        ]
    )
    coi_form = json.dumps(
        {
            "companyName": "Dummy Company Pvt Ltd",
            "address": "123 Test Street, Mumbai",
            "activityType": "Advisory board",
            "remarks": "Submitted via Postman dummy payload",
        }
    )
    cobce_rows_updated = json.dumps(
        [
            {
                "nature_of_violation": "Updated violation",
                "person_responsible": "Jane Smith",
            }
        ]
    )

    self_decl = [
        req(
            "Self Declaration Form Config",
            "GET",
            "/api/compliance/self-declaration/form-config",
            auth=False,
        ),
        req(
            "Get Self Declaration",
            "GET",
            "/api/compliance/self-declaration/{{self_declaration_id}}",
        ),
        req(
            "Save Self Declaration (COBCE draft)",
            "POST",
            "/api/compliance/self-declaration",
            body=form_body(
                [
                    {"key": "declaration_type", "value": "cobce"},
                    {
                        "key": "status",
                        "value": "draft",
                        "description": "draft | submit",
                    },
                    {"key": "subType", "value": "COBCE"},
                    {
                        "key": "description",
                        "value": "Dummy COBCE self-declaration description.",
                    },
                    {"key": "rows", "value": cobce_rows},
                    {"key": "files", "type": "file", "src": "fixtures/sample.txt"},
                ]
            ),
            desc="Omit id to create. Set returned id into self_declaration_id.",
        ),
        req(
            "Save Self Declaration (COI submit)",
            "POST",
            "/api/compliance/self-declaration",
            body=form_body(
                [
                    {"key": "declaration_type", "value": "coi"},
                    {"key": "status", "value": "submit"},
                    {"key": "subType", "value": "OUTSIDE_ACTIVITY"},
                    {
                        "key": "description",
                        "value": "Dummy COI outside activity declaration.",
                    },
                    {"key": "formData", "value": coi_form},
                    {"key": "files", "type": "file", "src": "fixtures/sample.txt"},
                ]
            ),
        ),
        req(
            "Update Self Declaration Draft",
            "POST",
            "/api/compliance/self-declaration",
            body=form_body(
                [
                    {"key": "declaration_type", "value": "cobce"},
                    {"key": "status", "value": "draft"},
                    {"key": "subType", "value": "COBCE"},
                    {"key": "id", "value": "{{self_declaration_id}}"},
                    {"key": "description", "value": "Updated dummy COBCE draft."},
                    {"key": "rows", "value": cobce_rows_updated},
                ]
            ),
        ),
    ]

    respond = [
        req("Get Conversation", "GET", "/api/compliance/conversation/{{record_id}}"),
        req(
            "Respond to Record",
            "POST",
            "/api/compliance/respond/{{record_id}}",
            body=form_body(
                [
                    {
                        "key": "message",
                        "value": "Dummy reply on shared respond endpoint.",
                    },
                    {"key": "files", "type": "file", "src": "fixtures/sample.txt"},
                ]
            ),
        ),
        req(
            "Close Record",
            "POST",
            "/api/compliance/close/{{record_id}}",
            body=form_body(
                [
                    {
                        "key": "remarks",
                        "value": "Closing record via Postman dummy remarks.",
                    }
                ]
            ),
            desc="Admin-only close.",
        ),
    ]

    admin = [
        req(
            "List Admins",
            "GET",
            "/api/compliance/admins",
            query=[
                {"key": "type", "value": "query"},
                {"key": "search", "value": "", "disabled": True},
                {"key": "page", "value": "1"},
                {"key": "page_size", "value": "10"},
            ],
            desc="type: Gift Declaration | Complaint | Query | Annual Declaration | Self Declaration",
        ),
        req(
            "Assign Admin",
            "PUT",
            "/api/compliance/assign/{{record_id}}",
            body=json_body({"staff_id": "{{assign_staff_id}}"}),
            headers=[{"key": "Content-Type", "value": "application/json"}],
        ),
    ]

    files = [
        req(
            "Download File (SAS URL)",
            "GET",
            "/api/compliance/querys/files",
            query=[{"key": "path", "value": "{{file_path}}"}],
            auth=False,
            desc="path must start with /helpdesk/",
        ),
    ]

    annual = [
        req(
            "Declaration Types",
            "GET",
            "/api/declarations/declarationtypes",
            auth=False,
        ),
        req(
            "User Declaration Status",
            "GET",
            "/api/declarations/user-declaration-status",
        ),
        req("Head Summary", "GET", "/api/declarations/head-summary"),
        req(
            "Head Summary Export",
            "GET",
            "/api/declarations/head-summary/export",
            query=[{"key": "declaration_name", "value": "COBCE/COI"}],
        ),
        req(
            "Create Declaration",
            "POST",
            "/api/declarations/create-declaration",
            body=json_body(
                {
                    "declaration_name": "COBCE/COI",
                    "financial_year": "2025-26",
                    "assigned_date": "2026-04-01",
                    "due_date": "2026-06-30",
                    "activity_closure_date": "2026-07-15",
                    "status": "Pending",
                }
            ),
            headers=[{"key": "Content-Type", "value": "application/json"}],
            desc="Copy returned id into declaration_id.",
        ),
        req(
            "List Declarations",
            "GET",
            "/api/declarations/list-declarations",
            query=[
                {"key": "page", "value": "1"},
                {"key": "page_size", "value": "25"},
                {"key": "declaration_name", "value": "COBCE/COI", "disabled": True},
                {"key": "financial_year", "value": "2025-26", "disabled": True},
            ],
            desc="Admin only",
        ),
        req(
            "Edit Declaration",
            "PUT",
            "/api/declarations/edit-declaration/{{declaration_id}}",
            body=json_body(
                {
                    "due_date": "2026-07-31",
                    "activity_closure_date": "2026-08-15",
                    "status": "Pending",
                }
            ),
            headers=[{"key": "Content-Type", "value": "application/json"}],
            desc="Admin only",
        ),
        req(
            "Export Declarations",
            "GET",
            "/api/declarations/export-declarations",
            query=[{"key": "financial_year", "value": "2025-26", "disabled": True}],
            desc="Admin only — downloads xlsx",
        ),
        req(
            "Declaration Responses",
            "GET",
            "/api/declarations/declaration-responses/{{declaration_id}}",
            query=[{"key": "staff_id", "value": "{{staff_id}}"}],
            desc="staff_id required for master admin",
        ),
        req(
            "Save Declaration (draft)",
            "POST",
            "/api/declarations/save-declaration/{{declaration_id}}",
            body=json_body(
                {
                    "status": "draft",
                    "responses": [
                        {
                            "question_id": "COBCE_Q1",
                            "response": "option_a",
                            "declaration_details": None,
                        },
                        {
                            "question_id": "COI_PREFACE",
                            "response": "true",
                            "declaration_details": None,
                        },
                        {
                            "question_id": "COI_Q1",
                            "response": "agree",
                            "declaration_details": None,
                        },
                    ],
                }
            ),
            headers=[{"key": "Content-Type", "value": "application/json"}],
        ),
        req(
            "Save Declaration (submit)",
            "POST",
            "/api/declarations/save-declaration/{{declaration_id}}",
            body=json_body(
                {
                    "status": "submit",
                    "responses": [
                        {"question_id": "COBCE_Q1", "response": "option_a"},
                        {"question_id": "COI_PREFACE", "response": "true"},
                        {"question_id": "COI_Q1", "response": "agree"},
                        {"question_id": "COI_Q2", "response": "agree"},
                        {"question_id": "COI_Q3", "response": "agree"},
                        {"question_id": "COI_Q4", "response": "agree"},
                        {"question_id": "COI_Q5", "response": "agree"},
                        {"question_id": "COI_Q6", "response": "agree"},
                    ],
                }
            ),
            headers=[{"key": "Content-Type", "value": "application/json"}],
            desc="Adjust responses if validation requires more fields.",
        ),
        req(
            "Upload Declaration File",
            "POST",
            "/api/declarations/upload-declaration-file/{{declaration_id}}",
            body=form_body(
                [
                    {
                        "key": "file",
                        "type": "file",
                        "src": "fixtures/sample_declaration.xlsx",
                    }
                ]
            ),
            desc="Requires a valid staff-list Excel for your environment.",
        ),
        req(
            "Download Declaration Template",
            "GET",
            "/api/declarations/download-declaration-file",
        ),
        req(
            "Download Declaration File by ID",
            "GET",
            "/api/declarations/download-declaration-file/{{declaration_id}}",
            desc="Admin only",
        ),
    ]

    collection = {
        "info": {
            "_postman_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "name": "Compliance Helpdesk + Annual Declarations",
            "description": (
                "Import this collection AND the matching environment.\n\n"
                "Setup:\n"
                "1. Set `base_url` (e.g. http://localhost:8000)\n"
                "2. Set `auth_token` (token only; Bearer is added automatically)\n"
                "3. Fill `declaration_id` and `assign_staff_id`\n"
                "4. If file fields are empty after import, attach "
                "postman/fixtures/sample.txt or sample_declaration.xlsx\n\n"
                "Prefilled: query_id=QRY-kpmg_nthompson-000022, "
                "record_id=CMP-kpmg_ktalwar-000011"
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "base_url", "value": "http://localhost:8000"},
            {"key": "auth_token", "value": ""},
            {"key": "query_id", "value": "QRY-kpmg_nthompson-000022"},
            {"key": "record_id", "value": "CMP-kpmg_ktalwar-000011"},
            {"key": "declaration_id", "value": ""},
            {"key": "assign_staff_id", "value": ""},
            {"key": "self_declaration_id", "value": ""},
            {"key": "staff_id", "value": "STAFF001"},
            {"key": "file_path", "value": "/helpdesk/dummy/path/sample.txt"},
        ],
        "auth": {
            "type": "bearer",
            "bearer": [
                {"key": "token", "value": "{{auth_token}}", "type": "string"}
            ],
        },
        "item": [
            {"name": "Health", "item": health},
            {"name": "Dashboard", "item": dashboard},
            {"name": "Recent Activity", "item": recent},
            {"name": "Query", "item": query},
            {"name": "Complaint", "item": complaint},
            {"name": "Gift", "item": gift},
            {"name": "Self Declaration", "item": self_decl},
            {"name": "Respond / Close / Conversation", "item": respond},
            {"name": "Admin", "item": admin},
            {"name": "Files", "item": files},
            {"name": "Annual Declarations", "item": annual},
        ],
    }

    env = {
        "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "name": "Compliance API Local",
        "values": [
            {
                "key": "base_url",
                "value": "http://localhost:8000",
                "type": "default",
                "enabled": True,
            },
            {
                "key": "auth_token",
                "value": "",
                "type": "secret",
                "enabled": True,
            },
            {
                "key": "query_id",
                "value": "QRY-kpmg_nthompson-000022",
                "type": "default",
                "enabled": True,
            },
            {
                "key": "record_id",
                "value": "CMP-kpmg_ktalwar-000011",
                "type": "default",
                "enabled": True,
            },
            {
                "key": "declaration_id",
                "value": "",
                "type": "default",
                "enabled": True,
            },
            {
                "key": "assign_staff_id",
                "value": "",
                "type": "default",
                "enabled": True,
            },
            {
                "key": "self_declaration_id",
                "value": "",
                "type": "default",
                "enabled": True,
            },
            {
                "key": "staff_id",
                "value": "STAFF001",
                "type": "default",
                "enabled": True,
            },
            {
                "key": "file_path",
                "value": "/helpdesk/dummy/path/sample.txt",
                "type": "default",
                "enabled": True,
            },
        ],
        "_postman_variable_scope": "environment",
    }

    (OUT / "Compliance_API.postman_collection.json").write_text(
        json.dumps(collection, indent=2), encoding="utf-8"
    )
    (OUT / "Compliance_API.postman_environment.json").write_text(
        json.dumps(env, indent=2), encoding="utf-8"
    )

    n = 0

    def count(items):
        nonlocal n
        for it in items:
            if "item" in it:
                count(it["item"])
            else:
                n += 1

    count(collection["item"])
    print(f"Wrote {n} requests + environment to {OUT}")


if __name__ == "__main__":
    build()
