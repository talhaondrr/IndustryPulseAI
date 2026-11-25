"""Read-only dashboard queries and published evaluation artifacts."""

import csv
import json
import logging
from pathlib import Path
from statistics import mean
from time import perf_counter

import psycopg
from confluent_kafka import Consumer, KafkaException
from fastapi import APIRouter, HTTPException, Query, Request
from psycopg.rows import dict_row

from src.database import connect
from streaming.kafka_producer import BOOTSTRAP, TOPIC

router = APIRouter(prefix="/analytics", tags=["Dashboard analytics"])
ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)
METRICS = ("accuracy", "balanced_accuracy", "precision", "recall", "f1", "roc_auc", "average_precision")


def read_query(sql, params=()):
    try:
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '3s'")
            return cursor.execute(sql, params).fetchall()
    except (psycopg.Error, KeyError, ValueError) as error:
        LOGGER.warning("Dashboard database query failed (%s).", type(error).__name__)
        raise HTTPException(503, "PostgreSQL data is currently unavailable.") from None


@router.get("/summary")
def summary():
    started = perf_counter()
    counts = read_query("""
        SELECT (SELECT count(*) FROM public.product_types) AS product_types,
               (SELECT count(*) FROM public.sensor_readings) AS sensor_records,
               (SELECT count(*) FROM public.failure_records) AS failure_records,
               count(*) AS training_records,
               count(*) FILTER (WHERE machine_failure = 1) AS failures,
               count(*) FILTER (WHERE machine_failure = 0) AS normal,
               to_regclass('public.stream_sensor_readings') IS NOT NULL AS stream_table_exists
        FROM public.ml_training_data
    """)[0]
    if counts.pop("stream_table_exists"):
        counts["stream_events"] = read_query("SELECT count(*) AS total FROM public.stream_sensor_readings")[0]["total"]
    else:
        counts["stream_events"] = None
    counts["count_query_ms"] = round((perf_counter() - started) * 1000, 1)
    benchmark = ROOT / "results/etl_dashboard_benchmark.json"
    try:
        counts["etl_benchmark"] = json.loads(benchmark.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        counts["etl_benchmark"] = None
    return counts


@router.get("/sensors")
def sensors(limit: int = Query(default=30, ge=1, le=100)):
    if not read_query("SELECT to_regclass('public.stream_sensor_readings') IS NOT NULL AS present")[0]["present"]:
        return {"table_available": False, "readings": []}
    readings = read_query("""
        SELECT event_id, event_time, product_type, air_temperature, process_temperature,
               rotational_speed, torque, tool_wear
        FROM public.stream_sensor_readings ORDER BY event_time DESC, event_id DESC LIMIT %s
    """, (limit,))
    return {"table_available": True, "readings": readings}


def csv_rows(path):
    with (ROOT / "results" / path).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


@router.get("/models")
def model_metrics():
    try:
        cross_validation = [
            {"model": row["model"], **{key: float(row[f"{key}_mean"]) for key in METRICS}}
            for row in csv_rows("mlp/model_comparison.csv")
        ]
        test, = csv_rows("test_metrics.csv")
        epochs = {}
        for row in csv_rows("mlp/training_history.csv"):
            epochs.setdefault(int(row["epoch"]), []).append(float(row["train_loss"]))
        return {
            "cross_validation": cross_validation,
            "independent_test": {
                "model": test["model"], **{metric: float(test[metric]) for metric in METRICS},
                **{key: int(test[key]) for key in ("tn", "fp", "fn", "tp")},
            },
            "mlp_training_loss": [{"epoch": epoch, "loss": mean(values)} for epoch, values in sorted(epochs.items())],
        }
    except (OSError, KeyError, ValueError) as error:
        LOGGER.warning("Dashboard model artifacts unavailable (%s).", type(error).__name__)
        raise HTTPException(503, "Published model metrics are currently unavailable.") from None


def kafka_status():
    client = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": "industrypulse-dashboard-health", "log_level": 0})
    try:
        metadata = client.list_topics(timeout=1.5)
        topic = metadata.topics.get(TOPIC)
        if topic is not None and topic.error is None and topic.partitions:
            return {"name": "Kafka", "status": "Ready", "detail": "Broker and industrial-sensor-data topic verified."}
        return {"name": "Kafka", "status": "Degraded", "detail": "Broker responded. Sensor topic is unavailable."}
    except KafkaException:
        return {"name": "Kafka", "status": "Unknown", "detail": "Broker metadata probe did not succeed."}
    finally:
        client.close()


@router.get("/health")
def service_health(request: Request):
    model_ready = request.app.state.prediction_service is not None
    try:
        read_query("SELECT 1")
        postgres = {"name": "PostgreSQL", "status": "Ready", "detail": "Read-only connection verified."}
    except HTTPException:
        postgres = {"name": "PostgreSQL", "status": "Unavailable", "detail": "Read-only connection failed."}
    return [
        {"name": "FastAPI", "status": "Ready", "detail": "Analytics endpoint responded."},
        {"name": "XGBoost model", "status": "Ready" if model_ready else "Unavailable",
         "detail": "Local pipeline loaded." if model_ready else "Local pipeline could not be loaded."},
        postgres,
        kafka_status(),
        {"name": "Spark", "status": "Unknown", "detail": "On-demand local job. No active-query probe is configured."},
    ]
