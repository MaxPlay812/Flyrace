"""Cross-platform font and path helpers."""
from __future__ import annotations
import sys
import os

# ------------------------------------------------------------------ fonts
# QFontDatabase.systemFont is available once QApplication exists.
# Call these from paint/init methods only, never at import time.

def mono_font(size: int):
    """System monospace font at given point size."""
    from PyQt5.QtGui import QFont, QFontDatabase
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSize(size)
    return f


def sans_font(size: int):
    """System sans-serif font at given point size."""
    from PyQt5.QtGui import QFont, QFontDatabase
    f = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
    f.setPointSize(size)
    return f


# CSS font stacks that work on all platforms
MONO_CSS = "Menlo, Consolas, 'DejaVu Sans Mono', 'Courier New', monospace"
SANS_CSS = "Segoe UI, Arial, 'DejaVu Sans', sans-serif"

# ------------------------------------------------------------------ paths
def app_data_dir() -> str:
    """Returns a writable directory for application data files."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    path = os.path.join(base, "flyrace")
    os.makedirs(path, exist_ok=True)
    return path


def project_root() -> str:
    """Absolute path to the project root (parent of src/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
