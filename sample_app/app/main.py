import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.faults import DEPENDENCY_NAME, FaultType, fault_manager
from app.logging_config import setup_logging
from app.metrics import (
    APP_DEPLOY_INFO,
    DB_HEALTHY,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)

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
    APP_DEPLOY_INFO.labels(version="1.2.2").set(1)
    APP_DEPLOY_INFO.labels(version="1.2.3-bad").set(0)
    health_task = asyncio.create_task(_check_db_health_loop())
    yield
    health_task.cancel()
    await fault_manager.deactivate()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(title="sample_app", lifespan=lifespan)


class FaultActivateRequest(BaseModel):
    duration_seconds: int = Field(default=60, ge=1, le=600)


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


@app.post("/admin/faults/{fault_type}")
async def activate_fault(
    fault_type: FaultType, body: FaultActivateRequest
) -> dict[str, str | int]:
    await fault_manager.activate(fault_type, body.duration_seconds)
    return {
        "status": "activated",
        "fault_type": fault_type.value,
        "duration_seconds": body.duration_seconds,
    }


@app.delete("/admin/faults/{fault_type}")
async def deactivate_fault(fault_type: FaultType) -> dict[str, str]:
    if fault_manager.active_fault != fault_type:
        raise HTTPException(
            status_code=404,
            detail=f"fault {fault_type.value} is not active",
        )
    await fault_manager.deactivate()
    return {"status": "deactivated", "fault_type": fault_type.value}


@app.get("/admin/faults")
async def list_faults() -> dict[str, str | None]:
    active = fault_manager.active_fault
    return {"active_fault": active.value if active else None}


@app.get("/order/{order_id}", response_model=None)
async def get_order(order_id: int) -> dict[str, Any] | JSONResponse:
    start = time.perf_counter()
    endpoint = f"/order/{order_id}"

    if fault_manager.is_active(FaultType.BAD_DEPLOY):
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.error(
            "application error",
            service="sample_app",
            endpoint=endpoint,
            method="GET",
            latency_ms=latency_ms,
            status_code=500,
            error="invalid configuration after deploy",
            version="1.2.3-bad",
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "invalid configuration after deploy"},
        )

    if fault_manager.is_active(FaultType.DEPENDENCY_TIMEOUT):
        try:
            await fault_manager.apply_dependency_timeout()
        except TimeoutError:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error(
                "dependency timeout",
                service="sample_app",
                endpoint=endpoint,
                method="GET",
                latency_ms=latency_ms,
                status_code=504,
                error=f"{DEPENDENCY_NAME} timed out",
                dependency=DEPENDENCY_NAME,
            )
            return JSONResponse(
                status_code=504,
                content={"detail": "inventory_service timed out"},
            )

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT id, customer_name, status, amount "
                    "FROM orders WHERE id = :id"
                ),
                {"id": order_id},
            )
            row = result.mappings().fetchone()
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.error(
            "database error",
            service="sample_app",
            endpoint=endpoint,
            method="GET",
            latency_ms=latency_ms,
            status_code=500,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "database error"},
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    return {
        "id": row["id"],
        "customer_name": row["customer_name"],
        "status": row["status"],
        "amount": float(row["amount"]),
    }
