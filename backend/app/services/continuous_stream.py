"""
Continuous Stream — SSE Broadcaster & Event Bus
================================================
Provides real-time push notifications to the frontend dashboard via
Server-Sent Events (SSE). When a payment arrives, a subscription renews,
or a billing batch completes, the event is broadcast to all connected clients
and continuously archived into the DataStax Astra DB telemetry repository.

Why SSE instead of WebSockets:
  SSE is HTTP/1.1-native, auto-reconnects, works through corporate proxies
  that block WebSocket upgrades, and is simpler to implement correctly.
  We don't need bidirectional communication — the dashboard only listens.
  If we ever need client→server pushes, we add a WebSocket endpoint later
  without touching the SSE plumbing.

Architecture:
  EventBroadcaster maintains an asyncio.Queue per connected client.
  When broadcast() is called, each queue gets a copy of the event.
  Disconnected clients are cleaned up lazily when their queue raises.
  Every event is asynchronously recorded into Astra DB for telemetry audit.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from app.services.astra_telemetry import astra_telemetry

logger = logging.getLogger("brightloop.stream")


class EventBroadcaster:
    """
    Thread-safe (asyncio-safe) fan-out broadcaster for SSE events.

    Why we use per-client queues instead of a single shared queue:
    A shared queue with multiple consumers means each consumer competes for
    the same event. Per-client queues guarantee every connected dashboard
    tab sees every event, which is critical for the Finance Lead who has
    the dashboard open on a second monitor all day.
    """

    def __init__(self):
        self._clients: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        """Register a new SSE client and return its dedicated event queue."""
        queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._clients.append(queue)
        logger.info(f"SSE client connected. Total clients: {len(self._clients)}")
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        """Remove a disconnected client's queue."""
        async with self._lock:
            try:
                self._clients.remove(queue)
            except ValueError:
                pass
        logger.info(f"SSE client disconnected. Total clients: {len(self._clients)}")

    async def broadcast(self, event: dict):
        """
        Push an event to all connected clients and archive to Astra DB telemetry.
        Why we don't await each put:
        If a slow client's queue is full (256 items), we drop the event for
        that client rather than blocking all other clients. The dashboard will
        self-heal on the next periodic refresh anyway.
        """
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        dead_clients = []

        async with self._lock:
            for queue in self._clients:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    dead_clients.append(queue)

        # Clean up clients whose queues overflowed — they're probably dead tabs
        for dq in dead_clients:
            await self.unsubscribe(dq)

        # Continuously ingest telemetry event into DataStax Astra DB repository adapter
        try:
            event_type = str(event.get("type", "stream_event"))
            await astra_telemetry.record_event(
                event_type=event_type,
                data=event,
                metadata={"source": "continuous_stream_broadcaster"},
            )
        except Exception as e:
            logger.debug("Non-blocking Astra DB logging notice: %s", e)

    async def event_generator(self, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
        """
        Yields SSE-formatted events from the client's queue.
        Includes a heartbeat every 15 seconds so proxies and load balancers
        don't kill the connection for inactivity.
        """
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat: keeps the connection alive through Nginx/ALB
                    yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
        except asyncio.CancelledError:
            pass


# Singleton broadcaster — imported by services that need to emit events
event_broadcaster = EventBroadcaster()
