from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from config import DEFAULT_SPEED, FLIGHT_ALT, MAX_SPEED, MIN_SPEED


class ControlPanel(QWidget):
    """Left-side flight control panel."""

    takeoff_requested = pyqtSignal(float)  # altitude
    land_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    speed_changed = pyqtSignal(float)  # m/s
    start_mission = pyqtSignal()
    stop_mission = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._armed = False
        self._mission_running = False
        self._build_ui()

    # ---------------------------------------------------------- layout
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        root.addWidget(self._build_flight_group())
        root.addWidget(self._build_speed_group())
        root.addWidget(self._build_mission_group())
        root.addWidget(self._build_stop_btn())
        root.addStretch()

    def _build_flight_group(self) -> QGroupBox:
        gb = QGroupBox("Управление полётом")
        lay = QGridLayout(gb)
        lay.setSpacing(6)

        self._btn_takeoff = QPushButton("Взлёт")
        self._btn_takeoff.setMinimumHeight(36)
        self._btn_takeoff.setStyleSheet(
            "QPushButton{background:#1e6e2e;color:white;font-weight:bold;border-radius:4px}"
            "QPushButton:hover{background:#2a9a40}"
            "QPushButton:disabled{background:#333}"
        )
        self._btn_takeoff.clicked.connect(self._on_takeoff)

        self._btn_land = QPushButton("Посадка")
        self._btn_land.setMinimumHeight(36)
        self._btn_land.setStyleSheet(
            "QPushButton{background:#4a3800;color:white;font-weight:bold;border-radius:4px}"
            "QPushButton:hover{background:#6a5000}"
            "QPushButton:disabled{background:#333}"
        )
        self._btn_land.setEnabled(False)
        self._btn_land.clicked.connect(self._on_land)

        self._alt_spin = QDoubleSpinBox()
        self._alt_spin.setRange(0.3, 3.0)
        self._alt_spin.setValue(FLIGHT_ALT)
        self._alt_spin.setSingleStep(0.1)
        self._alt_spin.setSuffix(" м")
        self._alt_spin.setToolTip("Высота взлёта")

        lay.addWidget(self._btn_takeoff, 0, 0)
        lay.addWidget(self._btn_land, 0, 1)
        lay.addWidget(QLabel("Высота:"), 1, 0)
        lay.addWidget(self._alt_spin, 1, 1)
        return gb

    def _build_speed_group(self) -> QGroupBox:
        gb = QGroupBox("Скорость")
        lay = QVBoxLayout(gb)
        lay.setSpacing(4)

        hlay = QHBoxLayout()
        self._speed_label = QLabel(f"{DEFAULT_SPEED:.1f} м/с")
        self._speed_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._speed_label.setMinimumWidth(70)
        hlay.addWidget(QLabel(f"{MIN_SPEED}"))
        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(int(MIN_SPEED * 10), int(MAX_SPEED * 10))
        self._speed_slider.setValue(int(DEFAULT_SPEED * 10))
        self._speed_slider.setTickPosition(QSlider.TicksBelow)
        self._speed_slider.setTickInterval(5)
        self._speed_slider.valueChanged.connect(self._on_speed_slider)
        hlay.addWidget(self._speed_slider, 1)
        hlay.addWidget(QLabel(f"{MAX_SPEED}"))
        lay.addLayout(hlay)

        hlay2 = QHBoxLayout()
        hlay2.addWidget(QLabel("Текущая:"))
        hlay2.addStretch()
        hlay2.addWidget(self._speed_label)
        lay.addLayout(hlay2)
        return gb

    def _build_mission_group(self) -> QGroupBox:
        gb = QGroupBox("Миссия (восьмёрка)")
        lay = QVBoxLayout(gb)
        lay.setSpacing(4)

        self._btn_start_mission = QPushButton("Запустить миссию")
        self._btn_start_mission.setMinimumHeight(34)
        self._btn_start_mission.setStyleSheet(
            "QPushButton{background:#1a4a7a;color:white;font-weight:bold;border-radius:4px}"
            "QPushButton:hover{background:#2060a0}"
            "QPushButton:disabled{background:#333}"
        )
        self._btn_start_mission.setEnabled(False)
        self._btn_start_mission.clicked.connect(self._on_start_mission)

        self._btn_stop_mission = QPushButton("Остановить миссию")
        self._btn_stop_mission.setMinimumHeight(34)
        self._btn_stop_mission.setStyleSheet(
            "QPushButton{background:#4a2020;color:white;border-radius:4px}"
            "QPushButton:hover{background:#6a3030}"
            "QPushButton:disabled{background:#333}"
        )
        self._btn_stop_mission.setEnabled(False)
        self._btn_stop_mission.clicked.connect(self._on_stop_mission)

        lay.addWidget(self._btn_start_mission)
        lay.addWidget(self._btn_stop_mission)
        return gb

    def _build_stop_btn(self) -> QPushButton:
        btn = QPushButton("⛔  АВАРИЙНАЯ ОСТАНОВКА")
        btn.setMinimumHeight(44)
        btn.setStyleSheet(
            "QPushButton{background:#8b0000;color:white;font-weight:bold;"
            "font-size:13px;border-radius:4px}"
            "QPushButton:hover{background:#cc0000}"
        )
        btn.clicked.connect(self.stop_requested)
        return btn

    # ---------------------------------------------------------- slots
    def _on_takeoff(self):
        alt = self._alt_spin.value()
        self.takeoff_requested.emit(alt)

    def _on_land(self):
        self.land_requested.emit()

    def _on_speed_slider(self, value: int):
        speed = value / 10.0
        self._speed_label.setText(f"{speed:.1f} м/с")
        self.speed_changed.emit(speed)

    def _on_start_mission(self):
        self._mission_running = True
        self._btn_start_mission.setEnabled(False)
        self._btn_stop_mission.setEnabled(True)
        self.start_mission.emit()

    def _on_stop_mission(self):
        self._mission_running = False
        self._btn_start_mission.setEnabled(True)
        self._btn_stop_mission.setEnabled(False)
        self.stop_mission.emit()

    # ---------------------------------------------------------- state update
    def set_armed(self, armed: bool):
        self._armed = armed
        self._btn_takeoff.setEnabled(not armed)
        self._btn_land.setEnabled(armed)
        self._btn_start_mission.setEnabled(armed and not self._mission_running)

    def set_speed_display(self, speed: float):
        self._speed_label.setText(f"{speed:.1f} м/с")
        val = int(speed * 10)
        self._speed_slider.blockSignals(True)
        self._speed_slider.setValue(val)
        self._speed_slider.blockSignals(False)
