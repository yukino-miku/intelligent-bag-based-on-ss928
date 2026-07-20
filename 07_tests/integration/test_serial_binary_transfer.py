from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT / "06_software" / "tools" / "board_debug" / "serial_binary_transfer.py"
)
SPEC = importlib.util.spec_from_file_location("serial_binary_transfer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
TRANSFER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSFER)


class ChunkPort:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = deque(chunks)

    def read(self, size: int) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks.popleft()
        if len(chunk) <= size:
            return chunk
        self.chunks.appendleft(chunk[size:])
        return chunk[:size]


class SerialBinaryTransferTest(unittest.TestCase):
    def test_read_marker_line_handles_split_marker_and_crlf(self) -> None:
        port = ChunkPort(
            [b"noise\r\n__SMART", b"BAG_DONE__ abc", b"123\r\nprompt"]
        )

        line = TRANSFER.read_marker_line(port, b"__SMARTBAG_DONE__ ", 1.0)

        self.assertEqual(line, b"abc123")

    def test_receiver_command_quotes_remote_path_and_size(self) -> None:
        command = TRANSFER.receiver_command("/root/staging/a file.bin", 12345)

        self.assertIn("mkdir -p /root/staging", command)
        self.assertIn("'/root/staging/a file.bin' 12345", command)
        self.assertIn("__SMARTBAG_TRANSFER_READY__", command)
        self.assertIn("__SMARTBAG_TRANSFER_DONE__", command)

    def test_sender_command_quotes_remote_path_and_has_handshake(self) -> None:
        command = TRANSFER.sender_command("/root/staging/a file.jpg")

        self.assertIn("'/root/staging/a file.jpg'", command)
        self.assertIn("__SMARTBAG_DOWNLOAD_READY__", command)
        self.assertIn("__SMARTBAG_DOWNLOAD_DONE__", command)
        self.assertIn('!= b"G"', command)

    def test_sha256_file_matches_hashlib(self) -> None:
        payload = b"smartbag-serial-transfer\x00\xff"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(payload)

            actual = TRANSFER.sha256_file(path)

        self.assertEqual(actual, hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
