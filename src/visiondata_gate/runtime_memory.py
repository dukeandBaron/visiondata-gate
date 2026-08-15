"""Bounded local memory for the agent runtime."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from .runtime_models import MemoryRecord


_RECORDS = TypeAdapter(list[MemoryRecord])


class LocalMemoryStore:
    """Persist small run summaries without storing images, prompts, or secrets."""

    def __init__(self, path: str | Path, *, max_records: int = 20) -> None:
        self.path = Path(path).expanduser().resolve()
        self.max_records = max(1, max_records)

    def load(self) -> tuple[list[MemoryRecord], str | None]:
        if not self.path.exists():
            return [], None
        if not self.path.is_file():
            return [], f"memory path is not a file: {self.path}"
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            records = _RECORDS.validate_python(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            return (
                [],
                f"memory ignored because validation failed: {type(error).__name__}",
            )
        return records[-self.max_records :], None

    def append(self, record: MemoryRecord) -> list[MemoryRecord]:
        records, _ = self.load()
        records.append(record)
        records = records[-self.max_records :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                [item.model_dump(mode="json") for item in records],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(self.path)
        return records


__all__ = ["LocalMemoryStore"]
