import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse, JSONResponse
from datetime import datetime

from db.db_manager import db_manager
from db.models import AnnualDeclaration, DeclarationType, SyncStatus, as_declaration_name
from db.validators import (
    AnnualDeclarationCreate,
    AnnualDeclarationFilters,
    SaveDeclarationRequest,
)
from services.declaration_service import (
    save_user_declaration,
    list_declarations,
    get_declaration_user_responses,
)
from services.excel_service import generate_declaration_report
from services.excel_sync_service import sync_pending_declarations
from storage.storage_ops import upload_bytes
from utils.deps import get_current_user

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
        await db_manager.create(AnnualDeclaration, data)
        return JSONResponse(
            content={"message": "Declaration record created successfully"},
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
    declaration_id: uuid.UUID,
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
    declaration_id: uuid.UUID,
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
    declaration_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        declaration = await db_manager.get(AnnualDeclaration, declaration_id)
        if not declaration:
            raise HTTPException(status_code=404, detail="Declaration not found")

        file_content = await file.read()
        blob_name = f"declaration_{declaration_id}_{file.filename}"
        await upload_bytes(blob_name, file_content)
        await db_manager.update(
            AnnualDeclaration,
            declaration_id,
            {
                "file_path": blob_name,
                "last_uploaded_file_at": datetime.now(),
                "last_uploaded_by": current_user["staff_id"],
                "sync_status": SyncStatus.PENDING,
            },
        )
        return JSONResponse(
            content={
                "message": "File uploaded successfully",
                "sync_status": SyncStatus.PENDING.value,
                "pending_count": declaration.pending_count,
                "total_count": declaration.total_count,
                "excel_pending_status": declaration.excel_pending_status,
            },
            status_code=201,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sync-declaration-file")
async def sync_declaration_file_endpoint(
    current_user: dict = Depends(get_current_user),
):
    """Process all Pending declarations that have an uploaded file."""
    try:
        result = await sync_pending_declarations()
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download-declaration-file/{declaration_id}")
async def download_declaration_file(
    declaration_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    """Download Excel built from user_declaration_status + user_declaration_responses."""
    declaration = await db_manager.get(AnnualDeclaration, declaration_id)
    if not declaration:
        raise HTTPException(status_code=404, detail="Declaration not found")

    try:
        report = await generate_declaration_report(declaration_id)
        decl_name = as_declaration_name(declaration.declaration_name).replace("/", "_")
        filename = (
            f"Declaration_Report_{decl_name}_FY_{declaration.financial_year}.xlsx"
        )
        return StreamingResponse(
            report,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/declarationtypes")
async def get_declaration_types():
    types = [e.value for e in DeclarationType]
    return JSONResponse(content={"declaration_types": types}, status_code=200)
