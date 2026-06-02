from __future__ import annotations
from typing import List, Optional

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel,
                              QSizePolicy, QVBoxLayout, QWidget)

from vision.aruco_detector import ArucoDetector, DetectedMarker
from utils.cuda import OpticalFlowTracker, bgr2rgb, cuda_available

try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False


class CameraWidget(QWidget):
    """Displays live camera feed with optional ArUco marker overlay.

    Optical flow uses CUDA (SparsePyrLK on GPU) when available,
    otherwise falls back to CPU. BGR→RGB conversion is also GPU-accelerated.
    """

    markers_detected = pyqtSignal(list)   # list[DetectedMarker]
    # Internal signal: delivers processed frame to main thread safely
    _frame_ready = pyqtSignal(object)     # tuple(np.ndarray, list[DetectedMarker])

    def __init__(self, parent=None):
        super().__init__(parent)
        self._detector = ArucoDetector()
        self._show_aruco = True
        self._show_of = False
        self._of_tracker = OpticalFlowTracker()
        self._frame_ready.connect(self._on_frame_main)
        self._source_change_cb = None   # set by main_window
        self._build_ui()

    # ---------------------------------------------------- layout
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        tb = QHBoxLayout()
        self._chk_aruco = QCheckBox("ArUco")
        self._chk_aruco.setChecked(True)
        self._chk_aruco.toggled.connect(lambda v: setattr(self, "_show_aruco", v))

        self._chk_of = QCheckBox("Optical flow")
        self._chk_of.setChecked(False)
        self._chk_of.toggled.connect(lambda v: setattr(self, "_show_of", v))

        gpu_badge = " (CUDA)" if cuda_available() else " (CPU)"
        self._chk_of.setText(f"Optical flow{gpu_badge}")

        # Camera source selector
        self._src_combo = QComboBox()
        self._src_combo.addItems(["Webcam (0)", "Webcam (1)",
                                  "Drone: /main_camera/image_raw", "Test pattern"])
        self._src_combo.setFixedWidth(200)
        self._src_combo.currentIndexChanged.connect(self._on_source_changed)

        tb.addWidget(self._chk_aruco)
        tb.addWidget(self._chk_of)
        tb.addWidget(self._src_combo)
        tb.addStretch()
        self._info_label = QLabel("Нет сигнала")
        self._info_label.setStyleSheet("color: #aaa; font-size: 11px;")
        tb.addWidget(self._info_label)
        self._src_label = QLabel("")
        self._src_label.setStyleSheet("color: #666; font-size: 10px;")
        tb.addWidget(self._src_label)
        lay.addLayout(tb)

        self._video_label = QLabel()
        self._video_label.setAlignment(Qt.AlignCenter)
        self._video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._video_label.setStyleSheet("background: #111; border: 1px solid #333;")
        self._video_label.setMinimumSize(320, 240)
        lay.addWidget(self._video_label, 1)

        self._det_label = QLabel("Маркеры: —")
        self._det_label.setStyleSheet("color: #8fc; font-size: 11px;")
        lay.addWidget(self._det_label)

    # ---------------------------------------------------- public
    def set_camera_matrix(self, matrix: np.ndarray, dist: np.ndarray):
        self._detector.camera_matrix = matrix
        self._detector.dist_coeffs = dist

    def set_source_change_callback(self, cb):
        """Called by main_window so CameraWidget can request a source switch."""
        self._source_change_cb = cb

    def set_source_label(self, text: str):
        self._src_label.setText(text)
        # Sync combo without triggering callback
        self._src_combo.blockSignals(True)
        for i in range(self._src_combo.count()):
            item = self._src_combo.itemText(i)
            if text in item or item in text:
                self._src_combo.setCurrentIndex(i)
                break
        self._src_combo.blockSignals(False)

    def _on_source_changed(self, idx: int):
        _SOURCES = [0, 1, "/main_camera/image_raw", None]
        src = _SOURCES[idx]
        if self._source_change_cb:
            self._source_change_cb(src)

    def on_frame(self, frame: np.ndarray):
        """Called from camera thread — do CV work here, then signal main thread."""
        if not _CV2_OK:
            return
        detected: List[DetectedMarker] = []
        if self._show_aruco and self._detector.available:
            detected = self._detector.detect(frame)
            frame = self._detector.draw_markers(frame, detected)
        if self._show_of:
            frame = self._draw_optical_flow(frame)
        if detected:
            self.markers_detected.emit(detected)
        # Signal crosses thread boundary safely
        self._frame_ready.emit((frame, detected))

    # ---------------------------------------------------- private
    def _on_frame_main(self, data):
        """Runs on main thread (connected via Qt signal)."""
        frame, detected = data
        self._update_display(frame, detected)

    def _draw_optical_flow(self, frame: np.ndarray) -> np.ndarray:
        vectors = self._of_tracker.track(frame)
        if not vectors:
            return frame
        out = frame.copy()
        for (cx, cy), (ax, ay) in vectors:
            cv2.arrowedLine(out, (cx, cy), (ax, ay),
                            (0, 200, 255), 1, tipLength=0.3)
        return out

    def _update_display(self, frame: np.ndarray,
                        detected: List[DetectedMarker]):
        h, w = frame.shape[:2]
        # GPU-accelerated BGR→RGB when CUDA is available
        rgb = bgr2rgb(frame)
        qi = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
        px = QPixmap.fromImage(qi).scaled(
            self._video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._video_label.setPixmap(px)
        self._info_label.setText(f"{w}×{h}  [{self._of_tracker.backend}]")
        if detected:
            ids_str = ", ".join(f"#{d.marker_id}" for d in detected)
            self._det_label.setText(f"Маркеры: {ids_str}")
        else:
            self._det_label.setText("Маркеры: —")
