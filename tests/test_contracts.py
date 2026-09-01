from __future__ import annotations

import pytest
from pydantic import ValidationError

from visiondata_gate.contracts import BatchManifest, SampleRecord


def sample(sample_id: str, relative_path: str = "images/a.png") -> SampleRecord:
    return SampleRecord(
        sample_id=sample_id,
        relative_path=relative_path,
        split="train",
        category="bearing",
        view="front",
        condition="bright",
        annotation_path="annotations/a.png",
    )


@pytest.mark.parametrize(
    "path",
    ["../secret.txt", "images/../../secret.txt", "C:/private/a.png", "/etc/passwd"],
)
def test_sample_manifest_rejects_nonportable_or_traversal_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        sample("a", path)


def test_batch_manifest_rejects_duplicate_sample_ids() -> None:
    with pytest.raises(ValidationError):
        BatchManifest(batch_id="demo", seed=1, samples=[sample("a"), sample("a")])


def test_manifest_round_trip_is_strict() -> None:
    manifest = BatchManifest(batch_id="demo", seed=1, samples=[sample("a")])
    payload = manifest.model_dump(mode="json")
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        BatchManifest.model_validate(payload)
