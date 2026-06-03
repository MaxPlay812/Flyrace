from __future__ import annotations
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (QGridLayout, QGroupBox, QLabel,
                              QProgressBar, QVBoxLayout, QWidget)

from drone.controller import Telemetry
from utils.compat import MONO_CSS

_MONO_STYLE = f"font-family: {MONO_CSS}; font-size: 12px;"


def _colored_label(color: str) -> QLabel:
    lbl = QLabel("—")
    lbl.setStyleSheet(f"color: {color}; {_MONO_STYLE}")
    return lbl


class StatusWidget(QWidget):
    """System status panel: battery, position, altitude, speed, lap counter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lap_count = 0
        self._restarts = 0
        self._start_time: float | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_clock)
        self._timer.start(500)
        self._build_ui()

    # -------------------------------------------------- build
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.addWidget(self._conn_group())
        root.addWidget(self._flight_group())
        root.addWidget(self._race_group())
        root.addStretch()

    def _conn_group(self) -> QGroupBox:
        gb = QGroupBox("Соединение")
        g = QGridLayout(gb)
        self._lbl_conn = _colored_label("#f88")
        self._lbl_mode = _colored_label("#aaa")
        self._lbl_of = _colored_label("#aaa")
        g.addWidget(QLabel("Статус:"), 0, 0)
        g.addWidget(self._lbl_conn, 0, 1)
        g.addWidget(QLabel("Режим:"), 1, 0)
        g.addWidget(self._lbl_mode, 1, 1)
        g.addWidget(QLabel("Opt. flow:"), 2, 0)
        g.addWidget(self._lbl_of, 2, 1)
        return gb

    def _flight_group(self) -> QGroupBox:
        gb = QGroupBox("Полёт")
        g = QGridLayout(gb)
        self._lbl_alt = _colored_label("#8cf")
        self._lbl_speed = _colored_label("#8cf")
        self._lbl_pos = _colored_label("#cf8")
        self._bar_bat = QProgressBar()
        self._bar_bat.setRange(0, 100)
        self._bar_bat.setValue(100)
        self._bar_bat.setTextVisible(True)
        self._bar_bat.setFormat("%v%")
        g.addWidget(QLabel("Высота:"), 0, 0)
        g.addWidget(self._lbl_alt, 0, 1)
        g.addWidget(QLabel("Скорость:"), 1, 0)
        g.addWidget(self._lbl_speed, 1, 1)
        g.addWidget(QLabel("Позиция:"), 2, 0)
        g.addWidget(self._lbl_pos, 2, 1)
        g.addWidget(QLabel("Батарея:"), 3, 0)
        g.addWidget(self._bar_bat, 3, 1)
        return gb

    def _race_group(self) -> QGroupBox:
        gb = QGroupBox("Гонка")
        g = QGridLayout(gb)
        self._lbl_laps = _colored_label("#fc8")
        self._lbl_restarts = _colored_label("#f88")
        self._lbl_score = _colored_label("#8f8")
        self._lbl_clock = _colored_label("#8cf")
        g.addWidget(QLabel("Кругов:"), 0, 0)
        g.addWidget(self._lbl_laps, 0, 1)
        g.addWidget(QLabel("Рестартов:"), 1, 0)
        g.addWidget(self._lbl_restarts, 1, 1)
        g.addWidget(QLabel("Очки:"), 2, 0)
        g.addWidget(self._lbl_score, 2, 1)
        g.addWidget(QLabel("Время:"), 3, 0)
        g.addWidget(self._lbl_clock, 3, 1)
        return gb

    # -------------------------------------------------- public update
    def update_telemetry(self, t: Telemetry):
        if t.connected:
            self._lbl_conn.setText("Подключён")
            self._lbl_conn.setStyleSheet("color:#8f8;font-family:Menlo,Consolas,'DejaVu Sans Mono','Courier New',monospace;font-size:12px")
        else:
            self._lbl_conn.setText("Нет связи")
            self._lbl_conn.setStyleSheet("color:#f88;font-family:Menlo,Consolas,'DejaVu Sans Mono','Courier New',monospace;font-size:12px")

        self._lbl_mode.setText(t.mode)
        self._lbl_of.setText("Активен" if t.of_active else "—")

        speed = (t.vx ** 2 + t.vy ** 2) ** 0.5
        self._lbl_alt.setText(f"{t.z:.2f} м")
        self._lbl_speed.setText(f"{speed:.2f} м/с")
        self._lbl_pos.setText(f"{t.x:.2f}, {t.y:.2f} м")

        if not t.connected:
            self._bar_bat.setValue(0)
            self._bar_bat.setFormat("—")
            self._bar_bat.setStyleSheet(
                "QProgressBar::chunk{background:#444}"
                "QProgressBar{text-align:center;color:#888;}"
            )
        else:
            bat = int(t.battery)
            self._bar_bat.setValue(bat)
            self._bar_bat.setFormat("%v%")
            color = "#4c4" if bat > 50 else "#f90" if bat > 20 else "#f44"
            self._bar_bat.setStyleSheet(
                f"QProgressBar::chunk{{background:{color}}}"
                "QProgressBar{text-align:center;}"
            )

    def increment_lap(self):
        self._lap_count += 1
        self._update_race_labels()

    def increment_restart(self):
        self._restarts += 1
        self._update_race_labels()

    def reset_race(self):
        self._lap_count = 0
        self._restarts = 0
        self._start_time = time.time()
        self._update_race_labels()

    def start_timer(self):
        self._start_time = time.time()

    def stop_timer(self):
        self._start_time = None

    # -------------------------------------------------- private
    def _update_race_labels(self):
        self._lbl_laps.setText(str(self._lap_count))
        self._lbl_restarts.setText(str(self._restarts))
        score = self._lap_count - self._restarts
        self._lbl_score.setText(str(score))
        self._lbl_score.setStyleSheet(
            f"color:{'#8f8' if score >= 0 else '#f88'};"
            "font-family:Menlo,Consolas,'DejaVu Sans Mono','Courier New',monospace;font-size:12px"
        )

    def _update_clock(self):
        if self._start_time is not None:
            elapsed = time.time() - self._start_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            remaining = max(0, 300 - int(elapsed))
            rm, rs = divmod(remaining, 60)
            self._lbl_clock.setText(f"{mins:02d}:{secs:02d}  (осталось {rm:02d}:{rs:02d})")
        else:
            self._lbl_clock.setText("—")
