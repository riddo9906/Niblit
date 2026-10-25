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

from PyInstaller.utils.hooks import collect_submodules

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(SPECPATH).resolve()  # stable regardless of caller cwd
# Prefer this repository's shared package over any similarly named sibling.
_repo_import_path = str(REPO_ROOT)
if _repo_import_path in sys.path:
    sys.path.remove(_repo_import_path)
sys.path.insert(0, _repo_import_path)
STAGING_ROOT = Path(os.environ.get("NIBLIT_BUILD_STAGING_DIR", REPO_ROOT / "dist" / "_staged")).expanduser().resolve()

# Pre-staged artefacts placed by niblit-build.js before PyInstaller runs.
# These paths are under dist/ (a sibling of this spec in REPO_ROOT).
STAGED_CLOUD_DIR = STAGING_ROOT / "cloud"
STAGED_LEAN_ALGOS_DIR = STAGING_ROOT / "lean-algos"
STAGED_TAURI_EXE = STAGING_ROOT / "niblit-ui.exe"

# A desktop release must never silently omit a required staged service.
_exe_suffix = ".exe" if os.name == "nt" else ""
for _required in (
    STAGED_TAURI_EXE,
    STAGED_CLOUD_DIR / f"niblit-cloud{_exe_suffix}",
    STAGED_LEAN_ALGOS_DIR / f"niblit-lean-algos{_exe_suffix}",
):
    if not _required.is_file():
        raise SystemExit(f"Required desktop artifact missing: {_required}. Run npm run build to stage all components.")

_lean_override = os.environ.get("NIBLIT_LEAN_ALGOS_ROOT") or os.environ.get("NIBLIT_LEAN_ALGOS")
_lean_candidates = [
    Path(_lean_override).expanduser() if _lean_override else None,
    STAGED_LEAN_ALGOS_DIR,          # preferred: staged by niblit-build.js Step 5
    REPO_ROOT / "niblit-lean-algos",
    REPO_ROOT.parent / "niblit-lean-algos",
]
LEAN_ALGOS_ROOT = next(
    (
        candidate.resolve()
        for candidate in _lean_candidates
        if candidate is not None and candidate.is_dir()
    ),
    REPO_ROOT / "niblit-lean-algos",
)

# ---------------------------------------------------------------------------
# Data files bundled into the package
# ---------------------------------------------------------------------------

datas = []

# The source distribution has a sibling ``shared`` package that can shadow
# Niblit's contracts during PyInstaller analysis. Ship the exact contract
# sources alongside the bundle so runtime imports remain available.
_shared_root = REPO_ROOT / "shared"
if _shared_root.is_dir():
    for _source in _shared_root.rglob("*.py"):
        _destination = str(_source.relative_to(REPO_ROOT).parent)
        datas.append((str(_source), _destination))

# Lean-algos bridge (Python package) and algorithm source files.
# These are NOT copied into the Python package; they live in the bundle as
# data so niblit.exe can reference them at the well-known relative paths:
#   <bundle>/lean-algos/niblit_bridge/
#   <bundle>/lean-algos/algorithms/
if STAGED_LEAN_ALGOS_DIR.is_dir():
    # Include the Lean one-folder runtime staged by niblit-build.js.
    datas += [(str(STAGED_LEAN_ALGOS_DIR), "lean-algos")]
elif LEAN_ALGOS_ROOT.is_dir():
    # Direct-spec development fallback: include repository source assets.
    for _name in ("niblit_bridge", "algorithms", "lean.json"):
        _path = LEAN_ALGOS_ROOT / _name
        if _path.is_dir():
            datas += [(str(_path), f"lean-algos/{_name}")]
        elif _path.is_file():
            datas += [(str(_path), "lean-algos")]

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
]

# Sweep every sub-package to catch dynamic imports inside modules.
for _pkg in ("modules", "core", "agents", "shared", "niblit_memory", "nibblebots", "niblit_core"):
    if _pkg == "niblit_memory":
        # Importing this package during spec evaluation starts memory workers
        # and attempts to persist user state. Discover module names from source
        # paths instead; PyInstaller's analysis imports them later as needed.
        _memory_root = REPO_ROOT / "niblit_memory"
        for _source in _memory_root.rglob("*.py"):
            _relative = _source.relative_to(REPO_ROOT).with_suffix("")
            if _relative.name == "__init__":
                _relative = _relative.parent
            hiddenimports.append(".".join(_relative.parts))
    else:
        hiddenimports += collect_submodules(_pkg)

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    [str(REPO_ROOT / "main.py")],
    pathex=[str(REPO_ROOT)],
    # Inference belongs to the separately bundled Cloud Server.
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
    contents_directory=".",  # keep sidecar services beside niblit.exe for runtime discovery
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
