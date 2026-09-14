from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

import winreg


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


def _windows_process_rows() -> list[dict]:
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT")
    if not system_root:
        raise RuntimeError("SystemRoot is unavailable for uninstall verification")
    powershell = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    command = (
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
        "$rows=@(Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,CommandLine); "
        "ConvertTo-Json -InputObject $rows -Compress"
    )
    completed = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError("could not inspect owned NSIS uninstall processes")
    value = json.loads(completed.stdout or "[]")
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise RuntimeError("invalid Windows process inventory")
    return value


def _owned_uninstaller_process_count(install_root: Path) -> int:
    target = str(install_root.resolve()).casefold()
    count = 0
    for row in _windows_process_rows():
        name = str(row.get("Name") or "").casefold()
        command_line = str(row.get("CommandLine") or "").casefold()
        if name in {"un.exe", "uninstall.exe"} and target in command_line:
            count += 1
    return count


def _uninstall_registry_entry_count() -> int:
    relative = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\VisionData Gate"
    checks = (
        (winreg.HKEY_CURRENT_USER, 0),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
    )
    count = 0
    for hive, view in checks:
        try:
            with winreg.OpenKey(hive, relative, 0, winreg.KEY_READ | view):
                count += 1
        except FileNotFoundError:
            pass
    return count


def _installer_shortcut_count() -> int:
    candidates: list[Path] = []
    if roaming := os.environ.get("APPDATA"):
        candidates.append(
            Path(roaming)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "VisionData Gate.lnk"
        )
    if profile := os.environ.get("USERPROFILE"):
        candidates.append(Path(profile) / "Desktop" / "VisionData Gate.lnk")
    if public := os.environ.get("PUBLIC"):
        candidates.append(Path(public) / "Desktop" / "VisionData Gate.lnk")
    return sum(path.is_file() for path in candidates)


def _observe_uninstall_completion(install_root: Path) -> dict:
    return {
        "owned_uninstaller_process_count": _owned_uninstaller_process_count(
            install_root
        ),
        "uninstall_registry_entry_count": _uninstall_registry_entry_count(),
        "installer_shortcut_count": _installer_shortcut_count(),
        "install_root_exists": install_root.exists(),
    }


def _wait_for_uninstall_completion(
    install_root: Path,
    *,
    timeout_seconds: float = 240.0,
    poll_seconds: float = 2.0,
    observer=None,
) -> dict:
    if not 0 < timeout_seconds <= 600 or not 0 <= poll_seconds <= 10:
        raise ValueError("invalid uninstall completion budget")
    observe = observer or _observe_uninstall_completion
    started = time.monotonic()
    deadline = started + timeout_seconds
    poll_count = 0
    expected = {
        "owned_uninstaller_process_count",
        "uninstall_registry_entry_count",
        "installer_shortcut_count",
        "install_root_exists",
    }
    while True:
        observed = observe(install_root)
        poll_count += 1
        if not isinstance(observed, dict) or set(observed) != expected:
            raise RuntimeError("invalid uninstall completion observation")
        if (
            any(
                type(observed[name]) is not int or observed[name] < 0
                for name in expected
                if name.endswith("_count")
            )
            or type(observed["install_root_exists"]) is not bool
        ):
            raise RuntimeError("invalid uninstall completion observation")
        complete = (
            observed["owned_uninstaller_process_count"] == 0
            and observed["uninstall_registry_entry_count"] == 0
            and observed["installer_shortcut_count"] == 0
            and observed["install_root_exists"] is False
        )
        result = {
            **observed,
            "complete": complete,
            "poll_count": poll_count,
            "elapsed_seconds": round(time.monotonic() - started, 4),
        }
        if complete or time.monotonic() >= deadline:
            return result
        time.sleep(poll_seconds)


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
    uninstall_completion = _wait_for_uninstall_completion(install_root)

    receipt = {
        "schema_version": "visiondata-gate.windows-installer-smoke.v1",
        "status": (
            "PASS_LOCAL_INSTALLED_SMOKE"
            if uninstall_completion["complete"]
            else "HOLD_LOCAL_UNINSTALL_INCOMPLETE"
        ),
        "installer_sha256": _sha256(installer),
        "installed_application_sha256": application_sha256,
        "installer_exit_code": install.returncode,
        "application_exit_code": exit_code,
        "uninstaller_exit_code": uninstall.returncode,
        "uninstall_completion": uninstall_completion,
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
    return 0 if uninstall_completion["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
