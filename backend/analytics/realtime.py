import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - optional dependency
    Redis = None  # type: ignore[assignment]

CHANNEL_NAME = os.getenv("ANALYTICS_STREAM_CHANNEL", "analytics:runs")
DEFAULT_MAX_QUEUE_SIZE = int(os.getenv("ANALYTICS_STREAM_QUEUE", "256"))

logger = logging.getLogger("analytics.realtime")

_redis_client: Optional["Redis"] = None
_listener_task: Optional[asyncio.Task] = None
_listener_lock = asyncio.Lock()
_subscribers: Dict[asyncio.Queue, Optional[str]] = {}


async def _get_redis() -> Optional["Redis"]:
    global _redis_client
    if _redis_client or Redis is None:
        return _redis_client
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        _redis_client = Redis.from_url(url)
    except Exception as exc:  # pragma: no cover - fallback
        logger.warning("Failed to connect to Redis: %s", exc)
        _redis_client = None
    return _redis_client


async def _ensure_listener() -> None:
    global _listener_task
    if _listener_task and not _listener_task.done():
        return
    async with _listener_lock:
        if _listener_task and not _listener_task.done():
            return
        redis = await _get_redis()
        if not redis:
            return
        _listener_task = asyncio.create_task(_redis_listener(redis))


async def _redis_listener(redis: "Redis") -> None:
    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe(CHANNEL_NAME)
        async for message in pubsub.listen():
            if message is None or message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                try:
                    event = json.loads(data.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
            else:
                event = data
            await _broadcast(event)
    except asyncio.CancelledError:  # pragma: no cover - shutdown
        raise
    except Exception as exc:  # pragma: no cover - resilience
        logger.error("Redis listener error: %s", exc)
    finally:
        try:
            await redis.close()
        except Exception:  # pragma: no cover
            pass


async def publish_run_event(event: Dict[str, Any]) -> None:
    redis = await _get_redis()
    if redis:
        try:
            await redis.publish(CHANNEL_NAME, json.dumps(event))
        except Exception as exc:  # pragma: no cover - fallback
            logger.warning("Redis publish failed: %s", exc)
            await _broadcast(event)
    else:
        await _broadcast(event)


async def subscribe(org_id: Optional[str] = None) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=DEFAULT_MAX_QUEUE_SIZE)
    _subscribers[queue] = org_id
    await _ensure_listener()
    return queue


async def unsubscribe(queue: asyncio.Queue) -> None:
    _subscribers.pop(queue, None)
    while not queue.empty():
        queue.get_nowait()


async def _broadcast(event: Dict[str, Any]) -> None:
    if not _subscribers:
        return
    for queue, org_filter in list(_subscribers.items()):
        if org_filter and event.get("org_id") != org_filter:
            continue
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except Exception:
                pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - drop if still full
                logger.debug("Dropping realtime event due to full queue")
