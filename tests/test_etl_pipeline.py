"""Unit and PostgreSQL integration tests for the AI4I batch."""

import unittest
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from psycopg import errors

from pipelines import etl_pipeline as etl
from src.database import connect


class ExtractTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = etl.extract().iloc[:2]

    def test_extract_rejects_missing_file_and_columns(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            with self.assertRaisesRegex(etl.ETLError, "bulunamadı"):
                etl.extract(path)
            path.write_text("UDI\n1\n", encoding="utf-8")
            with self.assertRaisesRegex(etl.ETLError, "Eksik CSV sütunları"):
                etl.extract(path)

    def test_transform_preserves_units_and_binary_labels(self):
        batch = etl.transform(self.sample)
        self.assertEqual(
            batch.sensor_readings[0],
            (1, "M14860", "M", Decimal("298.1"), Decimal("308.6"), 1551, Decimal("42.8"), 0),
        )
        self.assertEqual(batch.failure_records[0], (1, 0, 0, 0, 0, 0, 0))
        self.assertCountEqual([record[0] for record in batch.product_types], ["L", "M", "H"])

    def test_transform_rejects_invalid_rows(self):
        cases = [
            ("UDI", "1", "udi.*tekrarlanan"),
            ("Product ID", "M14860", "product_id.*tekrarlanan"),
            ("Air temperature [K]", "", "air_temperature.*eksik"),
            ("Air temperature [K]", "NaN", "air_temperature.*sonlu"),
            ("Process temperature [K]", "0", "process_temperature.*aralığı"),
            ("Rotational speed [rpm]", "1.5", "rotational_speed.*tam sayı"),
            ("Torque [Nm]", "-1", "torque.*aralığı"),
            ("Tool wear [min]", "2147483648", "tool_wear.*tam sayı"),
            ("Type", "X", "type_code"),
            ("Product ID", "H123", "product_id.*uyuşmuyor"),
            ("Machine failure", "2", "machine_failure.*0 veya 1"),
            ("RNF", "yes", "rnf.*geçersiz"),
        ]
        for column, value, pattern in cases:
            with self.subTest(column=column, value=value):
                frame = self.sample.copy()
                frame.loc[frame.index[1], column] = value
                if pattern == "product_id.*tekrarlanan":
                    frame.loc[frame.index[1], "Type"] = "M"
                with self.assertRaisesRegex(etl.ETLError, pattern):
                    etl.transform(frame)

    def test_pipeline_rejects_invalid_input_before_connecting(self):
        invalid = self.sample.copy()
        invalid.loc[invalid.index[0], "TWF"] = "2"
        with patch.object(etl, "extract", return_value=invalid), patch.object(etl, "connect") as database:
            with self.assertLogs(etl.LOGGER, level="ERROR") as logs:
                with self.assertRaisesRegex(etl.ETLError, "twf"):
                    etl.run_pipeline()
            database.assert_not_called()
        self.assertIn("ETL başarısız", logs.output[0])


class LoadTests(unittest.TestCase):
    def test_invalid_load_rolls_back_all_tables(self):
        def snapshot():
            with connect() as connection:
                return connection.execute("""
                    SELECT
                        (SELECT type_name FROM public.product_types WHERE type_code = 'L'),
                        (SELECT torque FROM public.sensor_readings WHERE udi = 1),
                        (SELECT machine_failure FROM public.failure_records WHERE udi = 1)
                """).fetchone()

        before = snapshot()
        batch = etl.Batch(
            [("L", "Rollback test", None), ("M", "Rollback test", None)],
            [(1, "M14860", "M", Decimal("298.1"), Decimal("308.6"), 1551, 12345, 0)],
            [(1, 2, 0, 0, 0, 0, 0)],
        )
        with self.assertRaises(errors.CheckViolation):
            etl.load(batch)
        self.assertEqual(snapshot(), before)

    def test_idempotency_and_counts(self):
        batch = etl.transform(etl.extract())
        connection = connect()
        self.addCleanup(connection.close)
        self.addCleanup(connection.rollback)
        connection.execute("SELECT 1")  # Start the outer transaction before the savepoints.

        @contextmanager
        def isolated_load():
            with connection.transaction():
                yield connection

        expected = {
            "product_types": 3,
            "sensor_readings": 10_000,
            "failure_records": 10_000,
            "ml_training_data": 10_000,
            "normal": 9_661,
            "failed": 339,
        }
        with patch.object(etl, "connect", isolated_load):
            self.assertEqual(etl.load(batch), expected)
            with self.assertLogs(etl.LOGGER, level="INFO") as logs:
                self.assertEqual(etl.load(batch), expected)
            self.assertEqual(len(logs.output), 3)
            self.assertTrue(all("0 kayıt eklendi" in entry for entry in logs.output))

            with self.assertRaisesRegex(etl.ETLError, "Kayıt sayıları uyuşmuyor"):
                etl.load(replace(batch, failure_records=[(1, 1, 0, 0, 0, 0, 0)]))
            self.assertEqual(etl.verify_counts(connection), expected)
