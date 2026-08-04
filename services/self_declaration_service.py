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
from storage.storage_ops import init_json, load_json, upload_files, resolve_file_urls
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
            })
        return normalized

    if description:
        return [{
            "nature_of_violation": description,
            "person_responsible": staff_id,
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
    """
    decl_type = declaration_type.lower()
    if decl_type not in ("cobce", "coi"):
        raise ValueError("declaration_type must be 'cobce' or 'coi'")
    if status not in ("draft", "submit"):
        raise ValueError("status must be 'draft' or 'submit'")

    if decl_type == "cobce":
        return await _save_cobce(
            staff_id, status, sub_type, record_id, description, files or [], rows
        )
    return await _save_coi(
        staff_id, status, sub_type, record_id, form_data or {}, files or []
    )


async def _submit_cobce_record(
    staff_id: str,
    sub_type: str,
    row: dict,
    files: list[UploadFile],
    attach_files: bool,
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
    file_paths = (
        await upload_files(record_id, "user", files) if attach_files else []
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
                "files": file_paths,
            }
        ],
    }
    json_path = await init_json(record_id, json_data)
    await db_manager.update(
        COBCEDeclarations,
        record_id,
        {
            "Status": "Completed",
            "PendingAt": 0,
            "OverallStatus": "Completed",
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

    if status == "draft":
        if draft_record_id:
            record = await db_manager.get(COBCEDeclarations, draft_record_id)
            if not record:
                raise ValueError("Declaration not found")
            if record.CreatedBy != staff_id:
                raise ValueError("Unauthorized")
            if record.Status != "Draft":
                raise ValueError("Only draft declarations can be edited")

            await db_manager.update(
                COBCEDeclarations,
                draft_record_id,
                {
                    "Description": cobce_rows[0]["nature_of_violation"],
                    "SubType": sub_type,
                    "PersonDetails": {
                        "name": cobce_rows[0]["person_responsible"],
                        "rows": cobce_rows,
                    },
                    "OverallStatus": "Draft",
                    "PendingAt": 0,
                },
            )
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
                        "rows": cobce_rows,
                    },
                    "Status": "Draft",
                    "CreatedOn": db_timestamp_now(),
                    "CreatedBy": staff_id,
                    "OverallStatus": "Draft",
                    "PendingAt": 0,
                    "ResponseJsonPath": None,
                },
            )

        return {
            "id": draft_record_id,
            "status": "Draft",
            "overall_status": "Draft",
            "declaration_type": "cobce",
            "row_count": len(cobce_rows),
        }

    created_ids: list[str] = []
    for index, row in enumerate(cobce_rows):
        created_ids.append(
            await _submit_cobce_record(
                staff_id,
                sub_type,
                row,
                files,
                attach_files=(index == 0),
            )
        )

    if draft_record_id:
        draft = await db_manager.get(COBCEDeclarations, draft_record_id)
        if draft and draft.Status == "Draft" and draft.CreatedBy == staff_id:
            await db_manager.delete(COBCEDeclarations, draft_record_id)

    if len(created_ids) == 1:
        return {
            "id": created_ids[0],
            "status": "Completed",
            "overall_status": "Completed",
            "declaration_type": "cobce",
            "row_count": 1,
        }

    return {
        "ids": created_ids,
        "status": "Completed",
        "overall_status": "Completed",
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
    if status == "submit":
        errors = _coi_validation_errors(sub_type, form_data)
        if errors:
            raise ValueError("; ".join(errors))

    if record_id:
        record = await db_manager.get(COIDeclarations, record_id)
        if not record:
            raise ValueError("Declaration not found")
        if record.CreatedBy != staff_id:
            raise ValueError("Unauthorized")
        if record.Status != "Draft":
            raise ValueError("Only draft declarations can be edited")

        await db_manager.update(
            COIDeclarations,
            record_id,
            {
                "FormData": form_data,
                "SubType": sub_type,
                "OverallStatus": "Draft",
                "PendingAt": 0,
            },
        )
    else:
        record_id = await next_self_decl_id(staff_id)
        await db_manager.create(
            COIDeclarations,
            {
                "COIId": record_id,
                "SubType": sub_type,
                "FormData": form_data,
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
    file_paths = await upload_files(record_id, "user", files)
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
                "files": file_paths,
            }
        ],
    }
    json_path = await init_json(record_id, json_data)
    await db_manager.update(
        COIDeclarations,
        record_id,
        {
            "Status": "Completed",
            "PendingAt": 0,
            "OverallStatus": "Completed",
            "ResponseJsonPath": json_path,
        },
    )
    return {
        "id": record_id,
        "status": "Completed",
        "overall_status": "Completed",
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
            }
            for row in stored_rows
        ]
    return [{
        "nature_of_violation": record.Description or "",
        "person_responsible": person_details.get("name", record.CreatedBy),
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
        data["pendingAt"] = await format_pending_at(record.PendingAt, record.CreatedBy)
    data["actor_name"] = await format_actor_name(record.CreatedBy)
    data["closed_by_name"] = await format_actor_name(record.ClosedBy)

    if record.ResponseJsonPath:
        try:
            data["conversation"] = await load_json(record.ResponseJsonPath)
            for entry in data["conversation"].get("conversation", []) or []:
                entry["files"] = await resolve_file_urls(entry.get("files"))
        except Exception:
            data["conversation"] = None

    return data
