from __future__ import annotations
from typing import List

from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import APP_VERSION, MARKERS_FILE, CAMERA_TOPIC
from drone.controller import CloverController, RosState
from models.marker import ArucoMarker, load_markers, save_markers
from vision.camera_thread import CameraThread
from vision.aruco_detector import DetectedMarker
from utils.cuda import cuda_available

from gui import theme
from gui.control_panel import ControlPanel
from gui.camera_widget import CameraWidget
from gui.map_widget import MapWidget
from gui.status_widget import StatusWidget
from gui.marker_dialog import MarkerManagerWidget
from gui.connection_dialog import ConnectionDialog
from gui.debug_widget import DebugWidget

_RACE, _SETUP = 0, 1


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clover 4 · Воздушные гонки")
        self.resize(1320, 820)
        self.setMinimumSize(960, 620)

        self._controller = CloverController()
        self._camera = CameraThread(source=0)
        self._markers: List[ArucoMarker] = load_markers(MARKERS_FILE)
        self._ros_cam_switched = False  # switch to drone cam once on first connect

        self._ctrl = ControlPanel()
        self._status = StatusWidget()
        self._camera_w = CameraWidget()
        self._map_w = MapWidget()
        self._marker_mgr = MarkerManagerWidget()
        self._debug_w = DebugWidget()

        self._build_ui()
        self._connect_signals()
        self._setup_telemetry_timer()
        self._camera.start()

    # ---------------------------------------------------------------- build
    def _build_ui(self):
        self.setStyleSheet(theme.STYLESHEET)
        self._map_w.set_markers(self._markers)
        self._marker_mgr.set_markers(self._markers)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)
        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        self.setCentralWidget(root)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        gpu = "GPU: CUDA" if cuda_available() else "GPU: CPU"
        self._status_bar.showMessage(f"Готов  ·  {gpu}")

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame{{background:{theme.SURFACE};border:1px solid {theme.BORDER};"
            "border-radius:10px;}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 12, 8)
        lay.setSpacing(12)

        title = QLabel("CLOVER 4")
        title.setStyleSheet(
            f"color:{theme.ACCENT};font-size:16px;font-weight:800;letter-spacing:2px;"
        )
        subtitle = QLabel("Воздушные гонки")
        subtitle.setStyleSheet(f"color:{theme.TEXT_DIM};font-size:12px;")
        lay.addWidget(title)
        lay.addWidget(subtitle)
        lay.addSpacing(18)

        # Mode switch (Гонка / Настройка)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for idx, name in ((_RACE, "Гонка"), (_SETUP, "Настройка")):
            btn = QPushButton(name)
            btn.setProperty("role", "mode")
            btn.setCheckable(True)
            btn.setChecked(idx == _RACE)
            btn.clicked.connect(lambda _=False, i=idx: self._set_mode(i))
            self._mode_group.addButton(btn, idx)
            lay.addWidget(btn)

        lay.addStretch(1)

        # Connection pill, battery pill, version
        self._btn_ros = QPushButton()
        self._btn_ros.setCursor(Qt.PointingHandCursor)
        self._btn_ros.clicked.connect(self._open_connection_dialog)
        lay.addWidget(self._btn_ros)

        self._lbl_batt = QLabel("—")
        self._lbl_batt.setMinimumWidth(86)
        self._lbl_batt.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._lbl_batt)

        ver = QLabel(f"v{APP_VERSION}")
        ver.setStyleSheet(f"color:{theme.TEXT_DIM};font-size:11px;")
        lay.addWidget(ver)

        self._update_ros_button()
        self._update_battery_pill(None)
        return bar

    def _build_body(self) -> QWidget:
        split = QSplitter(Qt.Horizontal)

        left = QSplitter(Qt.Vertical)
        left.addWidget(self._ctrl)
        left.addWidget(self._status)
        left.setSizes([420, 320])
        left.setFixedWidth(260)
        split.addWidget(left)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_race_page())
        self._stack.addWidget(self._build_setup_page())
        split.addWidget(self._stack)
        split.setStretchFactor(1, 1)
        return split

    def _build_race_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        for text, slot in (
            ("Круг +1", lambda: self._status.increment_lap()),
            ("Рестарт +1", lambda: self._status.increment_restart()),
            ("Сброс гонки", lambda: self._status.reset_race()),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        self._btn_add_marker = QPushButton("+ Маркер")
        self._btn_add_marker.setCheckable(True)
        self._btn_add_marker.setProperty("role", "primary")
        self._btn_add_marker.toggled.connect(self._on_add_marker_mode)
        row.addWidget(self._btn_add_marker)
        v.addLayout(row)

        self._race_tabs = QTabWidget()
        self._race_tabs.addTab(self._camera_w, "Камера")
        self._race_tabs.addTab(self._map_w, "Карта поля")
        v.addWidget(self._race_tabs, 1)
        return page

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        btn_conn = QPushButton("Подключение к дрону…")
        btn_conn.setProperty("role", "primary")
        btn_conn.clicked.connect(self._open_connection_dialog)
        row.addWidget(btn_conn)
        btn_reset_field = QPushButton("Сбросить поле к регламенту")
        btn_reset_field.clicked.connect(self._map_w.reset_field)
        row.addWidget(btn_reset_field)
        row.addStretch(1)
        v.addLayout(row)

        self._setup_tabs = QTabWidget()
        self._setup_tabs.addTab(self._marker_mgr, "ArUco маркеры")
        self._setup_tabs.addTab(self._debug_w, "Лог ROS")
        v.addWidget(self._setup_tabs, 1)
        return page

    def _set_mode(self, index: int):
        self._stack.setCurrentIndex(index)
        self._status_bar.showMessage("Режим гонки" if index == _RACE else "Настройка")

    # ---------------------------------------------------------------- connect
    def _connect_signals(self):
        self._ctrl.takeoff_requested.connect(self._on_takeoff)
        self._ctrl.land_requested.connect(self._on_land)
        self._ctrl.stop_requested.connect(self._on_emergency)
        self._ctrl.speed_changed.connect(self._controller.set_speed)
        self._ctrl.start_mission.connect(self._on_start_mission)
        self._ctrl.stop_mission.connect(self._on_stop_mission)

        self._camera.add_frame_callback(self._camera_w.on_frame)
        self._camera_w.set_source_change_callback(self._switch_camera)
        self._camera_w.markers_detected.connect(self._on_markers_detected)
        self._camera_w.line_detected.connect(self._on_line_detected)

        self._map_w.marker_add_requested.connect(self._on_map_add_marker)
        self._map_w.marker_selected.connect(self._on_map_marker_selected)
        self._map_w.field_changed.connect(self._controller.reload_field)
        self._map_w.markers_edited.connect(self._on_markers_dragged)

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
            self._set_mode(_RACE)
            self._race_tabs.setCurrentWidget(self._map_w)
            self._status_bar.showMessage(
                "Режим добавления: кликните на карте для размещения маркера"
            )
        else:
            self._status_bar.showMessage("Режим добавления отключён")

    @pyqtSlot(float, float)
    def _on_map_add_marker(self, x: float, y: float):
        self._marker_mgr.add_marker_at(x, y)
        self._btn_add_marker.setChecked(False)

    @pyqtSlot(int)
    def _on_map_marker_selected(self, marker_id: int):
        self._set_mode(_SETUP)
        self._setup_tabs.setCurrentWidget(self._marker_mgr)
        self._status_bar.showMessage(f"Выбран маркер #{marker_id}")

    @pyqtSlot(list)
    def _on_markers_updated(self, markers: List[ArucoMarker]):
        self._markers = markers
        self._map_w.set_markers(markers)

    @pyqtSlot()
    def _on_markers_dragged(self):
        """A marker was moved on the map — persist and refresh the list."""
        save_markers(MARKERS_FILE, self._markers)
        self._marker_mgr.set_markers(self._markers)
        self._status_bar.showMessage("Позиция маркера сохранена")

    @pyqtSlot(list)
    def _on_markers_detected(self, detected: List[DetectedMarker]):
        seen = []
        for dm in detected:
            known = next(
                (m for m in self._markers if m.marker_id == dm.marker_id), None
            )
            if known:
                self._apply_zone(known)
                seen.append((known, dm))
        if seen:
            self._update_position_from_markers(seen)

    def _update_position_from_markers(self, seen):
        """Estimate drone position on the map from detected ArUco markers.

        Each known marker has a fixed field position. The drone is placed at the
        average of the visible markers' positions (offset by pose translation
        when a calibrated camera provides it). This keeps the drone visible on
        the map alongside the line, even without ROS telemetry.
        """
        xs, ys = [], []
        for known, dm in seen:
            fx, fy = known.x, known.y  # mm
            if dm.tvec is not None:
                # Camera sees the marker at tvec (m, camera frame). Shift the
                # estimate by the horizontal offset so the drone, not the marker,
                # is placed on the map.
                fx -= float(dm.tvec[0]) * 1000.0
                fy += float(dm.tvec[2]) * 1000.0
            xs.append(fx)
            ys.append(fy)
        x_m = (sum(xs) / len(xs)) / 1000.0
        y_m = (sum(ys) / len(ys)) / 1000.0
        t = self._controller.get_telemetry()
        yaw = t.yaw if t.connected else 0.0
        self._map_w.set_drone_position(x_m, y_m, yaw)

    @pyqtSlot(object)
    def _on_line_detected(self, res):
        """Drive the drone along the dashed line without yawing."""
        vx, vy = self._controller.follow_line(
            res.offset_norm, res.angle_deg, res.crossing
        )
        mode = "прямо (перекрёсток)" if res.crossing else "следование за линией"
        self._status_bar.showMessage(
            f"Линия: {mode}  vx={vx:.2f} vy={vy:+.2f} м/с"
        )

    def _apply_zone(self, marker: ArucoMarker):
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
        self._update_ros_button()
        self._update_battery_pill(t)
        if t.connected and not self._ros_cam_switched:
            self._ros_cam_switched = True
            self._switch_camera(CAMERA_TOPIC)

    def _switch_camera(self, source):
        """Replace the running camera thread with a new source."""
        if source is None:
            source = "test"  # CameraThread will use test pattern for unknown str
        self._camera.stop()
        actual = source if source != "test" else 99
        self._camera = CameraThread(source=actual)
        self._camera.add_frame_callback(self._camera_w.on_frame)
        self._camera.start()
        label = str(source)
        self._camera_w.set_source_label(label)
        self._status_bar.showMessage(f"Камера: {label}")

    # ----------------------------------------------- header indicators
    def _pill_css(self, fg: str, border: str) -> str:
        return (
            f"color:{fg};font-weight:700;font-size:12px;"
            f"border:1px solid {border};border-radius:12px;padding:4px 12px;"
        )

    def _update_ros_button(self):
        state = self._controller.ros_state
        if state == RosState.FULL:
            connected = self._controller.get_telemetry().connected
            if connected:
                self._btn_ros.setText("● ROS подключён")
                self._btn_ros.setStyleSheet(self._pill_css(theme.SUCCESS, "#2c7a5b"))
            else:
                self._btn_ros.setText("● ROS нет ответа")
                self._btn_ros.setStyleSheet(self._pill_css(theme.WARNING, "#8a6d1f"))
        elif state == RosState.ROSPY:
            self._btn_ros.setText("● нет пакета clover")
            self._btn_ros.setStyleSheet(self._pill_css(theme.DANGER, "#7a2c2c"))
        else:
            self._btn_ros.setText("● Симуляция")
            self._btn_ros.setStyleSheet(self._pill_css(theme.TEXT_DIM, theme.BORDER))

    def _update_battery_pill(self, t):
        if t is None or not t.connected:
            self._lbl_batt.setText("🔋 —")
            self._lbl_batt.setStyleSheet(self._pill_css(theme.TEXT_DIM, theme.BORDER))
            return
        pct = int(t.battery)
        color = theme.battery_color(pct)
        self._lbl_batt.setText(f"🔋 {pct}% · {t.voltage:.1f}В")
        self._lbl_batt.setStyleSheet(self._pill_css(color, theme.BORDER))

    def _open_connection_dialog(self):
        dlg = ConnectionDialog(self._controller, self)
        dlg.exec_()

    # ---------------------------------------------------------------- close
    def closeEvent(self, event):
        self._camera.stop()
        self._controller.stop()
        event.accept()
