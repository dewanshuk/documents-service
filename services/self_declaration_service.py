import json
from typing import Any

from fastapi import UploadFile
from fastapi.responses import JSONResponse

from db.db_manager import db_manager
from db.models.helpdesk import (
    COBCEDeclarations,
    COIDeclarations,
)
from db.validators.comp_help import validate_coi_form
from storage.storage_ops import (
    MAX_COBCE_ROWS,
    build_upload_pool,
    copy_compliance_files,
    delete_compliance_files,
    init_json,
    load_json,
    parse_files_list,
    resolve_desired_files,
    resolve_file_urls,
)
from utils.actor_display import format_actor_name, format_pending_at
from utils.helpers import db_timestamp_now, now_ist
from utils.record_ids import next_self_decl_id, resolve_record

SELF_DECLARATION_TYPES = frozenset({"cobce", "coi"})


def _coi_validation_errors(sub_type: str, form_data: dict) -> list[str]:
    result = validate_coi_form(sub_type, form_data)
    if isinstance(result, JSONResponse):
        body = json.loads(result.body.decode())
        return [body.get("error", "COI form validation failed")]
    return []


def _normalize_cobce_rows(
    rows: list[dict] | None,
    description: str | None,
    staff_id: str,
) -> list[dict]:
    if rows:
        if len(rows) > MAX_COBCE_ROWS:
            raise ValueError(f"COBCE allows at most {MAX_COBCE_ROWS} rows")
        normalized = []
        for i, row in enumerate(rows):
            nature = row.get("nature_of_violation") or row.get("description")
            person = row.get("person_responsible") or staff_id
            if not nature:
                raise ValueError(
                    f"Row {i + 1}: nature_of_violation is required"
                )
            normalized.append({
                "nature_of_violation": nature,
                "person_responsible": person,
                "files": parse_files_list(row.get("files")),
            })
        return normalized

    if description:
        return [{
            "nature_of_violation": description,
            "person_responsible": staff_id,
            "files": None,
        }]

    raise ValueError(
        "COBCE requires description or rows "
        "(array of nature_of_violation + person_responsible)"
    )


