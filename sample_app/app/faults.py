import asyncio
import time
from enum import Enum

import structlog

from app.metrics import (
    APP_DEPLOY_INFO,
    DOWNSTREAM_REQUEST_DURATION_SECONDS,
    DOWNSTREAM_TIMEOUTS_TOTAL,
    PROCESS_MEMORY_BYTES,
)

logger = structlog.get_logger()

DEPENDENCY_NAME = "inventory_service"
BAD_DEPLOY_VERSION = "1.2.3-bad"
MEMORY_CHUNK_BYTES = 10 * 1024 * 1024
MEMORY_STEP_INTERVAL_SECONDS = 5
MEMORY_OOM_THRESHOLD_BYTES = 80 * 1024 * 1024
DEPENDENCY_TIMEOUT_SECONDS = 5.0
DEPENDENCY_TIMEOUT_LIMIT_SECONDS = 2.0


class FaultType(str, Enum):
    MEMORY_EXHAUSTION = "memory_exhaustion"
    DEPENDENCY_TIMEOUT = "dependency_timeout"
    BAD_DEPLOY = "bad_deploy"


class FaultManager:
    def __init__(self) -> None:
        self._active: FaultType | None = None
        self._expire_task: asyncio.Task[None] | None = None
        self._memory_task: asyncio.Task[None] | None = None
        self._memory_chunks: list[bytearray] = []
        self._oom_logged = False
        self._bad_deploy_logged = False

    @property
    def active_fault(self) -> FaultType | None:
        return self._active

    def is_active(self, fault: FaultType) -> bool:
        return self._active == fault

    async def activate(self, fault: FaultType, duration_seconds: int) -> None:
        await self.deactivate()
        self._active = fault
        self._oom_logged = False
        self._bad_deploy_logged = False

        if fault is FaultType.MEMORY_EXHAUSTION:
            self._memory_task = asyncio.create_task(self._memory_exhaustion_loop())
        elif fault is FaultType.BAD_DEPLOY:
            self._log_bad_deploy()

        self._expire_task = asyncio.create_task(
            self._auto_deactivate(duration_seconds)
        )
        logger.info(
            "fault activated",
            service="sample_app",
            fault_type=fault.value,
            duration_seconds=duration_seconds,
        )

    async def deactivate(self) -> None:
        if self._expire_task is not None:
            self._expire_task.cancel()
            try:
                await self._expire_task
            except asyncio.CancelledError:
                pass
            self._expire_task = None

        if self._memory_task is not None:
            self._memory_task.cancel()
            try:
                await self._memory_task
            except asyncio.CancelledError:
                pass
            self._memory_task = None

        if self._active is FaultType.MEMORY_EXHAUSTION:
            self._memory_chunks.clear()
            PROCESS_MEMORY_BYTES.set(0)

        if self._active is FaultType.BAD_DEPLOY:
            APP_DEPLOY_INFO.labels(version=BAD_DEPLOY_VERSION).set(0)
            APP_DEPLOY_INFO.labels(version="1.2.2").set(1)

        if self._active is not None:
            logger.info(
                "fault deactivated",
                service="sample_app",
                fault_type=self._active.value,
            )

        self._active = None
        self._bad_deploy_logged = False

    async def _auto_deactivate(self, duration_seconds: int) -> None:
        await asyncio.sleep(duration_seconds)
        self._expire_task = None
        await self.deactivate()

    async def _memory_exhaustion_loop(self) -> None:
        while True:
            self._memory_chunks.append(bytearray(MEMORY_CHUNK_BYTES))
            total_bytes = sum(len(chunk) for chunk in self._memory_chunks)
            PROCESS_MEMORY_BYTES.set(total_bytes)

            if total_bytes >= MEMORY_OOM_THRESHOLD_BYTES and not self._oom_logged:
                self._oom_logged = True
                logger.error(
                    "oom condition detected",
                    service="sample_app",
                    endpoint="/system",
                    method="INTERNAL",
                    latency_ms=0.0,
                    status_code=500,
                    memory_bytes=total_bytes,
                    error="memory limit exceeded",
                )
                logger.error(
                    "process restarting due to OOM",
                    service="sample_app",
                    endpoint="/system",
                    method="INTERNAL",
                    latency_ms=0.0,
                    status_code=500,
                    error="simulated OOM restart",
                )
                self._memory_chunks.clear()
                PROCESS_MEMORY_BYTES.set(0)

            await asyncio.sleep(MEMORY_STEP_INTERVAL_SECONDS)

    def _log_bad_deploy(self) -> None:
        if self._bad_deploy_logged:
            return

        self._bad_deploy_logged = True
        APP_DEPLOY_INFO.labels(version="1.2.2").set(0)
        APP_DEPLOY_INFO.labels(version=BAD_DEPLOY_VERSION).set(1)

        logger.info(
            "config reload completed",
            service="sample_app",
            endpoint="/system",
            method="POST",
            latency_ms=0.0,
            status_code=200,
            version=BAD_DEPLOY_VERSION,
        )
        logger.info(
            "deploy completed",
            service="sample_app",
            endpoint="/system",
            method="POST",
            latency_ms=0.0,
            status_code=200,
            version=BAD_DEPLOY_VERSION,
        )

    async def apply_dependency_timeout(self) -> None:
        start = time.perf_counter()
        try:
            await asyncio.wait_for(
                asyncio.sleep(DEPENDENCY_TIMEOUT_SECONDS),
                timeout=DEPENDENCY_TIMEOUT_LIMIT_SECONDS,
            )
        except TimeoutError:
            duration = time.perf_counter() - start
            DOWNSTREAM_REQUEST_DURATION_SECONDS.labels(
                dependency=DEPENDENCY_NAME
            ).observe(duration)
            DOWNSTREAM_TIMEOUTS_TOTAL.labels(dependency=DEPENDENCY_NAME).inc()
            raise


fault_manager = FaultManager()
