from __future__ import annotations

import hashlib

from visiondata_gate.operator_snapshot import _sha256_file


class GuardedReader:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, _error_type, _error, _traceback):
        return False

    def read(self, size: int) -> bytes:
        if size > 64 * 1024:
            raise MemoryError("synthetic allocation ceiling")
        if self.offset >= len(self.payload):
            return b""
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class GuardedPath:
    def __init__(self, payload: bytes):
        self.payload = payload

    def open(self, mode: str):
        assert mode == "rb"
        return GuardedReader(self.payload)


def test_operator_snapshot_hashing_uses_memory_bounded_streaming_chunks() -> None:
    payload = b"retention-manifest" * 10000
    assert _sha256_file(GuardedPath(payload)) == hashlib.sha256(payload).hexdigest()
