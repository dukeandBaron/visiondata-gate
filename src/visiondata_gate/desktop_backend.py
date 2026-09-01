"""Windows desktop sidecar entrypoint for the local VisionData Gate API."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PROTECTED_KEYS = {
    "VISIONDATA_DESKTOP_SESSION_TOKEN",
    "VISIONDATA_PRODUCT_ROOT",
    "VISIONDATA_RESOURCE_ROOT",
    "VISIONDATA_WEB_ORIGINS",
}
_URL_SUFFIXES = ("_BASE_URL", "_ENDPOINT")


def _resource_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[2]


def _default_local_root() -> Path:
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if not base:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return Path(base) / "VisionData Gate"


def _default_config_file() -> Path:
    base = os.environ.get("APPDATA", "").strip()
    if not base:
        raise RuntimeError("APPDATA is unavailable")
    return Path(base) / "VisionData Gate" / ".env.local"


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def load_desktop_environment(path: Path) -> tuple[str, ...]:
    """Load allowlisted VisionData settings without exposing their values."""

    if not path.is_file():
        return ()
    loaded: list[str] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            logging.warning("Ignored invalid desktop config line %s", line_number)
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if (
            not _ENV_KEY.fullmatch(key)
            or not key.startswith("VISIONDATA_")
            or key in _PROTECTED_KEYS
        ):
            logging.warning(
                "Ignored disallowed desktop config key on line %s", line_number
            )
            continue
        if value and key.endswith(_URL_SUFFIXES) and not _is_http_url(value):
            logging.warning("Ignored non-URL desktop endpoint on line %s", line_number)
            continue
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return tuple(loaded)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VisionData Gate desktop API sidecar")
    parser.add_argument("--port", required=True, type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1024 <= args.port <= 65535:
        raise SystemExit("--port must be between 1024 and 65535")

    local_root = _default_local_root()
    product_root = local_root / "product"
    log_root = local_root / "logs"
    product_root.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)

    log_path = Path(
        os.environ.get("VISIONDATA_DESKTOP_LOG_FILE", log_root / "backend.log")
    )
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )

    config_file = Path(
        os.environ.get("VISIONDATA_DESKTOP_CONFIG_FILE", _default_config_file())
    )
    loaded_keys = load_desktop_environment(config_file)
    logging.info("Loaded %s allowlisted desktop configuration keys", len(loaded_keys))

    os.environ.setdefault("VISIONDATA_PRODUCT_ROOT", str(product_root))
    os.environ.setdefault("VISIONDATA_RESOURCE_ROOT", str(_resource_root()))
    os.environ.setdefault(
        "VISIONDATA_WEB_ORIGINS",
        "http://tauri.localhost,https://tauri.localhost,tauri://localhost",
    )

    if not os.environ.get("VISIONDATA_DESKTOP_SESSION_TOKEN", "").strip():
        logging.error("Desktop session token is missing")
        return 2

    import uvicorn

    from visiondata_gate.api import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="warning",
        server_header=False,
    )
    server = uvicorn.Server(config)
    app.state.desktop_shutdown_callback = lambda: setattr(server, "should_exit", True)
    logging.info("Desktop API starting on loopback port %s", args.port)
    server.run()
    logging.info("Desktop API stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
