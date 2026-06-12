import json
from typing import Any

from fastapi import UploadFile
from fastapi.responses import JSONResponse

from db.db_manager import db_manager
from db.models.helpdesk import COBCEDeclarations, COIDeclarations
from db.validators.comp_help import validate_coi_form
from storage.storage_ops import init_json, upload_files
from utils.helpers import db_timestamp_now, now_ist
from utils.record_ids import build_record_id, new_suffix


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
    record_id = build_record_id(staff_id, new_suffix())
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
            "OverallStatus": None,
            "PendingAt": None,
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
            "Status": "In_Progress",
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
                },
            )
        else:
            draft_record_id = build_record_id(staff_id, new_suffix())
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
                    "OverallStatus": None,
                    "PendingAt": None,
                    "ResponseJsonPath": None,
                },
            )

        return {
            "id": draft_record_id,
            "status": "Draft",
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
            "status": "In_Progress",
            "declaration_type": "cobce",
            "row_count": 1,
        }

    return {
        "ids": created_ids,
        "status": "In_Progress",
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
            {"FormData": form_data, "SubType": sub_type},
        )
    else:
        record_id = build_record_id(staff_id, new_suffix())
        await db_manager.create(
            COIDeclarations,
            {
                "COIId": record_id,
                "SubType": sub_type,
                "FormData": form_data,
                "Status": "Draft",
                "CreatedOn": db_timestamp_now(),
                "CreatedBy": staff_id,
                "PendingAt": None,
                "OverallStatus": None,
                "ResponseJsonPath": None,
            },
        )

    if status == "draft":
        return {"id": record_id, "status": "Draft", "declaration_type": "coi"}

    record = await db_manager.get(COIDeclarations, record_id)
    now = now_ist()
    file_paths = await upload_files(record_id, "user", files)
    json_data = {
        "id": record_id,
        "conversation": [
            {
                "actor": "User",
                "actorId": staff_id,
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
            "Status": "In-Progress",
            "PendingAt": 1,
            "OverallStatus": "Pending",
            "ResponseJsonPath": json_path,
        },
    )
    return {
        "id": record_id,
        "status": "In-Progress",
        "declaration_type": "coi",
    }
