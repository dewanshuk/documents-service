from fastapi import APIRouter

from core.openapi_tags import TAG_HEALTH

router = APIRouter(tags=[TAG_HEALTH])


@router.get("/health")
async def health_check():
    return {"status": "ok"}
