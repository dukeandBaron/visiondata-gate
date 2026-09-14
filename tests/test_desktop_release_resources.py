"""Release code must never resolve back to build-machine sidecars."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_all_development_resource_paths_are_debug_only():
    source = (PROJECT_ROOT / "web/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    for name, following in [
        ("backend_executable", "gateway_jar"),
        ("gateway_jar", "gateway_java"),
        ("gateway_java", "expected_startup_proof"),
    ]:
        body = source.split(f"fn {name}(", 1)[1].split(f"fn {following}(", 1)[0]
        assert "#[cfg(debug_assertions)]\n    {\n        let development" in body
        assert body.count('env!("CARGO_MANIFEST_DIR")') == 1
        # Development lookup must finish before the unconditional missing-resource error.
        assert '\n    }\n    Err("the packaged ' in body


def test_optional_normality_worker_is_source_only_and_heavy_runtime_is_external():
    spec = (PROJECT_ROOT / "desktop/visiondata_gate_backend.spec").read_text(
        encoding="utf-8"
    )

    assert "normality_inference.py" in spec
    assert "THIRD_PARTY_NOTICES.md" in spec
    assert "SBOM.cdx.json" in spec
    assert '"torch"' in spec
    assert '"torchvision"' in spec
    assert '"ultralytics"' in spec
    assert "best_normality_model_pack.pt" not in spec
    assert "yolo26n-cls.pt" not in spec


def test_packaged_backend_disables_bytecode_residue_before_runtime_imports():
    source = (PROJECT_ROOT / "src/visiondata_gate/desktop_backend.py").read_text(
        encoding="utf-8"
    )

    guard = "sys.dont_write_bytecode = True"
    runtime_import = "from visiondata_gate.api import app"
    assert guard in source
    assert source.index(guard) < source.index(runtime_import)
