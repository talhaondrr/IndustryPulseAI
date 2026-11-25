"""Unit checks and an opt-in local Kafka delivery audit."""

import json
import os
import unittest
from itertools import islice
from time import monotonic
from unittest.mock import Mock, patch
from uuid import uuid4

from confluent_kafka import TopicPartition

from streaming.kafka_consumer import commit_message, make_consumer, process_message
from streaming.kafka_producer import BOOTSTRAP, TOPIC, publish_events
from streaming.sensor_simulator import EVENT_FIELDS, sensor_events, validate_event


class StreamingTests(unittest.TestCase):
    def test_generates_one_hundred_unique_utc_events_without_labels(self):
        events = list(islice(sensor_events(interval=0), 100))
        self.assertEqual(len({event["event_id"] for event in events}), 100)
        self.assertEqual(events[0]["air_temperature"], 298.1)
        self.assertEqual(events[0]["rotational_speed"], 1551)
        for event in events:
            self.assertEqual(set(event), EVENT_FIELDS)
            self.assertTrue(event["event_time"].endswith("Z"))
            validate_event(event)

    def test_paces_events_after_the_first(self):
        with patch("streaming.sensor_simulator.sleep") as sleep:
            events = sensor_events(interval=0.25)
            next(events)
            sleep.assert_not_called()
            next(events)
            sleep.assert_called_once_with(0.25)
            events.close()

    def test_rejects_missing_fields_and_invalid_values(self):
        event = next(sensor_events(interval=0))
        incomplete = event.copy()
        del incomplete["torque"]
        cases = (
            incomplete, {**event, "machine_failure": 1},
            {**event, "event_id": "broken"}, {**event, "event_time": "2026-01-01T12:00:00"},
            {**event, "event_time": "2026-01-01T12:00:00+03:00"},
            {**event, "product_type": "X"}, {**event, "rotational_speed": 1500.0},
            {**event, "tool_wear": False}, {**event, "torque": float("nan")},
            {**event, "air_temperature": "298.1"},
        )
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_event(invalid)

    def test_consumer_logs_invalid_json_and_accepts_valid_payload(self):
        message = Mock()
        message.error.return_value = None
        message.partition.return_value = 0
        message.offset.return_value = 12
        for invalid in (b"not json", b"{}", b"\xff", None):
            with self.subTest(invalid=invalid), self.assertLogs(
                "streaming.kafka_consumer", level="WARNING"
            ) as logs:
                message.value.return_value = invalid
                self.assertIsNone(process_message(message))
                self.assertIn("partition=0 offset=12", logs.output[0])
        event = next(sensor_events(interval=0))
        message.value.return_value = json.dumps(event).encode("utf-8")
        self.assertEqual(process_message(message), event)


@unittest.skipUnless(os.getenv("RUN_KAFKA_TESTS") == "1", "Kafka integration is opt-in")
class KafkaIntegrationTests(unittest.TestCase):
    def test_one_hundred_events_without_loss_or_duplicates_and_group_resume(self):
        bootstrap = os.getenv("KAFKA_TEST_BOOTSTRAP", BOOTSTRAP)
        group = f"industrypulse-audit-{uuid4()}"
        partition = TopicPartition(TOPIC, 0)
        expected = list(islice(sensor_events(interval=0), 100))
        expected_ids = {event["event_id"] for event in expected}
        self.assertEqual(len(expected_ids), 100)

        consumer = make_consumer(group, bootstrap)
        try:
            topic = consumer.list_topics(TOPIC, timeout=10).topics[TOPIC]
            self.assertIsNone(topic.error)
            self.assertEqual(set(topic.partitions), {0})
            self.assertEqual(len(topic.partitions[0].replicas), 1)
            _, start = consumer.get_watermark_offsets(partition, timeout=10)
            self.assertEqual(publish_events(expected, bootstrap), 100)
            _, end = consumer.get_watermark_offsets(partition, timeout=10)
            self.assertEqual(end - start, 100)

            def start_at_boundary(client, partitions):
                partitions[0].offset = start
                client.assign(partitions)

            consumer.subscribe([TOPIC], on_assign=start_at_boundary)
            received, offsets = [], []
            deadline = monotonic() + 20
            while len(received) < end - start and monotonic() < deadline:
                message = consumer.poll(0.5)
                if message is None:
                    continue
                event = process_message(message)
                self.assertIsNotNone(event)
                self.assertEqual(message.key().decode("utf-8"), event["event_id"])
                received.append(event)
                offsets.append(message.offset())
                commit_message(consumer, message)
            received_ids = [event["event_id"] for event in received]
            self.assertEqual(expected_ids - set(received_ids), set())
            self.assertEqual(len(received_ids) - len(set(received_ids)), 0)
            self.assertEqual(received, expected)
            self.assertEqual(offsets, list(range(start, end)))
        finally:
            consumer.close()

        resumed = make_consumer(group, bootstrap)
        try:
            self.assertEqual(resumed.committed([partition], timeout=10)[0].offset, end)
            resumed.subscribe([TOPIC])
            deadline = monotonic() + 10
            while not resumed.assignment() and monotonic() < deadline:
                self.assertIsNone(resumed.poll(0.5))
            self.assertTrue(resumed.assignment())
            self.assertIsNone(resumed.poll(1))
        finally:
            resumed.close()
        print(f"Kafka audit: 100/100; loss=0; duplicates=0; offsets={start}..{end - 1}; resume={end}")
