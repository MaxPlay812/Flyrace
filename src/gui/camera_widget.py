from __future__ import annotations
from typing import List, Optional

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QSizePolicy,
                              QVBoxLayout, QWidget)

from vision.aruco_detector import ArucoDetector, DetectedMarker

try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False


class CameraWidget(QWidget):
    """Displays live camera feed with optional ArUco marker overlay."""

    markers_detected = pyqtSignal(list)   # list[DetectedMarker]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._detector = ArucoDetector()
        self._show_aruco = True
        self._show_of = False
        self._prev_gray: Optional[np.ndarray] = None
        self._prev_pts: Optional[np.ndarray] = None
        self._build_ui()

    # ---------------------------------------------------- layout
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        # Toolbar
        tb = QHBoxLayout()
        self._chk_aruco = QCheckBox("ArUco")
        self._chk_aruco.setChecked(True)
        self._chk_aruco.toggled.connect(lambda v: setattr(self, "_show_aruco", v))
        self._chk_of = QCheckBox("Optical flow")
        self._chk_of.setChecked(False)
        self._chk_of.toggled.connect(lambda v: setattr(self, "_show_of", v))
        tb.addWidget(self._chk_aruco)
        tb.addWidget(self._chk_of)
        tb.addStretch()
        self._info_label = QLabel("Нет сигнала")
        self._info_label.setStyleSheet("color: #aaa; font-size: 11px;")
        tb.addWidget(self._info_label)
        lay.addLayout(tb)

        # Video area
        self._video_label = QLabel()
        self._video_label.setAlignment(Qt.AlignCenter)
        self._video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._video_label.setStyleSheet("background: #111; border: 1px solid #333;")
        self._video_label.setMinimumSize(320, 240)
        lay.addWidget(self._video_label, 1)

        # Detected markers list
        self._det_label = QLabel("Маркеры: —")
        self._det_label.setStyleSheet("color: #8fc; font-size: 11px;")
        lay.addWidget(self._det_label)

    # ---------------------------------------------------- public
    def set_camera_matrix(self, matrix: np.ndarray, dist: np.ndarray):
        self._detector.camera_matrix = matrix
        self._detector.dist_coeffs = dist

    def on_frame(self, frame: np.ndarray):
        """Called from camera thread with a new BGR frame."""
        if not _CV2_OK:
            return

        # ArUco detection
        detected: List[DetectedMarker] = []
        if self._show_aruco and self._detector.available:
            detected = self._detector.detect(frame)
            frame = self._detector.draw_markers(frame, detected)

        # Optical flow overlay
        if self._show_of:
            frame = self._draw_optical_flow(frame)

        # Emit signal for other widgets to react
        if detected:
            self.markers_detected.emit(detected)

        self._update_display(frame, detected)

    # ---------------------------------------------------- private
    def _draw_optical_flow(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        out = frame.copy()
        if self._prev_gray is not None and self._prev_pts is not None:
            new_pts, status, _ = cv2.calcOpticalFlowPyrLK(
                self._prev_gray, gray, self._prev_pts, None,
                winSize=(15, 15), maxLevel=2,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03)
            )
            for i, (new, old) in enumerate(zip(new_pts, self._prev_pts)):
                if status[i][0]:
                    a, b = new.ravel().astype(int)
                    c, d = old.ravel().astype(int)
                    cv2.arrowedLine(out, (c, d), (a, b), (0, 200, 255), 1,
                                    tipLength=0.3)
        # Refresh keypoints every frame
        self._prev_gray = gray
        pts = cv2.goodFeaturesToTrack(gray, maxCorners=80, qualityLevel=0.01,
                                      minDistance=8)
        self._prev_pts = pts if pts is not None else self._prev_pts
        return out

    def _update_display(self, frame: np.ndarray,
                        detected: List[DetectedMarker]):
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qi = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
        px = QPixmap.fromImage(qi).scaled(
            self._video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._video_label.setPixmap(px)
        self._info_label.setText(f"{w}×{h}")
        if detected:
            ids_str = ", ".join(f"#{d.marker_id}" for d in detected)
            self._det_label.setText(f"Маркеры: {ids_str}")
        else:
            self._det_label.setText("Маркеры: —")
