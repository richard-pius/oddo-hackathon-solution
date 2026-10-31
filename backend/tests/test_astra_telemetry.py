import unittest
import asyncio
from unittest.mock import patch, AsyncMock
from app.services.astra_telemetry import AstraDBTelemetryAdapter, astra_telemetry
from app.services.continuous_stream import event_broadcaster


class TestAstraDBTelemetryAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_offline_local_buffer_recording(self):
        adapter = AstraDBTelemetryAdapter()
        # Ensure offline mode
        adapter.api_endpoint = ""
        adapter.application_token = ""
        self.assertFalse(adapter.is_configured)

        test_data = {"subscription_id": 999, "amount": "499.00"}
        res = await adapter.record_event(
            event_type="test_sub_event",
            data=test_data,
            metadata={"origin": "unit_test"},
        )

        self.assertIn("event_id", res)
        self.assertEqual(res["event_type"], "test_sub_event")
        self.assertEqual(res["data"], test_data)

        # Verify retrieval from local buffer
        recent = await adapter.get_recent_events(limit=10)
        self.assertTrue(len(recent) > 0)
        matched = next((e for e in recent if e["event_id"] == res["event_id"]), None)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["event_type"], "test_sub_event")

    async def test_broadcast_integration_with_astra_telemetry(self):
        # Broadcasting via continuous_stream should automatically log to astra_telemetry
        broadcast_payload = {
            "type": "invoice_paid_telemetry_test",
            "invoice_number": "INV-2026-TEST",
            "amount": "1250.00",
        }

        await event_broadcaster.broadcast(broadcast_payload)

        # Check that astra_telemetry captured it
        events = await astra_telemetry.get_recent_events(limit=10)
        matched = next(
            (e for e in events if e.get("event_type") == "invoice_paid_telemetry_test"),
            None,
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched["data"]["invoice_number"], "INV-2026-TEST")

    async def test_cloud_post_payload_structure(self):
        adapter = AstraDBTelemetryAdapter()
        adapter.api_endpoint = "https://mock-db-region.apps.astra.datastax.com"
        adapter.application_token = "AstraCS:mocktoken123"
        self.assertTrue(adapter.is_configured)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {"status": {"insertedIds": ["mock-id"]}}

            res = await adapter.record_event(
                event_type="cloud_billing_batch_event",
                data={"invoices_count": 50},
            )

            self.assertEqual(res["event_type"], "cloud_billing_batch_event")
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            self.assertIn("json", call_kwargs)
            self.assertIn("insertOne", call_kwargs["json"])
            doc = call_kwargs["json"]["insertOne"]["document"]
            self.assertEqual(doc["event_type"], "cloud_billing_batch_event")


if __name__ == "__main__":
    unittest.main()
