"""Publish simulated sensor events to the local Kafka broker."""

import argparse
import itertools
import json
import logging

from confluent_kafka import Producer

from streaming.sensor_simulator import sensor_events

BOOTSTRAP = "127.0.0.1:9092"
TOPIC = "industrial-sensor-data"
LOGGER = logging.getLogger(__name__)


def publish_events(events, bootstrap=BOOTSTRAP):
    producer = Producer({
        "bootstrap.servers": bootstrap,
        "enable.idempotence": True,
        "acks": "all",
        "delivery.timeout.ms": 15000,
    })
    accepted = 0
    first_error = None

    def delivered(error, message):
        nonlocal accepted, first_error
        if error is None:
            accepted += 1
            LOGGER.debug("Teslim edildi partition=%s offset=%s", message.partition(), message.offset())
        elif first_error is None:
            first_error = error

    try:
        for event in events:
            payload = json.dumps(event, allow_nan=False, separators=(",", ":")).encode("utf-8")
            while True:
                try:
                    producer.produce(TOPIC, key=event["event_id"], value=payload, on_delivery=delivered)
                    break
                except BufferError:
                    producer.poll(0.1)
                    if first_error is not None:
                        break
            producer.poll(0)
            if first_error is not None:
                break
    finally:
        pending = producer.flush(20)
    if first_error is not None or pending:
        raise RuntimeError(f"Kafka teslimi tamamlanamadı. Bekleyen={pending}, hata={first_error}")
    return accepted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=BOOTSTRAP)
    parser.add_argument("--count", type=int, help="Olay sayısı. Verilmezse sürekli oynatılır.")
    parser.add_argument("--interval", type=float, default=1.0, help="Olaylar arası saniye.")
    args = parser.parse_args()
    if args.count is not None and args.count < 1:
        parser.error("--count pozitif olmalıdır.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    events = itertools.islice(sensor_events(interval=args.interval), args.count)
    try:
        LOGGER.info("Broker tarafından onaylanan olay sayısı=%d", publish_events(events, args.bootstrap))
    except KeyboardInterrupt:
        LOGGER.info("Producer durduruldu.")


if __name__ == "__main__":
    main()
