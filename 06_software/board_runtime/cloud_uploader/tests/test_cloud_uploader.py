import json
import sys
import tempfile
import unittest
from pathlib import Path


RUNTIME = Path(__file__).resolve().parents[2]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from cloud_uploader import BoundedOfflineQueue, CloudTelemetryUploader, HmacRequestSigner
from cloud_uploader.cloud_uploader import JsonlTailReader, UploaderConfig


class FakeTransport:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.requests = []

    def post(self, body, headers) -> None:
        self.requests.append((body, headers))
        if self.fail:
            raise OSError("offline")


class CloudUploaderTest(unittest.TestCase):
    def config(self, queue_file: Path) -> UploaderConfig:
        return UploaderConfig(True, "device-test", "https://example.invalid", "SECRET", queue_file, 3, 2048, 2, 1.0, 1.0, 8.0, (), (), queue_file.with_name("cursors.json"))

    def test_hmac_headers_cover_device_timestamp_nonce_and_body(self) -> None:
        headers = HmacRequestSigner("device-test", "secret").headers(b"{}", timestamp_s=10, nonce="abc")
        self.assertEqual("device-test", headers["X-SmartBag-Device"])
        self.assertEqual("10", headers["X-SmartBag-Timestamp"])
        self.assertEqual("abc", headers["X-SmartBag-Nonce"])
        self.assertEqual(64, len(headers["X-SmartBag-Signature"]))

    def test_queue_is_bounded_by_entry_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = BoundedOfflineQueue(Path(tmp) / "queue.jsonl", max_entries=3, max_file_bytes=2048)
            for index in range(5):
                queue.append({"index": index})
            self.assertEqual([2, 3, 4], [item["index"] for item in queue.peek(10)])

    def test_failed_upload_keeps_queue_and_success_acknowledges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(Path(tmp) / "queue.jsonl")
            queue = BoundedOfflineQueue(config.queue_file, max_entries=3, max_file_bytes=2048)
            signer = HmacRequestSigner(config.device_id, "secret")
            failed = FakeTransport(fail=True)
            uploader = CloudTelemetryUploader(config, signer, queue, failed, clock=lambda: 1.0)
            uploader.enqueue("controller", {"levels": {"left": 3}})
            with self.assertRaises(OSError):
                uploader.flush_once()
            self.assertEqual(1, queue.count())

            success = FakeTransport()
            uploader.transport = success
            self.assertEqual(1, uploader.flush_once())
            self.assertEqual(0, queue.count())
            payload = json.loads(success.requests[0][0])
            self.assertEqual("device-test", payload["device_id"])

    def test_jsonl_tail_cursor_prevents_duplicate_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.jsonl"
            events.write_text('{"typ":"alert","level":3}\n', encoding="utf-8")
            reader = JsonlTailReader(root / "cursors.json")
            self.assertEqual(1, len(reader.read([events])))
            self.assertEqual([], reader.read([events]))
            events.write_text(events.read_text(encoding="utf-8") + '{"typ":"alert","level":0}\n', encoding="utf-8")
            self.assertEqual(0, reader.read([events])[0]["level"])

    def test_jsonl_cursor_is_not_advanced_when_durable_sink_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.jsonl"
            cursor = root / "cursors.json"
            events.write_text('{"typ":"alert","level":3}\n', encoding="utf-8")
            reader = JsonlTailReader(cursor)

            def reject(_event) -> None:
                raise OSError("queue unavailable")

            with self.assertRaises(OSError):
                reader.read_into([events], reject)
            self.assertFalse(cursor.exists())
            accepted = []
            self.assertEqual(1, reader.read_into([events], accepted.append))
            self.assertEqual(3, accepted[0]["level"])


if __name__ == "__main__":
    unittest.main()
