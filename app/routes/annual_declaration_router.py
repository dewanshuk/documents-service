import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse
from datetime import datetime
from db.db_manager import db_manager
from db.models import AnnualDeclaration, DeclarationType
from db.validators import AnnualDeclarationCreate, AnnualDeclarationFilters
from services.declaration_service import enrich_declaration_data
from storage.storage_ops import upload_bytes, download_to_stream
from utils.deps import get_current_user

router = APIRouter()

@router.post("/create_declaration")
async def create_declaration(payload: AnnualDeclarationCreate,
    current_user: dict = Depends(get_current_user)
):
    try:
        
        declaration_type_enum = payload.declaration_name
        existing = await db_manager.list(
            AnnualDeclaration,
            filters={
                "declaration_name": declaration_type_enum,
                "financial_year": payload.financial_year,
            },
            limit=1,
            offset=0,
            include_total=True,
        )
        if existing["total"] > 0:
            raise HTTPException(status_code=409, detail="Declaration cycle already exists")

        create_payload = payload.model_dump()
        await db_manager.create(AnnualDeclaration, create_payload)
        return JSONResponse(content={"message": "Declaration record created successfully"}, status_code=201)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/list_declarations")
async def list_declarations(
    filters: AnnualDeclarationFilters = Depends(),
    page: int = 1,
    page_size: int = 25,
    current_user: dict = Depends(get_current_user)
):
    try:
        query_filters = {}
        if filters.declaration_name:
            query_filters["declaration_name"] = {"$ilike": filters.declaration_name}
        if filters.financial_year:
            query_filters["financial_year"] = filters.financial_year
        if filters.assigned_date_from or filters.assigned_date_to:
            query_filters["assigned_date"] = {}
            if filters.assigned_date_from:
                query_filters["assigned_date"]["$gte"] = filters.assigned_date_from
            if filters.assigned_date_to:
                query_filters["assigned_date"]["$lte"] = filters.assigned_date_to
        if filters.due_date_from or filters.due_date_to:
            query_filters["due_date"] = {}
            if filters.due_date_from:
                query_filters["due_date"]["$gte"] = filters.due_date_from
            if filters.due_date_to:
                query_filters["due_date"]["$lte"] = filters.due_date_to
        if filters.activity_closure_date_from or filters.activity_closure_date_to:
            query_filters["activity_closure_date"] = {}
            if filters.activity_closure_date_from:
                query_filters["activity_closure_date"]["$gte"] = filters.activity_closure_date_from
            if filters.activity_closure_date_to:
                query_filters["activity_closure_date"]["$lte"] = filters.activity_closure_date_to

        offset = (page - 1) * page_size
        result = await db_manager.list(
            AnnualDeclaration,
            filters=query_filters,
            limit=page_size,
            offset=offset,
            include_total=True
        )

        return JSONResponse(
            content={
                "items": enrich_declaration_data(result["items"]),
                "total": result["total"],
                "page": page,
                "page_size": page_size,
                "offset": offset,
            },
            status_code=200,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload_declaration_file/{declaration_id}")
async def upload_declaration_file(
    declaration_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    try:
        declaration = await db_manager.get(AnnualDeclaration, declaration_id)
        if not declaration:
            raise HTTPException(status_code=404, detail="Declaration not found")

        file_content = await file.read()
        blob_name = f"declaration_{declaration_id}_{file.filename}"
        await upload_bytes(
            blob_name,
            file_content,
        )
        await db_manager.update(
            AnnualDeclaration,
            declaration_id,
            {
                "file_path": blob_name,
                "last_uploaded_file_at": datetime.now(),
                "last_uploaded_by": current_user["staff_id"],
            },
        )
        return JSONResponse(content={"message": "File uploaded successfully"}, status_code=201)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/download_declaration_file/{declaration_id}")
async def download_declaration_file(
    declaration_id: uuid.UUID,
    current_user: dict = Depends(get_current_user)
):
    try:
        declaration = await db_manager.get(AnnualDeclaration, declaration_id)
        if not declaration or not declaration.file_path:
            raise HTTPException(status_code=404, detail="Declaration file not found")
        file_stream = await download_to_stream(declaration.file_path)
        filename = os.path.basename(declaration.file_path)
        return StreamingResponse(
            file_stream,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename}\"",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/declarationtypes")
async def get_declaration_types():
    try:
        types = [e.value for e in DeclarationType]
        return JSONResponse(content={"declaration_types": types}, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))