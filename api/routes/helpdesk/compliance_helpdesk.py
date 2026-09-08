from fastapi import APIRouter
from .query_routes import router as query_router
from .self_declaration_routes import router as self_declaration_router
from .generic_routes import router as generic_router
from .respond_routes import router as respond_router
from .dashboard_routes import router as dashboard_router
from .recent_activity_routes import router as recent_activity_router
from .admin_routes import router as admin_router

router = APIRouter()


router.include_router(recent_activity_router)
router.include_router(dashboard_router)
router.include_router(generic_router)
router.include_router(respond_router)
router.include_router(query_router)
router.include_router(self_declaration_router)
router.include_router(admin_router)
