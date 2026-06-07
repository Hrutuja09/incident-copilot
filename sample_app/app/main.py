import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.logging_config import setup_logging

setup_logging()

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/incidents",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


app = FastAPI(title="sample_app", lifespan=lifespan)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Any) -> Any:
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "http request",
        service="sample_app",
        endpoint=request.url.path,
        method=request.method,
        latency_ms=latency_ms,
        status_code=response.status_code,
    )
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/order/{order_id}")
async def get_order(order_id: int) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id, customer_name, status, amount "
                "FROM orders WHERE id = :id"
            ),
            {"id": order_id},
        )
        row = result.mappings().fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    return {
        "id": row["id"],
        "customer_name": row["customer_name"],
        "status": row["status"],
        "amount": float(row["amount"]),
    }
