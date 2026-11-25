"""Exercise deployment files, prediction contracts and failure paths."""

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import joblib
import pandas as pd
from fastapi.testclient import TestClient

from api.main import app
from api.schemas import MAX_BATCH_SIZE
from src.export_model import PIPELINE_FILE
from src.preprocessing import FEATURES

READING = {
    "type": "M", "air_temperature": 298.1, "process_temperature": 308.6,
    "rotational_speed": 1551, "torque": 42.8, "tool_wear": 0,
}
SECOND = {
    "type": "L", "air_temperature": 300.0, "process_temperature": 310.0,
    "rotational_speed": 1300, "torque": 70.0, "tool_wear": 220,
}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = cls.enterClassContext(TestClient(app))
        cls.pipeline = joblib.load(PIPELINE_FILE)

    def test_root_health_model_info_and_swagger(self):
        self.assertEqual(self.client.get("/").json()["docs"], "/docs")
        self.assertEqual(self.client.get("/health").json(), {"service": "running", "model": "ready"})
        info = self.client.get("/model/info").json()
        self.assertEqual((info["model_name"], info["training_records"]), ("XGBoost", 8000))
        self.assertEqual(info["input_features"], FEATURES)
        self.assertEqual(info["previous_metrics"]["cross_validation"]["average_precision_mean"], 0.76432948)
        self.assertEqual(info["previous_metrics"]["independent_test"]["average_precision"], 0.8428867)
        self.assertTrue(info["dataset"]["synthetic"])
        docs = self.client.get("/docs")
        self.assertEqual(docs.status_code, 200)
        self.assertIn("/swagger-assets/swagger-ui-bundle.js", docs.text)
        self.assertEqual(self.client.get("/swagger-assets/swagger-ui-bundle.js").status_code, 200)
        self.assertIn("/predict/batch", self.client.get("/openapi.json").json()["paths"])

    def test_single_and_batch_scores_match_the_saved_pipeline(self):
        frame = pd.DataFrame([
            ["M", 298.1, 308.6, 1551, 42.8, 0],
            ["L", 300.0, 310.0, 1300, 70.0, 220],
        ], columns=FEATURES)
        expected_scores = self.pipeline.predict_proba(frame)[:, 1]
        expected_classes = self.pipeline.predict(frame)
        self.assertEqual(expected_classes.tolist(), [0, 1])
        single = self.client.post("/predict", json=READING)
        batch = self.client.post("/predict/batch", json={"readings": [READING, SECOND]})
        self.assertEqual((single.status_code, batch.status_code), (200, 200))
        predictions = batch.json()["predictions"]
        self.assertEqual(len(predictions), 2)
        self.assertEqual(single.json()["failure_score"], predictions[0]["failure_score"])
        for result, score, label in zip(predictions, expected_scores, expected_classes, strict=True):
            self.assertEqual(result["failure_score"], float(score))
            self.assertEqual(result["predicted_class"], int(label))
            self.assertEqual(result["decision_threshold"], 0.5)
            self.assertEqual(result["model_version"], "1.0.0")
            self.assertEqual(datetime.fromisoformat(result["prediction_timestamp"]).utcoffset(), timedelta(0))

    def test_missing_wrong_or_forbidden_inputs_are_rejected(self):
        missing = {key: value for key, value in READING.items() if key != "torque"}
        cases = [
            missing, {**READING, "type": "X"}, {**READING, "air_temperature": 0},
            {**READING, "process_temperature": -1}, {**READING, "torque": -1},
            {**READING, "rotational_speed": 1.5}, {**READING, "rotational_speed": -1},
            {**READING, "tool_wear": False}, {**READING, "air_temperature": True},
            {**READING, "tool_wear": -1}, {**READING, "torque": "42.8"},
            *({**READING, field: 1} for field in ("UDI", "Product ID", "Machine failure", "TWF")),
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/predict", json=payload).status_code, 422)

    def test_nonfinite_and_malformed_json_return_422(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            response = self.client.post(
                "/predict", content=json.dumps({**READING, "torque": value}),
                headers={"content-type": "application/json"},
            )
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.post("/predict", content="{", headers={
            "content-type": "application/json",
        }).status_code, 422)

    def test_batch_limit_and_invalid_member(self):
        for readings in ([], [READING] * (MAX_BATCH_SIZE + 1), [READING, {**READING, "torque": -1}]):
            response = self.client.post("/predict/batch", json={"readings": readings})
            self.assertEqual(response.status_code, 422)
        response = self.client.post("/predict/batch", json={"readings": [READING] * MAX_BATCH_SIZE})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["predictions"]), MAX_BATCH_SIZE)


class UnavailableModelTests(unittest.TestCase):
    def test_missing_model_returns_503_while_docs_still_work(self):
        module = "api.services.prediction_service"
        with TemporaryDirectory() as folder:
            path = Path(folder).resolve()
            (path / "model_metadata.json").write_text("{}", encoding="utf-8")
            with patch.multiple(module, MODELS=path, PIPELINE_FILE=path / PIPELINE_FILE.name,
                                METADATA_FILE=path / "model_metadata.json"):
                with TestClient(app) as client:
                    self.assertEqual(client.get("/").status_code, 200)
                    status = client.get("/health")
                    self.assertEqual(status.status_code, 503)
                    self.assertEqual(status.json(), {"service": "running", "model": "unavailable"})
                    self.assertEqual(client.get("/model/info").status_code, 503)
                    self.assertEqual(client.post("/predict", json=READING).status_code, 503)
                    self.assertEqual(client.post("/predict/batch", json={"readings": [READING]}).status_code, 503)
                    self.assertEqual(client.get("/docs").status_code, 200)

    def test_digest_mismatch_prevents_deserialization(self):
        module = "api.services.prediction_service"
        with TemporaryDirectory() as folder:
            path = Path(folder).resolve()
            artifact = path / PIPELINE_FILE.name
            metadata = path / "model_metadata.json"
            artifact.write_bytes(b"unexpected bytes")
            metadata.write_text(json.dumps({"artifact_sha256": "0" * 64}), encoding="utf-8")
            with patch.multiple(module, MODELS=path, PIPELINE_FILE=artifact, METADATA_FILE=metadata):
                with patch(f"{module}.joblib.load") as load, TestClient(app) as client:
                    self.assertEqual(client.get("/health").status_code, 503)
                    load.assert_not_called()
