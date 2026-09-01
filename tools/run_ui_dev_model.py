"""Bounded OpenToken client used only for the UI development workflow.

The client intentionally does not expose credentials to product-runtime code.
It reads the ignored .env.local file, accepts a text-only prompt, writes the
model response under ignored output/ui-dev, and records a hash-only receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV_PATH = REPOSITORY_ROOT / ".env.local"
OUTPUT_ROOT = REPOSITORY_ROOT / "output" / "ui-dev"
LEDGER_PATH = OUTPUT_ROOT / "usage-ledger.jsonl"
ALLOWED_HOSTS = {"gw.opentoken.io", "cn2.gw.opentoken.io"}
MAX_PROMPT_CHARACTERS = 180_000
MAX_CALLS_PER_WORKTREE = 8


def _read_local_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    if LOCAL_ENV_PATH.exists():
        for raw_line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    for key, value in os.environ.items():
        if (
            key.startswith("VISIONDATA_UI_DEV_")
            or key == "VISIONDATA_OPENTOKEN_API_KEY"
        ):
            values[key] = value
    return values


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def _completed_call_count() -> int:
    if not LEDGER_PATH.exists():
        return 0
    return sum(
        1
        for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _extract_content(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        candidate_content = (
            candidate.get("content") if isinstance(candidate, dict) else None
        )
        parts = (
            candidate_content.get("parts")
            if isinstance(candidate_content, dict)
            else None
        )
        if isinstance(parts, list):
            text_parts = [
                part.get("text", "")
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            joined = "\n".join(part for part in text_parts if part).strip()
            if joined:
                return joined

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("gateway response did not include choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        text_parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        ]
        joined = "\n".join(part for part in text_parts if part).strip()
        if joined:
            return joined
    raise RuntimeError("gateway response did not include textual model output")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=8_000)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--purpose", default="ui-development")
    args = parser.parse_args()

    environment = _read_local_environment()
    if environment.get("VISIONDATA_UI_DEV_ALLOW_REMOTE", "false").lower() != "true":
        raise SystemExit("UI development remote access is disabled")

    api_key = environment.get("VISIONDATA_OPENTOKEN_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("UI development API key is not configured")

    model = environment.get("VISIONDATA_UI_DEV_BUILDER_MODEL", "").strip()
    if not model:
        raise SystemExit("UI development builder model is not configured")

    base_url = environment.get(
        "VISIONDATA_UI_DEV_BASE_URL", "https://gw.opentoken.io"
    ).rstrip("/")
    endpoint = environment.get("VISIONDATA_UI_DEV_ENDPOINT", "").strip()
    native_gemini = not endpoint and model.startswith("gemini-")
    endpoint = endpoint or (
        f"{base_url}/v1beta/models/{quote(model, safe='-._')}:generateContent"
        if native_gemini
        else f"{base_url}/v1/chat/completions"
    )
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise SystemExit("UI development endpoint is outside the fixed HTTPS allowlist")

    if not args.prompt.is_file():
        raise SystemExit("prompt file does not exist")
    prompt = args.prompt.read_text(encoding="utf-8")
    if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARACTERS:
        raise SystemExit("prompt is empty or exceeds the bounded character limit")
    if not 256 <= args.max_tokens <= 32_000:
        raise SystemExit("max tokens must be between 256 and 32000")
    if not 0 <= args.temperature <= 1:
        raise SystemExit("temperature must be between 0 and 1")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if _completed_call_count() >= MAX_CALLS_PER_WORKTREE:
        raise SystemExit("UI development call limit reached for this worktree")

    system_instruction = (
        "You are the lead product designer and frontend engineer for a governed "
        "industrial computer-vision data release product. Treat every claim boundary "
        "and status label in the supplied brief as binding. Do not invent APIs, customer "
        "deployment, production authority, metrics, or evidence. Return implementation-"
        "ready output, not generic advice. Never request or reproduce credentials."
    )
    if native_gemini:
        request_payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_instruction}\n\n{prompt}"}],
                }
            ],
            "generationConfig": {
                "temperature": args.temperature,
                "maxOutputTokens": args.max_tokens,
            },
        }
        protocol = "gemini-generate-content"
    else:
        request_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "stream": False,
        }
        protocol = "openai-chat-completions"
    encoded = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        endpoint,
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "VisionData-Gate-UI-Dev/1.0",
        },
    )

    try:
        with urlopen(request, timeout=120) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
            http_status = int(response.status)
    except HTTPError as error:
        error_detail = ""
        try:
            error_payload = json.loads(error.read().decode("utf-8"))
            if isinstance(error_payload, dict):
                nested = error_payload.get("error")
                if isinstance(nested, dict):
                    error_detail = str(
                        nested.get("message") or nested.get("code") or ""
                    )
                else:
                    error_detail = str(error_payload.get("message") or "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            error_detail = ""
        error_detail = error_detail.replace(api_key, "[REDACTED]")[:600]
        suffix = f": {error_detail}" if error_detail else ""
        raise SystemExit(f"gateway HTTP error: {error.code}{suffix}") from None
    except URLError as error:
        raise SystemExit(
            f"gateway connection error: {type(error.reason).__name__}"
        ) from None

    content = _extract_content(response_payload)
    output_path = args.output.resolve()
    output_root = OUTPUT_ROOT.resolve()
    if output_root not in output_path.parents:
        raise SystemExit("model output must stay inside output/ui-dev")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content + "\n", encoding="utf-8")

    usage = (
        response_payload.get("usage")
        if isinstance(response_payload.get("usage"), dict)
        else {}
    )
    if not usage and isinstance(response_payload.get("usageMetadata"), dict):
        usage = response_payload["usageMetadata"]
    model_returned = response_payload.get("model") or (model if native_gemini else None)
    receipt = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": args.purpose,
        "host": parsed.hostname,
        "http_status": http_status,
        "protocol": protocol,
        "model_requested": model,
        "model_returned": model_returned,
        "prompt_sha256": _sha256_text(prompt),
        "response_sha256": _sha256_text(content),
        "prompt_characters": len(prompt),
        "response_characters": len(content),
        "usage": usage,
        "credential_logged": False,
        "image_transmitted": False,
    }
    with LEDGER_PATH.open("a", encoding="utf-8", newline="\n") as ledger:
        ledger.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")

    print(
        json.dumps(
            {
                "status": "MODEL_RESPONSE_SAVED",
                "host": parsed.hostname,
                "http_status": http_status,
                "protocol": protocol,
                "model_requested": model,
                "model_returned": model_returned,
                "output": str(output_path.relative_to(REPOSITORY_ROOT)),
                "response_characters": len(content),
                "response_sha256": receipt["response_sha256"],
                "usage": usage,
                "credential_logged": False,
                "image_transmitted": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
