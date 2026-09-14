from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path.cwd().resolve()
source_root = project_root / "src"
entrypoint = project_root / "desktop" / "backend_main.py"

# Reviewer evidence is deliberately allowlisted file-by-file.  Do not replace
# this with the whole 10_reports directory: most reports are development-only
# material and are not runtime dependencies of the desktop sidecar.
FROZEN_EVALUATION_REPORT_NAMES = (
    "DYNAMICBENCH_V3_REPLANNING_20260829.json",
    "DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json",
)
frozen_evaluation_report_datas = [
    (
        str((project_root / "10_reports" / report_name).resolve(strict=True)),
        "10_reports",
    )
    for report_name in FROZEN_EVALUATION_REPORT_NAMES
]

datas = [
    (str(project_root / "examples"), "examples"),
    (str(project_root / "rulepacks"), "rulepacks"),
    (str(project_root / "schemas"), "schemas"),
    # The optional external Python executes this reviewed standalone source by
    # __file__; keeping only its PYZ bytecode would make probe/train unavailable.
    (str(source_root / "visiondata_gate/learning_yolo_backend.py"), "visiondata_gate"),
    # Normality inference follows the same boundary: the packaged FastAPI
    # process never imports Torch or deserializes a model pack.  An explicitly
    # registered external runtime executes this exact reviewed source file.
    (str(source_root / "visiondata_gate/normality_inference.py"), "visiondata_gate"),
    # The v4 stability contract hashes these exact reviewed source files while
    # rebuilding the three-run evidence inside the packaged backend.  PYZ
    # bytecode alone does not create an on-disk __file__ for that hash step.
    (str(source_root / "visiondata_gate/model_stability.py"), "visiondata_gate"),
    (str(source_root / "visiondata_gate/model_experiment_agent.py"), "visiondata_gate"),
    (str(project_root / "docs/WINDOWS_INSTALLER.md"), "docs"),
    (str(project_root / "docs/THIRD_PARTY_NOTICES.md"), "docs"),
    (str(project_root / "docs/SBOM.cdx.json"), "docs"),
    *frozen_evaluation_report_datas,
]

hiddenimports = sorted(
    set(collect_submodules("visiondata_gate") + collect_submodules("uvicorn"))
)

a = Analysis(
    [str(entrypoint)],
    pathex=[str(source_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pandas", "pytest", "streamlit", "torch", "torchvision", "ultralytics"],
    noarchive=False,
    optimize=1,
)
# PEP 610 local/editable installation origins describe this build machine, not
# runtime dependencies. Retain METADATA, RECORD and all legal/license files.
a.datas = [
    entry for entry in a.datas
    if not (
        ".dist-info/" in entry[0].replace("\\", "/").lower()
        and entry[0].replace("\\", "/").lower().endswith("/direct_url.json")
    )
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="visiondata-gate-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="visiondata-gate-backend",
)
