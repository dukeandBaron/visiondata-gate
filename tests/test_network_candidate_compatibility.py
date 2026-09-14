"""Destination identity must stay the destination actually connected to."""

import socket

import pytest

from tests.test_network_deadline import _server
from visiondata_gate.network_resilience import (
    HTTPClientPolicy,
    HTTPTransportError,
    ResilientJSONClient,
    _endpoint_metadata,
)


def test_explicit_zero_port_is_not_silently_rewritten_to_default():
    policy = HTTPClientPolicy(allowed_hosts=["localhost"], allow_local=True)
    metadata = _endpoint_metadata("http://localhost:0/path", policy)
    assert metadata[2] == 0


def test_circuit_open_keeps_verified_loopback_alias_scope_without_dns(monkeypatch):
    lookup = socket.getaddrinfo
    calls = []

    def alias(host, port, **kwargs):
        calls.append(host)
        return lookup("127.0.0.1", port, **kwargs)

    with _server() as (_, root):
        monkeypatch.setattr(socket, "getaddrinfo", alias)
        client = ResilientJSONClient(
            HTTPClientPolicy(
                allowed_hosts=["loopback.test"],
                allow_local=True,
                max_retries=0,
                circuit_failure_threshold=1,
                max_response_bytes=1,
            )
        )
        endpoint = root.replace("127.0.0.1", "loopback.test") + "/ok"
        with pytest.raises(HTTPTransportError) as first:
            client.request_json(endpoint, method="GET")
        with pytest.raises(HTTPTransportError) as second:
            client.request_json(endpoint, method="GET")
    assert first.value.receipt.endpoint_scope == "local"
    assert second.value.receipt.status == "CIRCUIT_OPEN"
    assert second.value.receipt.endpoint_scope == "local"
    assert calls == ["loopback.test"]
