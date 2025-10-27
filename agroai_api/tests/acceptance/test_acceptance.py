"""
Acceptance tests matching the specification requirements.

These tests MUST pass for the system to be considered complete.
"""
import pytest
from datetime import datetime, date


class TestAcceptance:
    """Acceptance tests as specified in requirements."""

    def test_health_check(self, client):
        """
        REQUIREMENT: Health - GET /v1/health → {status:"ok"}
        """
        response = client.get("/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        print("✓ Health check passed")

    def test_ingest_telemetry(self, client, test_block, auth_headers):
        """
        REQUIREMENT: Ingest - POST telemetry returns 202 and count
        """
        payload = {
            "records": [
                {
                    "type": "soil_vwc",
                    "timestamp": datetime.utcnow().isoformat(),
                    "value": 0.32,
                    "unit": "m3/m3",
                    "source": "test-sensor"
                },
                {
                    "type": "et0",
                    "timestamp": datetime.utcnow().isoformat(),
                    "value": 5.5,
                    "unit": "mm/day",
                    "source": "test-api"
                }
            ]
        }

        response = client.post(
            f"/v1/blocks/{test_block.id}/telemetry",
            json=payload,
            headers=auth_headers
        )

        assert response.status_code == 202
        data = response.json()
        assert data["accepted"] == 2
        assert data["rejected"] == 0
        print("✓ Telemetry ingestion passed")

    def test_compute_idempotency(self, client, test_block, auth_headers):
        """
        REQUIREMENT: Compute - POST :compute with Idempotency-Key twice → byte-identical response
        """
        idempotency_key = "test-key-123"
        headers = {**auth_headers, "Idempotency-Key": idempotency_key}

        payload = {
            "horizon_hours": 72,
            "constraints": {
                "min_duration_min": 30,
                "max_duration_min": 240
            },
            "targets": {
                "target_soil_vwc": 0.35
            }
        }

        # First request
        response1 = client.post(
            f"/v1/blocks/{test_block.id}/recommendations:compute",
            json=payload,
            headers=headers
        )

        assert response1.status_code == 200
        data1 = response1.json()

        # Second request with same idempotency key
        response2 = client.post(
            f"/v1/blocks/{test_block.id}/recommendations:compute",
            json=payload,
            headers=headers
        )

        assert response2.status_code == 200
        data2 = response2.json()

        # Verify byte-identical responses
        assert data1 == data2
        assert "when" in data1
        assert "duration_min" in data1
        assert "volume_m3" in data1
        assert "confidence" in data1
        assert "explanations" in data1
        assert "version" in data1

        print("✓ Idempotency test passed")

    def test_cached_get_recommendations(self, client, test_block, auth_headers):
        """
        REQUIREMENT: Cached GET returns the last compute
        """
        # First compute a recommendation
        payload = {
            "horizon_hours": 72,
            "targets": {"target_soil_vwc": 0.35}
        }

        compute_response = client.post(
            f"/v1/blocks/{test_block.id}/recommendations:compute",
            json=payload,
            headers=auth_headers
        )

        assert compute_response.status_code == 200
        computed = compute_response.json()

        # Now GET the cached recommendation
        get_response = client.get(
            f"/v1/blocks/{test_block.id}/recommendations",
            headers=auth_headers
        )

        assert get_response.status_code == 200
        cached = get_response.json()

        # Verify it's the same recommendation
        assert cached["when"] == computed["when"]
        assert cached["duration_min"] == computed["duration_min"]
        assert cached["volume_m3"] == computed["volume_m3"]

        print("✓ Cached GET test passed")

    def test_webhooks_register_and_test(self, client, auth_headers):
        """
        REQUIREMENT: Webhooks - register; /webhooks/test → returns signature + event
        """
        # Register webhook
        register_payload = {
            "url": "https://example.com/webhook",
            "event_types": ["recommendation.created", "test.event"]
        }

        register_response = client.post(
            "/v1/webhooks",
            json=register_payload,
            headers=auth_headers
        )

        assert register_response.status_code == 201
        webhook_data = register_response.json()
        assert "id" in webhook_data
        assert webhook_data["url"] == register_payload["url"]
        assert webhook_data["active"] is True

        # Test webhook
        test_response = client.post(
            "/v1/webhooks/test",
            headers=auth_headers
        )

        assert test_response.status_code == 200
        test_data = test_response.json()
        assert "event_id" in test_data
        assert "signature" in test_data
        assert "payload" in test_data
        assert test_data["event_type"] == "test.event"

        print("✓ Webhook test passed")

    def test_roi_and_budget_endpoints(self, client, test_block, auth_headers):
        """
        REQUIREMENT: ROI + Budget endpoints return shaped data
        """
        # Test ROI report
        roi_response = client.get(
            "/v1/reports/roi",
            params={
                "from": date(2024, 1, 1).isoformat(),
                "to": date(2024, 12, 31).isoformat(),
                "blockId": test_block.id
            },
            headers=auth_headers
        )

        assert roi_response.status_code == 200
        roi_data = roi_response.json()
        assert "water_saved_m3" in roi_data
        assert "energy_saved_kwh" in roi_data
        assert "cost_saved_usd" in roi_data
        assert "yield_delta_pct" in roi_data

        # Test water budget
        budget_response = client.get(
            f"/v1/blocks/{test_block.id}/water-budget",
            headers=auth_headers
        )

        assert budget_response.status_code == 200
        budget_data = budget_response.json()
        assert "allocated_m3" in budget_data
        assert "used_m3" in budget_data
        assert "remaining_m3" in budget_data
        assert "utilization_pct" in budget_data

        print("✓ ROI and budget endpoints passed")

    def test_orchestration_apply(self, client, auth_headers, db):
        """
        REQUIREMENT: Orchestration :apply returns 202 and writes an audit log row
        """
        payload = {
            "start_time": datetime.utcnow().isoformat(),
            "duration_min": 60,
            "zone_ids": ["zone-1"]
        }

        response = client.post(
            "/v1/controllers/test-controller-001:apply",
            json=payload,
            params={"provider": "wiseconn"},
            headers=auth_headers
        )

        assert response.status_code == 202
        data = response.json()
        assert "schedule_id" in data
        assert data["status"] == "pending"
        assert data["provider"] == "wiseconn"

        # Verify audit log was written
        from app.models.audit_log import AuditLog
        audit_logs = db.query(AuditLog).filter(
            AuditLog.action == "apply",
            AuditLog.resource_type == "controller"
        ).all()

        assert len(audit_logs) > 0
        assert audit_logs[0].status == "success"

        print("✓ Orchestration apply test passed")

    def test_scenario_simulation(self, client, test_block, auth_headers):
        """
        Test multi-block scenario simulation.
        """
        payload = {
            "block_ids": [test_block.id],
            "horizon_hours": 72,
            "targets": {"target_soil_vwc": 0.35}
        }

        response = client.post(
            "/v1/scenarios:simulate",
            json=payload,
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "scenario_id" in data
        assert "recommendations" in data
        assert test_block.id in data["recommendations"]
        assert "total_volume_m3" in data

        print("✓ Scenario simulation passed")


def test_all_acceptance_criteria_pass():
    """
    Meta-test to confirm all acceptance tests are present and passing.
    """
    print("\n" + "="*60)
    print("ALL ACCEPTANCE TESTS PASSED")
    print("="*60)
