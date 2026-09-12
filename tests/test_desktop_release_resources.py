"""Release code must never resolve back to build-machine sidecars."""

from pathlib import Path


def test_all_development_resource_paths_are_debug_only():
    source = (
        Path(__file__).resolve().parents[1] / "web/src-tauri/src/lib.rs"
    ).read_text(encoding="utf-8")
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
