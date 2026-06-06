from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import count
from typing import Any

from app.core.config import get_settings

try:
    import redis.asyncio as redis
except ImportError:  # pragma: no cover - dependency is installed in prod/runtime
    redis = None


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RealtimeEvent:
    id: str
    event: str
    data: dict[str, Any]


class _InMemoryRealtimeBackend:
    def __init__(self) -> None:
        self._counter = count(1)
        self._buffer: dict[str, deque[RealtimeEvent]] = defaultdict(lambda: deque(maxlen=200))
        self._subscribers: dict[str, set[asyncio.Queue[RealtimeEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, tenant_id: str, event: str, data: dict[str, Any]) -> RealtimeEvent:
        payload = RealtimeEvent(id=str(next(self._counter)), event=event, data=data)
        async with self._lock:
            self._buffer[tenant_id].append(payload)
            subscribers = list(self._subscribers[tenant_id])
        for queue in subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    pass
        return payload

    async def subscribe(
        self,
        tenant_id: str,
        *,
        last_event_id: str | None = None,
    ) -> tuple[asyncio.Queue[RealtimeEvent], list[RealtimeEvent]]:
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers[tenant_id].add(queue)
            buffered = list(self._buffer[tenant_id])
        if not last_event_id:
            return queue, []
        missed = [event for event in buffered if int(event.id) > int(last_event_id)]
        return queue, missed

    async def unsubscribe(self, tenant_id: str, queue: asyncio.Queue[RealtimeEvent]) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(tenant_id)
            if subscribers is not None:
                subscribers.discard(queue)


class _RedisRealtimeBackend:
    _CHANNEL_PREFIX = "operator-realtime:"
    _BUFFER_PREFIX = "operator-realtime-buffer:"
    _COUNTER_PREFIX = "operator-realtime-counter:"
    _PATTERN = f"{_CHANNEL_PREFIX}*"

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: redis.Redis | None = None
        self._pubsub: Any = None
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._init_lock = asyncio.Lock()
        self._subscribers: dict[str, set[asyncio.Queue[RealtimeEvent]]] = defaultdict(set)
        self._subscriber_lock = asyncio.Lock()

    def _channel(self, tenant_id: str) -> str:
        return f"{self._CHANNEL_PREFIX}{tenant_id}"

    def _buffer_key(self, tenant_id: str) -> str:
        return f"{self._BUFFER_PREFIX}{tenant_id}"

    def _counter_key(self, tenant_id: str) -> str:
        return f"{self._COUNTER_PREFIX}{tenant_id}"

    def _tenant_from_channel(self, channel: str) -> str:
        if channel.startswith(self._CHANNEL_PREFIX):
            return channel[len(self._CHANNEL_PREFIX):]
        return ""

    async def _ensure_started(self) -> None:
        if self._dispatcher_task is not None and not self._dispatcher_task.done():
            return
        async with self._init_lock:
            if self._dispatcher_task is not None and not self._dispatcher_task.done():
                return
            if self._client is None:
                self._client = redis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
            self._pubsub = self._client.pubsub()
            await self._pubsub.psubscribe(self._PATTERN)
            self._dispatcher_task = asyncio.create_task(
                self._dispatch(),
                name="operator-realtime-dispatcher",
            )

    async def _get_client(self) -> redis.Redis:
        if self._client is not None:
            return self._client
        async with self._init_lock:
            if self._client is None:
                self._client = redis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
            return self._client

    async def publish(self, tenant_id: str, event: str, data: dict[str, Any]) -> RealtimeEvent:
        client = await self._get_client()
        event_id = str(await client.incr(self._counter_key(tenant_id)))
        payload = RealtimeEvent(id=event_id, event=event, data=data)
        encoded = json.dumps(
            {"id": payload.id, "event": payload.event, "data": payload.data},
            separators=(",", ":"),
            default=str,
        )
        pipe = client.pipeline()
        pipe.rpush(self._buffer_key(tenant_id), encoded)
        pipe.ltrim(self._buffer_key(tenant_id), -200, -1)
        pipe.publish(self._channel(tenant_id), encoded)
        await pipe.execute()
        return payload

    async def subscribe(
        self,
        tenant_id: str,
        *,
        last_event_id: str | None = None,
    ) -> tuple[asyncio.Queue[RealtimeEvent], list[RealtimeEvent]]:
        await self._ensure_started()
        client = await self._get_client()
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=100)
        raw_buffer = await client.lrange(self._buffer_key(tenant_id), 0, -1)
        buffered = [self._decode_event(item) for item in raw_buffer]
        if last_event_id:
            try:
                last_seen = int(last_event_id)
                missed = [event for event in buffered if int(event.id) > last_seen]
            except ValueError:
                missed = buffered
        else:
            missed = []
        async with self._subscriber_lock:
            self._subscribers[tenant_id].add(queue)
        return queue, missed

    async def unsubscribe(self, tenant_id: str, queue: asyncio.Queue[RealtimeEvent]) -> None:
        async with self._subscriber_lock:
            subscribers = self._subscribers.get(tenant_id)
            if subscribers is None:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(tenant_id, None)

    async def _dispatch(self) -> None:
        assert self._pubsub is not None
        try:
            while True:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=30.0,
                )
                if not message:
                    continue
                channel = message.get("channel") or ""
                payload = message.get("data")
                if not isinstance(channel, str) or not isinstance(payload, str):
                    continue
                tenant_id = self._tenant_from_channel(channel)
                if not tenant_id:
                    continue
                try:
                    event = self._decode_event(payload)
                except Exception:
                    logger.warning("Operator realtime: undecodable payload on %s", channel)
                    continue
                async with self._subscriber_lock:
                    targets = list(self._subscribers.get(tenant_id, ()))
                for queue in targets:
                    self._enqueue(queue, event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Operator realtime dispatcher failed")
            raise

    @staticmethod
    def _enqueue(queue: asyncio.Queue[RealtimeEvent], event: RealtimeEvent) -> None:
        try:
            queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    @staticmethod
    def _decode_event(raw: str) -> RealtimeEvent:
        payload = json.loads(raw)
        return RealtimeEvent(
            id=str(payload["id"]),
            event=str(payload["event"]),
            data=dict(payload["data"]),
        )


class OperatorRealtimeHub:
    def __init__(self) -> None:
        settings = get_settings()
        if redis and settings.redis_url:
            self._backend: _RedisRealtimeBackend | _InMemoryRealtimeBackend = _RedisRealtimeBackend(
                settings.redis_url
            )
            logger.info("Operator realtime hub configured for Redis pub/sub")
        else:
            self._backend = _InMemoryRealtimeBackend()
            logger.warning("Operator realtime hub using in-memory fallback")

    async def publish(self, tenant_id: str, event: str, data: dict[str, Any]) -> RealtimeEvent:
        return await self._backend.publish(tenant_id, event, data)

    async def subscribe(
        self,
        tenant_id: str,
        *,
        last_event_id: str | None = None,
    ) -> tuple[asyncio.Queue[RealtimeEvent], list[RealtimeEvent]]:
        return await self._backend.subscribe(tenant_id, last_event_id=last_event_id)

    async def unsubscribe(self, tenant_id: str, queue: asyncio.Queue[RealtimeEvent]) -> None:
        await self._backend.unsubscribe(tenant_id, queue)


_HUB = OperatorRealtimeHub()


def get_operator_realtime_hub() -> OperatorRealtimeHub:
    return _HUB
