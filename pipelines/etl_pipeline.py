"""Load the AI4I batch into PostgreSQL without changing its measurement units."""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter

import pandas as pd
import psycopg
from psycopg import sql

from src.database import connect


LOGGER = logging.getLogger(__name__)
CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "ai4i2020.csv"
COLUMNS = {
    "UDI": "udi",
    "Product ID": "product_id",
    "Type": "type_code",
    "Air temperature [K]": "air_temperature",
    "Process temperature [K]": "process_temperature",
    "Rotational speed [rpm]": "rotational_speed",
    "Torque [Nm]": "torque",
    "Tool wear [min]": "tool_wear",
    "Machine failure": "machine_failure",
    "TWF": "twf",
    "HDF": "hdf",
    "PWF": "pwf",
    "OSF": "osf",
    "RNF": "rnf",
}
READING_COLUMNS = tuple(COLUMNS.values())[:8]
FAILURE_COLUMNS = ("udi", *tuple(COLUMNS.values())[8:])
PRODUCT_TYPES = {
    "H": ("High", "High-quality product variant"),
    "L": ("Low", "Low-quality product variant"),
    "M": ("Medium", "Medium-quality product variant"),
}
EXPECTED_COUNTS = {
    "product_types": 3,
    "sensor_readings": 10_000,
    "failure_records": 10_000,
    "ml_training_data": 10_000,
    "normal": 9_661,
    "failed": 339,
}


class ETLError(ValueError):
    """An actionable ETL error safe to display in logs."""


@dataclass
class Batch:
    product_types: list[tuple]
    sensor_readings: list[tuple]
    failure_records: list[tuple]


def extract(path: Path = CSV_PATH) -> pd.DataFrame:
    """Read CSV fields as text so validation sees the original values."""
    path = Path(path)
    if not path.is_file():
        raise ETLError(f"CSV dosyası bulunamadı: {path.name}")
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, skip_blank_lines=False)
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
        raise ETLError(f"CSV dosyası okunamadı veya biçimi geçersiz: {path.name}") from None
    missing = COLUMNS.keys() - set(frame.columns)
    if missing:
        raise ETLError(f"Eksik CSV sütunları: {', '.join(sorted(missing))}")
    if not isinstance(frame.index, pd.RangeIndex):
        raise ETLError("CSV başlığı ve veri satırlarının alan sayıları uyuşmuyor.")
    return frame


def parse_number(value: str, column: str, row: int) -> Decimal | int:
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ETLError(f"Veri satırı {row}, {column}: geçersiz sayı.") from None

    if not number.is_finite():
        raise ETLError(f"Veri satırı {row}, {column}: sonlu sayı gerekli.")
    if column in FAILURE_COLUMNS[1:]:
        if number not in (0, 1):
            raise ETLError(f"Veri satırı {row}, {column}: değer 0 veya 1 olmalı.")
        return int(number)
    if column in ("udi", "rotational_speed", "tool_wear"):
        minimum = 1 if column == "udi" else 0
        if not minimum <= number <= 2_147_483_647 or number != number.to_integral_value():
            raise ETLError(f"Veri satırı {row}, {column}: {minimum} ile 2147483647 arasında tam sayı gerekli.")
        return int(number)
    if number < 0 or (column != "torque" and number == 0):
        raise ETLError(f"Veri satırı {row}, {column}: fiziksel ölçüm aralığı geçersiz.")
    return number


def transform(frame: pd.DataFrame) -> Batch:
    """Validate the batch and build records in database column order."""
    if frame.empty:
        raise ETLError("CSV dosyasında veri satırı yok.")
    frame = frame.rename(columns=COLUMNS).loc[:, list(COLUMNS.values())]
    readings = []
    failures = []
    seen_udis = set()
    seen_products = set()
    for row, values in enumerate(frame.itertuples(index=False, name=None), start=1):
        for column, value in zip(frame.columns, values, strict=True):
            if pd.isna(value) or (isinstance(value, str) and not value.strip()):
                raise ETLError(f"Veri satırı {row}, {column}: eksik değer.")

        raw_udi, product_id, type_code, *numbers = values
        udi = parse_number(raw_udi, "udi", row)
        if type_code not in PRODUCT_TYPES:
            raise ETLError(f"Veri satırı {row}, type_code: ürün tipi L, M veya H olmalı.")
        if not isinstance(product_id, str) or not re.fullmatch(r"[LMH][0-9]+", product_id):
            raise ETLError(f"Veri satırı {row}, product_id: geçersiz ürün kimliği.")
        if product_id[0] != type_code:
            raise ETLError(f"Veri satırı {row}, product_id: ürün tipi ile uyuşmuyor.")
        if udi in seen_udis or product_id in seen_products:
            column = "udi" if udi in seen_udis else "product_id"
            raise ETLError(f"Veri satırı {row}, {column}: tekrarlanan kimlik.")
        seen_udis.add(udi)
        seen_products.add(product_id)

        measures = tuple(
            parse_number(value, column, row)
            for column, value in zip(READING_COLUMNS[3:], numbers[:5], strict=True)
        )
        flags = tuple(
            parse_number(value, column, row)
            for column, value in zip(FAILURE_COLUMNS[1:], numbers[5:], strict=True)
        )
        readings.append((udi, product_id, type_code, *measures))
        failures.append((udi, *flags))

    types = [(code, *details) for code, details in PRODUCT_TYPES.items()]
    return Batch(types, sorted(readings), sorted(failures))


