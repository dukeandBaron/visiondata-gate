"""Loopback-only real API fixture with an automatically removed temporary product root."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading

import uvicorn


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root / "src"))
    from visiondata_gate.api import create_app
    from visiondata_gate.product_service import ProductService

    if len(os.environ.get("VISIONDATA_SESSION_TOKEN", "")) < 32:
        raise RuntimeError("isolated startup capability is required")
    os.environ["VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS"] = "false"
    os.environ["VISIONDATA_SESSION_ACTOR_USER_ID"] = "usr_local_demo"
    with tempfile.TemporaryDirectory(prefix="vdg-identity-http-") as temporary:
        product_root = Path(temporary).resolve() / "product"
        product = ProductService(product_root, recover_interrupted=False)
        app = create_app(product)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                log_config=None,
                access_log=False,
                log_level="critical",
                proxy_headers=False,
                host="127.0.0.1",
            )
        )

        def stop_on_stdin() -> None:
            # Parent controls only this fixture; EOF also requests graceful exit.
            sys.stdin.readline()
            server.should_exit = True

        threading.Thread(target=stop_on_stdin, daemon=True).start()
        # Emit routing metadata only: no token, password, database path or user body.
        print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
        try:
            server.run(sockets=[listener])
        finally:
            listener.close()
            product.close(wait=True)


if __name__ == "__main__":
    main()
