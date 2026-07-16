from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse, JSONResponse
from datetime import datetime

from db.db_manager import db_manager
from db.models import AnnualDeclaration, DeclarationType, as_declaration_name
from db.validators import (
    AnnualDeclarationCreate,
    AnnualDeclarationFilters,
    SaveDeclarationRequest,
)
from services.declaration_service import (
    save_user_declaration,
    list_declarations,
    get_declaration_user_responses,
    invalidate_declarations_list_cache,
    get_user_declaration_status,
)
from services.head_summary_service import (
    HeadSummaryAccessError,
    generate_head_summary_export,
    get_head_summary,
)
from services.excel_sync_service import process_declaration_excel
from storage.storage_ops import (
    upload_bytes,
    download_to_stream,
    ANNUAL_DECLARATION_BLOB_NAME,
)
from utils.deps import get_current_user
from utils.record_ids import next_annual_cycle_ref

router = APIRouter()


@router.post("/create-declaration")
async def create_declaration(
    payload: AnnualDeclarationCreate,
    current_user: dict = Depends(get_current_user),
):
    try:
        decl_name = as_declaration_name(payload.declaration_name)
        existing = await db_manager.list(
            AnnualDeclaration,
            filters={
                "declaration_name": decl_name,
                "financial_year": payload.financial_year,
            },
            limit=1,
            offset=0,
            include_total=True,
        )
        if existing["total"] > 0:
            raise HTTPException(
                status_code=409, detail="Declaration cycle already exists"
            )

        data = payload.model_dump()
        data["declaration_name"] = decl_name
        data["id"] = await next_annual_cycle_ref()
        created = await db_manager.create(AnnualDeclaration, data)
        await invalidate_declarations_list_cache()
        return JSONResponse(
            content={
                "message": "Declaration record created successfully",
                "id": created.id,
            },
            status_code=201,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/list-declarations")
async def list_declarations_endpoint(
    filters: AnnualDeclarationFilters = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    if not current_user.get("is_master_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    data = await list_declarations(filters, page, page_size)
    return JSONResponse(content=data, status_code=200)


@router.get("/declaration-responses/{declaration_id}")
async def declaration_responses(
    declaration_id: str,
    staff_id: str | None = Query(
        None, description="Required for master admin; ignored for regular users"
    ),
    current_user: dict = Depends(get_current_user),
):
    target_staff_id = current_user["staff_id"]
    if current_user.get("is_master_admin"):
        if not staff_id:
            raise HTTPException(
                status_code=400,
                detail="staff_id query parameter is required for admin",
            )
        target_staff_id = staff_id
    elif staff_id and staff_id != current_user["staff_id"]:
        raise HTTPException(status_code=403, detail="Cannot view another user's responses")

    try:
        data = await get_declaration_user_responses(declaration_id, target_staff_id)
        return JSONResponse(content=data, status_code=200)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/save-declaration/{declaration_id}")
async def save_declaration(
    declaration_id: str,
    payload: SaveDeclarationRequest,
    current_user: dict = Depends(get_current_user),
):
    """Unified save: status=draft (partial) or status=submit (all mandatory fields)."""
    try:
        responses = [r.model_dump() for r in payload.responses]
        result = await save_user_declaration(
            declaration_id,
            current_user["staff_id"],
            responses,
            status=payload.status,
        )
        message = (
            "Declaration submitted successfully"
            if payload.status == "submit"
            else "Draft saved successfully"
        )
        return JSONResponse(content={"message": message, **result}, status_code=200)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/upload-declaration-file/{declaration_id}")
async def upload_declaration_file(
    declaration_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        declaration = await db_manager.get(AnnualDeclaration, declaration_id)
        if not declaration:
            raise HTTPException(status_code=404, detail="Declaration not found")

        file_content = await file.read()
        try:
            process_result = await process_declaration_excel(declaration_id, file_content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to process Excel file: {exc}",
            ) from exc

        blob_name = ANNUAL_DECLARATION_BLOB_NAME
        await upload_bytes(blob_name, file_content)
        await db_manager.update(
            AnnualDeclaration,
            declaration_id,
            {
                "file_path": blob_name,
                "last_uploaded_file_at": datetime.now(),
                "last_uploaded_by": current_user["staff_id"],
            },
        )
        await invalidate_declarations_list_cache()
        return JSONResponse(
            content={
                "message": "File uploaded and processed successfully",
                **process_result,
            },
            status_code=201,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/download-declaration-file")
async def download_declaration_file(
    current_user: dict = Depends(get_current_user),
):
    """Download the annual declaration template file from blob storage."""
    try:
        stream = await download_to_stream(ANNUAL_DECLARATION_BLOB_NAME)
        return StreamingResponse(
            stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{ANNUAL_DECLARATION_BLOB_NAME}"'
                )
            },
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Declaration file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/head-summary")
async def head_summary(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("staff_id") if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        summary = await get_head_summary(user_id)
        return JSONResponse(content={"summary": summary}, status_code=200)
    except HeadSummaryAccessError as exc:
        return JSONResponse(
            content={"error": exc.message}, status_code=exc.status_code
        )


@router.get("/head-summary/export")
async def export_head_summary(
    declaration_name: DeclarationType = Query(
        ..., description="Declaration type: COBCE/COI or R5.18"
    ),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("staff_id") if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        stream, filename = await generate_head_summary_export(
            user_id, declaration_name
        )
        return StreamingResponse(
            stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HeadSummaryAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

@router.get("/user-declaration-status")
async def user_declaration_status_endpoint(
    current_user: dict = Depends(get_current_user),
):
    """Get the active annual declaration status for the current user."""
    try:
        staff_id = current_user["staff_id"]
        status_data = await get_user_declaration_status(staff_id)
        return JSONResponse(content=status_data, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/declarationtypes")
async def get_declaration_types():
    types = [e.value for e in DeclarationType]
    return JSONResponse(content={"declaration_types": types}, status_code=200)
