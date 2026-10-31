"""
DataStax Astra DB Telemetry & Event Logging Adapter
===================================================
Provides a robust repository adapter for continuous event telemetry and audit
logging into DataStax Astra DB.

Why DataStax Astra DB for Event Telemetry:
  In financial-grade ERPs, high-throughput event logging (e.g. batch billing
  milestones, payment reconciliation, state transitions) should avoid competing
  with relational transaction locks in PostgreSQL. Astra DB's serverless NoSQL
  document engine offers massive append throughput with sub-second queries.

Local-First & Offline Resilience:
  In accordance with Rule #1 (Dynamic Data & Local-First), if Astra credentials
  are not supplied or the machine is offline, the adapter seamlessly falls back
  to an in-memory sliding buffer. Operations never fail due to cloud telemetry
  unavailability.
"""

import collections
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger("brightloop.astra")


class AstraDBTelemetryAdapter:
    """
    Repository adapter for DataStax Astra DB Document/JSON API v1.
    Handles continuous logging of ERP lifecycle events, payments, and batch billing telemetry.
    """

    def __init__(self):
        self.api_endpoint = (settings.ASTRA_DB_API_ENDPOINT or "").strip().rstrip("/")
        self.application_token = (settings.ASTRA_DB_APPLICATION_TOKEN or "").strip()
        self.keyspace = settings.ASTRA_DB_KEYSPACE
        self.collection = settings.ASTRA_DB_COLLECTION
        # Sliding buffer for offline local development and rapid retrieval
        self._local_buffer: collections.deque = collections.deque(maxlen=1000)

    @property
    def is_configured(self) -> bool:
        """Returns True if valid Astra DB endpoint and token are present."""
        return bool(self.api_endpoint and self.application_token)

    async def record_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Record a telemetry event. Sends to Astra DB if configured; otherwise logs to local buffer.
        """
        event_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        telemetry_doc = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": timestamp,
            "data": data,
            "metadata": metadata or {},
        }

        # Always record in the local buffer for instant dashboard inspection
        self._local_buffer.append(telemetry_doc)

        if not self.is_configured:
            logger.debug(
                "Astra DB [Offline/Local-First]: Recorded %s (id: %s)",
                event_type,
                event_id,
            )
            return telemetry_doc

        # Dispatch to DataStax Astra DB Document/Data API v1
        url = f"{self.api_endpoint}/api/json/v1/{self.keyspace}/{self.collection}"
        headers = {
            "Token": self.application_token,
            "Content-Type": "application/json",
        }
        payload = {"insertOne": {"document": telemetry_doc}}

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code in (200, 201):
                    logger.info("Astra DB: Successfully ingested event %s", event_type)
                else:
                    logger.warning(
                        "Astra DB ingestion status %s: %s",
                        res.status_code,
                        res.text[:200],
                    )
        except Exception as exc:
            # Telemetry delivery failures must NEVER interrupt business transactions
            logger.warning("Astra DB non-blocking push error: %s", exc)

        return telemetry_doc

    async def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch recent events from Astra DB if configured; otherwise from local buffer.
        """
        if not self.is_configured:
            events = list(self._local_buffer)
            events.reverse()
            return events[:limit]

        url = f"{self.api_endpoint}/api/json/v1/{self.keyspace}/{self.collection}"
        headers = {
            "Token": self.application_token,
            "Content-Type": "application/json",
        }
        payload = {
            "find": {
                "options": {
                    "limit": limit,
                    "sort": {"timestamp": -1},
                }
            }
        }

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    docs = data.get("data", {}).get("documents", [])
                    return docs
        except Exception as exc:
            logger.warning("Failed to query Astra DB, falling back to local buffer: %s", exc)

        events = list(self._local_buffer)
        events.reverse()
        return events[:limit]


# Singleton repository adapter
astra_telemetry = AstraDBTelemetryAdapter()
