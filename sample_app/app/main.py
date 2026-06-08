import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import make_asgi_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.logging_config import setup_logging
from app.metrics import DB_HEALTHY, HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL

setup_logging()

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/incidents",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _check_db_health_loop() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            DB_HEALTHY.set(1.0)
        except Exception:
            DB_HEALTHY.set(0.0)
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    health_task = asyncio.create_task(_check_db_health_loop())
    yield
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(title="sample_app", lifespan=lifespan)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Any) -> Any:
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    endpoint = request.url.path
    method = request.method
    status_code = str(response.status_code)

    HTTP_REQUESTS_TOTAL.labels(
        method=method, endpoint=endpoint, status_code=status_code
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(
        duration
    )

    latency_ms = round(duration * 1000, 2)
    logger.info(
        "http request",
        service="sample_app",
        endpoint=endpoint,
        method=method,
        latency_ms=latency_ms,
        status_code=response.status_code,
    )
    return response


app.mount("/metrics", make_asgi_app())


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
