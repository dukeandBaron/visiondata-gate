"""Synthetic, non-building tests for the staged authority-source builder."""

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

import pytest


TOOL = Path(__file__).resolve().parents[1] / "tools/build_learning_installer.py"


def test_builder_entrypoint_exists():
    assert TOOL.is_file(), "new-staging learning installer driver is missing"


def test_model_reproducibility_drivers_are_frozen_source_inputs(builder):
    assert {
        "tools/run_visa_yolo26_normality.py",
        "tools/summarize_visa_yolo26_stability.py",
        "tools/run_normality_registry_smoke.py",
        "tools/smoke_desktop_identity.mjs",
        "docs/VISION_MODEL_API_CONTRACT.md",
        "docs/MODEL_JOB_RETENTION.md",
    }.issubset(set(builder.REQUIRED_INPUTS))


def test_public_main_freeze_does_not_require_internal_reports(builder):
    assert all(
        not name.startswith("10_reports/") for name in builder.REQUIRED_INPUTS
    )
    assert {
        "benchmarks/DYNAMICBENCH_V3_REPLANNING_20260829.json",
        "benchmarks/DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json",
    }.issubset(set(builder.REQUIRED_INPUTS))
    assert all(
        "10_reports" not in reason
        for reason in builder.EXCLUDED_SOURCE_SUBTREES.values()
    )


