"""
SSE Stream Router — Brightloop
=================================
Exposes the Server-Sent Events endpoint for real-time dashboard updates.
The Finance Lead's browser connects to this endpoint and receives push
notifications whenever payments arrive, invoices are generated, or
subscriptions change status.
"""

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.models import User
from app.services.auth_service import get_current_user
from app.services.continuous_stream import event_broadcaster

router = APIRouter(prefix="/api/v1/stream", tags=["Real-Time Stream"])


@router.get("/events")
async def sse_stream(current_user: User = Depends(get_current_user)):
    """
    Server-Sent Events endpoint for continuous dashboard updates.

    Why we require auth on the SSE endpoint:
    Without auth, anyone who discovers the URL can monitor every billing
    event in real time — payment amounts, customer names, subscription
    changes. That's a GDPR violation waiting to happen.
    """
    queue = await event_broadcaster.subscribe()

    async def event_generator():
        try:
            async for event_data in event_broadcaster.event_generator(queue):
                yield event_data
        finally:
            await event_broadcaster.unsubscribe(queue)

    return EventSourceResponse(event_generator())
