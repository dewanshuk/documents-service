from api.routes.helpdesk import compliance_helpdesk
from fastapi import FastAPI
from db.db_manager import init_db
from db.models.helpdesk import Base
from db.models.annual_dec import Base as AnnualBase
from contextlib import asynccontextmanager
from storage.storage_ops import close_clients as close_storage_clients
from db.redis_cache import close_redis
from utils.loggers import init_ai_logger
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from core import config
from api.routes.annual_dec import  annual_declaration_router
# IMPORT YOUR COMPLIANCE ROUTER
from api.routes.helpdesk import health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(Base)
    await init_db(AnnualBase)
    init_ai_logger()
    yield
    await close_storage_clients()
    await close_redis()


app = FastAPI(
    lifespan=lifespan,
    docs_url="/api/compliance/docs",
    redoc_url="/api/compliance/redoc",
    openapi_url="/api/compliance/openapi.json",
    title="Compliance Helpdesk API",
    description="API for managing compliance helpdesk queries including raise, respond, close, and view operations.",
    version="1.0.0",
)


# Security Middleware (unchanged)
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        docs_paths = [
            "/api/compliance/docs",
            "/api/compliance/redoc",
            "/api/compliance/openapi.json",
        ]

        if any(request.url.path.startswith(path) for path in docs_paths):
            for header, value in config.SECURITY_RESPONSE_HEADERS.items():
                if header != "Content-Security-Policy":
                    response.headers[header] = value
        else:
            for header, value in config.SECURITY_RESPONSE_HEADERS.items():
                response.headers[header] = value

        return response


app.add_middleware(SecurityHeadersMiddleware)


# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)


# ROUTERS

app.include_router(annual_declaration_router.router, prefix="/api/declarations", tags=["Annual Declarations"])
# Health
app.include_router(
    health_router.router,
    tags=["Health"],
    prefix="/api/compliance"
)

# Compliance Helpdesk 
app.include_router(
    compliance_helpdesk.router,
    tags=["Compliance Helpdesk"],
    prefix="/api/compliance"
)
