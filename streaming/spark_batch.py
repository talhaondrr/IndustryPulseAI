"""Read and summarize the AI4I CSV locally with Spark."""

import os
import re
import sys
from pathlib import Path

from pyspark.sql import SparkSession, functions as F, types as T

from streaming.sensor_simulator import DATASET

ROOT = Path(__file__).resolve().parents[1]
SPARK_WORK = ROOT / ".spark"
KAFKA_CONNECTOR = "org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.2"
CSV_COLUMNS = (
    ("UDI", "udi", T.IntegerType()), ("Product ID", "product_id", T.StringType()),
    ("Type", "type_code", T.StringType()),
    ("Air temperature [K]", "air_temperature", T.DoubleType()),
    ("Process temperature [K]", "process_temperature", T.DoubleType()),
    ("Rotational speed [rpm]", "rotational_speed", T.IntegerType()),
    ("Torque [Nm]", "torque", T.DoubleType()),
    ("Tool wear [min]", "tool_wear", T.IntegerType()),
    ("Machine failure", "machine_failure", T.IntegerType()),
    *((name, name.lower(), T.IntegerType()) for name in ("TWF", "HDF", "PWF", "OSF", "RNF")),
)


def spark_session(*, kafka=False):
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    ivy = SPARK_WORK / "ivy" / sys.platform
    ivy.mkdir(parents=True, exist_ok=True)
    builder = (
        SparkSession.builder.master("local[2]").appName("IndustryPulseAI")
        .config("spark.driver.memory", "1g")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.jars.ivy", str(ivy))
        .config("spark.sql.warehouse.dir", (SPARK_WORK / "warehouse").as_uri())
    )
    if kafka:
        builder = builder.config("spark.jars.packages", KAFKA_CONNECTOR)
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark


def read_ai4i(spark, path=DATASET):
    schema = T.StructType([T.StructField(header, kind) for header, _, kind in CSV_COLUMNS])
    data = (spark.read.schema(schema).option("header", True).option("enforceSchema", False)
            .option("mode", "FAILFAST").csv(Path(path).resolve().as_uri())
            .toDF(*(column for _, column, _ in CSV_COLUMNS)))
    invalid = F.lit(False)
    for field in data.columns:
        invalid = invalid | F.col(field).isNull()
    invalid = invalid | ~F.col("type_code").isin("H", "L", "M") | ~F.col("machine_failure").isin(0, 1)
    audit = data.agg(F.count("*"), F.countDistinct("udi"), F.count_if(invalid)).first()
    if tuple(audit) != (10_000, 10_000, 0):
        raise ValueError(f"Beklenen 10.000 geçerli benzersiz UDI doğrulanamadı: {tuple(audit)}")
    return data


def analytics_queries():
    sql = (ROOT / "sql/02_analytics_queries.sql").read_text(encoding="utf-8")
    parts = re.split(r"(?m)^-- name: (\w+)\s*$", sql)
    return {
        name: statement for name, statement in zip(parts[1::2], parts[2::2], strict=True)
        if not name.startswith("plan_")
    }


def analyze(spark, data):
    # Expose the CSV as the same logical tables used by the PostgreSQL queries.
    for view in ("ml_training_data", "sensor_readings", "failure_records"):
        data.createOrReplaceTempView(view)
    spark.sql("""
        SELECT * FROM VALUES ('H', 'High'), ('L', 'Low'), ('M', 'Medium')
        AS product_types(type_code, type_name)
    """).createOrReplaceTempView("product_types")
    queries = {name: statement.replace("public.", "")
               for name, statement in analytics_queries().items()}
    # Spark STACK unpivots the five totals calculated by PostgreSQL's LATERAL VALUES.
    queries["failure_modes"] = """
        WITH totals AS (
            SELECT sum(twf) AS twf, sum(hdf) AS hdf, sum(pwf) AS pwf,
                   sum(osf) AS osf, sum(rnf) AS rnf
            FROM failure_records
        )
        SELECT stack(5, 'TWF', twf, 'HDF', hdf, 'PWF', pwf, 'OSF', osf, 'RNF', rnf)
               AS (failure_type, record_count)
        FROM totals
        ORDER BY record_count DESC, failure_type
    """
    return {name: spark.sql(statement) for name, statement in queries.items()}


def main():
    spark = spark_session()
    try:
        data = read_ai4i(spark)
        data.printSchema()
        results = analyze(spark, data)
        for name, result in results.items():
            print(name)
            result.show(10)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
