"""Verify Spark SQL parity and Kafka-to-PostgreSQL recovery locally."""

import json
import logging
import os
import subprocess
import sys
import unittest
from datetime import timezone
from itertools import islice, repeat
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from confluent_kafka import Producer, TopicPartition
from psycopg.errors import CheckViolation
from pyspark.sql import functions as F

from src.database import connect
from streaming.kafka_consumer import make_consumer
from streaming.kafka_producer import BOOTSTRAP, TOPIC, publish_events
from streaming.sensor_simulator import DATASET, sensor_events
from streaming.spark_batch import ROOT, SPARK_WORK, analytics_queries, analyze, read_ai4i, spark_session
from streaming.spark_streaming import (
    FIELDS, ensure_schema, kafka_events, parse_events, start_query, write_readings,
)

RUN_STREAM = os.environ.get("RUN_SPARK_STREAM_TESTS") == "1"


@unittest.skipUnless(os.environ.get("RUN_SPARK_TESTS") == "1" or RUN_STREAM,
                     "Spark tests require the optional local Java environment")
class SparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = spark_session(kafka=RUN_STREAM)
        cls.addClassCleanup(cls.spark.stop)

    def test_batch_matches_pandas_and_postgresql(self):
        data = read_ai4i(self.spark)
        results = analyze(self.spark, data)
        source = pd.read_csv(DATASET)
        failures = source["Machine failure"]
        torque = source["Torque [Nm]"]
        self.assertEqual((len(source), int(failures.sum())), (10_000, 339))
        expected = (len(source), failures.sum(), (failures == 0).sum(),
                    round(100 * failures.mean(), 2), round(torque.mean(), 5),
                    torque.min(), torque.max())
        self.assertEqual(tuple(results["overview"].first()), expected)
        self.assertEqual(results["above_average"].count(), int((torque > torque.mean()).sum()))

        with connect() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            for name, statement in analytics_queries().items():
                with self.subTest(query=name):
                    pg_rows = connection.execute(statement).fetchall()
                    expected = [tuple(float(value) if hasattr(value, "as_tuple") else value
                                      for value in row) for row in pg_rows]
                    self.assertEqual([tuple(row) for row in results[name].collect()], expected)

    def test_json_schema_utc_and_sensor_validation(self):
        event = next(sensor_events(interval=0))
        missing = {key: value for key, value in event.items() if key != "torque"}
        payloads = [
            json.dumps(row) for row in (
                event, missing, {**event, "torque": "3.2"}, {**event, "torque": -1},
                {**event, "tool_wear": True}, {**event, "tool_wear": 2.5},
                {**event, "process_temperature": 0}, {**event, "rotational_speed": -1},
                {**event, "torque": float("nan")}, {**event, "product_type": "unknown"},
                {**event, "event_id": "invalid"}, {**event, "machine_failure": 1},
                {**event, "event_time": "2026-11-25T15:00:00+03:00"},
                {**event, "event_time": "2026-02-30T15:00:00Z"},
            )
        ] + ["broken json"]
        # Spark's JVM SQL range avoids a Python worker for the test data.
        source = self.spark.range(len(payloads)).select(
            F.lit(TOPIC).alias("topic"), F.lit(0).alias("partition"),
            F.col("id").alias("offset"),
            F.get(F.array(*[F.lit(payload) for payload in payloads]), "id").alias("value"),
        )
        rows = parse_events(source).orderBy("offset").select("valid", "event_time").collect()
        self.assertEqual([row.valid for row in rows], [True] + [False] * (len(payloads) - 1))
        self.assertIsNotNone(rows[0].event_time)

    def test_database_transaction_rolls_back_previous_chunk(self):
        ensure_schema()
        events = list(islice(sensor_events(interval=0), 2))
        first, invalid = [tuple(event[name] for name in FIELDS) for event in events]
        invalid = (*invalid[:6], -1, invalid[-1])
        with self.assertRaises(CheckViolation):
            write_readings((*repeat(first, 250), invalid))
        self.assertEqual(self.read_rows(events), {})

    @staticmethod
    def read_rows(events):
        ids = [event["event_id"] for event in events]
        with connect() as connection:
            return dict(connection.execute("""
                SELECT event_id::text, event_time FROM public.stream_sensor_readings
                WHERE event_id = ANY(%s::uuid[])
            """, (ids,)).fetchall())

    @staticmethod
    def remove_fixture_rows(event_ids):
        with connect() as connection:
            connection.execute(
                "DELETE FROM public.stream_sensor_readings WHERE event_id = ANY(%s::uuid[])",
                (event_ids,),
            )

    @unittest.skipUnless(RUN_STREAM, "Kafka/Spark/PostgreSQL integration is opt-in")
    def test_stream_restart_duplicates_and_invalid_message(self):
        ensure_schema()
        bootstrap = os.getenv("SPARK_KAFKA_BOOTSTRAP", BOOTSTRAP)
        consumer = make_consumer("spark-offset-audit", bootstrap)
        try:
            start = consumer.get_watermark_offsets(TopicPartition(TOPIC, 0), timeout=10)[1]
        finally:
            consumer.close()
        start_json = json.dumps({TOPIC: {"0": start}})
        events = list(islice(sensor_events(interval=0), 100))
        expected = {event["event_id"]: event["event_time"] for event in events}
        self.assertEqual(len(expected), 100)
        self.assertEqual(self.read_rows(events), {})
        self.addCleanup(self.remove_fixture_rows, list(expected))
        self.assertEqual(publish_events(events, bootstrap), 100)
        SPARK_WORK.mkdir(exist_ok=True)

        def run(checkpoint, *, offsets, windows=False):
            source = kafka_events(self.spark, bootstrap=bootstrap, starting_offsets=offsets)
            query = start_query(source, checkpoint, available_now=True, windows=windows)
            try:
                self.assertTrue(query.awaitTermination(90))
                return sum(progress["numInputRows"] for progress in query.recentProgress)
            finally:
                if query.isActive:
                    query.stop()

        with TemporaryDirectory(dir=SPARK_WORK) as folder:
            checkpoint = Path(folder) / "readings"
            with self.assertLogs("streaming.spark_streaming", level=logging.INFO) as first:
                self.assertEqual(run(checkpoint, offsets=start_json), 100)
            self.assertTrue(any("eklenen=100" in message for message in first.output))
            stored = self.read_rows(events)
            self.assertEqual({key: value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                              for key, value in stored.items()}, expected)

            # A new Spark process ignores startingOffsets when it finds this checkpoint.
            restart = subprocess.run(
                [sys.executable, "-m", "streaming.spark_streaming", "--bootstrap", bootstrap,
                 "--starting-offsets", "earliest", "--checkpoint", str(checkpoint), "--available-now"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
            )
            self.assertEqual(restart.returncode, 0, restart.stderr)
            self.assertIn("Son batch Kafka girdisi=0", restart.stderr)
            self.assertNotIn("eklenen=", restart.stderr)
            self.assertEqual(publish_events(events, bootstrap), 100)
            malformed = Producer({"bootstrap.servers": bootstrap})
            malformed.produce(TOPIC, value=b'{"torque":-1}')
            self.assertEqual(malformed.flush(10), 0)
            with self.assertLogs("streaming.spark_streaming", level=logging.INFO) as replay:
                self.assertEqual(run(checkpoint, offsets="earliest"), 101)
            self.assertTrue(any("Geçersiz sensör olayı" in line and f"offset={start + 200}" in line
                                for line in replay.output))
            self.assertTrue(any("geçersiz=1 eklenen=0" in line for line in replay.output))
            self.assertEqual(self.read_rows(events), stored)

            with self.assertLogs("streaming.spark_streaming", level=logging.INFO) as windows:
                source_count = run(Path(folder) / "windows", offsets=start_json, windows=True)
            self.assertGreaterEqual(source_count, 201)
            self.assertTrue(any("pencere batch=" in line for line in windows.output))
            print(f"Spark audit: offset={start}..{start + 99}; inserted=100; "
                  "restart_input=0; replay_inserted=0; invalid=1")
