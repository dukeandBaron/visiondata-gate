"""Freeze authority inputs, then build a new unsigned three-tier staging tree.

No old build script, installer, delivery directory, dependency updater, or
recursive deletion is invoked. `freeze` and `build` are separate explicit steps.
Dependencies/tool caches have separate manifests and are never source inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import types
import zipfile


LEARNING_MODULES = tuple(
    "visiondata_gate.learning_" + name
    for name in (
        "api",
        "contracts",
        "dataset",
        "engine",
        "evaluation",
        "operations",
        "projection",
        "service",
    )
)
RUNTIME_MODULES = LEARNING_MODULES + tuple(
    "visiondata_gate." + name
    for name in (
        "api",
        "desktop_backend",
        "product_service",
        "task_store",
        "identity_service",
        "identity_api",
        "local_workbench",
        "data_pool",
        "data_pool_api",
        "local_model_registry",
        "learning_detection_dataset",
        "learning_yolo_backend",
        "normality_inference",
        "model_stability",
        "model_experiment_agent",
        "vision_model_api",
        "vision_data_pool_bridge",
        "vision_feedback",
    )
)
REQUIRED_INPUTS = (
    "LICENSE",
    "NOTICE",
    "README.md",
    "docs/WINDOWS_INSTALLER.md",
    "docs/VISION_MODEL_API_CONTRACT.md",
    "docs/MODEL_JOB_RETENTION.md",
    "docs/THIRD_PARTY_NOTICES.md",
    "docs/SBOM.cdx.json",
    "pyproject.toml",
    "uv.lock",
    "desktop/backend_main.py",
    "desktop/visiondata_gate_backend.spec",
    "desktop/default.env.example",
    "gateway/pom.xml",
    "web/package.json",
    "web/package-lock.json",
    "web/index.html",
    "web/tsconfig.json",
    "web/tsconfig.app.json",
    "web/tsconfig.node.json",
    "web/vite.config.ts",
    "web/src-tauri/Cargo.toml",
    "web/src-tauri/Cargo.lock",
    "web/src-tauri/build.rs",
    "web/src-tauri/nsis-hooks.nsh",
    "web/src-tauri/tauri.conf.json",
    "benchmarks/DYNAMICBENCH_V3_REPLANNING_20260829.json",
    "benchmarks/DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json",
    "tools/build_learning_installer.py",
    "tools/smoke_packaged_learning.py",
    "tools/smoke_desktop_identity.mjs",
    "tools/run_learning_demo.py",
    "tools/run_visa_yolo26_normality.py",
    "tools/summarize_visa_yolo26_stability.py",
    "tools/run_normality_registry_smoke.py",
)
SOURCE_TREES = (
    "src",
    "web/src",
    "web/public",
    "web/src-tauri/src",
    "web/src-tauri/icons",
    "web/src-tauri/capabilities",
    "gateway/src",
    "examples",
    "rulepacks",
    "schemas",
    "sample_data",
)
UNTRACKED_CODE_TREES = ("src/", "web/src/", "web/src-tauri/src/", "gateway/src/")
UNTRACKED_CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".css",
    ".rs",
    ".java",
    ".yml",
    ".yaml",
}
EXPLICIT_ADDITIONS = {
    "schemas/compute_handoff_request.v1.json",
    "schemas/operator_acceptance_requirements.v1.json",
    "schemas/vision_model_requests.v1.json",
}
EXCLUDED_SOURCE_SUBTREES = {
    "examples/reproducibility/": "Explicitly excluded parallel public benchmark fixtures; not required by this learning or installed runtime."
}
IGNORE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    ".vite",
    ".vite-temp",
    ".tmp",
}

EXTERNAL_RUNTIME_RESOURCES = (
    (
        "src/visiondata_gate/learning_yolo_backend.py",
        "_internal/visiondata_gate/learning_yolo_backend.py",
    ),
    (
        "src/visiondata_gate/normality_inference.py",
        "_internal/visiondata_gate/normality_inference.py",
    ),
    (
        "src/visiondata_gate/model_stability.py",
        "_internal/visiondata_gate/model_stability.py",
    ),
    (
        "src/visiondata_gate/model_experiment_agent.py",
        "_internal/visiondata_gate/model_experiment_agent.py",
    ),
    (
        "docs/THIRD_PARTY_NOTICES.md",
        "_internal/docs/THIRD_PARTY_NOTICES.md",
    ),
    (
        "docs/SBOM.cdx.json",
        "_internal/docs/SBOM.cdx.json",
    ),
)
FORBIDDEN_BUNDLED_MODEL_PACKAGES = ("torch", "torchvision", "ultralytics")
FORBIDDEN_BUNDLED_MODEL_SUFFIXES = (".pt", ".onnx", ".safetensors", ".engine")
FORBIDDEN_BUNDLED_NATIVE_MODEL_SUFFIXES = (".dll", ".pyd", ".so", ".dylib")
FORBIDDEN_BUNDLED_NATIVE_MODEL_TOKENS = (
    "libtorch",
    "torch_cpu",
    "torch_cuda",
    "onnxruntime",
)
JLINK_MODULES = (
    "java.base",
    "java.compiler",
    "java.desktop",
    "java.instrument",
    "java.management",
    "java.naming",
    "java.net.http",
    "java.prefs",
    "java.security.jgss",
    "java.sql",
    "java.transaction.xa",
    "java.xml",
    "jdk.crypto.ec",
    "jdk.management",
    "jdk.naming.dns",
    "jdk.unsupported",
    "jdk.zipfs",
)
ENV_KEYS = (
    "SystemRoot",
    "SYSTEMROOT",
    "WINDIR",
    "ComSpec",
    "COMSPEC",
    "PATHEXT",
    "SystemDrive",
    "SYSTEMDRIVE",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramW6432",
    "VCINSTALLDIR",
    "VCToolsInstallDir",
    "WindowsSdkDir",
    "WindowsSDKVersion",
    "INCLUDE",
    "LIB",
    "LIBPATH",
)


class BuildError(ValueError):
    """A controlled error code without exception paths or configuration values."""


def canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def safe_relative(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or any(char in name for char in '\\:<>"|?*')
    ):
        raise BuildError("RELATIVE_PATH")
    if any(
        part in {"", ".", ".."} or part.endswith((".", " ")) for part in name.split("/")
    ) or any(ord(char) < 32 for char in name):
        raise BuildError("RELATIVE_PATH")
    return name


def no_links(path: Path) -> None:
    for entry in (path, *path.parents):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(
            info, "st_file_attributes", 0
        ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise BuildError("PATH_LINK_OR_REPARSE")


def safe_root(value: Path) -> Path:
    path = Path(os.path.abspath(value))
    no_links(path)
    if not path.is_dir() or path == Path(path.anchor):
        raise BuildError("ROOT_DIRECTORY_REQUIRED")
    return path.resolve(strict=True)


def tool_root(value: Path) -> Path:
    """An explicitly supplied cache may be a known link; use only its real root."""
    return safe_root(Path(value).resolve(strict=True))


def safe_file(root: Path, name: str) -> Path:
    path = root / safe_relative(name)
    no_links(path)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise BuildError("REGULAR_FILE_SCOPE")
    return resolved


def private_name(name: str) -> bool:
    parts = Path(name.lower()).parts
    leaf = parts[-1]
    if any(part.startswith(".env") and part != ".env.example" for part in parts):
        return True
    return leaf.endswith(
        (
            ".sqlite",
            ".sqlite3",
            ".db",
            ".sqlite-wal",
            ".sqlite-shm",
            ".key",
            ".pfx",
            ".p12",
        )
    ) or leaf in {"id_rsa", "id_ed25519", ".npmrc"}


def hash_file(path: Path, label: str) -> dict:
    no_links(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise BuildError("REGULAR_FILE_REQUIRED")
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise BuildError("FILE_CHANGED_DURING_HASH")
    return {"path": label, "size": after.st_size, "sha256": sha}


def walk_files(root: Path, *, ignore_dirs=(), excluded_paths=()) -> list[Path]:
    pending, result = [root], []
    while pending:
        for path in sorted(pending.pop().iterdir()):
            if path in excluded_paths:
                continue
            no_links(path)
            if path.is_dir():
                if path.name not in ignore_dirs:
                    pending.append(path)
            elif path.is_file():
                result.append(path)
            else:
                raise BuildError("NON_REGULAR_RESOURCE")
    return sorted(result)


def inventory_tree(root: Path, *, ignore_dirs=()) -> dict:
    root = safe_root(root)
    rows = []
    for path in walk_files(root, ignore_dirs=ignore_dirs):
        name = safe_relative(path.relative_to(root).as_posix())
        if private_name(name):
            raise BuildError("PRIVATE_FILE")
        rows.append(hash_file(path, name))
        if len(rows) > 100_000:
            raise BuildError("RESOURCE_FILE_COUNT_LIMIT")
    return {
        "files": rows,
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "content_sha256": digest(rows),
    }


def verify_external_runtime_bundle(source_root: Path, backend_root: Path) -> dict:
    """Bind standalone workers and prove heavy model payloads remain external."""

    source_root = safe_root(source_root)
    backend_root = safe_root(backend_root)
    for path in walk_files(backend_root):
        name = safe_relative(path.relative_to(backend_root).as_posix())
        parts = name.casefold().split("/")
        package_found = any(
            part == package
            or part.startswith(package + "-")
            or part.startswith(package + ".")
            for part in parts
            for package in FORBIDDEN_BUNDLED_MODEL_PACKAGES
        )
        leaf = parts[-1]
        native_suffix = leaf.endswith(FORBIDDEN_BUNDLED_NATIVE_MODEL_SUFFIXES)
        native_runtime_found = native_suffix and (
            any(
                token in leaf
                for token in FORBIDDEN_BUNDLED_NATIVE_MODEL_TOKENS
            )
            or leaf == "c10.dll"
            or leaf.startswith("c10_")
        )
        if (
            package_found
            or name.casefold().endswith(FORBIDDEN_BUNDLED_MODEL_SUFFIXES)
            or native_runtime_found
        ):
            raise BuildError("BUNDLED_MODEL_RUNTIME_FORBIDDEN")

    resources = []
    for source_name, packaged_name in EXTERNAL_RUNTIME_RESOURCES:
        source = hash_file(
            safe_file(source_root, source_name),
            source_name,
        )
        packaged = hash_file(
            safe_file(backend_root, packaged_name),
            packaged_name,
        )
        if (source["size"], source["sha256"]) != (
            packaged["size"],
            packaged["sha256"],
        ):
            raise BuildError("PACKAGED_STANDALONE_RESOURCE_DRIFT")
        resources.append(
            {
                "source_path": source_name,
                "packaged_path": packaged_name,
                "size": source["size"],
                "sha256": source["sha256"],
                "source_matches_packaged": True,
            }
        )
    return {
        "status": "PASS",
        "capability": "EXTERNAL_RUNTIME_REQUIRED",
        "resources": resources,
        "model_pack_bundled": False,
        "torch_bundled": False,
        "torchvision_bundled": False,
        "ultralytics_bundled": False,
        "yolo_weights_bundled": False,
        "production_release_allowed": False,
    }


def write_json_new(path: Path, value) -> None:
    no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
            ).encode("utf-8")
            + b"\n"
        )


def read_json(path: Path):
    no_links(path)
    return json.loads(path.read_text(encoding="utf-8"))


def git_state(authority: Path) -> tuple[dict, set[str]]:
    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(authority), *args], capture_output=True, check=False
        )
        if result.returncode:
            raise BuildError("AUTHORITY_GIT_STATE_UNAVAILABLE")
        return result.stdout

    tracked = {
        name.decode("utf-8")
        for name in git("ls-files", "-z", "--cached").split(b"\0")
        if name
    }
    state = {
        "head": git("rev-parse", "HEAD").decode().strip(),
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "branch": git("branch", "--show-current").decode().strip(),
        "dirty": bool(git("status", "--porcelain=v1", "--untracked-files=normal")),
    }
    return state, tracked


def source_names(root: Path) -> set[str]:
    names = set(REQUIRED_INPUTS)
    names.update("src/" + name.replace(".", "/") + ".py" for name in RUNTIME_MODULES)
    for tree in SOURCE_TREES:
        directory = root / tree
        if not directory.exists():
            continue
        no_links(directory)
        if not directory.is_dir():
            raise BuildError("SOURCE_TREE_NOT_DIRECTORY")
        for path in walk_files(
            directory,
            ignore_dirs=IGNORE_DIRS,
            excluded_paths={
                root / name.rstrip("/") for name in EXCLUDED_SOURCE_SUBTREES
            },
        ):
            name = path.relative_to(root).as_posix()
            if any(
                part.endswith((".egg-info", ".dist-info"))
                for part in path.relative_to(directory).parts
            ):
                continue
            if path.suffix in {".pyc", ".pyo"}:
                continue
            if private_name(name):
                raise BuildError("PRIVATE_FILE")
            names.add(safe_relative(name))
    return names


def copy_verified(source: Path, destination: Path, row: dict) -> None:
    no_links(source)
    no_links(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise BuildError("COPY_DESTINATION_EXISTS")
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
    if (
        hash_file(destination, row["path"]) != row
        or hash_file(source, row["path"]) != row
    ):
        raise BuildError("COPY_SOURCE_DRIFT")


def freeze_sources(authority: Path, staging: Path) -> dict:
    authority = safe_root(authority)
    staging = Path(os.path.abspath(staging))
    no_links(staging)
    if staging.exists():
        raise BuildError("STAGING_EXISTS")
    safe_root(staging.parent)
    state, tracked = git_state(authority)
    names = sorted(source_names(authority))
    rows = []
    for name in names:
        if not (authority / name).is_file():
            raise BuildError("REQUIRED_SOURCE_MISSING: " + name)
        code_addition = (
            name.startswith(UNTRACKED_CODE_TREES)
            and Path(name).suffix in UNTRACKED_CODE_SUFFIXES
        )
        if (
            name not in tracked
            and name not in REQUIRED_INPUTS
            and name not in EXPLICIT_ADDITIONS
            and not code_addition
        ):
            raise BuildError("UNALLOWLISTED_RESOURCE: " + name)
        if private_name(name):
            raise BuildError("PRIVATE_FILE")
        rows.append(hash_file(safe_file(authority, name), name))
    manifest = {
        "schema_version": "visiondata-gate.authority-build-source.v1",
        "authority": state,
        "scope": "EXPLICIT_AUTHORITY_SOURCE_AND_RUNTIME_RESOURCE_ALLOWLIST",
        "original_public_ci_artifact": False,
        "files": rows,
        "source_content_sha256": digest(rows),
        "untracked_allowlisted_inputs": sorted(set(names) - tracked),
        "dependency_bytes_are_source": False,
        "excluded_subtrees": [
            {"path": path, "reason": reason}
            for path, reason in EXCLUDED_SOURCE_SUBTREES.items()
        ],
        "production_release_allowed": False,
    }
    staging.mkdir()
    (staging / "source").mkdir()
    for row in rows:
        copy_verified(authority / row["path"], staging / "source" / row["path"], row)
    write_json_new(staging / "evidence/SOURCE_MANIFEST.json", manifest)
    verify_frozen(staging)
    return manifest


def verify_frozen(staging: Path) -> dict:
    staging = safe_root(staging)
    manifest = read_json(staging / "evidence/SOURCE_MANIFEST.json")
    if manifest.get("schema_version") != "visiondata-gate.authority-build-source.v1":
        raise BuildError("SOURCE_MANIFEST_SCHEMA")
    rows = manifest["files"]
    if digest(rows) != manifest["source_content_sha256"]:
        raise BuildError("SOURCE_MANIFEST_DIGEST")
    expected = {row["path"] for row in rows}
    if source_names(staging / "source") != expected:
        raise BuildError("SOURCE_FILE_SET")
    for row in rows:
        if hash_file(safe_file(staging / "source", row["path"]), row["path"]) != row:
            raise BuildError("SOURCE_DRIFT: " + row["path"])
    return manifest


def tauri_cache_destination(staging: Path) -> Path:
    # Tauri's Windows known-folder resolver derives this from USERPROFILE;
    # setting LOCALAPPDATA to an unrelated directory does not redirect it.
    return staging / "build/user-profile/AppData/Local/tauri"


def build_environment(staging: Path, tools: dict, original=None) -> dict[str, str]:
    original = os.environ if original is None else original
    env = {key: original[key] for key in ENV_KEYS if key in original}
    paths = [
        str(Path(tools[key]).parent)
        for key in ("python", "node", "npm", "cargo", "java")
        if key in tools
    ]
    system = env.get("SystemRoot", env.get("SYSTEMROOT", ""))
    if system:
        paths.extend([str(Path(system) / "System32"), system])
    env.update(
        {
            "PATH": os.pathsep.join(dict.fromkeys(paths)),
            "TEMP": str(staging / "build/temp"),
            "TMP": str(staging / "build/temp"),
            "LOCALAPPDATA": str(tauri_cache_destination(staging).parent),
            "APPDATA": str(staging / "build/user-profile/AppData/Roaming"),
            "USERPROFILE": str(staging / "build/user-profile"),
            "PYTHONPATH": str(staging / "source/src"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPYCACHEPREFIX": str(staging / "build/pycache"),
            "PYINSTALLER_CONFIG_DIR": str(staging / "build/pyinstaller-cache"),
            "CARGO_TARGET_DIR": str(staging / "build/cargo-target"),
            "CARGO_NET_OFFLINE": "true",
            "NPM_CONFIG_USERCONFIG": str(staging / "build/empty.npmrc"),
            "NPM_CONFIG_GLOBALCONFIG": str(staging / "build/empty-global.npmrc"),
            "NPM_CONFIG_CACHE": str(staging / "build/npm-cache"),
            "NPM_CONFIG_OFFLINE": "true",
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
            "VISIONDATA_PRODUCT_ROOT": str(staging / "build/analysis-product"),
            "VISIONDATA_RESOURCE_ROOT": str(staging / "source"),
            "VISIONDATA_AGENTTEAMS_MODE": "off",
            "VISIONDATA_INCIDENT_MODEL_MODE": "off",
            "VISIONDATA_PRODUCT_MODEL_KEYS_ENABLED": "false",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "CI": "true",
        }
    )
    if "java" in tools:
        env["JAVA_HOME"] = str(Path(tools["java"]).parent.parent)
    if "cargo_home" in tools:
        env["CARGO_HOME"] = str(tools["cargo_home"])
    if "rustc" in tools:
        env["RUSTC"] = str(tools["rustc"])
    remaps = [(staging, "build")]
    if "cargo_home" in tools:
        remaps.append((Path(tools["cargo_home"]), "cargo-cache"))
    if "rustc" in tools:
        remaps.append((Path(tools["rustc"]).parent.parent, "rust-toolchain"))
    # Compile-time panic/source locations must not retain the builder's profile.
    # Encoded arguments preserve paths containing spaces without shell quoting.
    flags = []
    for path, label in remaps:
        for spelling in dict.fromkeys((str(path), path.as_posix())):
            flags.append(f"--remap-path-prefix={spelling}={label}")
    env["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(flags)
    env["RUSTUP_AUTO_INSTALL"] = "0"
    return env


def build_commands(staging: Path, tools: dict) -> list[dict]:
    source = staging / "source"
    settings = staging / "build/maven-settings.xml"
    commands = [
        (
            "MAVEN_PACKAGE",
            source / "gateway",
            [
                str(tools["java"]),
                "-Dfile.encoding=UTF-8",
                f"-Dmaven.home={tools['maven_home']}",
                f"-Dmaven.multiModuleProjectDirectory={source / 'gateway'}",
                f"-Dclassworlds.conf={Path(tools['maven_home']) / 'bin/m2.conf'}",
                "-classpath",
                str(tools["maven_launcher"]),
                "org.codehaus.plexus.classworlds.launcher.Launcher",
                "--offline",
                "-s",
                str(settings),
                "-gs",
                str(settings),
                "-f",
                str(source / "gateway/pom.xml"),
                "package",
            ],
            600,
        ),
        (
            "JLINK_RUNTIME",
            source,
            [
                str(tools["jlink"]),
                "--add-modules",
                ",".join(JLINK_MODULES),
                "--bind-services",
                "--strip-debug",
                "--no-header-files",
                "--no-man-pages",
                "--compress=2",
                "--output",
                str(source / "gateway/runtime"),
            ],
            240,
        ),
        (
            "PYINSTALLER_BACKEND",
            source,
            [
                str(tools["python"]),
                "-m",
                "PyInstaller",
                "--distpath",
                str(source / "desktop/dist"),
                "--workpath",
                str(staging / "build/pyinstaller"),
                str(source / "desktop/visiondata_gate_backend.spec"),
            ],
            900,
        ),
        (
            "TAURI_NSIS",
            source / "web",
            [
                str(tools["node"]),
                str(source / "web/node_modules/@tauri-apps/cli/tauri.js"),
                "build",
                "--ci",
                "--bundles",
                "nsis",
                "--no-sign",
                "--runner",
                str(tools["cargo"]),
                "--",
                "--locked",
                "--offline",
            ],
            2400,
        ),
    ]
    return [
        {"name": name, "cwd": str(cwd), "argv": argv, "timeout_seconds": timeout}
        for name, cwd, argv, timeout in commands
    ]


def verify_learning_names(names) -> dict:
    missing = sorted(set(LEARNING_MODULES) - set(names))
    if missing:
        raise BuildError("LEARNING_MODULES_MISSING: " + ",".join(missing))
    return {
        "status": "PASS",
        "required_modules": list(LEARNING_MODULES),
        "verified_in": "PYINSTALLER_PYZ_ARCHIVE",
    }


def verify_runtime_names(names) -> dict:
    missing = sorted(set(RUNTIME_MODULES) - set(names))
    if missing:
        raise BuildError("RUNTIME_MODULES_MISSING: " + ",".join(missing))
    return {
        "status": "PASS",
        "required_modules": list(RUNTIME_MODULES),
        "verified_in": "PYINSTALLER_PYZ_ARCHIVE",
    }


def validate_rust_toolchain(cargo: Path) -> dict:
    cargo = Path(cargo).resolve(strict=True)
    rustc = cargo.with_name("rustc.exe")
    cargo_sha = hash_file(cargo, "cargo.exe")["sha256"]
    shim = cargo.with_name("rustup.exe")
    if shim.is_file() and hash_file(shim, "rustup.exe")["sha256"] == cargo_sha:
        raise BuildError("RUSTUP_SHIM_NOT_ALLOWED")
    if not rustc.is_file():
        raise BuildError("EXPLICIT_INSTALLED_RUST_TOOLCHAIN_REQUIRED")
    if hash_file(rustc, "rustc.exe")["sha256"] == cargo_sha:
        raise BuildError("RUSTUP_SHIM_NOT_ALLOWED")
    return {"cargo": cargo, "rustc": rustc}


def _code_value(value):
    if isinstance(value, types.CodeType):
        fields = (
            "co_argcount",
            "co_posonlyargcount",
            "co_kwonlyargcount",
            "co_nlocals",
            "co_stacksize",
            "co_flags",
            "co_code",
            "co_consts",
            "co_names",
            "co_varnames",
            "co_freevars",
            "co_cellvars",
            "co_name",
            "co_qualname",
            "co_firstlineno",
            "co_linetable",
            "co_exceptiontable",
        )
        return {name: _code_value(getattr(value, name)) for name in fields}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, (tuple, list)):
        return [_code_value(item) for item in value]
    if isinstance(value, frozenset):
        return {
            "frozenset": sorted((_code_value(item) for item in value), key=canonical)
        }
    if isinstance(value, float):
        return {"float": value.hex()}
    if isinstance(value, complex):
        return {"complex": [value.real.hex(), value.imag.hex()]}
    if value is Ellipsis:
        return {"ellipsis": True}
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise BuildError("PYZ_UNSUPPORTED_CONSTANT_TYPE")


def verify_compiled_source(code, source_path: Path, source_root: Path) -> dict:
    if not isinstance(code, types.CodeType):
        raise BuildError("PYZ_CODE_OBJECT_REQUIRED")
    source_root = safe_root(source_root)
    source_path = source_path.resolve(strict=True)
    if not source_path.is_relative_to(source_root):
        raise BuildError("STAGED_SOURCE_PATH")
    filename = Path(code.co_filename)
    if filename.is_absolute():
        if not filename.resolve().is_relative_to(source_root):
            raise BuildError("PYZ_FILENAME_OUTSIDE_STAGED_SOURCE")
        display_filename = (
            "staged-src/" + filename.resolve().relative_to(source_root).as_posix()
        )
    else:
        display_filename = code.co_filename.replace("\\", "/")
        safe_relative(display_filename)
    source_bytes = source_path.read_bytes()
    expected = compile(
        source_bytes, str(source_path), "exec", dont_inherit=True, optimize=1
    )
    actual_digest = digest(_code_value(code))
    if actual_digest != digest(_code_value(expected)):
        raise BuildError("PYZ_STAGED_SOURCE_MISMATCH")
    return {
        "co_filename": display_filename,
        "matched_staged_source": True,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "canonical_code_sha256": actual_digest,
        "comparison": "ALL_CODE_FIELDS_EXCEPT_FILENAME_WITH_RECURSIVE_CONSTANTS_OPTIMIZE_1",
    }


def inspect_archive(executable: Path, source_root: Path | None = None) -> dict:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    name = next(key for key in archive.toc if key.endswith(".pyz"))
    pyz = archive.open_embedded_archive(name)
    result = verify_runtime_names(pyz.toc)
    if source_root is not None:
        result["staged_source_code_checks"] = [
            {
                "module": module,
                **verify_compiled_source(
                    pyz.extract(module),
                    source_root / (module.replace(".", "/") + ".py"),
                    source_root,
                ),
            }
            for module in RUNTIME_MODULES
        ]
    else:
        result["staged_source_code_checks"] = "NOT_REQUESTED_ARTIFACT_HASH_BINDING_ONLY"
    return result


def verify_archive(
    python: Path, executable: Path, staging: Path, environment: dict
) -> dict:
    staged_source = staging / "source/src"
    arguments = [
        str(python),
        "-B",
        str(Path(__file__).resolve()),
        "archive",
        "--executable",
        str(executable),
    ]
    if staged_source.is_dir():
        arguments += ["--source-root", str(staged_source)]
    completed = subprocess.run(
        arguments,
        cwd=staging,
        env=environment,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode:
        raise BuildError("PYINSTALLER_ARCHIVE_INSPECTION_FAILED")
    result = json.loads(completed.stdout)
    verify_runtime_names(result["required_modules"])
    return result


def _dependency_inventory(root: Path) -> tuple[dict, dict]:
    rows, links, source_files = [], [], {}
    pending = [("", root, frozenset({root}))]
    while pending:
        prefix, directory, ancestors = pending.pop()
        for entry in sorted(directory.iterdir()):
            if entry.name in IGNORE_DIRS:
                continue
            name = safe_relative(prefix + entry.name)
            info = entry.lstat()
            is_link = stat.S_ISLNK(info.st_mode) or bool(
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
            if is_link:
                resolved = entry.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    raise BuildError("DEPENDENCY_LINK_OUTSIDE_ROOT")
                if not resolved.is_dir():
                    raise BuildError("DEPENDENCY_FILE_LINK_NOT_ALLOWED")
                no_links(resolved)
                if resolved in ancestors:
                    raise BuildError("DEPENDENCY_LINK_CYCLE")
                links.append(
                    {"path": name, "target": resolved.relative_to(root).as_posix()}
                )
                pending.append((name + "/", resolved, ancestors | {resolved}))
            elif entry.is_dir():
                pending.append((name + "/", entry, ancestors | {entry}))
            elif entry.is_file():
                if private_name(name):
                    raise BuildError("PRIVATE_FILE")
                rows.append(hash_file(entry, name))
                source_files[name] = entry
                if len(rows) > 100_000:
                    raise BuildError("DEPENDENCY_FILE_COUNT_LIMIT")
            else:
                raise BuildError("NON_REGULAR_DEPENDENCY")
    rows.sort(key=lambda row: row["path"])
    return {
        "files": rows,
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "content_sha256": digest(rows),
        "internal_directory_links_materialized": sorted(
            links, key=lambda row: row["path"]
        ),
    }, source_files


def copy_dependency_tree(
    source: Path, target: Path, *, materialize_internal_links=False
) -> dict:
    source = tool_root(source)
    if materialize_internal_links:
        inventory, source_files = _dependency_inventory(source)
    else:
        inventory = inventory_tree(source, ignore_dirs=IGNORE_DIRS)
        source_files = {row["path"]: source / row["path"] for row in inventory["files"]}
    if inventory["total_bytes"] > 8 * 1024**3:
        raise BuildError("DEPENDENCY_SIZE_LIMIT")
    target.mkdir(parents=True, exist_ok=False)
    print(
        json.dumps(
            {
                "step": "DEPENDENCY_COPY",
                "file_count": inventory["file_count"],
                "total_bytes": inventory["total_bytes"],
            }
        ),
        flush=True,
    )
    for row in inventory["files"]:
        copy_verified(source_files[row["path"]], target / row["path"], row)
    return inventory


def run_step(step: dict, staging: Path, environment: dict) -> dict:
    cwd = safe_root(Path(step["cwd"]))
    if not cwd.is_relative_to(staging):
        raise BuildError("BUILD_CWD_OUTSIDE_STAGING")
    logfile = staging / "build/logs" / (step["name"] + ".log")
    logfile.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    print(json.dumps({"step": step["name"], "status": "STARTING"}), flush=True)
    with logfile.open("xb") as stream:
        completed = subprocess.run(
            step["argv"],
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=step["timeout_seconds"],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
    receipt = {
        "step": step["name"],
        "exit_code": completed.returncode,
        "elapsed_seconds": time.monotonic() - started,
        "local_log_sha256": hash_file(logfile, logfile.name)["sha256"],
    }
    write_json_new(staging / "evidence" / (step["name"] + ".json"), receipt)
    if completed.returncode:
        raise BuildError(step["name"] + "_FAILED")
    return receipt


def bind_artifacts(staging: Path, source_manifest: dict, modules: dict) -> dict:
    source = staging / "source"
    installers = sorted(
        (staging / "build/cargo-target/release/bundle/nsis").glob("*.exe")
    )
    if len(installers) != 1:
        raise BuildError("ONE_NEW_NSIS_INSTALLER_REQUIRED")
    installer = installers[0]
    jar = source / "gateway/target/visiondata-gate-gateway.jar"
    external_runtime_model = verify_external_runtime_bundle(
        source,
        source / "desktop/dist/visiondata-gate-backend",
    )
    libraries = []
    with zipfile.ZipFile(jar) as archive:
        for name in sorted(archive.namelist()):
            if name.startswith("BOOT-INF/lib/") and name.endswith(".jar"):
                data = archive.read(name)
                libraries.append(
                    {
                        "path": name,
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
    record = {
        "schema_version": "visiondata-gate.staged-learning-build.v1",
        "status": "BUILD_COMPLETE_VALIDATION_PENDING",
        "runtime_architecture": "TAURI_SPRING_WEBFLUX_FASTAPI",
        "source_content_sha256": source_manifest["source_content_sha256"],
        "learning_module_archive_check": modules,
        "external_runtime_model_capability": external_runtime_model,
        "artifacts": {
            "frontend_dist": inventory_tree(source / "web/dist"),
            "backend": inventory_tree(source / "desktop/dist/visiondata-gate-backend"),
            "gateway_jar": hash_file(jar, "gateway/visiondata-gate-gateway.jar"),
            "gateway_dependency_jars": libraries,
            "java_runtime": inventory_tree(source / "gateway/runtime"),
            "tauri_executable": hash_file(
                staging / "build/cargo-target/release/visiondata-gate-desktop.exe",
                "visiondata-gate-desktop.exe",
            ),
            "installer": hash_file(installer, installer.name),
            "sample_data": inventory_tree(source / "sample_data"),
            "config_template": hash_file(
                source / "desktop/default.env.example", "config/.env.example"
            ),
            "legal": [
                hash_file(source / name, "legal/" + name)
                for name in ("LICENSE", "NOTICE")
            ],
        },
        "code_signed": False,
        "production_release_allowed": False,
        "packaged_learning_validation": "NOT_RUN",
        "native_gui_validation": "NOT_RUN",
        "installer_install_validation": "NOT_RUN",
        "clean_machine_validation": "NOT_RUN",
        "remote_execution_verified": False,
    }
    delivery = staging / "deliverables"
    delivery.mkdir(exist_ok=False)
    copy_verified(
        installer, delivery / installer.name, record["artifacts"]["installer"]
    )
    write_json_new(staging / "evidence/BUILD_MANIFEST.json", record)
    # Keep source/build identity beside the installer. Copying deliverables must
    # not silently detach the executable from its frozen source and HOLD gates.
    write_json_new(delivery / "BUILD_MANIFEST.json", record)
    write_json_new(delivery / "SOURCE_MANIFEST.json", source_manifest)
    write_json_new(
        delivery / "DELIVERY_STATUS.json",
        {
            "schema_version": "visiondata-gate.build-delivery-status.v1",
            "status": record["status"],
            "installer_sha256": record["artifacts"]["installer"]["sha256"],
            "source_content_sha256": source_manifest["source_content_sha256"],
            "scope": "INTERNAL_PREVIEW_REVIEW_BEFORE_PUBLIC_DISTRIBUTION",
            "production_release_allowed": False,
            "code_signed": False,
            "validation": {
                "packaged_learning": "NOT_RUN",
                "native_gui": "NOT_RUN",
                "installer_install": "NOT_RUN",
                "clean_machine": "NOT_RUN",
            },
        },
    )
    with (delivery / "SHA256SUMS.txt").open(
        "x", encoding="utf-8", newline="\n"
    ) as sums:
        for member in sorted(delivery.iterdir()):
            if member.name != "SHA256SUMS.txt":
                sums.write(
                    f"{hash_file(member, member.name)['sha256']}  {member.name}\n"
                )
    return record


def build_staging(
    staging: Path, tools: dict, node_modules: Path, tauri_cache: Path
) -> dict:
    staging = safe_root(staging)
    source_manifest = verify_frozen(staging)
    if (staging / "build").exists():
        raise BuildError("BUILD_ATTEMPT_EXISTS_USE_NEW_STAGING")
    (staging / "build").mkdir()
    for name in ("temp", "localappdata", "appdata", "analysis-product", "user-profile"):
        (staging / "build" / name).mkdir()
    tauri_cache_destination(staging).parent.mkdir(parents=True, exist_ok=True)
    (staging / "build/user-profile/AppData/Roaming").mkdir(parents=True, exist_ok=True)
    for name in ("empty.npmrc", "empty-global.npmrc"):
        (staging / "build" / name).write_bytes(
            b"# isolated build; no user credentials\n"
        )
    from xml.sax.saxutils import escape

    repository = tool_root(Path(tools["maven_repository"]))
    settings = (
        '<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"><localRepository>'
        + escape(str(repository))
        + "</localRepository><offline>true</offline></settings>\n"
    )
    with (staging / "build/maven-settings.xml").open("x", encoding="utf-8") as stream:
        stream.write(settings)
    tool_records = []
    for key, value in tools.items():
        path = Path(value).resolve(strict=True)
        if path.is_file():
            tool_records.append({"role": key, **hash_file(path, path.name)})
    write_json_new(
        staging / "evidence/TOOL_INPUTS.json",
        {
            "files": tool_records,
            "content_sha256": digest(tool_records),
            "scope": "EXPLICIT_EXECUTABLE_AND_LAUNCHER_INPUTS_NOT_ALL_TRANSITIVE_COMPILER_BYTES",
        },
    )
    node_inventory = copy_dependency_tree(
        node_modules,
        staging / "source/web/node_modules",
        materialize_internal_links=True,
    )
    # Verify every installed package represented in the locked dependency graph.
    lock = read_json(staging / "source/web/package-lock.json")
    for name, item in lock.get("packages", {}).items():
        if not name.startswith("node_modules/") or not item.get("version"):
            continue
        package = staging / "source/web" / name / "package.json"
        if package.exists() and read_json(package).get("version") != item["version"]:
            raise BuildError("NODE_DEPENDENCY_LOCK_VERSION_MISMATCH")
    write_json_new(staging / "evidence/NODE_DEPENDENCY_INPUTS.json", node_inventory)
    cache = tool_root(tauri_cache)
    safe_file(cache, "NSIS/makensis.exe")
    safe_file(cache, "NSIS/Plugins/x86-unicode/additional/nsis_tauri_utils.dll")
    nsis_inventory = copy_dependency_tree(
        cache / "NSIS", tauri_cache_destination(staging) / "NSIS"
    )
    bootstrap = safe_file(cache, "MicrosoftEdgeWebview2Setup.exe")
    bootstrap_row = hash_file(bootstrap, bootstrap.name)
    copy_verified(
        bootstrap, tauri_cache_destination(staging) / bootstrap.name, bootstrap_row
    )
    write_json_new(
        staging / "evidence/NSIS_TOOL_INPUTS.json",
        {"nsis": nsis_inventory, "webview_bootstrapper": bootstrap_row},
    )
    env = build_environment(staging, tools)
    steps = []
    modules = None
    for step in build_commands(staging, tools):
        verify_frozen(staging)
        steps.append(run_step(step, staging, env))
        if step["name"] == "PYINSTALLER_BACKEND":
            modules = verify_archive(
                Path(tools["python"]),
                staging
                / "source/desktop/dist/visiondata-gate-backend/visiondata-gate-backend.exe",
                staging,
                env,
            )
            write_json_new(staging / "evidence/LEARNING_MODULE_ARCHIVE.json", modules)
    verify_frozen(staging)
    if modules is None:
        raise BuildError("LEARNING_ARCHIVE_VALIDATION_NOT_RUN")
    result = bind_artifacts(staging, source_manifest, modules)
    write_json_new(staging / "evidence/BUILD_STEPS.json", {"steps": steps})
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser(
        "freeze",
        help="Explicitly freeze current authority source into a new staging root",
    )
    freeze.add_argument("--authority", type=Path, required=True)
    freeze.add_argument("--staging", type=Path, required=True)
    build = commands.add_parser(
        "build",
        help="Build an existing frozen staging tree exactly once; never installs",
    )
    build.add_argument("--staging", type=Path, required=True)
    for name in (
        "python",
        "node",
        "npm",
        "cargo",
        "jdk-home",
        "maven-home",
        "maven-repository",
        "node-modules",
        "tauri-cache",
    ):
        build.add_argument("--" + name, type=Path, required=True)
    build.add_argument("--cargo-home", type=Path)
    archive = commands.add_parser(
        "archive",
        help="Read-only PYZ membership and optional staged-source code-object comparison",
    )
    archive.add_argument("--executable", type=Path, required=True)
    archive.add_argument("--source-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            result = freeze_sources(args.authority, args.staging)
            print(
                json.dumps(
                    {
                        "status": "SOURCE_FROZEN_BUILD_NOT_RUN",
                        "source_content_sha256": result["source_content_sha256"],
                        "file_count": len(result["files"]),
                    }
                )
            )
        elif args.command == "archive":
            print(
                json.dumps(
                    inspect_archive(args.executable, args.source_root), sort_keys=True
                )
            )
        else:
            jdk, maven = tool_root(args.jdk_home), tool_root(args.maven_home)
            launchers = list((maven / "boot").glob("plexus-classworlds-*.jar"))
            if len(launchers) != 1:
                raise BuildError("MAVEN_LAUNCHER_REQUIRED")
            tools = {
                key: getattr(args, key).resolve(strict=True)
                for key in ("python", "node", "npm", "cargo", "maven_repository")
            }
            tools.update(validate_rust_toolchain(tools["cargo"]))
            tools.update(
                java=safe_file(jdk, "bin/java.exe"),
                jlink=safe_file(jdk, "bin/jlink.exe"),
                maven_home=maven,
                maven_launcher=launchers[0],
            )
            if args.cargo_home:
                tools["cargo_home"] = tool_root(args.cargo_home)
            else:
                raise BuildError("EXPLICIT_CARGO_HOME_REQUIRED")
            result = build_staging(
                args.staging, tools, args.node_modules, args.tauri_cache
            )
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "installer_sha256": result["artifacts"]["installer"]["sha256"],
                        "packaged_learning_validation": "NOT_RUN",
                    }
                )
            )
        return 0
    except (BuildError, OSError, subprocess.TimeoutExpired, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "HOLD",
                    "error_code": str(error)
                    if isinstance(error, BuildError)
                    else type(error).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
