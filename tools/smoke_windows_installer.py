from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install, start, and uninstall the Windows desktop test bundle"
    )
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--work-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _assert_empty_work_root(path: Path, project_root: Path) -> None:
    output_root = (project_root / "output").resolve()
    if output_root not in path.parents:
        raise ValueError("installer smoke work root must be under project output/")
    if path.exists() and any(path.iterdir()):
        raise ValueError("installer smoke work root must be empty")
    path.mkdir(parents=True, exist_ok=True)


def _find_application(install_root: Path) -> Path:
    preferred = install_root / "VisionData Gate.exe"
    if preferred.is_file():
        return preferred
    candidates = [
        path
        for path in install_root.glob("*.exe")
        if "uninstall" not in path.name.casefold()
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one installed application executable, observed {len(candidates)}"
        )
    return candidates[0]


def _find_uninstaller(install_root: Path) -> Path:
    candidates = [
        path
        for path in install_root.glob("*.exe")
        if "uninstall" in path.name.casefold()
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one installed uninstaller, observed {len(candidates)}"
        )
    return candidates[0]


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("Windows installer smoke is Windows-only")
    args = _parser().parse_args()
    project_root = Path(__file__).resolve().parents[1]
    installer = args.installer.expanduser().resolve(strict=True)
    work_root = args.work_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    _assert_empty_work_root(work_root, project_root)

    install_root = work_root / "installed"
    local_app_data = work_root / "local-app-data"
    roaming_app_data = work_root / "roaming-app-data"
    local_app_data.mkdir(parents=True)
    roaming_app_data.mkdir(parents=True)

    install = subprocess.run(
        [str(installer), "/S", f"/D={install_root}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=240,
        check=False,
    )
    if install.returncode != 0:
        raise RuntimeError(f"silent installer returned {install.returncode}")

    application = _find_application(install_root)
    uninstaller = _find_uninstaller(install_root)
    application_sha256 = _sha256(application)
    environment = os.environ.copy()
    environment.update(
        {
            "LOCALAPPDATA": str(local_app_data),
            "APPDATA": str(roaming_app_data),
            "VISIONDATA_DESKTOP_SMOKE_EXIT_AFTER_READY_MS": "1500",
        }
    )
    process = subprocess.Popen(
        [str(application)],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        exit_code = process.wait(timeout=75)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        raise RuntimeError("installed desktop did not exit after its smoke readiness")
    if exit_code != 0:
        raise RuntimeError(f"installed desktop returned {exit_code}")

    runtime_root = local_app_data / "VisionData Gate"
    startup_path = runtime_root / "logs" / "desktop-startup.json"
    if not startup_path.is_file():
        raise RuntimeError("installed desktop did not emit its startup receipt")
    startup = json.loads(startup_path.read_text(encoding="utf-8"))
    if startup.get("status") != "READY":
        raise RuntimeError("installed desktop startup receipt is not READY")
    if startup.get("hmac_readiness_verified") is not True:
        raise RuntimeError("installed desktop did not verify backend identity")
    if startup.get("production_release_allowed") is not False:
        raise RuntimeError("installed desktop widened production authority")
    if startup.get("machine_write_permitted") is not False:
        raise RuntimeError("installed desktop widened machine authority")

    database = runtime_root / "product" / "product.sqlite3"
    if not database.is_file():
        raise RuntimeError("installed desktop did not create its local database")
    with closing(sqlite3.connect(database)) as connection:
        sqlite_integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if sqlite_integrity != "ok":
        raise RuntimeError(f"installed SQLite integrity failed: {sqlite_integrity}")

    uninstall = subprocess.run(
        [str(uninstaller), "/S"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    if uninstall.returncode != 0:
        raise RuntimeError(f"silent uninstaller returned {uninstall.returncode}")

    receipt = {
        "schema_version": "visiondata-gate.windows-installer-smoke.v1",
        "status": "PASS_LOCAL_INSTALLED_SMOKE",
        "installer_sha256": _sha256(installer),
        "installed_application_sha256": application_sha256,
        "installer_exit_code": install.returncode,
        "application_exit_code": exit_code,
        "uninstaller_exit_code": uninstall.returncode,
        "startup_receipt": startup,
        "sqlite_integrity_check": sqlite_integrity,
        "user_data_retained_after_uninstall": database.is_file(),
        "clean_machine_validation": "NOT_RUN",
        "code_signature_status": "NOT_SIGNED",
        "production_release_allowed": False,
        "machine_write_permitted": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    output.write_text(serialized, encoding="utf-8", newline="\n")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
