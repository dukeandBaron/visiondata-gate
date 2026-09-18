"""Public-only deterministic reuse checks must fail closed and never overwrite."""

from __future__ import annotations

import hashlib
import ast
import importlib.util
import json
import socket
import stat
from types import SimpleNamespace
from pathlib import Path

import pytest

from visiondata_gate.audit_envelope import canonical_jcs_bytes


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/run_open_reuse_smoke.py"


def _tool():
    assert TOOL.is_file(), "one-command public reuse smoke is missing"
    spec = importlib.util.spec_from_file_location("open_reuse_smoke_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_components_produce_three_bound_artifacts_and_aggregate(tmp_path):
    tool = _tool()
    output = tmp_path / "new-smoke"
    report = tool.run_smoke(output)
    assert sorted(p.name for p in output.iterdir()) == [
        "OPEN_REUSE_RECEIPT.json",
        "adapter.json",
        "rulepack.json",
        "skill.json",
    ]
    assert report["schema_version"] == "visiondata-gate.open-reuse-receipt.v1"
    assert report["status"] == "PASS_OPEN_REUSE_SMOKE"
    assert report["execution_scope"] == "MAINTAINER_OR_USER_LOCAL_SYNTHETIC_OPEN_REUSE"
    assert (
        report["evidence_scope"]
        == "MAINTAINER_CI_CLEAN_CHECKOUT_NOT_THIRD_PARTY_ADOPTION"
    )
    assert (
        report["third_party_reproduction_status"] == "THIRD_PARTY_REPRODUCTION_PENDING"
    )
    assert report["actual_model_call_count"] == report["network_call_count"] == 0
    for key in (
        "production_release_allowed",
        "third_party_adoption_verified",
        "independent_external_reproduction_verified",
        "industrial_performance_verified",
    ):
        assert report[key] is False
    assert set(report["components"]) == {"skill", "rulepack", "adapter"}
    for name, identity in report["components"].items():
        data = (output / identity["artifact"]).read_bytes()
        assert identity["artifact"] == name + ".json"
        assert hashlib.sha256(data).hexdigest() == identity["sha256"]
        assert len(data) == identity["bytes"]
        assert canonical_jcs_bytes(json.loads(data)) == data
    skill = json.loads((output / "skill.json").read_bytes())
    assert skill["outcome"]["status"] == "OK"
    assert skill["outcome"]["observations"][0]["decision"]["observed_value"] == 2
    assert json.loads((output / "rulepack.json").read_bytes())["rule_count"] == 5
    adapter = json.loads((output / "adapter.json").read_bytes())
    assert len(adapter["checks"]) == 7
    assert all(row["status"] == "PASS" for row in adapter["checks"])
    raw = (output / "OPEN_REUSE_RECEIPT.json").read_bytes()
    assert raw == canonical_jcs_bytes(report)
    payload = {key: value for key, value in report.items() if key != "receipt_sha256"}
    assert (
        report["receipt_sha256"]
        == hashlib.sha256(canonical_jcs_bytes(payload)).hexdigest()
    )
    assert tool.verify_receipt(output) == report


def test_two_new_directories_are_byte_identical_and_do_not_leak_host(
    tmp_path, monkeypatch
):
    tool = _tool()
    monkeypatch.setenv("USERNAME", "private-owner-do-not-publish")
    first, second = tmp_path / "private-first", tmp_path / "private-second"
    tool.run_smoke(first)
    tool.run_smoke(second)
    for path in first.iterdir():
        raw = path.read_bytes()
        assert raw == (second / path.name).read_bytes()
        assert str(tmp_path).encode() not in raw
        assert b"private-owner-do-not-publish" not in raw


@pytest.mark.parametrize("kind", ["directory", "file", "drive_root"])
def test_output_must_be_new_nonroot_and_existing_bytes_are_preserved(tmp_path, kind):
    tool = _tool()
    destination = tmp_path / "existing"
    if kind == "directory":
        destination.mkdir()
        (destination / "keep.txt").write_text("preserve", encoding="utf-8")
    elif kind == "file":
        destination.write_bytes(b"preserve")
    else:
        destination = Path(tmp_path.anchor)
    with pytest.raises(tool.OpenReuseSmokeError, match="OUTPUT_"):
        tool.run_smoke(destination)
    if kind == "directory":
        assert (destination / "keep.txt").read_text("utf-8") == "preserve"
    elif kind == "file":
        assert destination.read_bytes() == b"preserve"


def test_missing_parent_is_not_created(tmp_path):
    tool = _tool()
    with pytest.raises(tool.OpenReuseSmokeError, match="OUTPUT_PARENT_REQUIRED"):
        tool.run_smoke(tmp_path / "absent" / "child")
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("component", ["skill", "rulepack", "adapter"])
def test_failed_or_tampered_component_never_publishes_pass(
    tmp_path, monkeypatch, component
):
    tool = _tool()
    if component == "skill":
        real = tool.run_example

        def bad():
            return real().model_copy(update={"receipt_sha256": "0" * 64})

        monkeypatch.setattr(tool, "run_example", bad)
    elif component == "rulepack":
        real = tool.verify_rule_pack

        def bad(*args, **kwargs):
            return real(*args, **kwargs).model_copy(
                update={"source_file_sha256": "0" * 64}
            )

        monkeypatch.setattr(tool, "verify_rule_pack", bad)
    else:
        real = tool.verify_adapter_conformance

        def bad(*args, **kwargs):
            value = real(*args, **kwargs)
            value["status"] = "FAIL"
            return value

        monkeypatch.setattr(tool, "verify_adapter_conformance", bad)
    output = tmp_path / component
    with pytest.raises(tool.OpenReuseSmokeError):
        tool.run_smoke(output)
    assert not (output / "OPEN_REUSE_RECEIPT.json").exists()


@pytest.mark.parametrize(
    "target", ["skill.json", "rulepack.json", "adapter.json", "OPEN_REUSE_RECEIPT.json"]
)
def test_readback_rejects_tampered_saved_bytes(tmp_path, target):
    tool = _tool()
    output = tmp_path / "audit"
    tool.run_smoke(output)
    path = output / target
    value = json.loads(path.read_bytes())
    value["tampered"] = True
    path.write_bytes(canonical_jcs_bytes(value))
    with pytest.raises(tool.OpenReuseSmokeError, match="RECEIPT_"):
        tool.verify_receipt(output)


def test_cli_reports_safe_failure_without_paths(tmp_path, capsys):
    tool = _tool()
    output = tmp_path / "new-cli"
    assert tool.main(["--output-root", str(output)]) == 0
    success = json.loads(capsys.readouterr().out)
    assert success["status"] == "PASS_OPEN_REUSE_SMOKE"
    assert tool.main(["--output-root", str(output)]) == 2
    failure = capsys.readouterr()
    assert str(tmp_path) not in failure.out + failure.err
    assert json.loads(failure.out)["status"] == "HOLD"


def test_component_exception_is_redacted_and_never_publishes_pass(
    tmp_path, monkeypatch, capsys
):
    tool = _tool()

    def broken():
        raise RuntimeError("private-owner at C:/private/customer/secret-data")

    monkeypatch.setattr(tool, "run_example", broken)
    output = tmp_path / "component-error"
    assert tool.main(["--output-root", str(output)]) == 2
    captured = capsys.readouterr()
    assert "private-owner" not in captured.out + captured.err
    assert "C:/private" not in captured.out + captured.err
    assert json.loads(captured.out)["status"] == "HOLD"
    assert not (output / "OPEN_REUSE_RECEIPT.json").exists()


def test_tamper_during_write_is_detected_before_publishing_pass(tmp_path, monkeypatch):
    tool = _tool()
    original = tool._write_new

    def changed(path, value):
        result = original(path, value)
        if path.name == "adapter.json":
            (path.parent / "rulepack.json").write_bytes(b"{}")
        return result

    monkeypatch.setattr(tool, "_write_new", changed)
    output = tmp_path / "changed"
    with pytest.raises(
        tool.OpenReuseSmokeError, match="RECEIPT_COMPONENT_CHANGED_BEFORE_PUBLISH"
    ):
        tool.run_smoke(output)
    assert not (output / "OPEN_REUSE_RECEIPT.json").exists()


def test_smoke_does_not_use_network_or_load_model_runtime(tmp_path, monkeypatch):
    import sys

    tool = _tool()
    models_before = {
        name for name in sys.modules if name.split(".")[0] in {"torch", "ultralytics"}
    }

    def denied(*_args, **_kwargs):
        pytest.fail("public reuse smoke attempted a network call")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    tool.run_smoke(tmp_path / "offline")
    assert models_before == {
        name for name in sys.modules if name.split(".")[0] in {"torch", "ultralytics"}
    }


def test_reparse_parent_is_rejected_before_output_creation(tmp_path, monkeypatch):
    tool = _tool()
    parent = tmp_path / "simulated-reparse"
    parent.mkdir()
    original = Path.lstat

    def metadata(path, *args, **kwargs):
        if path == parent:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", metadata)
    with pytest.raises(tool.OpenReuseSmokeError, match="OUTPUT_LINK_OR_REPARSE"):
        tool.run_smoke(parent / "new-output")
    assert not (parent / "new-output").exists()


def test_public_input_drift_during_api_call_cannot_publish_pass(tmp_path, monkeypatch):
    tool = _tool()
    copies = {}
    for name, source in tool.INPUTS.items():
        target = tmp_path / (name + ".json")
        target.write_bytes(source.read_bytes())
        copies[name] = target
    monkeypatch.setattr(tool, "INPUTS", copies)
    real = tool.verify_rule_pack

    def changed(path):
        receipt = real(path)
        path.write_bytes(path.read_bytes() + b"\n")
        return receipt

    monkeypatch.setattr(tool, "verify_rule_pack", changed)
    output = tmp_path / "input-changed"
    with pytest.raises(tool.OpenReuseSmokeError, match="INPUT_CHANGED_DURING_SMOKE"):
        tool.run_smoke(output)
    assert not (output / "OPEN_REUSE_RECEIPT.json").exists()


def test_tool_has_no_subprocess_network_or_model_imports():
    _tool()
    tree = ast.parse(TOOL.read_text("utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.module or "").split(".")[0])
    assert not imports & {
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "httpx",
        "torch",
        "ultralytics",
    }


@pytest.mark.parametrize("operation", ["run_smoke", "verify_receipt"])
def test_unc_output_is_rejected_before_any_filesystem_probe(monkeypatch, operation):
    tool = _tool()

    def network_probe(*_args, **_kwargs):
        pytest.fail("network output path must be rejected before filesystem access")

    monkeypatch.setattr(Path, "lstat", network_probe)
    with pytest.raises(tool.OpenReuseSmokeError, match="OUTPUT_NETWORK_PATH_FORBIDDEN"):
        getattr(tool, operation)(Path("//untrusted-share-host/share/new-output"))
