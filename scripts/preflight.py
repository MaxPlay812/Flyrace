#!/usr/bin/env python3
"""Pre-launch self-test for the Clover 4 Race GUI.

Verifies the Python version, required third-party packages and a couple of
internal invariants (track geometry, module imports) before the GUI starts.
Run directly:  ``python3 scripts/preflight.py``

Exit code 0 means the app is safe to launch; any other code means a problem
was found and printed with a hint on how to fix it.
"""

from __future__ import annotations

import importlib
import os
import sys

# Make ``src`` importable whether run from the repo root or scripts/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

MIN_PYTHON = (3, 8)
REQUIRED = [
    ("PyQt5", "PyQt5", "pip install 'PyQt5>=5.15'"),
    ("cv2", "opencv-contrib-python", "pip install 'opencv-contrib-python>=4.8'"),
    ("numpy", "numpy", "pip install 'numpy>=1.24'"),
]

_GREEN, _RED, _YELLOW, _RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {_GREEN}[ok]{_RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}[warn]{_RESET} {msg}")


def _fail(msg: str, hint: str = "") -> None:
    print(f"  {_RED}[FAIL]{_RESET} {msg}")
    if hint:
        print(f"         → {hint}")


def check_python() -> bool:
    if sys.version_info[:2] < MIN_PYTHON:
        _fail(
            f"Python {sys.version_info.major}.{sys.version_info.minor} too old",
            f"need Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
        )
        return False
    _ok(f"Python {sys.version_info.major}.{sys.version_info.minor}")
    return True


def check_packages() -> bool:
    everything_ok = True
    for module_name, dist_name, hint in REQUIRED:
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            _fail(f"missing package '{dist_name}'", hint)
            everything_ok = False
            continue
        version = getattr(mod, "__version__", "?")
        _ok(f"{dist_name} {version}")
    return everything_ok


def check_qt_conflict() -> bool:
    """Detect the macOS PyQt5/PyQt6 clash that segfaults the app.

    Uses ``find_spec`` so we never actually load Qt6 (importing it would
    create the very conflict we are checking for).
    """
    import importlib.util

    has_qt5 = importlib.util.find_spec("PyQt5") is not None
    has_qt6 = importlib.util.find_spec("PyQt6") is not None
    if has_qt5 and has_qt6:
        _warn(
            "both PyQt5 and PyQt6 are installed — on macOS this can "
            "segfault. Use an isolated venv (see run.sh)."
        )
        return False
    _ok("no PyQt5/PyQt6 conflict")
    return True


def check_geometry() -> bool:
    """The ∞ track must be a non-empty curve with poles at the loop centroids."""
    import math

    from models.field import FieldConfig

    field = FieldConfig()
    points = field.lemniscate_points(360)
    if len(points) < 100:
        _fail("lemniscate produced too few points")
        return False

    # Outer tip distance must equal a·√2.
    cx, cy = field.center
    tx, ty = field.tip_point()
    expected = field.param_a * math.sqrt(2.0)
    if abs(math.hypot(tx - cx, ty - cy) - expected) > 1.0:
        _fail("tip distance does not match the lemniscate parameter")
        return False
    _ok(f"track geometry ({len(points)} points, a={field.param_a:.0f} mm)")
    return True


def check_imports() -> bool:
    """Import the heavy GUI modules headless to catch syntax/logic errors."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    for name in (
        "config",
        "drone.controller",
        "vision.camera_thread",
        "gui.map_widget",
        "gui.main_window",
    ):
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - report any import failure
            _fail(f"import {name}: {exc}")
            return False
    _ok("all GUI modules import cleanly")
    return True


def main() -> int:
    print("Clover 4 GUI — preflight self-test")
    checks = [
        check_python(),
        check_packages(),
        check_qt_conflict(),
        check_geometry(),
        check_imports(),
    ]
    # check_qt_conflict is advisory: a warning should not block launch.
    blocking = checks[:2] + checks[3:]
    if all(blocking):
        print(f"{_GREEN}preflight passed{_RESET}")
        return 0
    print(f"{_RED}preflight found problems — see above{_RESET}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