async def save_self_declaration(
    staff_id: str,
    declaration_type: str,
    status: str,
    sub_type: str,
    record_id: str | None = None,
    description: str | None = None,
    form_data: dict | None = None,
    files: list[UploadFile] | None = None,
    rows: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Unified save for COBCE / COI self-declarations.
    status: draft | submit — create when record_id is omitted, update when provided.

    COBCE: each row may include optional files (null | [] | [filenames]).
    COI: formData.files is optional (null | [] | [filenames]).
    Multipart uploads are matched to those names by filename.
    """
    decl_type = declaration_type.lower()
    if decl_type not in ("cobce", "coi"):
        raise ValueError("declaration_type must be 'cobce' or 'coi'")
    if status not in ("draft", "submit"):
        raise ValueError("status must be 'draft' or 'submit'")

    if decl_type == "cobce":
        return await _save_cobce(
            staff_id,
            status,
            sub_type,
            record_id,
            description,
            files or [],
            rows,
        )
    return await _save_coi(
        staff_id,
        status,
        sub_type,
        record_id,
        form_data or {},
        files or [],
    )


async def _submit_cobce_record(
    staff_id: str,
    sub_type: str,
    row: dict,
    file_entries: list[dict[str, str]],
) -> str:
    record_id = await next_self_decl_id(staff_id)
    nature = row["nature_of_violation"]
    person = row.get("person_responsible", staff_id)
    person_details = {"name": person}
    created_on = db_timestamp_now()

    await db_manager.create(
        COBCEDeclarations,
        {
            "COBCEId": record_id,
            "SubType": sub_type,
            "Description": nature,
            "PersonDetails": person_details,
            "Status": "Draft",
            "CreatedOn": created_on,
            "CreatedBy": staff_id,
            "OverallStatus": "Draft",
            "PendingAt": 0,
            "ResponseJsonPath": None,
        },
    )

    now = now_ist()
    conv_files = (
        await copy_compliance_files(file_entries, record_id)
        if file_entries
        else []
    )
    json_data = {
        "id": record_id,
        "conversation": [
            {
                "actor": "User",
                "actorId": staff_id,
                "actor_name": await format_actor_name(staff_id),
                "dateTime": now.isoformat(),
                "data": {
                    "subType": sub_type,
                    "natureOfViolation": nature,
                    "description": nature,
                    "personDetails": person_details,
                },
                "files": conv_files,
            }
        ],
    }
    json_path = await init_json(record_id, json_data)
    await db_manager.update(
        COBCEDeclarations,
        record_id,
        {
            "Status": "In-Progress",
            "PendingAt": 1,
            "OverallStatus": "Pending",
            "ResponseJsonPath": json_path,
        },
    )
    return record_id


async def _save_cobce(
    staff_id: str,
    status: str,
    sub_type: str,
    record_id: str | None,
    description: str | None,
    files: list[UploadFile],
    rows: list[dict] | None,
) -> dict[str, Any]:
    cobce_rows = _normalize_cobce_rows(rows, description, staff_id)
    draft_record_id = record_id
    existing_rows: list[dict] = []

    if draft_record_id:
        record = await db_manager.get(COBCEDeclarations, draft_record_id)
        if not record:
            raise ValueError("Declaration not found")
        if record.CreatedBy != staff_id:
            raise ValueError("Unauthorized")
        if record.Status != "Draft":
            raise ValueError("Only draft declarations can be edited")
        existing_rows = _cobce_rows_from_record(record)
    else:
        draft_record_id = await next_self_decl_id(staff_id)
        await db_manager.create(
            COBCEDeclarations,
            {
                "COBCEId": draft_record_id,
                "SubType": sub_type,
                "Description": cobce_rows[0]["nature_of_violation"],
                "PersonDetails": {
                    "name": cobce_rows[0]["person_responsible"],
                    "rows": [
                        {
                            "nature_of_violation": r["nature_of_violation"],
                            "person_responsible": r["person_responsible"],
                            "files": [],
                        }
                        for r in cobce_rows
                    ],
                },
                "Status": "Draft",
                "CreatedOn": db_timestamp_now(),
                "CreatedBy": staff_id,
                "OverallStatus": "Draft",
                "PendingAt": 0,
                "ResponseJsonPath": None,
            },
        )

    upload_pool = build_upload_pool(files)
    stored_rows: list[dict] = []
    orphaned_files: list = []
    if len(cobce_rows) < len(existing_rows):
        for dropped in existing_rows[len(cobce_rows):]:
            orphaned_files.extend(dropped.get("files") or [])

    for index, row in enumerate(cobce_rows):
        prev_files = []
        if index < len(existing_rows):
            prev_files = existing_rows[index].get("files") or []
        resolved = await resolve_desired_files(
            draft_record_id,
            prev_files,
            row["files"],
            upload_pool,
            prefix=f"row{index}",
        )
        stored_rows.append({
            "nature_of_violation": row["nature_of_violation"],
            "person_responsible": row["person_responsible"],
            "files": resolved,
        })

    if upload_pool:
        raise ValueError(
            f"Unmapped uploaded file(s): {', '.join(sorted(upload_pool))}"
        )
    if orphaned_files:
        await delete_compliance_files(orphaned_files)

    person_details = {
        "name": stored_rows[0]["person_responsible"],
        "rows": stored_rows,
    }

    await db_manager.update(
        COBCEDeclarations,
        draft_record_id,
        {
            "Description": stored_rows[0]["nature_of_violation"],
            "SubType": sub_type,
            "PersonDetails": person_details,
            "OverallStatus": "Draft",
            "PendingAt": 0,
        },
    )

    if status == "draft":
        return {
            "id": draft_record_id,
            "status": "Draft",
            "overall_status": "Draft",
            "declaration_type": "cobce",
            "row_count": len(stored_rows),
        }

    created_ids: list[str] = []
    all_row_files: list[dict] = []
    for row in stored_rows:
        row_files = row.get("files") or []
        all_row_files.extend(row_files)
        created_ids.append(
            await _submit_cobce_record(
                staff_id,
                sub_type,
                row,
                row_files,
            )
        )

    if all_row_files:
        await delete_compliance_files(all_row_files)

    draft = await db_manager.get(COBCEDeclarations, draft_record_id)
    if draft and draft.Status == "Draft" and draft.CreatedBy == staff_id:
        await db_manager.delete(COBCEDeclarations, draft_record_id)

    if len(created_ids) == 1:
        return {
            "id": created_ids[0],
            "status": "Pending",
            "overall_status": "Pending",
            "declaration_type": "cobce",
            "row_count": 1,
        }

    return {
        "ids": created_ids,
        "status": "Pending",
        "overall_status": "Pending",
        "declaration_type": "cobce",
        "row_count": len(created_ids),
    }


async def _save_coi(
    staff_id: str,
    status: str,
    sub_type: str,
    record_id: str | None,
    form_data: dict,
    files: list[UploadFile],
) -> dict[str, Any]:
    desired_files = parse_files_list(form_data.get("files")) if form_data else None
    # Strip files before COI field validation.
    form_fields = {k: v for k, v in (form_data or {}).items() if k != "files"}

    if status == "submit":
        errors = _coi_validation_errors(sub_type, form_fields)
        if errors:
            raise ValueError("; ".join(errors))

    is_new = False
    existing_files: list = []
    if not record_id:
        record_id = await next_self_decl_id(staff_id)
        is_new = True
    else:
        record = await db_manager.get(COIDeclarations, record_id)
        if not record:
            raise ValueError("Declaration not found")
        if record.CreatedBy != staff_id:
            raise ValueError("Unauthorized")
        if record.Status != "Draft":
            raise ValueError("Only draft declarations can be edited")
        existing_files = (record.FormData or {}).get("files") or []

    upload_pool = build_upload_pool(files)
    stored = dict(form_fields)
    stored["files"] = await resolve_desired_files(
        record_id, existing_files, desired_files, upload_pool
    )
    if upload_pool:
        raise ValueError(
            f"Unmapped uploaded file(s): {', '.join(sorted(upload_pool))}"
        )

    if not is_new:
        await db_manager.update(
            COIDeclarations,
            record_id,
            {
                "FormData": stored,
                "SubType": sub_type,
                "OverallStatus": "Draft",
                "PendingAt": 0,
            },
        )
    else:
        await db_manager.create(
            COIDeclarations,
            {
                "COIId": record_id,
                "SubType": sub_type,
                "FormData": stored,
                "Status": "Draft",
                "CreatedOn": db_timestamp_now(),
                "CreatedBy": staff_id,
                "PendingAt": 0,
                "OverallStatus": "Draft",
                "ResponseJsonPath": None,
            },
        )

    if status == "draft":
        return {
            "id": record_id,
            "status": "Draft",
            "overall_status": "Draft",
            "declaration_type": "coi",
        }

    record = await db_manager.get(COIDeclarations, record_id)
    now = now_ist()

    json_data = {
        "id": record_id,
        "conversation": [
            {
                "actor": "User",
                "actorId": staff_id,
                "actor_name": await format_actor_name(staff_id),
                "dateTime": now.isoformat(),
                "data": {
                    "subType": record.SubType,
                    "formData": record.FormData,
                },
                "files": record.FormData.get("files", []),
            }
        ],
    }
    json_path = await init_json(record_id, json_data)
    await db_manager.update(
        COIDeclarations,
        record_id,
        {
            "Status": "In-Progress",
            "PendingAt": 1,
            "OverallStatus": "Pending",
            "ResponseJsonPath": json_path,
        },
    )
    return {
        "id": record_id,
        "status": "Pending",
        "overall_status": "Pending",
        "declaration_type": "coi",
    }


def _cobce_rows_from_record(record: COBCEDeclarations) -> list[dict]:
    person_details = record.PersonDetails or {}
    stored_rows = person_details.get("rows")
    if stored_rows:
        return [
            {
                "nature_of_violation": row.get("nature_of_violation")
                or row.get("description", ""),
                "person_responsible": row.get("person_responsible")
                or person_details.get("name", record.CreatedBy),
                "files": row.get("files") or [],
            }
            for row in stored_rows
        ]
    return [{
        "nature_of_violation": record.Description or "",
        "person_responsible": person_details.get("name", record.CreatedBy),
        "files": [],
    }]


def _serialize_self_declaration_record(
    record_type: str,
    record,
    record_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": record_id,
        "declaration_type": record_type,
        "subType": record.SubType,
        "status": record.Status,
        "overallStatus": record.OverallStatus,
        "pendingAt": record.PendingAt,
        "createdBy": record.CreatedBy,
        "createdOn": (
            record.CreatedOn.isoformat() if record.CreatedOn else None
        ),
        "closureDate": (
            record.ClosureDate.isoformat() if record.ClosureDate else None
        ),
        "closedBy": record.ClosedBy,
        "responseJsonPath": record.ResponseJsonPath,
    }

    if record_type == "cobce":
        payload["description"] = record.Description
        payload["rows"] = _cobce_rows_from_record(record)
    else:
        payload["formData"] = record.FormData or {}

    return payload


async def get_self_declaration_by_id(
    record_id: str,
    staff_id: str,
    is_admin: bool,
) -> dict[str, Any]:
    """Fetch COBCE / COI self-declaration by composite record id."""
    try:
        _, record_type, db_id = await resolve_record(record_id)
    except ValueError as exc:
        raise ValueError("Declaration not found") from exc

    if record_type not in SELF_DECLARATION_TYPES:
        raise ValueError("Not a self-declaration record")

    if record_type == "cobce":
        record = await db_manager.get(COBCEDeclarations, db_id)
    else:
        record = await db_manager.get(COIDeclarations, db_id)

    if not record:
        raise ValueError("Declaration not found")

    if record.CreatedBy != staff_id and not is_admin:
        raise ValueError("Unauthorized")

    data = _serialize_self_declaration_record(record_type, record, db_id)

    if record.Status == "Draft" or record.OverallStatus == "Closed":
        data["pendingAt"] = "-"
    else:
        data["pendingAt"] = await format_pending_at(
            record.PendingAt,
            record.CreatedBy,
            is_admin=is_admin,
            assigned_to=getattr(record, "AssignedTo", None),
        )
    data["actor_name"] = await format_actor_name(record.CreatedBy)
    data["closed_by_name"] = await format_actor_name(record.ClosedBy)

    if record.ResponseJsonPath:
        try:
            data["conversation"] = await load_json(record.ResponseJsonPath)
            for entry in data["conversation"].get("conversation", []) or []:
                entry["files"] = await resolve_file_urls(entry.get("files"))
        except Exception:
            data["conversation"] = None

    if record_type == "coi" and data.get("formData") and "files" in data["formData"]:
        data["formData"] = dict(data["formData"])
        data["formData"]["files"] = await resolve_file_urls(data["formData"]["files"])

    if record_type == "cobce" and data.get("rows"):
        rows_out = []
        for row in data["rows"]:
            row_out = dict(row)
            if row_out.get("files"):
                row_out["files"] = await resolve_file_urls(row_out["files"])
            rows_out.append(row_out)
        data["rows"] = rows_out

    return data
