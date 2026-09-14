"""Installer-smoke completion checks for the NSIS second-stage uninstaller."""

from __future__ import annotations

import importlib.util
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "tools" / "smoke_windows_installer.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("windows_installer_smoke", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uninstall_waits_for_second_stage_and_all_shell_residue(tmp_path: Path):
    tool = _load_tool()
    assert hasattr(tool, "_wait_for_uninstall_completion")
    observations = iter(
        [
            {
                "owned_uninstaller_process_count": 1,
                "uninstall_registry_entry_count": 1,
                "installer_shortcut_count": 2,
                "install_root_exists": False,
            },
            {
                "owned_uninstaller_process_count": 0,
                "uninstall_registry_entry_count": 0,
                "installer_shortcut_count": 0,
                "install_root_exists": False,
            },
        ]
    )

    result = tool._wait_for_uninstall_completion(
        tmp_path / "installed",
        timeout_seconds=1.0,
        poll_seconds=0.0,
        observer=lambda _root: next(observations),
    )

    assert result["complete"] is True
    assert result["poll_count"] == 2
    assert result["owned_uninstaller_process_count"] == 0
    assert result["uninstall_registry_entry_count"] == 0
    assert result["installer_shortcut_count"] == 0
    assert result["install_root_exists"] is False


def test_uninstall_timeout_remains_hold_instead_of_premature_pass(tmp_path: Path):
    tool = _load_tool()
    dirty = {
        "owned_uninstaller_process_count": 1,
        "uninstall_registry_entry_count": 1,
        "installer_shortcut_count": 2,
        "install_root_exists": False,
    }

    result = tool._wait_for_uninstall_completion(
        tmp_path / "installed",
        timeout_seconds=0.01,
        poll_seconds=0.0,
        observer=lambda _root: dict(dirty),
    )

    assert result["complete"] is False
    assert result["owned_uninstaller_process_count"] == 1
    assert result["uninstall_registry_entry_count"] == 1
    assert result["installer_shortcut_count"] == 2

