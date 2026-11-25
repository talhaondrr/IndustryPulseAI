"""Consume Kafka with Spark and write valid readings to PostgreSQL."""

import argparse
import logging
import os
from itertools import batched
from pathlib import Path

from pyspark.sql import functions as F, types as T

from src.database import connect
from streaming.kafka_producer import BOOTSTRAP, TOPIC
from streaming.sensor_simulator import SENSOR_COLUMNS
from streaming.spark_batch import ROOT, SPARK_WORK, spark_session

LOGGER = logging.getLogger(__name__)
FIELDS = ("event_id", "event_time", "product_type", *SENSOR_COLUMNS)
EVENT_SCHEMA = T.StructType([
    *[T.StructField(name, T.StringType()) for name in FIELDS[:3]],
    *[T.StructField(name, T.IntegerType() if kind is int else T.DoubleType())
      for name, (_, kind) in SENSOR_COLUMNS.items()],
])
INSERT = """
INSERT INTO public.stream_sensor_readings (
    event_id, event_time, product_type, air_temperature, process_temperature,
    rotational_speed, torque, tool_wear
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (event_id) DO NOTHING
"""


def ensure_schema():
    ddl = (ROOT / "sql/03_streaming_schema.sql").read_text(encoding="utf-8")
    with connect() as connection:
        connection.execute(ddl)


def parse_events(source):
    payload = F.col("value").cast("string")
    parsed = source.select(
        "topic", "partition", "offset",
        F.from_json(payload, EVENT_SCHEMA, {"allowNonNumericNumbers": "false"}).alias("event"),
        F.json_object_keys(payload).alias("keys"),
    ).select("topic", "partition", "offset", "keys", "event.*")
    utc_time = F.col("event_time").rlike(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$"
    )
    valid = (
        (F.array_sort("keys") == F.array(*[F.lit(name) for name in sorted(FIELDS)]))
        & F.col("event_id").rlike(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
        & utc_time & F.try_to_timestamp("event_time").isNotNull()
        & F.col("product_type").isin("H", "L", "M")
        & (F.col("air_temperature") > 0) & (F.col("process_temperature") > 0)
        & (F.col("rotational_speed") >= 0) & (F.col("tool_wear") >= 0) & (F.col("torque") >= 0)
    )
    for name in ("air_temperature", "process_temperature", "torque"):
        valid = valid & (F.col(name) < float("inf"))
    return (parsed.withColumn("valid", F.coalesce(valid, F.lit(False))).drop("keys")
            .withColumn("event_time", F.try_to_timestamp("event_time")))


def kafka_events(spark, *, bootstrap=None, starting_offsets="earliest"):
    bootstrap = bootstrap or os.getenv("SPARK_KAFKA_BOOTSTRAP", BOOTSTRAP)
    source = (
        spark.readStream.format("kafka").option("kafka.bootstrap.servers", bootstrap)
        .option("subscribe", TOPIC).option("startingOffsets", starting_offsets)
        .option("kafka.allow.auto.create.topics", "false")
        .option("maxOffsetsPerTrigger", 1000).load()
    )
    return parse_events(source)


def write_readings(records):
    """Commit one micro-batch; a failed chunk rolls back all earlier chunks."""
    inserted = 0
    with connect() as connection, connection.cursor() as cursor:
        for group in batched(records, 250):
            cursor.executemany(INSERT, group)
            inserted += cursor.rowcount
    return inserted


def process_batch(batch, batch_id):
    batch.persist()
    try:
        good = batch.where("valid")
        summary = batch.agg(
            F.count("*").alias("total"), F.count_if("valid").alias("valid_count"),
            F.avg(F.when(F.col("valid"), F.col("torque"))).alias("avg_torque"),
            F.avg(F.when(F.col("valid"), F.col("air_temperature"))).alias("avg_air_temp"),
            F.avg(F.when(F.col("valid"), F.col("process_temperature"))).alias("avg_process_temp"),
        ).first()
        if summary.total != summary.valid_count:
            invalid = batch.where("not valid").select("topic", "partition", "offset")
            for row in invalid.toLocalIterator():
                LOGGER.warning("Geçersiz sensör olayı topic=%s partition=%s offset=%s", *row)
        inserted = 0
        if summary.valid_count:
            # Serializing with an explicit UTC offset avoids the Python host's local timezone.
            utc = F.date_format("event_time", "yyyy-MM-dd'T'HH:mm:ss.SSSSSS'Z'")
            records = good.withColumn("event_time", utc).select(*FIELDS).toLocalIterator()
            inserted = write_readings(records)
        LOGGER.info(
            "batch=%s toplam=%s geçerli=%s geçersiz=%s eklenen=%s ort_tork=%s ort_hava=%s ort_proses=%s",
            batch_id, summary.total, summary.valid_count, summary.total - summary.valid_count,
            inserted, summary.avg_torque, summary.avg_air_temp, summary.avg_process_temp,
        )
    finally:
        batch.unpersist()


def window_totals(events):
    return (events.where("valid").withWatermark("event_time", "2 minutes")
            .groupBy(F.window("event_time", "1 minute"))
            .agg(F.count("*").alias("events"), F.avg("torque").alias("avg_torque"),
                 F.avg("air_temperature").alias("avg_air_temperature")))


def log_windows(batch, batch_id):
    for row in batch.select(
        F.date_format("window.start", "yyyy-MM-dd'T'HH:mm:ss'Z'").alias("start"),
        F.date_format("window.end", "yyyy-MM-dd'T'HH:mm:ss'Z'").alias("end"),
        "events", "avg_torque", "avg_air_temperature",
    ).toLocalIterator():
        LOGGER.info("pencere batch=%s %s", batch_id, row.asDict())


def start_query(events, checkpoint, *, available_now=False, windows=False):
    if windows:
        writer = window_totals(events).writeStream.outputMode("update").foreachBatch(log_windows)
    else:
        writer = events.writeStream.foreachBatch(process_batch)
    writer = writer.option("checkpointLocation", Path(checkpoint).resolve().as_uri())
    if available_now:
        return writer.trigger(availableNow=True).start()
    return writer.trigger(processingTime="5 seconds").start()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=os.getenv("SPARK_KAFKA_BOOTSTRAP", BOOTSTRAP))
    parser.add_argument("--starting-offsets", default="earliest")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--available-now", action="store_true")
    parser.add_argument("--windows", action="store_true", help="Olay zamanı pencerelerini logla.")
    args = parser.parse_args()
    checkpoint = args.checkpoint or SPARK_WORK / ("windows" if args.windows else "readings")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.windows:
        ensure_schema()
    spark = spark_session(kafka=True)
    try:
        events = kafka_events(spark, bootstrap=args.bootstrap, starting_offsets=args.starting_offsets)
        query = start_query(events, checkpoint, available_now=args.available_now, windows=args.windows)
        try:
            query.awaitTermination()
            if args.available_now:
                LOGGER.info("Tetik tamamlandı. Son batch Kafka girdisi=%s",
                            (query.lastProgress or {}).get("numInputRows", 0))
        except KeyboardInterrupt:
            query.stop()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
