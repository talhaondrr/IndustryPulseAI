"""Integration and leakage checks for the machine learning workflow."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.evaluate_models import evaluate
from src.preprocessing import FEATURES, NUMERIC_FEATURES, split_data
from src.train_models import build_models, compare_models, fit_model, load_training_data


class MachineLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.X, cls.y = load_training_data()

    def test_view_is_complete_and_repeatable(self):
        self.assertEqual(self.X.shape, (10_000, 6))
        self.assertEqual(list(self.X), FEATURES)
        self.assertEqual(self.y.value_counts().to_dict(), {0: 9661, 1: 339})
        X_again, y_again = load_training_data()
        pd.testing.assert_frame_equal(self.X, X_again)
        pd.testing.assert_series_equal(self.y, y_again)

    def test_split_is_stratified_disjoint_and_repeatable(self):
        X_train, X_test, y_train, y_test = split_data(self.X, self.y)
        self.assertEqual((len(X_train), len(X_test)), (8000, 2000))
        self.assertEqual((int(y_train.sum()), int(y_test.sum())), (271, 68))
        self.assertTrue(X_train.index.intersection(X_test.index).empty)
        for first, second in zip((X_train, X_test, y_train, y_test), split_data(self.X, self.y)):
            self.assertTrue(first.equals(second))

    def test_pipeline_only_fits_preprocessing_on_supplied_rows(self):
        X_train, X_test, y_train, _ = split_data(self.X, self.y)
        pipeline = build_models()["Dummy Classifier"]
        fitted, _ = fit_model(pipeline, X_train, y_train)
        self.assertFalse(hasattr(pipeline.named_steps["preprocessor"], "transformers_"))
        scaler = fitted.named_steps["preprocessor"].named_transformers_["numeric"]
        np.testing.assert_allclose(scaler.mean_, X_train[NUMERIC_FEATURES].mean())
        self.assertFalse(np.allclose(scaler.mean_, X_test[NUMERIC_FEATURES].mean()))

    def test_baseline_uses_five_disjoint_training_folds(self):
        X_train, _, y_train, _ = split_data(self.X, self.y)
        models = {"Dummy Classifier": build_models()["Dummy Classifier"]}
        with patch("src.train_models.fit_model", wraps=fit_model) as fit, patch(
            "src.train_models.evaluate", wraps=evaluate
        ) as score:
            row = compare_models(models, X_train, y_train).iloc[0]
        self.assertEqual(fit.call_count, 5)
        self.assertEqual(score.call_count, 5)
        held_out = []
        for fit_call, score_call in zip(fit.call_args_list, score.call_args_list):
            fit_indices = fit_call.args[1].index
            validation_indices = score_call.args[1].index
            self.assertTrue(fit_indices.intersection(validation_indices).empty)
            self.assertEqual(len(fit_indices), 6400)
            held_out.extend(validation_indices)
        self.assertCountEqual(held_out, X_train.index)
        self.assertEqual(tuple(row[["tn", "fp", "fn", "tp"]]), (7729, 0, 271, 0))
        self.assertAlmostEqual(row["average_precision_mean"], y_train.mean())
