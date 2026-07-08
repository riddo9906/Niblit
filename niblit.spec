# -*- mode: python ; coding: utf-8 -*-
"""
niblit.spec — PyInstaller build specification for the complete Niblit system.

Produces a one-folder Windows bundle:

    dist/niblit/
    ├── niblit.exe                  ← entry point (run this to start everything)
    ├── niblit-ui.exe               ← Tauri UI executable (staged by niblit-build.js)
    ├── cloud/                      ← Cloud-server bundle (staged by niblit-build.js)
    │   └── niblit-cloud.exe
    ├── lean-algos/                 ← Lean-algos bridge + algorithms
    │   ├── niblit_bridge/
    │   └── algorithms/
    └── <Python deps & modules>

Build via the npm script (preferred — validates all repos and stages sidecars first):
    npm run build

Or directly, after staging cloud/ and niblit-ui.exe into dist/:
    pyinstaller niblit.spec
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(SPECPATH)  # directory containing this .spec file

# Pre-staged artefacts placed by niblit-build.js before PyInstaller runs.
# These paths are under dist/ (a sibling of this spec in REPO_ROOT).
STAGED_CLOUD_DIR = REPO_ROOT / "dist" / "_staged" / "cloud"
STAGED_TAURI_EXE = REPO_ROOT / "dist" / "_staged" / "niblit-ui.exe"

# niblit-lean-algos is already a subdirectory inside the niblit repo.
LEAN_ALGOS_ROOT = REPO_ROOT / "niblit-lean-algos"

# ---------------------------------------------------------------------------
# Data files bundled into the package
# ---------------------------------------------------------------------------

datas = []

# Lean-algos bridge (Python package) and algorithm source files.
# These are NOT copied into the Python package; they live in the bundle as
# data so niblit.exe can reference them at the well-known relative paths:
#   <bundle>/lean-algos/niblit_bridge/
#   <bundle>/lean-algos/algorithms/
if LEAN_ALGOS_ROOT.is_dir():
    bridge_dir = LEAN_ALGOS_ROOT / "niblit_bridge"
    algos_dir = LEAN_ALGOS_ROOT / "algorithms"
    lean_json = LEAN_ALGOS_ROOT / "lean.json"
    if bridge_dir.is_dir():
        datas += [(str(bridge_dir), "lean-algos/niblit_bridge")]
    if algos_dir.is_dir():
        datas += [(str(algos_dir), "lean-algos/algorithms")]
    if lean_json.is_file():
        datas += [(str(lean_json), "lean-algos")]

# Environment template shipped with the bundle.
env_example = REPO_ROOT / ".env.example"
if env_example.is_file():
    datas += [(str(env_example), ".")]

# Runtime profile env files (niblit.env, cloud-server.env, etc.)
profiles_dir = REPO_ROOT / "tools" / "runtime_profiles"
if profiles_dir.is_dir():
    datas += [(str(profiles_dir), "tools/runtime_profiles")]

# Pre-staged cloud-server one-folder bundle placed by niblit-build.js.
# At runtime this is found at <bundle_base>/cloud/niblit-cloud.exe.
if STAGED_CLOUD_DIR.is_dir():
    datas += [(str(STAGED_CLOUD_DIR), "cloud")]

# Pre-staged Tauri UI executable placed by niblit-build.js.
# At runtime this is found at <bundle_base>/niblit-ui.exe.
if STAGED_TAURI_EXE.is_file():
    datas += [(str(STAGED_TAURI_EXE), ".")]

# ---------------------------------------------------------------------------
# Hidden imports — modules discovered at runtime via dynamic import
# ---------------------------------------------------------------------------

hiddenimports = [
    # HTTP server layer
    "uvicorn",
    "uvicorn.main",
    "uvicorn.config",
    "uvicorn.lifespan.off",
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.logging",
    "fastapi",
    "starlette",
    "starlette.middleware",
    "starlette.routing",
    # Niblit runtime modules imported dynamically
    "server",
    "modules.niblit_ui_launcher",
    "modules.runtime_bootstrap",
    "modules.resilient_boot",
    "modules.structured_logging",
    # Optional heavy imports that PyInstaller misses
    "email.mime.text",
    "email.mime.multipart",
    "pkg_resources.py2_warn",
]

# Sweep every sub-package to catch dynamic imports inside modules.
for _pkg in ("modules", "core", "agents", "niblit_memory", "nibblebots", "niblit_core"):
    hiddenimports += collect_submodules(_pkg)

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    [str(REPO_ROOT / "main.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy GUI / notebook toolkits not used at runtime
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "PIL",
        "Pillow",
        "cv2",
        "tensorflow",
        "torch",
        # Test infra
        "pytest",
        "pytest_cov",
        "_pytest",
        "ruff",
        "black",
        "mypy",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # one-folder mode: deps collected separately
    name="niblit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX makes startup faster but is optional
    console=True,            # keep console so users can see startup logs
    icon=None,               # set to str(REPO_ROOT/"assets"/"niblit.ico") if icon exists
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="niblit",
)
