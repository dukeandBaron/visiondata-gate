from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest


pytestmark = pytest.mark.tier_release

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAVEN_NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def test_spring_gateway_uses_pinned_java_and_webflux_contract() -> None:
    pom = ElementTree.parse(PROJECT_ROOT / "gateway" / "pom.xml").getroot()
    assert pom.findtext("m:parent/m:version", namespaces=MAVEN_NS) == "4.1.1"
    assert pom.findtext("m:properties/m:java.version", namespaces=MAVEN_NS) == "21"
    dependencies = {
        item.findtext("m:artifactId", namespaces=MAVEN_NS)
        for item in pom.findall("m:dependencies/m:dependency", namespaces=MAVEN_NS)
    }
    assert "spring-boot-starter-webflux" in dependencies

    config = (
        PROJECT_ROOT / "gateway" / "src" / "main" / "resources" / "application.yml"
    ).read_text(encoding="utf-8")
    assert "address: 127.0.0.1" in config
    assert "VISIONDATA_FASTAPI_BASE_URL" in config
    assert "shutdown: graceful" in config


def test_portable_java_bootstrap_is_pinned_and_never_changes_system_path() -> None:
    source = (PROJECT_ROOT / "tools" / "bootstrap_java_toolchain.ps1").read_text(
        encoding="utf-8"
    )
    assert 'JdkVersion = "21.0.12.1+1"' in source
    assert "f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e" in source
    assert 'MavenVersion = "3.9.11"' in source
    assert "SetEnvironmentVariable" not in source
    assert "setx" not in source.casefold()


def test_tauri_bundle_contains_fastapi_gateway_and_java_runtime() -> None:
    config = json.loads(
        (PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    resources = config["bundle"]["resources"]
    assert resources["../../desktop/dist/visiondata-gate-backend"] == "backend"
    assert resources["../../gateway/target/visiondata-gate-gateway.jar"] == (
        "gateway/visiondata-gate-gateway.jar"
    )
    assert resources["../../gateway/runtime"] == "gateway/runtime"
    assert resources["../../desktop/default.env.example"] == "config/.env.example"
    assert "../../.env.example" not in resources
    assert config["bundle"]["targets"] == ["nsis"]


def test_core_desktop_bundle_does_not_embed_optional_model_payloads() -> None:
    config = json.loads(
        (PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    resources = json.dumps(config["bundle"]["resources"], sort_keys=True).casefold()

    assert "model_pack" not in resources
    assert "ultralytics" not in resources
    assert "torchvision" not in resources
    assert "yolo26" not in resources


def test_nsis_preuninstall_hook_removes_shortcuts_before_target_resolution() -> None:
    config = json.loads(
        (PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    hook_name = config["bundle"]["windows"]["nsis"]["installerHooks"]
    hook = (PROJECT_ROOT / "web" / "src-tauri" / hook_name).read_text(
        encoding="utf-8"
    )

    assert "!macro NSIS_HOOK_PREUNINSTALL" in hook
    assert 'Delete "$SMPROGRAMS\\${PRODUCTNAME}.lnk"' in hook
    assert 'Delete "$DESKTOP\\${PRODUCTNAME}.lnk"' in hook
    assert "IfSilent" in hook and "SetAutoClose true" in hook


def test_packaged_desktop_defaults_do_not_contain_build_machine_paths() -> None:
    source = (PROJECT_ROOT / "desktop" / "default.env.example").read_text(
        encoding="utf-8"
    )
    assert "VISIONDATA_INCIDENT_MODEL_MODE=off" in source
    assert "VISIONDATA_PRODUCT_MODEL_KEYS_ENABLED=false" in source
    assert "VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS=" not in source
    assert ":\\" not in source


def test_tauri_starts_and_stops_both_local_services() -> None:
    source = (PROJECT_ROOT / "web" / "src-tauri" / "src" / "lib.rs").read_text(
        encoding="utf-8"
    )
    assert "fastapi_child" in source
    assert "gateway_child" in source
    assert "VISIONDATA_FASTAPI_BASE_URL" in source
    assert "VISIONDATA_GATEWAY_PORT" in source
    assert "visiondata-gate-gateway.jar" in source
    assert "java.exe" in source
    assert "windows_process_path" in source
    assert 'strip_prefix("\\\\\\\\?\\\\")' in source
    assert "stop_services" in source
    assert 'api_base_url: format!("http://127.0.0.1:{gateway_port}")' in source
    assert "desktop-startup.json" in source
    assert "VISIONDATA_DESKTOP_SMOKE_EXIT_AFTER_READY_MS" in source


def test_windows_build_requires_gateway_runtime_and_joint_smoke() -> None:
    build = (PROJECT_ROOT / "build_windows_installer.ps1").read_text(encoding="utf-8")
    assert "bootstrap_java_toolchain.ps1" in build
    assert "build_gateway_runtime.ps1" in build
    assert "smoke_spring_gateway.py" in build
    assert "GATEWAY_SMOKE.json" in build
    assert "BACKEND_SIDECAR_SMOKE.json" in build
    assert "BUILD_MANIFEST.json" in build


def test_joint_smoke_fails_closed_and_records_both_runtimes() -> None:
    source = (PROJECT_ROOT / "tools" / "smoke_spring_gateway.py").read_text(
        encoding="utf-8"
    )
    assert "/gateway/v1/health" in source
    assert "/v1/desktop/readiness" in source
    assert '"production_release_allowed": False' in source
    assert '"machine_write_permitted": False' in source
    assert '"status": "PASS"' in source


def test_installer_smoke_runs_install_start_database_check_and_uninstall() -> None:
    source = (PROJECT_ROOT / "tools" / "smoke_windows_installer.py").read_text(
        encoding="utf-8"
    )
    assert '"/S"' in source
    assert "VISIONDATA_DESKTOP_SMOKE_EXIT_AFTER_READY_MS" in source
    assert "desktop-startup.json" in source
    assert "PRAGMA integrity_check" in source
    assert '"PASS_LOCAL_INSTALLED_SMOKE"' in source
    assert '"HOLD_LOCAL_UNINSTALL_INCOMPLETE"' in source
    assert "_wait_for_uninstall_completion" in source
    assert '"clean_machine_validation": "NOT_RUN"' in source
