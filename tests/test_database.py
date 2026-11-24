"""Integration tests for the applied PostgreSQL schema."""

import unittest
from decimal import Decimal
from uuid import uuid4

import psycopg
from psycopg import errors

from src.database import connect


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        try:
            self.connection = connect()
        except (psycopg.Error, KeyError, ValueError):
            self.fail("PostgreSQL bağlantısı kurulamadı.")
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)

    def create_reading(self):
        self.connection.execute(
            "INSERT INTO public.product_types (type_code, type_name) "
            "VALUES ('L', 'Low') ON CONFLICT (type_code) DO NOTHING"
        )
        udi = uuid4().int % 1_000_000_000 + 1_000_000_000
        self.connection.execute(
            "INSERT INTO public.sensor_readings "
            "(udi, product_id, type_code, air_temperature, process_temperature, "
            "rotational_speed, torque, tool_wear) "
            "VALUES (%s, 'LTEST', 'L', 300, 310, 1500, 40, 0)",
            (udi,),
        )
        return udi

    def test_connection(self):
        self.assertEqual(
            self.connection.execute("SELECT current_database(), 1").fetchone(),
            ("industrypulse_db", 1),
        )

    def test_tables_exist(self):
        tables = self.connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "AND table_name IN ('product_types', 'sensor_readings', 'failure_records')"
        ).fetchall()
        self.assertCountEqual(
            tables, [("product_types",), ("sensor_readings",), ("failure_records",)]
        )

    def test_integrity(self):
        udi = self.create_reading()
        self.connection.execute(
            "INSERT INTO public.failure_records VALUES (%s, 1, 0, 0, 0, 0, 0)",
            (udi,),
        )
        cases = [
            (errors.UniqueViolation, "INSERT INTO public.product_types VALUES ('L', 'Low')", ()),
            (errors.UniqueViolation, "INSERT INTO public.sensor_readings SELECT * FROM public.sensor_readings WHERE udi = %s", (udi,)),
            (errors.UniqueViolation, "INSERT INTO public.failure_records VALUES (%s, 1, 0, 0, 0, 0, 0)", (udi,)),
            (errors.ForeignKeyViolation, "UPDATE public.sensor_readings SET type_code = 'X' WHERE udi = %s", (udi,)),
            (errors.ForeignKeyViolation, "DELETE FROM public.sensor_readings WHERE udi = %s", (udi,)),
            (errors.NotNullViolation, "UPDATE public.sensor_readings SET product_id = NULL WHERE udi = %s", (udi,)),
            (errors.CheckViolation, "UPDATE public.sensor_readings SET tool_wear = -1 WHERE udi = %s", (udi,)),
            (errors.CheckViolation, "UPDATE public.sensor_readings SET torque = 'NaN' WHERE udi = %s", (udi,)),
            (errors.CheckViolation, "UPDATE public.failure_records SET machine_failure = 2 WHERE udi = %s", (udi,)),
        ]
        for expected_error, statement, params in cases:
            with self.subTest(statement=statement):
                with self.assertRaises(expected_error):
                    with self.connection.transaction():
                        self.connection.execute(statement, params)

    def test_training_view(self):
        columns = self.connection.execute("SELECT * FROM public.ml_training_data LIMIT 0")
        self.assertEqual(
            [column.name for column in columns.description],
            [
                "type_code", "air_temperature", "process_temperature",
                "rotational_speed", "torque", "tool_wear", "machine_failure",
            ],
        )
        query = (
            "SELECT * FROM public.ml_training_data EXCEPT ALL "
            "SELECT * FROM baseline_training_data"
        )
        self.connection.execute(
            "CREATE TEMP TABLE baseline_training_data AS SELECT * FROM public.ml_training_data"
        )
        udi = self.create_reading()
        self.connection.execute(
            "UPDATE public.sensor_readings SET torque = 98765.4321 WHERE udi = %s",
            (udi,),
        )
        self.assertEqual(self.connection.execute(query).fetchall(), [])
        self.connection.execute(
            "INSERT INTO public.failure_records VALUES (%s, 1, 0, 0, 0, 0, 0)",
            (udi,),
        )
        self.assertEqual(
            self.connection.execute(query).fetchall(),
            [("L", 300, 310, 1500, Decimal("98765.4321"), 0, 1)],
        )
