from fastapi import FastAPI
from db.db_manager import init_db
from db.models import Base
from contextlib import asynccontextmanager
from storage.storage_ops import close_clients as close_storage_clients
from app.routes.annual_declaration_router import router as annual_declaration_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(Base)

    yield
    await close_storage_clients()



app = FastAPI(lifespan=lifespan,
              docs_url="/docs", 
              redoc_url="/redoc",
              title="ECP Annual Declaration API",
              description="API for managing annual declarations in the ECP system, including declaration creation, retrieval, updating, and deletion.",
              version="1.0.0"
              )

app.include_router(annual_declaration_router)