from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path

import httpx


_V3_REPORT_NAME = "DYNAMICBENCH_V3_REPLANNING_20260829.json"
_V4_REPORT_NAME = "DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json"


def _prepare_semifinal_product(product_root: Path) -> str:
    preparer = Path(__file__).resolve().with_name("prepare_semifinal_demo.py")
    completed = subprocess.run(
        [
            sys.executable,
            str(preparer),
            "--product-root",
            str(product_root),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            "semifinal product preparation failed before sidecar smoke: "
            f"{detail[-1000:]}"
        )
    manifest_path = product_root / "semifinal_demo_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_sha256 = str(manifest["manifest_sha256"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "semifinal product preparation did not emit a readable manifest"
        ) from exc
    if len(manifest_sha256) != 64:
        raise RuntimeError("prepared semifinal manifest SHA-256 is malformed")
    return manifest_sha256


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke the packaged Windows API sidecar"
    )
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument(
        "--sample",
        type=Path,
        default=Path("sample_data/clear/clean-val-gear.png"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional UTF-8 JSON receipt path; stdout is always retained.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    executable = args.executable.expanduser().resolve(strict=True)
    sample = args.sample.expanduser().resolve(strict=True)
    port = _free_port()
    token = uuid.uuid4().hex + uuid.uuid4().hex
    actor_headers = {
        "X-Actor-User-Id": "usr_local_demo",
        "X-VisionData-Desktop-Token": token,
    }

    receipt: dict[str, object] | None = None
    with tempfile.TemporaryDirectory(prefix="visiondata-gate-desktop-smoke-") as temp:
        smoke_root = Path(temp)
        product_root = smoke_root / "product"
        expected_manifest_sha256 = _prepare_semifinal_product(product_root)
        environment = os.environ.copy()
        environment.pop("VISIONDATA_RESOURCE_ROOT", None)
        environment.update(
            {
                "VISIONDATA_DESKTOP_SESSION_TOKEN": token,
                "VISIONDATA_PRODUCT_ROOT": str(product_root),
                "VISIONDATA_DESKTOP_CONFIG_FILE": str(smoke_root / ".env.local"),
                "VISIONDATA_DESKTOP_LOG_FILE": str(smoke_root / "backend.log"),
                "VISIONDATA_WEB_ORIGINS": "http://tauri.localhost",
            }
        )
        process = subprocess.Popen(
            [str(executable), "--port", str(port)],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 25
            while True:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"sidecar exited during startup: {process.returncode}"
                    )
                try:
                    response = httpx.get(f"{base_url}/v1/health", timeout=0.5)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "sidecar did not become healthy within 25 seconds"
                    )
                time.sleep(0.2)

            evaluation = httpx.get(
                f"{base_url}/v1/review/evaluation-evidence/dynamicbench",
                headers=actor_headers,
                timeout=15,
            )
            evaluation.raise_for_status()
            evaluation_payload = evaluation.json()
            if evaluation_payload["status"] != "PASS_LOCAL_EVIDENCE":
                raise RuntimeError(
                    "packaged DynamicBench evidence failed closed: "
                    f"{evaluation_payload.get('failure_codes')}"
                )
            if evaluation_payload["verification_status"] != "VERIFIED":
                raise RuntimeError("packaged DynamicBench evidence was not verified")
            if evaluation_payload["pair_binding_status"] != "VERIFIED":
                raise RuntimeError(
                    "packaged DynamicBench pair binding was not verified"
                )
            report_names = {
                report["source_artifact_name"]
                for report in evaluation_payload["reports"]
            }
            if report_names != {_V3_REPORT_NAME, _V4_REPORT_NAME}:
                raise RuntimeError(
                    f"unexpected packaged DynamicBench report set: {report_names}"
                )
            evaluation_sha256 = evaluation_payload["projection_sha256"]
            if (
                evaluation.headers.get("x-evaluation-evidence-sha256")
                != evaluation_sha256
            ):
                raise RuntimeError("DynamicBench projection SHA header drifted")
            if evaluation.headers.get("etag") != f'"{evaluation_sha256}"':
                raise RuntimeError("DynamicBench projection ETag drifted")
            if evaluation_payload["production_release_allowed"] is not False:
                raise RuntimeError("DynamicBench projection widened release authority")
            if evaluation_payload["machine_write_permitted"] is not False:
                raise RuntimeError("DynamicBench projection widened machine authority")

            semifinal = httpx.get(
                f"{base_url}/v1/review/semifinal-demo-manifest",
                headers=actor_headers,
                timeout=15,
            )
            semifinal.raise_for_status()
            semifinal_payload = semifinal.json()
            if semifinal_payload["status"] != "PASS_LOCAL_DEMO_VERIFIED":
                raise RuntimeError(
                    "packaged semifinal manifest projection failed closed: "
                    f"{semifinal_payload.get('failure_code')}"
                )
            if semifinal_payload["manifest_sha256"] != expected_manifest_sha256:
                raise RuntimeError("packaged semifinal manifest binding drifted")
            semifinal_projection_sha256 = semifinal_payload["projection_sha256"]
            if semifinal.headers.get("x-content-sha256") != semifinal_projection_sha256:
                raise RuntimeError("semifinal projection SHA header drifted")
            if semifinal.headers.get("etag") != f'"{semifinal_projection_sha256}"':
                raise RuntimeError("semifinal projection ETag drifted")
            if (
                semifinal.headers.get("x-semifinal-manifest-sha256")
                != expected_manifest_sha256
            ):
                raise RuntimeError("semifinal manifest SHA header drifted")
            if semifinal_payload["production_release_allowed"] is not False:
                raise RuntimeError("semifinal projection widened release authority")
            if semifinal_payload["machine_write_permitted"] is not False:
                raise RuntimeError("semifinal projection widened machine authority")

            assets_url = f"{base_url}/v1/operator-workspaces/wsp_local_demo/assets"
            denied = httpx.get(
                assets_url,
                headers={"X-Actor-User-Id": "usr_local_demo"},
                timeout=5,
            )
            if denied.status_code != 401:
                raise RuntimeError(
                    f"desktop session guard returned {denied.status_code}"
                )

            with sample.open("rb") as handle:
                upload = httpx.post(
                    assets_url,
                    headers=actor_headers,
                    files={"files": (sample.name, handle, "image/png")},
                    timeout=30,
                )
            upload.raise_for_status()
            payload = upload.json()
            asset = payload["assets"][0]
            analysis = httpx.post(
                f"{assets_url}/{asset['asset_id']}/analysis-runs",
                headers=actor_headers,
                timeout=60,
            )
            analysis.raise_for_status()
            analysis_payload = analysis.json()
            if analysis_payload["model_call_count"] != 0:
                raise RuntimeError(
                    "desktop smoke unexpectedly made an external model call"
                )
            if analysis_payload["raw_images_transmitted"] is not False:
                raise RuntimeError("desktop smoke reported raw image transmission")

            shutdown = httpx.post(
                f"{base_url}/v1/desktop/shutdown",
                headers={"X-VisionData-Desktop-Token": token},
                timeout=5,
            )
            if shutdown.status_code != 202:
                raise RuntimeError(f"graceful shutdown returned {shutdown.status_code}")
            process.wait(timeout=10)

            database = product_root / "product.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            receipt = {
                "schema_version": "visiondata-gate.windows-sidecar-smoke.v1",
                "status": "PASS",
                "executable_sha256": hashlib.sha256(
                    executable.read_bytes()
                ).hexdigest(),
                "dynamicbench_status": evaluation_payload["status"],
                "dynamicbench_projection_sha256": evaluation_sha256,
                "dynamicbench_report_names": sorted(report_names),
                "semifinal_manifest_status": semifinal_payload["status"],
                "semifinal_manifest_sha256": expected_manifest_sha256,
                "semifinal_projection_sha256": semifinal_projection_sha256,
                "asset_id": asset["asset_id"],
                "asset_source_sha256": asset["source_sha256"],
                "analysis_run_id": analysis_payload["analysis_run_id"],
                "analysis_run_sha256": analysis_payload["document_sha256"],
                "model_call_count": analysis_payload["model_call_count"],
                "raw_images_transmitted": analysis_payload["raw_images_transmitted"],
                "sqlite_integrity_check": integrity,
                "graceful_exit_code": process.returncode,
                "production_release_allowed": False,
                "machine_write_permitted": False,
                "desktop_release_status": "NOT_CLAIMED",
            }
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    if receipt is None:
        raise RuntimeError("desktop sidecar smoke did not produce a receipt")
    serialized = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8", newline="\n")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