@pytest.fixture
def builder():
    spec = importlib.util.spec_from_file_location("learning_installer_builder", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(root, name, content=b"fixture"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def authority(builder, tmp_path, monkeypatch):
    root = tmp_path / "authority"
    root.mkdir()
    for name in builder.REQUIRED_INPUTS:
        write(root, name)
    for name in getattr(builder, "RUNTIME_MODULES", builder.LEARNING_MODULES):
        write(root, "src/" + name.replace(".", "/") + ".py")
    write(root, "src/visiondata_gate/__init__.py")
    write(root, "web/src/App.tsx")
    write(root, "gateway/src/main/java/Gateway.java")
    write(root, "sample_data/synthetic.png")
    tracked = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    monkeypatch.setattr(
        builder,
        "git_state",
        lambda path: (
            {"head": "a" * 40, "tree": "b" * 40, "branch": "fixture", "dirty": True},
            tracked,
        ),
    )
    return root


def test_source_snapshot_copies_only_allowlisted_inputs(builder, authority, tmp_path):
    write(authority, ".env.local", b"never read")
    write(authority, "output/private.sqlite", b"never read")
    write(authority, "web/node_modules/pkg/private.js", b"not source")
    stage = tmp_path / "stage"
    manifest = builder.freeze_sources(authority, stage)
    assert manifest["authority"]["dirty"] is True
    names = {row["path"] for row in manifest["files"]}
    assert "src/visiondata_gate/learning_engine.py" in names
    assert (
        not {".env.local", "output/private.sqlite", "web/node_modules/pkg/private.js"}
        & names
    )
    assert "e09bac5" not in json.dumps(manifest)
    assert str(authority) not in json.dumps(manifest)
    assert (
        builder.verify_frozen(stage)["source_content_sha256"]
        == manifest["source_content_sha256"]
    )


def test_existing_stage_refused_without_modification(builder, authority, tmp_path):
    stage = tmp_path / "stage"
    write(stage, "keep.txt", b"keep")
    with pytest.raises(builder.BuildError, match="STAGING_EXISTS"):
        builder.freeze_sources(authority, stage)
    assert (stage / "keep.txt").read_bytes() == b"keep"


def test_post_freeze_source_change_rejected(builder, authority, tmp_path):
    stage = tmp_path / "stage"
    builder.freeze_sources(authority, stage)
    write(stage / "source", "src/visiondata_gate/learning_engine.py", b"changed")
    with pytest.raises(builder.BuildError, match="SOURCE_DRIFT"):
        builder.verify_frozen(stage)


def test_post_freeze_new_code_rejected(builder, authority, tmp_path):
    stage = tmp_path / "stage"
    builder.freeze_sources(authority, stage)
    write(stage / "source", "src/visiondata_gate/unattested.py")
    with pytest.raises(builder.BuildError, match="SOURCE_FILE_SET"):
        builder.verify_frozen(stage)


def test_untracked_resource_image_is_not_read(builder, authority, tmp_path):
    write(authority, "sample_data/private.png", b"untracked private picture")
    with pytest.raises(builder.BuildError, match="UNALLOWLISTED_RESOURCE"):
        builder.freeze_sources(authority, tmp_path / "stage")


@pytest.mark.parametrize(
    "name", ["../escape", "C:/private", "images/x:stream", "x\\y", "/absolute"]
)
def test_unsafe_relative_paths_rejected(builder, name):
    with pytest.raises(builder.BuildError, match="RELATIVE_PATH"):
        builder.safe_relative(name)


def test_private_file_in_resource_tree_rejected(builder, authority, tmp_path):
    write(authority, "src/visiondata_gate/user.sqlite", b"private")
    with pytest.raises(builder.BuildError, match="PRIVATE_FILE"):
        builder.freeze_sources(authority, tmp_path / "stage")


def test_missing_learning_module_rejected(builder, authority, tmp_path):
    (authority / "src/visiondata_gate/learning_engine.py").unlink()
    with pytest.raises(builder.BuildError, match="REQUIRED_SOURCE_MISSING"):
        builder.freeze_sources(authority, tmp_path / "stage")


def test_editable_install_metadata_is_not_an_authority_source_input(
    builder, authority, tmp_path
):
    write(
        authority,
        "src/visiondata_gate.egg-info/PKG-INFO",
        b"generated editable metadata",
    )
    manifest = builder.freeze_sources(authority, tmp_path / "stage")
    assert all(".egg-info/" not in row["path"] for row in manifest["files"])


def test_parallel_public_reproducibility_subtree_is_explicitly_excluded(
    builder, authority, tmp_path
):
    write(
        authority,
        "examples/reproducibility/new-public.json",
        b"parallel public fixture",
    )
    manifest = builder.freeze_sources(authority, tmp_path / "stage")
    assert all(
        not row["path"].startswith("examples/reproducibility/")
        for row in manifest["files"]
    )
    assert manifest["excluded_subtrees"][0]["path"] == "examples/reproducibility/"


def test_build_plan_uses_only_stage_cwds_and_all_three_runtimes(builder, tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    tools = {
        key: tmp_path / "tools" / key
        for key in (
            "python",
            "java",
            "jlink",
            "maven_home",
            "maven_launcher",
            "maven_repository",
            "node",
            "npm",
            "cargo",
        )
    }
    plan = builder.build_commands(stage, tools)
    assert [step["name"] for step in plan] == [
        "MAVEN_PACKAGE",
        "JLINK_RUNTIME",
        "PYINSTALLER_BACKEND",
        "TAURI_NSIS",
    ]
    assert all(Path(step["cwd"]).is_relative_to(stage) for step in plan)
    rendered = json.dumps(plan)
    assert "build_windows_installer.ps1" not in rendered
    assert "build_gateway_runtime.ps1" not in rendered
    assert "--offline" in rendered
    assert "--locked" in rendered
    assert "--no-sign" in rendered


def test_build_env_cannot_inherit_model_secrets_or_private_roots(builder, tmp_path):
    stage = tmp_path / "stage"
    environment = builder.build_environment(
        stage,
        {},
        {
            "SystemRoot": "C:/Windows",
            "OPENAI_API_KEY": "secret",
            "HTTP_PROXY": "https://private",
            "VISIONDATA_PRODUCT_ROOT": "private-data",
            "PYTHONPATH": "private-source",
        },
    )
    assert "OPENAI_API_KEY" not in environment
    assert "HTTP_PROXY" not in environment
    assert environment["VISIONDATA_PRODUCT_ROOT"] == str(
        stage / "build/analysis-product"
    )
    assert environment["CARGO_TARGET_DIR"] == str(stage / "build/cargo-target")
    assert environment["CARGO_NET_OFFLINE"] == "true"
    assert environment["USERPROFILE"] == str(stage / "build/user-profile")


def test_rust_binary_paths_are_remapped_without_changing_global_environment(
    builder, tmp_path
):
    stage = tmp_path / "stage"
    cargo_home = tmp_path / "private-user-cache"
    rustc = tmp_path / "private-toolchain/bin/rustc.exe"
    env = builder.build_environment(
        stage, {"cargo_home": cargo_home, "rustc": rustc}, {}
    )
    flags = env.get("CARGO_ENCODED_RUSTFLAGS", "").split("\x1f")
    assert f"--remap-path-prefix={stage}=build" in flags
    assert f"--remap-path-prefix={cargo_home}=cargo-cache" in flags
    assert f"--remap-path-prefix={rustc.parent.parent}=rust-toolchain" in flags


def test_nsis_cache_matches_native_windows_profile_resolution(builder, tmp_path):
    stage = tmp_path / "stage"
    env = builder.build_environment(stage, {}, {})
    expected = stage / "build/user-profile/AppData/Local"
    assert Path(env["LOCALAPPDATA"]) == expected
    assert Path(env["APPDATA"]) == stage / "build/user-profile/AppData/Roaming"
    assert builder.tauri_cache_destination(stage) == expected / "tauri"


def test_archive_gate_requires_all_eight_learning_modules(builder):
    with pytest.raises(builder.BuildError, match="LEARNING_MODULES_MISSING"):
        builder.verify_learning_names(builder.LEARNING_MODULES[:-1])
    assert builder.verify_learning_names(builder.LEARNING_MODULES)["status"] == "PASS"


def test_new_platform_schema_is_explicitly_freezable(builder, authority, tmp_path):
    write(authority, "schemas/vision_model_requests.v1.json", b'{"type":"object"}')
    result = builder.freeze_sources(authority, tmp_path / "stage")
    assert "schemas/vision_model_requests.v1.json" in {
        row["path"] for row in result["files"]
    }


def test_archive_gate_requires_identity_pool_and_model_feedback_modules(builder):
    assert hasattr(builder, "RUNTIME_MODULES"), (
        "Archive only checks old reference-learning modules"
    )
    expected = {
        "visiondata_gate.identity_api",
        "visiondata_gate.identity_service",
        "visiondata_gate.data_pool",
        "visiondata_gate.data_pool_api",
        "visiondata_gate.local_model_registry",
        "visiondata_gate.vision_feedback",
        "visiondata_gate.learning_yolo_backend",
        "visiondata_gate.normality_inference",
        "visiondata_gate.model_stability",
        "visiondata_gate.model_experiment_agent",
        "visiondata_gate.vision_model_api",
    }
    assert expected <= set(builder.RUNTIME_MODULES)
    with pytest.raises(builder.BuildError, match="RUNTIME_MODULES_MISSING"):
        builder.verify_runtime_names(builder.LEARNING_MODULES)
    assert builder.verify_runtime_names(builder.RUNTIME_MODULES)["status"] == "PASS"


def test_spec_carries_standalone_external_runner_and_excludes_install_origin(
    authority, monkeypatch
):
    import runpy
    from types import SimpleNamespace
    import PyInstaller.utils.hooks

    monkeypatch.chdir(authority)
    monkeypatch.setattr(
        PyInstaller.utils.hooks, "collect_submodules", lambda name: [name]
    )
    artifact = SimpleNamespace(
        pure=[],
        scripts=[],
        binaries=[],
        datas=[
            (
                "visiondata_gate-0.1.0.dist-info/direct_url.json",
                "private-local-origin",
                "DATA",
            ),
            ("visiondata_gate-0.1.0.dist-info/METADATA", "package-description", "DATA"),
        ],
    )
    analysis_options = {}

    def analysis(*args, **kwargs):
        analysis_options.update(kwargs)
        return artifact

    values = runpy.run_path(
        str(TOOL.parents[1] / "desktop/visiondata_gate_backend.spec"),
        init_globals={
            "Analysis": analysis,
            "PYZ": lambda *args, **kwargs: None,
            "EXE": lambda *args, **kwargs: None,
            "COLLECT": lambda *args, **kwargs: None,
        },
    )
    for worker in (
        "learning_yolo_backend.py",
        "normality_inference.py",
        "model_stability.py",
        "model_experiment_agent.py",
    ):
        assert (
            str(authority / "src/visiondata_gate" / worker),
            "visiondata_gate",
        ) in values["datas"]
    for notice_material in ("THIRD_PARTY_NOTICES.md", "SBOM.cdx.json"):
        assert (
            str(authority / "docs" / notice_material),
            "docs",
        ) in values["datas"]
    assert {"torch", "torchvision", "ultralytics"} <= set(analysis_options["excludes"])
    assert not any(
        Path(source).suffix.casefold() in {".pt", ".onnx", ".safetensors", ".engine"}
        for source, _destination in values["datas"]
    )
    assert all(not row[0].endswith("direct_url.json") for row in artifact.datas)
    assert any(row[0].endswith("METADATA") for row in artifact.datas)


def _write_external_runtime_bundle_fixture(root):
    source = root / "source"
    backend = root / "backend"
    resources = {
        "src/visiondata_gate/learning_yolo_backend.py": b"training worker\n",
        "src/visiondata_gate/normality_inference.py": b"inference worker\n",
        "src/visiondata_gate/model_stability.py": b"stability verifier\n",
        "src/visiondata_gate/model_experiment_agent.py": b"outcome policy\n",
        "docs/THIRD_PARTY_NOTICES.md": b"third-party notices\n",
        "docs/SBOM.cdx.json": b'{"bomFormat":"CycloneDX"}\n',
    }
    for name, content in resources.items():
        write(source, name, content)
        if name.startswith("src/visiondata_gate/"):
            packaged = "_internal/visiondata_gate/" + Path(name).name
        else:
            packaged = "_internal/docs/" + Path(name).name
        write(backend, packaged, content)
    return source, backend


def test_external_runtime_bundle_binds_workers_and_notice_materials(builder, tmp_path):
    source, backend = _write_external_runtime_bundle_fixture(tmp_path)

    receipt = builder.verify_external_runtime_bundle(source, backend)

    assert receipt["status"] == "PASS"
    assert receipt["capability"] == "EXTERNAL_RUNTIME_REQUIRED"
    assert receipt["production_release_allowed"] is False
    assert receipt["model_pack_bundled"] is False
    assert receipt["torch_bundled"] is False
    assert receipt["torchvision_bundled"] is False
    assert receipt["ultralytics_bundled"] is False
    assert receipt["yolo_weights_bundled"] is False
    assert len(receipt["resources"]) == 6
    assert all(row["source_matches_packaged"] for row in receipt["resources"])


@pytest.mark.parametrize(
    "payload",
    (
        "_internal/torch/__init__.py",
        "_internal/torchvision/models.py",
        "_internal/ultralytics/__init__.py",
        "_internal/models/best_normality_model_pack.pt",
        "_internal/models/yolo26n.onnx",
        "_internal/libtorch_cpu.dll",
        "_internal/torch_cpu.dll",
        "_internal/libtorch_cuda.dll",
        "_internal/c10.dll",
        "_internal/c10_cuda.dll",
        "_internal/onnxruntime.dll",
        "_internal/onnxruntime_providers_cuda.dll",
    ),
)
def test_external_runtime_bundle_rejects_model_payloads(builder, tmp_path, payload):
    source, backend = _write_external_runtime_bundle_fixture(tmp_path)
    write(backend, payload, b"forbidden payload")

    with pytest.raises(builder.BuildError, match="BUNDLED_MODEL_RUNTIME_FORBIDDEN"):
        builder.verify_external_runtime_bundle(source, backend)


def test_build_manifest_binds_external_runtime_capability(builder, tmp_path):
    staging = tmp_path / "stage"
    source = staging / "source"
    backend = source / "desktop/dist/visiondata-gate-backend"
    for source_name, packaged_name in builder.EXTERNAL_RUNTIME_RESOURCES:
        content = (source_name + "\n").encode()
        write(source, source_name, content)
        write(backend, packaged_name, content)
    write(source, "web/dist/index.html")
    write(source, "gateway/runtime/bin/java.exe")
    write(source, "sample_data/sample.png")
    write(source, "desktop/default.env.example")
    write(source, "LICENSE")
    write(source, "NOTICE")
    write(staging, "build/cargo-target/release/visiondata-gate-desktop.exe")
    write(staging, "build/cargo-target/release/bundle/nsis/setup.exe")
    jar = source / "gateway/target/visiondata-gate-gateway.jar"
    jar.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("BOOT-INF/lib/dependency.jar", b"dependency")

    manifest = builder.bind_artifacts(
        staging,
        {"source_content_sha256": "a" * 64},
        {"status": "PASS"},
    )

    capability = manifest["external_runtime_model_capability"]
    assert capability["capability"] == "EXTERNAL_RUNTIME_REQUIRED"
    assert capability["model_pack_bundled"] is False
    assert capability["production_release_allowed"] is False

    delivery = staging / "deliverables"
    assert json.loads((delivery / "BUILD_MANIFEST.json").read_text("utf-8")) == manifest
    assert json.loads((delivery / "SOURCE_MANIFEST.json").read_text("utf-8")) == {
        "source_content_sha256": "a" * 64,
    }
    sums = (delivery / "SHA256SUMS.txt").read_text("utf-8")
    for name in (
        "setup.exe",
        "BUILD_MANIFEST.json",
        "SOURCE_MANIFEST.json",
        "DELIVERY_STATUS.json",
    ):
        digest = hashlib.sha256((delivery / name).read_bytes()).hexdigest()
        assert f"{digest}  {name}" in sums
    status = json.loads((delivery / "DELIVERY_STATUS.json").read_text("utf-8"))
    assert status["status"] == "BUILD_COMPLETE_VALIDATION_PENDING"
    assert status["production_release_allowed"] is False
    assert all(value == "NOT_RUN" for value in status["validation"].values())
    assert not (delivery / "INSTALLER_SMOKE.json").exists()


def test_resource_inventory_rejects_database_and_does_not_read_it(builder, tmp_path):
    root = tmp_path / "runtime"
    write(root, "business.sqlite")
    with pytest.raises(builder.BuildError, match="PRIVATE_FILE"):
        builder.inventory_tree(root)


def test_compiled_archive_code_is_bound_to_staged_source_not_only_module_name(
    builder, tmp_path
):
    source = write(
        tmp_path,
        "src/visiondata_gate/learning_engine.py",
        b"def value():\n    return 3\n",
    )
    packaged = compile(
        source.read_bytes(), "visiondata_gate/learning_engine.py", "exec", optimize=1
    )
    assert (
        builder.verify_compiled_source(packaged, source, tmp_path / "src")[
            "matched_staged_source"
        ]
        is True
    )
    wrong = compile(
        b"def value():\n    return 999\n",
        "visiondata_gate/learning_engine.py",
        "exec",
        optimize=1,
    )
    with pytest.raises(builder.BuildError, match="PYZ_STAGED_SOURCE_MISMATCH"):
        builder.verify_compiled_source(wrong, source, tmp_path / "src")


def test_absolute_authority_editable_filename_is_not_accepted_as_staged(
    builder, tmp_path
):
    source = write(
        tmp_path, "staged/src/visiondata_gate/learning_engine.py", b"VALUE = 3\n"
    )
    packaged = compile(
        source.read_bytes(),
        str(tmp_path / "authority/src/visiondata_gate/learning_engine.py"),
        "exec",
        optimize=1,
    )
    with pytest.raises(builder.BuildError, match="PYZ_FILENAME_OUTSIDE_STAGED_SOURCE"):
        builder.verify_compiled_source(packaged, source, tmp_path / "staged/src")


def test_rustup_shim_requires_explicit_installed_toolchain(builder, tmp_path):
    shim = write(tmp_path, "shims/cargo.exe", b"same shim")
    write(tmp_path, "shims/rustup.exe", b"same shim")
    with pytest.raises(builder.BuildError, match="RUSTUP_SHIM_NOT_ALLOWED"):
        builder.validate_rust_toolchain(shim)
    cargo = write(tmp_path, "toolchain/bin/cargo.exe", b"real cargo")
    write(tmp_path, "toolchain/bin/rustc.exe", b"real rustc")
    assert builder.validate_rust_toolchain(cargo)["cargo"] == cargo


@pytest.mark.parametrize("outside", [False, True])
def test_dependency_junction_materialization_stays_inside_explicit_root(
    builder, tmp_path, outside
):
    if os.name != "nt":
        pytest.skip("Windows junction test")
    root = tmp_path / "node_modules"
    root.mkdir()
    target = tmp_path / "outside" if outside else root / ".pnpm/pkg/node_modules/pkg"
    write(target, "package.json", b'{"name":"pkg","version":"1"}')
    junction = root / "pkg"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        check=False,
    )
    if created.returncode:
        pytest.skip("junction creation unavailable")
    try:
        if outside:
            with pytest.raises(
                builder.BuildError, match="DEPENDENCY_LINK_OUTSIDE_ROOT"
            ):
                builder.copy_dependency_tree(
                    root, tmp_path / "copy", materialize_internal_links=True
                )
        else:
            receipt = builder.copy_dependency_tree(
                root, tmp_path / "copy", materialize_internal_links=True
            )
            assert (tmp_path / "copy/pkg/package.json").read_bytes() == (
                target / "package.json"
            ).read_bytes()
            assert not (tmp_path / "copy/pkg").is_junction()
            assert receipt["internal_directory_links_materialized"][0]["path"] == "pkg"
    finally:
        os.rmdir(junction)
