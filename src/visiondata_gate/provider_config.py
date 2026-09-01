"""Secret-free helpers for operator-supplied OpenAI-compatible gateways."""

from __future__ import annotations

import urllib.parse


def resolve_chat_completions_endpoint(
    *,
    explicit_endpoint: str | None,
    base_url: str | None,
    default_endpoint: str,
) -> str:
    """Resolve a Chat Completions URL without accepting embedded credentials.

    An explicit endpoint always wins.  A gateway root such as
    ``https://gateway.example`` is expanded to ``/v1/chat/completions``.  A
    base ending in ``/v1`` receives only ``/chat/completions``.  The returned
    endpoint is still subject to each runtime's HTTPS, host-allowlist, and
    authorization checks.
    """

    endpoint = (explicit_endpoint or "").strip()
    if endpoint:
        return endpoint
    candidate = (base_url or "").strip()
    if not candidate:
        return default_endpoint
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OpenAI-compatible base URL must be absolute HTTP(S)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "OpenAI-compatible base URL cannot contain credentials, query, or fragment"
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        resolved_path = path
    elif path.endswith("/v1"):
        resolved_path = f"{path}/chat/completions"
    elif path:
        resolved_path = f"{path}/v1/chat/completions"
    else:
        resolved_path = "/v1/chat/completions"
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, resolved_path, "", "")
    )


__all__ = ["resolve_chat_completions_endpoint"]
