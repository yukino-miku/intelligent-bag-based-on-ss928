#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.parse import urlparse


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


class HmacRequestSigner:
    def __init__(self, device_id: str, secret: str) -> None:
        if not device_id or not secret:
            raise ValueError("device_id and HMAC secret are required")
        self.device_id = device_id
        self.secret = secret.encode("utf-8")

    def headers(
        self,
        body: bytes,
        *,
        timestamp_s: int | None = None,
        nonce: str | None = None,
    ) -> dict[str, str]:
        timestamp_s = int(time.time()) if timestamp_s is None else int(timestamp_s)
        nonce = nonce or secrets.token_hex(16)
        body_sha = hashlib.sha256(body).hexdigest()
        canonical = f"{self.device_id}\n{timestamp_s}\n{nonce}\n{body_sha}".encode("utf-8")
        signature = hmac.new(self.secret, canonical, hashlib.sha256).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-SmartBag-Device": self.device_id,
            "X-SmartBag-Timestamp": str(timestamp_s),
            "X-SmartBag-Nonce": nonce,
            "X-SmartBag-Body-SHA256": body_sha,
            "X-SmartBag-Signature": signature,
        }


class BoundedOfflineQueue:
    def __init__(self, path: Path, *, max_entries: int, max_file_bytes: int) -> None:
        self.path = Path(path)
        self.max_entries = max(1, int(max_entries))
        self.max_file_bytes = max(1024, int(max_file_bytes))

    def append(self, event: Mapping[str, object]) -> None:
        encoded = canonical_json(dict(event))
        if len(encoded) + 1 > self.max_file_bytes:
            raise ValueError("telemetry event exceeds offline queue file limit")
        records = self._read() + [dict(event)]
        self._write_bounded(records)

    def peek(self, limit: int) -> list[dict[str, object]]:
        return self._read()[: max(1, int(limit))]

    def acknowledge(self, count: int) -> None:
        records = self._read()
        self._write_bounded(records[max(0, int(count)) :])

    def count(self) -> int:
        return len(self._read())

    def _read(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        result = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    def _write_bounded(self, records: list[dict[str, object]]) -> None:
        records = records[-self.max_entries :]
        encoded = [canonical_json(record) for record in records]
        total = sum(len(item) + 1 for item in encoded)
        while encoded and total > self.max_file_bytes:
            total -= len(encoded[0]) + 1
            encoded.pop(0)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("wb") as handle:
            for item in encoded:
                handle.write(item + b"\n")
        temporary.replace(self.path)


class JsonlTailReader:
    def __init__(self, cursor_file: Path) -> None:
        self.cursor_file = Path(cursor_file)
        try:
            value = json.loads(self.cursor_file.read_text(encoding="utf-8"))
            self.offsets = {str(path): int(offset) for path, offset in value.items()}
        except (OSError, ValueError, json.JSONDecodeError, AttributeError):
            self.offsets: dict[str, int] = {}

    def read(self, paths: Iterable[Path]) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        self.read_into(paths, events.append)
        return events

    def read_into(
        self,
        paths: Iterable[Path],
        sink: Callable[[dict[str, object]], None],
    ) -> int:
        delivered = 0
        changed = False
        for path in paths:
            key = str(path)
            try:
                size = path.stat().st_size
                offset = self.offsets.get(key, 0)
                if offset > size:
                    offset = 0
            except OSError:
                continue
            try:
                handle = path.open("r", encoding="utf-8", errors="replace")
            except OSError:
                continue
            with handle:
                handle.seek(offset)
                for line in handle:
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        # Persist the cursor only after the durable queue accepts the event.
                        sink(value)
                        delivered += 1
                self.offsets[key] = handle.tell()
                changed = True
        if changed:
            self.cursor_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cursor_file.with_suffix(self.cursor_file.suffix + ".tmp")
            temporary.write_text(json.dumps(self.offsets, sort_keys=True), encoding="utf-8")
            temporary.replace(self.cursor_file)
        return delivered


class HttpsJsonTransport:
    def __init__(self, endpoint: str, *, timeout_s: float = 5.0, allow_http_for_tests: bool = False) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" and not (allow_http_for_tests and parsed.scheme == "http"):
            raise ValueError("Cloud telemetry endpoint must use HTTPS")
        self.endpoint = endpoint
        self.timeout_s = max(0.1, float(timeout_s))

    def post(self, body: bytes, headers: Mapping[str, str]) -> None:
        request = urllib.request.Request(self.endpoint, data=body, headers=dict(headers), method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            if not 200 <= int(response.status) < 300:
                raise RuntimeError(f"cloud upload HTTP {response.status}")


@dataclass(frozen=True)
class UploaderConfig:
    enabled: bool
    device_id: str
    endpoint: str
    secret_env: str
    queue_file: Path
    max_entries: int
    max_file_bytes: int
    batch_size: int
    timeout_s: float
    interval_s: float
    max_backoff_s: float
    status_files: tuple[Path, ...]
    event_jsonl_files: tuple[Path, ...]
    cursor_file: Path


def load_config(path: str | Path) -> UploaderConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("cloud uploader config must be an object")
    return UploaderConfig(
        enabled=bool(raw.get("enabled", False)),
        device_id=str(raw.get("device_id", "")),
        endpoint=str(raw.get("endpoint", "")),
        secret_env=str(raw.get("secret_env", "SMARTBAG_HMAC_SECRET")),
        queue_file=Path(str(raw.get("queue_file", "/var/lib/smartbag/cloud-queue.jsonl"))),
        max_entries=int(raw.get("max_entries", 2000)),
        max_file_bytes=int(raw.get("max_file_bytes", 4 * 1024 * 1024)),
        batch_size=int(raw.get("batch_size", 50)),
        timeout_s=float(raw.get("timeout_s", 5.0)),
        interval_s=float(raw.get("interval_s", 2.0)),
        max_backoff_s=float(raw.get("max_backoff_s", 60.0)),
        status_files=tuple(Path(str(item)) for item in raw.get("status_files", [])),
        event_jsonl_files=tuple(Path(str(item)) for item in raw.get("event_jsonl_files", [])),
        cursor_file=Path(str(raw.get("cursor_file", "/var/lib/smartbag/cloud-cursors.json"))),
    )


class CloudTelemetryUploader:
    def __init__(
        self,
        config: UploaderConfig,
        signer: HmacRequestSigner,
        queue: BoundedOfflineQueue,
        transport: object,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.signer = signer
        self.queue = queue
        self.transport = transport
        self.clock = clock
        self.failure_count = 0

    def enqueue(self, kind: str, payload: Mapping[str, object]) -> None:
        self.queue.append(
            {
                "kind": str(kind),
                "device_id": self.config.device_id,
                "ts": self.clock(),
                "payload": dict(payload),
            }
        )

    def flush_once(self) -> int:
        events = self.queue.peek(self.config.batch_size)
        if not events:
            return 0
        body = canonical_json({"device_id": self.config.device_id, "events": events})
        headers = self.signer.headers(body)
        try:
            self.transport.post(body, headers)  # type: ignore[attr-defined]
        except Exception:
            self.failure_count += 1
            raise
        self.queue.acknowledge(len(events))
        self.failure_count = 0
        return len(events)

    def backoff_s(self) -> float:
        return min(self.config.max_backoff_s, self.config.interval_s * (2 ** min(self.failure_count, 8)))


def read_status_files(paths: Iterable[Path]) -> list[tuple[str, dict[str, object]]]:
    snapshots = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            snapshots.append((path.stem, value))
    return snapshots


def run(config: UploaderConfig, *, once: bool = False) -> int:
    if not config.enabled:
        print("cloud uploader disabled", file=os.sys.stderr)
        return 0
    secret = os.environ.get(config.secret_env, "")
    if not secret:
        raise RuntimeError(f"HMAC secret environment variable {config.secret_env} is not set")
    signer = HmacRequestSigner(config.device_id, secret)
    queue = BoundedOfflineQueue(
        config.queue_file,
        max_entries=config.max_entries,
        max_file_bytes=config.max_file_bytes,
    )
    uploader = CloudTelemetryUploader(
        config,
        signer,
        queue,
        HttpsJsonTransport(config.endpoint, timeout_s=config.timeout_s),
    )
    tails = JsonlTailReader(config.cursor_file)
    while True:
        for kind, snapshot in read_status_files(config.status_files):
            uploader.enqueue(kind, snapshot)
        tails.read_into(
            config.event_jsonl_files,
            lambda event: uploader.enqueue(
                str(event.get("type") or event.get("typ") or "event"), event
            ),
        )
        try:
            uploader.flush_once()
        except (OSError, RuntimeError, urllib.error.URLError) as exc:
            print(f"cloud upload deferred: {type(exc).__name__}", file=os.sys.stderr)
        if once:
            return 0
        time.sleep(uploader.backoff_s() if uploader.failure_count else config.interval_s)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optional non-blocking SmartBag CloudBase telemetry uploader")
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    raise SystemExit(run(load_config(cli_args.config), once=cli_args.once))
