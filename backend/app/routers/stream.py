"""
SSE Stream Router — Brightloop
=================================
Exposes the Server-Sent Events endpoint (/api/v1/stream) for real-time dashboard updates
and telemetry inspection. The Finance Lead's browser connects to this endpoint
and receives push notifications whenever payments arrive, invoices are generated,
or subscriptions change status.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sse_starlette.sse import EventSourceResponse

from app.models import User
from app.services.auth_service import get_current_user, require_staff_or_admin
from app.services.continuous_stream import event_broadcaster
from app.services.astra_telemetry import astra_telemetry

router = APIRouter(prefix="/api/v1/stream", tags=["Real-Time Stream"])


@router.get("", include_in_schema=True)
@router.get("/", include_in_schema=False)
@router.get("/events", include_in_schema=True)
async def sse_stream(current_user: User = Depends(get_current_user)):
    """
    Server-Sent Events endpoint (/api/v1/stream) for continuous dashboard updates.

    Why we require auth on the SSE endpoint:
    Without auth, anyone who discovers the URL can monitor every billing
    event in real time — payment amounts, customer names, subscription
    changes. Authenticated JWT tokens via cookie or ?token= guarantee security.
    """
    queue = await event_broadcaster.subscribe()

    async def event_generator():
        try:
            async for event_data in event_broadcaster.event_generator(queue):
                yield event_data
        finally:
            await event_broadcaster.unsubscribe(queue)

    return EventSourceResponse(event_generator())


@router.get("/telemetry")
async def get_telemetry_events(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(require_staff_or_admin),
):
    """
    Retrieve recent continuous event telemetry from DataStax Astra DB (or local buffer in offline mode).
    Staff & Admin only.
    """
    events = await astra_telemetry.get_recent_events(limit=limit)
    return {
        "connected_to_cloud": astra_telemetry.is_configured,
        "keyspace": astra_telemetry.keyspace,
        "collection": astra_telemetry.collection,
        "count": len(events),
        "events": events,
    }