def upsert(cursor, table: str, columns: tuple[str, ...], records: list[tuple]) -> None:
    key, *fields = map(sql.Identifier, columns)
    assignments = sql.SQL(", ").join(
        sql.SQL("{0} = EXCLUDED.{0}").format(field) for field in fields
    )
    query = sql.SQL(
        "INSERT INTO public.{} AS current_row ({}) VALUES ({}) "
        "ON CONFLICT ({}) DO UPDATE SET {} WHERE ({}) IS DISTINCT FROM ({})"
    ).format(
        sql.Identifier(table),
        sql.SQL(", ").join([key, *fields]),
        sql.SQL(", ").join([sql.Placeholder()] * len(columns)),
        key,
        assignments,
        sql.SQL(", ").join(sql.SQL("current_row.{}").format(field) for field in fields),
        sql.SQL(", ").join(sql.SQL("EXCLUDED.{}").format(field) for field in fields),
    )
    cursor.executemany(query, records)
    LOGGER.info("%s: %s kayıt gönderildi, %s kayıt eklendi veya güncellendi.", table, len(records), cursor.rowcount)


def verify_counts(connection) -> dict[str, int]:
    counts = dict(zip(EXPECTED_COUNTS, connection.execute("""
        SELECT
            (SELECT count(*) FROM public.product_types),
            (SELECT count(*) FROM public.sensor_readings),
            (SELECT count(*) FROM public.failure_records),
            count(*),
            count(*) FILTER (WHERE machine_failure = 0),
            count(*) FILTER (WHERE machine_failure = 1)
        FROM public.ml_training_data
    """).fetchone(), strict=True))
    if counts != EXPECTED_COUNTS:
        differences = ", ".join(
            f"{name}={actual} (beklenen {EXPECTED_COUNTS[name]})"
            for name, actual in counts.items() if actual != EXPECTED_COUNTS[name]
        )
        raise ETLError(f"Kayıt sayıları uyuşmuyor: {differences}")
    return counts


def load(batch: Batch) -> dict[str, int]:
    """Commit all three batches only after database count verification."""
    with connect() as connection:
        with connection.cursor() as cursor:
            upsert(cursor, "product_types", ("type_code", "type_name", "description"), batch.product_types)
            upsert(cursor, "sensor_readings", READING_COLUMNS, batch.sensor_readings)
            upsert(cursor, "failure_records", FAILURE_COLUMNS, batch.failure_records)
        return verify_counts(connection)


def run_pipeline(path: Path = CSV_PATH) -> dict[str, int]:
    started = perf_counter()
    LOGGER.info("ETL başladı.")
    try:
        frame = extract(path)
        LOGGER.info("Extract: %s CSV kaydı okundu.", len(frame))
        batch = transform(frame)
        LOGGER.info("Transform: %s ölçüm doğrulandı.", len(batch.sensor_readings))
        counts = load(batch)
    except (ETLError, psycopg.Error, KeyError, ValueError) as error:
        if isinstance(error, ETLError):
            message = str(error)
        elif isinstance(error, psycopg.Error):
            message = f"PostgreSQL işlemi başarısız (SQLSTATE {error.sqlstate or 'yok'})."
        else:
            message = "ETL yapılandırması veya veri biçimi geçersiz."
        LOGGER.error("ETL başarısız (%.2f sn). %s", perf_counter() - started, message)
        raise ETLError(message) from None
    LOGGER.info("ETL tamamlandı (%.2f sn). %s", perf_counter() - started, counts)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run_pipeline()
    except ETLError:
        raise SystemExit(1) from None
