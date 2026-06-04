"""Live debug log viewer widget."""

from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from utils.debug_log import get_new_lines, get_history, get_level_color

_MONO = "font-family: 'Menlo','Consolas','DejaVu Sans Mono','Courier New',monospace;"


class DebugWidget(QWidget):
    """Scrolling log view that polls the debug_log queue every 200 ms."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paused = False
        self._build_ui()
        self._load_history()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(200)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        tb = QHBoxLayout()
        self._chk_scroll = QCheckBox("Автоскролл")
        self._chk_scroll.setChecked(True)
        tb.addWidget(self._chk_scroll)

        self._chk_debug = QCheckBox("DEBUG")
        self._chk_debug.setChecked(True)
        tb.addWidget(self._chk_debug)

        btn_clear = QPushButton("Очистить")
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._on_clear)
        tb.addStretch()
        tb.addWidget(btn_clear)
        lay.addLayout(tb)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(
            f"background:#0d0d0d; color:#ccc; {_MONO} font-size:11px;"
            "border:1px solid #333;"
        )
        self._text.setMaximumBlockCount(3000)
        lay.addWidget(self._text, 1)

    def _load_history(self):
        for line in get_history():
            self._append(line)

    def _poll(self):
        if self._paused:
            return
        for line in get_new_lines():
            self._append(line)

    def _append(self, line: dict):
        if line["level"] == "DEBUG" and not self._chk_debug.isChecked():
            return
        color = get_level_color(line["level"])
        self._text.appendHtml(
            f'<span style="color:{color}; {_MONO} font-size:11px;">'
            f"{_esc(line['full'])}</span>"
        )
        if self._chk_scroll.isChecked():
            self._text.moveCursor(QTextCursor.End)

    def _on_clear(self):
        self._text.clear()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
