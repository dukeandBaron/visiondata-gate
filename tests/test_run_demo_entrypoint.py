"""Exercise the Windows launcher's argument forwarding without starting services."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(not SHELL, reason="Windows PowerShell launcher")


def invoke(tmp_path, code=0):
    executable = tmp_path / "synthetic-python.cmd"
    executable.write_text(f"@echo off\n@echo %*\n@exit /b {code}\n", encoding="ascii")
    return subprocess.run([SHELL, "-NoProfile", "-File", str(ROOT / "run_demo.ps1"),
        "-Python", str(executable), "-Check", "-NoBrowser", "-ApiPort", "18787",
        "-Port", "15173", "-SmokeSeconds", "2"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30, cwd=tmp_path)


def test_public_demo_forwards_to_live_launcher_without_private_evidence(tmp_path):
    result = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "run_cross_platform_workbench.py" in result.stdout
    for expected in ["--check", "--no-browser", "--api-port 18787", "--web-port 15173", "--smoke-seconds 2"]:
        assert expected in result.stdout
    assert "omni_gate_result" not in result.stdout


def test_launcher_does_not_hide_child_failure(tmp_path):
    assert invoke(tmp_path, code=7).returncode != 0
