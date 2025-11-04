import logging
import os
import traceback
from typing import Optional

try:  # pragma: no cover - optional dependency
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
except ImportError:  # pragma: no cover - optional dependency
    sentry_sdk = None  # type: ignore[assignment]
    LoggingIntegration = None  # type: ignore[assignment]

from backend.db import RunHistory, get_session

_logger = logging.getLogger("freeagent")
_initialized = False


def init_monitoring() -> None:
    global _initialized
    if _initialized:
        return

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    dsn = os.getenv("SENTRY_DSN")
    if dsn and sentry_sdk and LoggingIntegration:
        sentry_logging = LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
        sentry_sdk.init(
            dsn=dsn,
            integrations=[sentry_logging],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("ENVIRONMENT", "development")),
        )
        _logger.info("Sentry initialized")
    else:
        _logger.info("Sentry DSN not provided; skipping initialization")

    _initialized = True


async def record_run(
    *,
    stage: str,
    user_id: str,
    lead_id: Optional[int],
    success: bool,
    duration_ms: float,
    error_text: Optional[str] = None,
) -> None:
    entry = RunHistory(
        user_id=user_id,
        lead_id=lead_id,
        stage=stage,
        success=success,
        error_text=error_text[:1024] if error_text else None,
        duration_ms=duration_ms,
    )
    async with get_session() as session:
        session.add(entry)
        await session.commit()


def capture_exception(exc: BaseException) -> None:
    _logger.error("Exception captured", exc_info=exc)
    if sentry_sdk and sentry_sdk.Hub.current.client:
        sentry_sdk.capture_exception(exc)


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
