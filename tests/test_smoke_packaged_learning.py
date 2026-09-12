"""No real services or training: boundaries for the packaged stack driver."""

import importlib.util
from pathlib import Path

import httpx
import pytest


TOOL = Path(__file__).resolve().parents[1] / "tools/smoke_packaged_learning.py"


def test_packaged_smoke_entrypoint_exists():
    assert TOOL.is_file(), "three-tier packaged learning smoke driver is missing"


@pytest.fixture
def smoke():
    spec = importlib.util.spec_from_file_location("packaged_learning_smoke", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic artifact")
    return path


def test_runtime_environment_has_no_source_override_or_inherited_key(smoke, tmp_path):
    env = smoke.runtime_environment(
        tmp_path,
        "token-value",
        "startup-value",
        {
            "SystemRoot": "C:/Windows",
            "OPENAI_API_KEY": "private",
            "VISIONDATA_RESOURCE_ROOT": "source-code",
            "PYTHONPATH": "source-code",
            "VISIONDATA_PRODUCT_ROOT": "business-data",
            "HTTP_PROXY": "https://outside",
        },
    )
    assert (
        not {"OPENAI_API_KEY", "VISIONDATA_RESOURCE_ROOT", "PYTHONPATH", "HTTP_PROXY"}
        & env.keys()
    )
    assert env["VISIONDATA_PRODUCT_ROOT"] == str(tmp_path / "product")
    assert env["VISIONDATA_DESKTOP_SESSION_TOKEN"] == "token-value"
    assert env["VISIONDATA_DESKTOP_STARTUP_SECRET"] == "startup-value"


def test_commands_start_only_explicit_packaged_exe_and_java(smoke, tmp_path):
    root = tmp_path / "package"
    backend = write(root, "backend/visiondata-gate-backend.exe")
    java = write(root, "gateway/runtime/bin/java.exe")
    jar = write(root, "gateway/visiondata-gate-gateway.jar")
    commands = smoke.runtime_commands(
        root, backend.parent, java.parent.parent, jar, 24001
    )
    assert commands["backend"] == [str(backend), "--port", "24001"]
    assert commands["gateway"][0] == str(java)
    assert commands["gateway"][-2:] == ["-jar", str(jar)]
    assert all(
        "uvicorn" not in argument and not argument.endswith(".py")
        for values in commands.values()
        for argument in values
    )


def test_mixed_external_backend_is_rejected(smoke, tmp_path):
    root = tmp_path / "package"
    java = write(root, "gateway/runtime/bin/java.exe")
    jar = write(root, "gateway/gateway.jar")
    backend = write(tmp_path / "outside", "visiondata-gate-backend.exe")
    with pytest.raises(ValueError, match="ARTIFACT_ROOT_SCOPE"):
        smoke.runtime_commands(root, backend.parent, java.parent.parent, jar, 24001)


def test_gateway_header_required_for_business_requests(smoke):
    request = httpx.Request("GET", "http://127.0.0.1:24002/v1/projects")
    response = httpx.Response(
        200, request=request, headers={"X-VisionData-Gateway": "spring-webflux"}
    )
    smoke.require_gateway_response(response)
    with pytest.raises(smoke.SmokeError, match="GATEWAY_HEADER_REQUIRED"):
        smoke.require_gateway_response(httpx.Response(200, request=request))


def test_existing_output_is_refused_before_process_start(smoke, tmp_path):
    with pytest.raises(ValueError, match="OUTPUT_ROOT_EXISTS"):
        smoke.new_smoke_root(tmp_path)


def test_owned_process_cleanup_does_not_enumerate_other_processes(smoke):
    class Process:
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 1

        def wait(self, timeout):
            return self.returncode

    process = Process()
    assert smoke.stop_owned_process(process) == 1
    assert process.terminated is True
    assert smoke.stop_owned_process(None) is None
