from fastapi import APIRouter
from .query_routes import router as query_router
from .gift_routes import router as gift_router
from .complaint_routes import router as complaint_router
from .cobce_routes import router as cobce_router
from .coi_routes import router as coi_router
from .generic_routes import router as generic_router

router = APIRouter()

# Aggregator router for all compliance helpdesk endpoints.
router.include_router(query_router)
router.include_router(gift_router)
router.include_router(complaint_router)
router.include_router(cobce_router)
router.include_router(coi_router)
router.include_router(generic_router)
