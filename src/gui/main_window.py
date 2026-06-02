from __future__ import annotations
from typing import List

from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QAction, QMainWindow, QSplitter, QStatusBar,
                              QTabWidget, QToolBar, QWidget, QVBoxLayout,
                              QCheckBox, QLabel)

from config import APP_TITLE, MARKERS_FILE
from drone.controller import CloverController, Telemetry
from models.marker import ArucoMarker, load_markers
from vision.camera_thread import CameraThread
from vision.aruco_detector import DetectedMarker
from utils.cuda import cuda_available, cuda_info

from gui.control_panel import ControlPanel
from gui.camera_widget import CameraWidget
from gui.map_widget import MapWidget
from gui.status_widget import StatusWidget
from gui.marker_dialog import MarkerManagerWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)

        self._controller = CloverController()
        self._camera = CameraThread(source=0)
        self._markers: List[ArucoMarker] = load_markers(MARKERS_FILE)

        self._ctrl = ControlPanel()
        self._status = StatusWidget()
        self._camera_w = CameraWidget()
        self._map_w = MapWidget()
        self._marker_mgr = MarkerManagerWidget()

        self._build_ui()
        self._connect_signals()
        self._setup_telemetry_timer()
        self._camera.start()

    # ---------------------------------------------------------------- build
    def _build_ui(self):
        self._toolbar = self._build_toolbar()
        self.addToolBar(self._toolbar)

        # Root splitter: [left panel | right area]
        root_split = QSplitter(Qt.Horizontal)

        # Left: controls + status
        left_split = QSplitter(Qt.Vertical)
        left_split.addWidget(self._ctrl)
        left_split.addWidget(self._status)
        left_split.setSizes([350, 350])
        left_split.setFixedWidth(250)

        # Right: tabs (camera, map, markers)
        self._tabs = QTabWidget()
        self._map_w.set_markers(self._markers)
        self._marker_mgr.set_markers(self._markers)
        self._tabs.addTab(self._camera_w, "Камера")
        self._tabs.addTab(self._map_w, "Карта поля")
        self._tabs.addTab(self._marker_mgr, "ArUco маркеры")

        root_split.addWidget(left_split)
        root_split.addWidget(self._tabs)
        root_split.setSizes([250, 1030])
        root_split.setStretchFactor(1, 1)

        self.setCentralWidget(root_split)
        self._set_dark_theme()

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        sim = "" if self._controller.ros_available else " [СИМУЛЯЦИЯ]"
        gpu = "  |  GPU: " + ("CUDA" if cuda_available() else "нет")
        self._status_bar.showMessage(f"Clover 4 GUI готов{sim}{gpu}")

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar("Основная")
        tb.setMovable(False)

        self._act_add_marker = QAction("➕ Добавить маркер", self)
        self._act_add_marker.setCheckable(True)
        self._act_add_marker.setToolTip(
            "Включить режим добавления: кликните на карте для размещения маркера"
        )
        self._act_add_marker.toggled.connect(self._on_add_marker_mode)
        tb.addAction(self._act_add_marker)

        tb.addSeparator()

        act_lap = QAction("Круг +1", self)
        act_lap.triggered.connect(lambda: self._status.increment_lap())
        tb.addAction(act_lap)

        act_restart = QAction("Рестарт +1", self)
        act_restart.triggered.connect(lambda: self._status.increment_restart())
        tb.addAction(act_restart)

        act_reset = QAction("Сброс гонки", self)
        act_reset.triggered.connect(lambda: self._status.reset_race())
        tb.addAction(act_reset)

        return tb

    # ---------------------------------------------------------------- connect
    def _connect_signals(self):
        # Control panel → controller
        self._ctrl.takeoff_requested.connect(self._on_takeoff)
        self._ctrl.land_requested.connect(self._on_land)
        self._ctrl.stop_requested.connect(self._on_emergency)
        self._ctrl.speed_changed.connect(self._controller.set_speed)
        self._ctrl.start_mission.connect(self._on_start_mission)
        self._ctrl.stop_mission.connect(self._on_stop_mission)

        # Camera → camera widget
        self._camera.add_frame_callback(self._camera_w.on_frame)

        # Camera widget → map (marker detection)
        self._camera_w.markers_detected.connect(self._on_markers_detected)

        # Map → add marker
        self._map_w.marker_add_requested.connect(self._on_map_add_marker)
        self._map_w.marker_selected.connect(self._on_map_marker_selected)

        # Marker manager → refresh map
        self._marker_mgr.markers_changed.connect(self._on_markers_updated)

    def _setup_telemetry_timer(self):
        self._telem_timer = QTimer(self)
        self._telem_timer.timeout.connect(self._poll_telemetry)
        self._telem_timer.start(100)  # 10 Hz

    # ---------------------------------------------------------------- slots
    @pyqtSlot(float)
    def _on_takeoff(self, altitude: float):
        self._controller.takeoff(altitude)
        self._status.start_timer()
        self._status_bar.showMessage(f"Взлёт на {altitude:.1f} м")

    @pyqtSlot()
    def _on_land(self):
        self._controller.land()
        self._status.stop_timer()
        self._status_bar.showMessage("Посадка")

    @pyqtSlot()
    def _on_emergency(self):
        self._controller.emergency_stop()
        self._status_bar.showMessage("⛔ АВАРИЙНАЯ ОСТАНОВКА")

    @pyqtSlot()
    def _on_start_mission(self):
        self._status.reset_race()
        self._map_w.clear_trail()
        self._status_bar.showMessage("Миссия запущена")

    @pyqtSlot()
    def _on_stop_mission(self):
        self._status.stop_timer()
        self._status_bar.showMessage("Миссия остановлена")

    @pyqtSlot(bool)
    def _on_add_marker_mode(self, enabled: bool):
        self._map_w.set_add_mode(enabled)
        if enabled:
            self._tabs.setCurrentWidget(self._map_w)
            self._status_bar.showMessage(
                "Режим добавления: кликните на карте для размещения маркера"
            )
        else:
            self._status_bar.showMessage("Режим добавления отключён")

    @pyqtSlot(float, float)
    def _on_map_add_marker(self, x: float, y: float):
        self._marker_mgr.add_marker_at(x, y)
        self._act_add_marker.setChecked(False)

    @pyqtSlot(int)
    def _on_map_marker_selected(self, marker_id: int):
        self._tabs.setCurrentWidget(self._marker_mgr)
        self._status_bar.showMessage(f"Выбран маркер #{marker_id}")

    @pyqtSlot(list)
    def _on_markers_updated(self, markers: List[ArucoMarker]):
        self._markers = markers
        self._map_w.set_markers(markers)

    @pyqtSlot(list)
    def _on_markers_detected(self, detected: List[DetectedMarker]):
        for dm in detected:
            known = next((m for m in self._markers
                          if m.marker_id == dm.marker_id), None)
            if known:
                self._apply_zone(known)

    def _apply_zone(self, marker: ArucoMarker):
        from models.marker import ZoneType
        self._controller.set_speed(marker.speed_value)
        self._ctrl.set_speed_display(marker.speed_value)
        self._status_bar.showMessage(
            f"Зона: {marker.zone_type.label()}  →  {marker.speed_value:.1f} м/с"
        )

    @pyqtSlot()
    def _poll_telemetry(self):
        t = self._controller.get_telemetry()
        self._status.update_telemetry(t)
        self._ctrl.set_armed(t.armed)
        if t.connected and t.armed:
            self._map_w.set_drone_position(t.x, t.y, t.yaw)

    # ---------------------------------------------------------------- theme
    def _set_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #1a1a1a; color: #ddd;
            }
            QGroupBox {
                border: 1px solid #444; border-radius: 4px;
                margin-top: 6px; padding-top: 4px;
                font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab {
                background: #2a2a2a; color: #bbb; padding: 6px 16px;
                border: 1px solid #444; border-bottom: none;
            }
            QTabBar::tab:selected { background: #1a1a1a; color: white; }
            QSlider::groove:horizontal {
                height: 6px; background: #333; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 14px; height: 14px; border-radius: 7px;
                background: #5080c0; margin: -4px 0;
            }
            QProgressBar {
                border: 1px solid #555; border-radius: 3px; height: 14px;
                text-align: center; font-size: 11px;
            }
            QToolBar { background: #222; border-bottom: 1px solid #444; spacing: 4px; }
            QStatusBar { background: #181818; color: #999; font-size: 11px; }
            QListWidget { background: #1e1e1e; alternate-background-color: #232323; }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
                background: #2a2a2a; border: 1px solid #555; border-radius: 3px;
                padding: 2px 4px;
            }
        """)

    # ---------------------------------------------------------------- close
    def closeEvent(self, event):
        self._camera.stop()
        self._controller.stop()
        event.accept()
