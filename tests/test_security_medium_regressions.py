from __future__ import annotations

from pathlib import Path

import pytest

import tools.api_smoke as api_smoke
import tools.run_ui_dev_model as ui_dev_model
import tools.run_visa_yolo26_normality as visa_normality


def test_api_smoke_accepts_only_loopback_http_endpoints() -> None:
    assert api_smoke._validated_base_url("http://127.0.0.1:8787") == (
        "http://127.0.0.1:8787"
    )
    for endpoint in (
        "file:///tmp/private.json",
        "https://example.com",
        "http://127.0.0.1:8787/path",
        "http://user:secret@127.0.0.1:8787",
    ):
        with pytest.raises(ValueError, match="loopback HTTP API origin"):
            api_smoke._validated_base_url(endpoint)


def test_ui_dev_endpoint_requires_fixed_https_origin() -> None:
    parsed = ui_dev_model._validated_remote_endpoint(
        "https://gw.opentoken.io/v1/chat/completions"
    )
    assert parsed.hostname == "gw.opentoken.io"
    for endpoint in (
        "file:///tmp/private.json",
        "http://gw.opentoken.io/v1/chat/completions",
        "https://example.com/v1/chat/completions",
        "https://" + "user:secret" + "@" + "gw.opentoken.io/v1/chat/completions",
    ):
        with pytest.raises(SystemExit, match="fixed HTTPS allowlist"):
            ui_dev_model._validated_remote_endpoint(endpoint)


def test_model_pack_roundtrip_loader_is_weights_only_and_cpu_bound() -> None:
    calls: list[tuple[Path, dict[str, object]]] = []

    class TorchProbe:
        @staticmethod
        def load(path: Path, **kwargs: object) -> dict[str, bool]:
            calls.append((path, kwargs))
            return {"loaded": True}

    checkpoint = Path("synthetic-model-pack.pt")
    result = visa_normality._load_model_pack_checkpoint(TorchProbe, checkpoint)

    assert result == {"loaded": True}
    assert calls == [
        (checkpoint, {"map_location": "cpu", "weights_only": True})
    ]
