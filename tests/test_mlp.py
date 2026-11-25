"""Check the MLP architecture and validation boundaries."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import StratifiedKFold
from torch import nn

from src.mlp_model import FailureMLP
from src.preprocessing import NUMERIC_FEATURES
from src.train_mlp import (
    cross_validate_mlp, fit_fold, load_development_data, positive_weight, prepare_fold,
)
from src.train_models import training_folds


class MLPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.X, cls.y = load_development_data()

    def test_architecture_returns_unbounded_logits(self):
        model = FailureMLP()
        layers = list(model.network)
        self.assertEqual(
            [(layer.in_features, layer.out_features) for layer in layers if isinstance(layer, nn.Linear)],
            [(8, 32), (32, 16), (16, 1)],
        )
        self.assertEqual([type(layer) for layer in layers],
                         [nn.Linear, nn.ReLU, nn.Linear, nn.ReLU, nn.Linear])
        with torch.no_grad():
            layers[-1].weight.zero_()
            layers[-1].bias.fill_(-3)
        torch.testing.assert_close(model(torch.zeros(1, 8)), torch.tensor([-3.0]))

    def test_fold_preprocessing_uses_only_fit_rows(self):
        fit, validation = training_folds(self.X, self.y)[0]
        X_fit = self.X.iloc[fit]
        X_validation = self.X.iloc[validation]
        train, valid, preprocessor = prepare_fold(X_fit, X_validation)
        self.assertEqual((train.shape, valid.shape), ((6400, 8), (1600, 8)))
        scaler = preprocessor.named_steps["preprocessor"].named_transformers_["numeric"]
        np.testing.assert_allclose(scaler.mean_, X_fit[NUMERIC_FEATURES].mean())
        self.assertFalse(np.allclose(scaler.mean_, X_validation[NUMERIC_FEATURES].mean()))

    def test_cv_uses_original_folds_and_training_labels_for_weights(self):
        self.assertEqual((len(self.y), int(self.y.sum())), (8000, 271))
        expected = list(StratifiedKFold(5, shuffle=True, random_state=42).split(self.X, self.y))
        with patch("src.train_mlp.EPOCHS", 1), patch(
            "src.train_mlp.fit_fold", wraps=fit_fold
        ) as fit_model:
            folds, history, oof = cross_validate_mlp(self.X, self.y)
        self.assertEqual(fit_model.call_count, 5)
        self.assertEqual(len(history), 5)
        self.assertTrue(np.isfinite(oof).all())
        for i, (fit, validation) in enumerate(expected):
            _, y_fit, _, y_validation = fit_model.call_args_list[i].args
            self.assertTrue(y_fit.equals(self.y.iloc[fit]))
            self.assertTrue(y_validation.equals(self.y.iloc[validation]))
            self.assertAlmostEqual(folds.iloc[i]["pos_weight"], (y_fit == 0).sum() / y_fit.sum())
        with self.assertRaises(ValueError):
            positive_weight(pd.Series([0, 0]))

    def test_seeded_fold_produces_identical_predictions(self):
        fit, validation = training_folds(self.X, self.y)[0]
        args = (self.X.iloc[fit[:192]], self.y.iloc[fit[:192]],
                self.X.iloc[validation], self.y.iloc[validation])
        with patch("src.train_mlp.EPOCHS", 2):
            first, first_scores, _ = fit_fold(*args, seed=42)
            second, second_scores, _ = fit_fold(*args, seed=42)
        self.assertEqual(first, second)
        np.testing.assert_array_equal(first_scores, second_scores)
