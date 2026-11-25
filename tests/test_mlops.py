"""Validate monitoring logic and optional local MLflow round trips."""

import os
import unittest

import numpy as np
import pandas as pd
from mlflow import MlflowClient

from mlops.monitoring import compare_distributions
from mlops.register_model import ALIAS, MODEL_NAME, register_pipeline
from mlops.tracking import EXPERIMENT, TRACKING_URI, import_runs
from src.preprocessing import FEATURES


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.reference = pd.DataFrame([
            ["L", 298 + i / 10, 308 + i / 10, 1500 + i, 40 + i / 10, i] for i in range(40)
        ], columns=FEATURES)

    def test_identical_distributions_have_no_shift(self):
        result = compare_distributions(self.reference, self.reference)
        self.assertEqual(len(result["features"]), 6)
        self.assertTrue(all(row["score"] == 0 for row in result["features"]))
        self.assertTrue(all(row["status"] == "below_threshold" for row in result["features"]))

    def test_detects_shift_and_excludes_invalid_numeric_values(self):
        changed = self.reference.copy()
        changed["Torque [Nm]"] += 60
        changed.loc[0, "Torque [Nm]"] = np.inf
        changed.loc[1, "Torque [Nm]"] = -2.0
        changed["Type"] = "M"
        results = {row["feature"]: row for row in compare_distributions(self.reference, changed)["features"]}
        torque = results["Torque [Nm]"]
        self.assertEqual((torque["missing_or_nonfinite"], torque["out_of_domain"], torque["valid_stream_rows"]),
                         (1, 1, 38))
        self.assertEqual((torque["status"], results["Type"]["status"]), ("review", "review"))

    def test_small_or_empty_stream_is_not_reported_as_no_drift(self):
        for rows in (self.reference.iloc[:0], self.reference.iloc[:5]):
            result = compare_distributions(self.reference, rows)
            self.assertTrue(all(row["score"] is None and row["status"] == "insufficient_data"
                                for row in result["features"]))


@unittest.skipUnless(os.getenv("RUN_MLFLOW_TESTS") == "1", "Local MLflow Tracking Server is opt-in")
class MlflowIntegrationTests(unittest.TestCase):
    def test_import_is_idempotent_and_evaluations_are_separated(self):
        client = MlflowClient(tracking_uri=TRACKING_URI)
        existing = import_runs()
        self.assertEqual(existing, import_runs())
        self.assertEqual(sum(split == "cross_validation" for _, split in existing), 7)
        experiment = client.get_experiment_by_name(EXPERIMENT)
        runs = client.search_runs([experiment.experiment_id], "tags.origin = 'imported'")
        self.assertEqual(len({run.data.tags["import_key"] for run in runs if run.info.status == "FINISHED"}),
                         len([run for run in runs if run.info.status == "FINISHED"]))
        cross_validation = client.get_run(existing[("XGBoost", "cross_validation")])
        test_run_id = existing[("XGBoost", "independent_test")]
        test = client.get_run(test_run_id)
        self.assertEqual(cross_validation.data.metrics["average_precision_mean"], 0.76432948)
        self.assertNotIn("average_precision", cross_validation.data.metrics)
        self.assertEqual(test.data.metrics["average_precision"], 0.8428867)
        self.assertIn("source/confusion_matrix.png", [item.path for item in client.list_artifacts(test_run_id, "source")])

    def test_registry_reuses_verified_source_and_predicts_identically(self):
        first = register_pipeline()
        again = register_pipeline()
        self.assertEqual(first.version, again.version)
        self.assertEqual(again.tags["parity_rows"], "8000")
        self.assertEqual(again.tags["verification"], "verified")
        client = MlflowClient(tracking_uri=TRACKING_URI, registry_uri=TRACKING_URI)
        self.assertEqual(client.get_model_version_by_alias(MODEL_NAME, ALIAS).version, first.version)
