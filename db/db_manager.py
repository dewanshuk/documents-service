from typing import Any, Optional, Type, TypeVar, List, Dict, Union
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeMeta
from sqlalchemy import select, text, cast, String
from sqlalchemy.sql import Select , and_, or_, func
import os

POSTGRES_USER = os.getenv("POSTGRES_USER", "authuser")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "authpass")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_DB = os.getenv("POSTGRES_DB", "auth-flow")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))


# POSTGRES_USER = get_secret_sync("POSTGRES-USER")
# POSTGRES_PASSWORD = get_secret_sync("POSTGRES-PASSWORD")
# POSTGRES_HOST = get_secret_sync("POSTGRES-HOST")
# POSTGRES_DB = config.POSTGRES_DB
# DB_PORT = 5432
POSTGRES_URL = (
    f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{DB_PORT}/{POSTGRES_DB}"
)


if not POSTGRES_URL:
    raise RuntimeError("PostgreSQL connection URL not found in Key Vault.")

engine: AsyncEngine = create_async_engine(
    POSTGRES_URL,
    echo=False,       # flip to True for SQL debugging
    future=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
)

async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

@asynccontextmanager
async def get_session():
    session = async_session_factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

ModelType = TypeVar("ModelType", bound=DeclarativeMeta)

def _model_pk_col(model: Type[ModelType]):
    """Return the mapped primary key column of the model."""
    return model.__mapper__.primary_key[0]

def _attrs_from_names(model: Type[ModelType], columns: List[str]):
    attrs = []
    for name in columns:
        if not hasattr(model, name):
            raise ValueError(f"Column '{name}' not found on model '{model.__name__}'.")
        attrs.append(getattr(model, name))
    return attrs

class DBManager:
    async def create(self, model: Type[ModelType], data: Dict[str, Any]) -> ModelType:
        async with get_session() as session:
            obj = model(**data)
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj

    # ----- GET BY PRIMARY KEY (with optional column projection) -----
    async def get(
        self,
        model: Type[ModelType],
        obj_id: Any,
        columns: Optional[List[str]] = None,
    ):
        async with get_session() as session:
            if columns is None:
                return await session.get(model, obj_id)
            attrs = _attrs_from_names(model, columns)
            pk_col = _model_pk_col(model)
            stmt: Select = select(*attrs).where(pk_col == obj_id)
            row = (await session.execute(stmt)).one_or_none()
            if not row:
                return None
            return dict(zip(columns, row))

    # ----- LIST (filters + optional column projection + pagination) -----
    async def list(
        self,
        model: Type[ModelType],
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
        columns: Optional[List[str]] = None,
        order_by: Optional[List[str]] = None,
        include_total: bool = True,  # ✅ pagination metadata
    ):
        async with get_session() as session:

            # ✅ Base select
            if columns is None:
                stmt: Select = select(model)
            else:
                attrs = _attrs_from_names(model, columns)
                stmt = select(*attrs)

            # ✅ Helper: build AND conditions
            def build_conditions(filter_dict: Dict[str, Any]):
                conditions = []

                for key, value in filter_dict.items():
                    if not hasattr(model, key):
                        raise ValueError(
                            f"Filter column '{key}' not found on model '{model.__name__}'."
                        )

                    column = getattr(model, key)

                    if isinstance(value, dict):
                        for op, v in value.items():
                            if op == "$gte":
                                conditions.append(column >= v)
                            elif op == "$lte":
                                conditions.append(column <= v)
                            elif op == "$gt":
                                conditions.append(column > v)
                            elif op == "$lt":
                                conditions.append(column < v)
                            elif op == "$in":
                                conditions.append(column.in_(v))
                            elif op == "$ilike":
                                conditions.append(cast(column, String).ilike(f"%{v}%"))
                            else:
                                raise ValueError(
                                    f"Unsupported operator '{op}' for column '{key}'"
                                )
                    else:
                        conditions.append(column == value)

                return conditions

            # ✅ APPLY FILTERS (AND / OR)
            if filters:
                if "$or" in filters:
                    or_blocks = []

                    for or_filter in filters["$or"]:
                        and_conditions = build_conditions(or_filter)
                        if and_conditions:
                            or_blocks.append(and_(*and_conditions))

                    if or_blocks:
                        stmt = stmt.where(or_(*or_blocks))

                    remaining_filters = {k: v for k, v in filters.items() if k != "$or"}
                    if remaining_filters:
                        stmt = stmt.where(*build_conditions(remaining_filters))
                else:
                    stmt = stmt.where(*build_conditions(filters))

            # ✅ ORDER BY
            if order_by:
                ob_criteria = []
                for name in order_by:
                    desc = name.startswith("-")
                    col_name = name[1:] if desc else name

                    if not hasattr(model, col_name):
                        raise ValueError(
                            f"Order-by column '{col_name}' not found on model '{model.__name__}'."
                        )

                    col = getattr(model, col_name)
                    ob_criteria.append(col.desc() if desc else col.asc())

                if ob_criteria:
                    stmt = stmt.order_by(*ob_criteria)

            # ✅ TOTAL COUNT (before pagination)
            total = None
            if include_total:
                count_stmt = select(func.count()).select_from(
                    stmt.subquery()
                )
                total = await session.scalar(count_stmt)

            stmt = stmt.limit(limit).offset(offset)

            result = await session.execute(stmt)

            if columns is None:
                items = result.scalars().all()
            else:
                rows = result.all()
                items = [dict(zip(columns, r)) for r in rows]

            if include_total:
                return {
                    "items": items,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }

            return items

    # ----- UPDATE -----
    async def update(
        self,
        model: Type[ModelType],
        obj_id: Any,
        updates: Dict[str, Any],
    ):
        async with get_session() as session:
            db_obj = await session.get(model, obj_id)
            if not db_obj:
                return None
            for k, v in updates.items():
                if not hasattr(model, k):
                    raise ValueError(f"Column '{k}' not found on model '{model.__name__}'.")
                setattr(db_obj, k, v)
            await session.commit()
            await session.refresh(db_obj)
            return db_obj

    # ----- DELETE -----
    async def delete(self, model: Type[ModelType], obj_id: Any) -> bool:
        async with get_session() as session:
            db_obj = await session.get(model, obj_id)
            if not db_obj:
                return False
            await session.delete(db_obj)
            await session.commit()
            return True


# Singleton instance
db_manager = DBManager()

async def init_db(Base):
    """Create schemas and all tables defined in db.models."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS users"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS annual_declarations"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS compliance"))
        helpdesk_tables = [
            "compliance_queries",
            "gift_declarations",
            "complaints",
            "cobce_declarations",
            "coi_declarations",
            "r518_declarations",
        ]
        for tbl in helpdesk_tables:
            await conn.execute(text(
                f"ALTER TABLE compliance.{tbl} "
                "ADD COLUMN IF NOT EXISTS \"AssignedTo\" VARCHAR(255)"
            ))
            await conn.execute(text(
                f"ALTER TABLE compliance.{tbl} "
                "ADD COLUMN IF NOT EXISTS \"ClosedBy\" VARCHAR(255)"
            ))
            await conn.execute(text(
                f"ALTER TABLE compliance.{tbl} "
                "ADD COLUMN IF NOT EXISTS \"LastUpdatedOn\" TIMESTAMPTZ"
            ))

        await conn.execute(text("SET search_path TO compliance, public;"))
        await conn.run_sync(Base.metadata.create_all)
