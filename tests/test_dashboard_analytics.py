"""Verify dashboard API data and honest service status."""

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app


class DashboardAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = cls.enterClassContext(TestClient(app))

    def test_summary_matches_training_data(self):
        response = self.client.get("/analytics/summary")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["sensor_records"], data["failures"], data["normal"]), (10000, 339, 9661))
        self.assertGreaterEqual(data["count_query_ms"], 0)

    def test_sensor_limit_and_order(self):
        self.assertEqual(self.client.get("/analytics/sensors?limit=101").status_code, 422)
        response = self.client.get("/analytics/sensors?limit=3")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["readings"]
        self.assertLessEqual(len(rows), 3)
        timestamps = [row["event_time"] for row in rows]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_completed_model_evaluations_are_separate(self):
        response = self.client.get("/analytics/models")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["cross_validation"]), 7)
        self.assertEqual(data["cross_validation"][0]["average_precision"], 0.76432948)
        self.assertEqual(data["independent_test"]["tp"], 61)
        self.assertEqual(len(data["mlp_training_loss"]), 50)

    def test_health_reports_unknown_spark_and_unavailable_postgres(self):
        with patch("api.analytics.read_query", side_effect=HTTPException(503)), patch(
            "api.analytics.kafka_status",
            return_value={"name": "Kafka", "status": "Unknown", "detail": "Probe unavailable."},
        ):
            response = self.client.get("/analytics/health")
            self.assertEqual(self.client.get("/analytics/summary").status_code, 503)
        statuses = {row["name"]: row["status"] for row in response.json()}
        self.assertEqual(statuses["PostgreSQL"], "Unavailable")
        self.assertEqual(statuses["Spark"], "Unknown")
