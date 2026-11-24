"""Ön işleme ve eğitim/test ayrımının temel davranış testleri."""

import unittest
from pathlib import Path

import numpy as np

from src.preprocessing import (
    EXCLUDED_COLUMNS, FEATURES, NUMERIC_FEATURES, TARGET,
    create_preprocessing_pipeline, load_data, select_features, split_data,
)

ROOT = Path(__file__).resolve().parent.parent


class PreprocessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_data(ROOT / "data/raw/ai4i2020.csv")
        cls.X, cls.y = select_features(cls.data)

    def test_schema_and_validation(self):
        self.assertEqual(list(self.X.columns), FEATURES)
        self.assertFalse(set(EXCLUDED_COLUMNS + [TARGET]) & set(self.X.columns))
        with self.assertRaises(ValueError):
            select_features(self.data.drop(columns=[TARGET]))
        invalid = self.data.copy()
        invalid.loc[0, 'Type'] = None
        with self.assertRaises(ValueError):
            select_features(invalid)

    def test_split_and_train_only_fit(self):
        X_train, X_test, y_train, y_test = split_data(self.X, self.y)
        self.assertEqual((len(X_train), len(X_test)), (8000, 2000))
        self.assertTrue(set(X_train.index).isdisjoint(X_test.index))
        self.assertAlmostEqual(y_train.mean(), y_test.mean(), delta=0.001)
        pipeline = create_preprocessing_pipeline()
        train = pipeline.fit_transform(X_train)
        scaler = pipeline.named_steps['preprocessor'].named_transformers_['numeric']
        np.testing.assert_allclose(scaler.mean_, X_train[NUMERIC_FEATURES].mean())
        before = scaler.mean_.copy()
        test = pipeline.transform(X_test)
        np.testing.assert_array_equal(before, scaler.mean_)
        self.assertEqual(train.shape, (8000, 8))
        self.assertEqual(test.shape, (2000, 8))
        np.testing.assert_allclose(train[:, :5].mean(axis=0), 0, atol=1e-10)
        unseen = X_test.iloc[:1].copy()
        unseen.loc[:, 'Type'] = 'unknown'
        np.testing.assert_array_equal(pipeline.transform(unseen)[0, 5:], [0, 0, 0])


if __name__ == '__main__':
    unittest.main()
