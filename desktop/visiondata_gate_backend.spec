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
    excludes=["pandas", "pytest", "streamlit"],
    noarchive=False,
    optimize=1,
)
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
