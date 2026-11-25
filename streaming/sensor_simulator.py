"""Replay the AI4I sensor measurements as fresh UTC events."""

import csv
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from time import sleep
from uuid import UUID, uuid4

DATASET = Path(__file__).resolve().parents[1] / "data" / "raw" / "ai4i2020.csv"
SENSOR_COLUMNS = {
    "air_temperature": ("Air temperature [K]", float),
    "process_temperature": ("Process temperature [K]", float),
    "rotational_speed": ("Rotational speed [rpm]", int),
    "torque": ("Torque [Nm]", float),
    "tool_wear": ("Tool wear [min]", int),
}
EVENT_FIELDS = {"event_id", "event_time", "product_type", *SENSOR_COLUMNS}


def sensor_events(path=DATASET, *, interval=1.0):
    """Stream rows in CSV order and restart at the beginning at EOF."""
    if not isfinite(interval) or interval < 0:
        raise ValueError("Olay aralığı sonlu ve sıfır veya daha büyük olmalıdır.")
    first = True
    while True:
        has_rows = False
        with open(path, encoding="utf-8", newline="") as source:
            rows = csv.DictReader(source)
            for row in rows:
                has_rows = True
                if not first and interval:
                    sleep(interval)
                first = False
                event = {
                    "event_id": str(uuid4()),
                    "event_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "product_type": row["Type"],
                    **{name: convert(row[column]) for name, (column, convert) in SENSOR_COLUMNS.items()},
                }
                validate_event(event)
                yield event
        if not has_rows:
            raise ValueError("Sensör CSV dosyasında veri satırı bulunamadı.")


def validate_event(event):
    """Reject missing or extra fields, malformed identifiers and invalid sensor types."""
    if not isinstance(event, dict) or event.keys() != EVENT_FIELDS:
        raise ValueError("Olay şeması beklenen zorunlu alanlarla eşleşmiyor.")
    event_id = event["event_id"]
    try:
        if not isinstance(event_id, str) or str(UUID(event_id)) != event_id:
            raise ValueError
    except ValueError:
        raise ValueError("event_id standart UUID biçiminde olmalıdır.") from None
    timestamp = event["event_time"]
    try:
        if not isinstance(timestamp, str) or "T" not in timestamp:
            raise ValueError
        if datetime.fromisoformat(timestamp).utcoffset() != timedelta(0):
            raise ValueError
    except ValueError:
        raise ValueError("event_time ISO 8601 biçiminde bir UTC zamanı olmalıdır.") from None
    if event["product_type"] not in ("L", "M", "H"):
        raise ValueError("product_type L, M veya H olmalıdır.")
    for field, (_, kind) in SENSOR_COLUMNS.items():
        value = event[field]
        allowed = (int,) if kind is int else (int, float)
        if type(value) not in allowed or (type(value) is float and not isfinite(value)):
            raise ValueError(f"{field} sonlu bir {kind.__name__} değeri olmalıdır.")
