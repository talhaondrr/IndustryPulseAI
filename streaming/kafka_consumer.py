"""Validate and log sensor events, then commit the next Kafka offset."""

import argparse
import json
import logging

from confluent_kafka import Consumer, KafkaException

from streaming.kafka_producer import BOOTSTRAP, TOPIC
from streaming.sensor_simulator import validate_event

LOGGER = logging.getLogger(__name__)


def make_consumer(group, bootstrap=BOOTSTRAP, start="earliest"):
    return Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": group,
        "auto.offset.reset": start,
        "enable.auto.commit": False,
    })


def process_message(message):
    """Validate one message and log its position even when the payload is invalid."""
    if message.error():
        raise KafkaException(message.error())
    try:
        event = json.loads(message.value())
        validate_event(event)
    except (TypeError, ValueError) as error:
        LOGGER.warning("Geçersiz olay partition=%d offset=%d neden=%s",
                       message.partition(), message.offset(), error)
        return None
    LOGGER.info("partition=%d offset=%d event=%s", message.partition(), message.offset(), event)
    return event


def commit_message(consumer, message):
    for partition in consumer.commit(message=message, asynchronous=False):
        if partition.error:
            raise KafkaException(partition.error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=BOOTSTRAP)
    parser.add_argument("--group", default="industrial-sensor-learning")
    parser.add_argument("--start", choices=("earliest", "latest"), default="earliest")
    parser.add_argument("--count", type=int, help="İşlenecek Kafka kaydı sayısı.")
    args = parser.parse_args()
    if args.count is not None and args.count < 1:
        parser.error("--count pozitif olmalıdır.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    consumer = make_consumer(args.group, args.bootstrap, args.start)
    processed = 0
    try:
        consumer.subscribe([TOPIC])
        LOGGER.info("Consumer group=%s", args.group)
        while args.count is None or processed < args.count:
            message = consumer.poll(1)
            if message is None:
                continue
            process_message(message)
            commit_message(consumer, message)
            processed += 1
    except KeyboardInterrupt:
        LOGGER.info("Consumer durduruldu.")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
