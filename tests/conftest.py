"""Shared pytest setup: make ``src`` importable and force headless Qt."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# GUI tests must never try to open a real window.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
