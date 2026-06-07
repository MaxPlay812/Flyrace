from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List
import numpy as np

try:
    import cv2

    _CV2_OK = True
    try:
        _DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        _PARAMS = cv2.aruco.DetectorParameters()
        _DETECTOR = cv2.aruco.ArucoDetector(_DICT, _PARAMS)
        _NEW_API = True
    except AttributeError:
        _DICT = cv2.aruco.Dictionary_get(cv2.aruco.DICT_4X4_50)
        _PARAMS = cv2.aruco.DetectorParameters_create()
        _DETECTOR = None
        _NEW_API = False
    _ARUCO_OK = True
except ImportError:
    _CV2_OK = False
    _ARUCO_OK = False


@dataclass
class DetectedMarker:
    marker_id: int
    corners: np.ndarray  # shape (4, 2) pixel coords
    center: tuple  # (px, py)
    rvec: Optional[np.ndarray] = None
    tvec: Optional[np.ndarray] = None
    distance: Optional[float] = None


def generate_marker_image(marker_id: int, size_px: int = 200) -> Optional[np.ndarray]:
    """Render an ArUco marker as a numpy image for display or printing."""
    if not _CV2_OK or not _ARUCO_OK:
        return None
    img = np.zeros((size_px, size_px), dtype=np.uint8)
    try:
        if _NEW_API:
            img = cv2.aruco.generateImageMarker(_DICT, marker_id, size_px)
        else:
            img = cv2.aruco.drawMarker(_DICT, marker_id, size_px)
    except Exception:
        return None
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def generate_printable_marker(
    marker_id: int, size_mm: float, dpi: int = 300
) -> Optional[np.ndarray]:
    """Render a print-ready marker: true-to-scale glyph, white quiet zone,
    a thin cut border and a caption with id and physical size.

    The marker glyph is rendered at ``size_mm`` for the given ``dpi`` so the
    printed square measures exactly ``size_mm`` on paper. Returns a BGR image.
    """
    if not _CV2_OK or not _ARUCO_OK:
        return None
    px_per_mm = dpi / 25.4
    glyph_px = max(60, int(round(size_mm * px_per_mm)))
    glyph = generate_marker_image(marker_id, glyph_px)
    if glyph is None:
        return None

    quiet = max(12, glyph_px // 8)  # white quiet zone (>= 1 module recommended)
    cap_h = max(36, glyph_px // 6)  # space for the caption strip
    full = glyph_px + 2 * quiet
    canvas = np.full((full + cap_h, full, 3), 255, dtype=np.uint8)
    canvas[quiet : quiet + glyph_px, quiet : quiet + glyph_px] = glyph

    # Thin cut border around the quiet zone
    cv2.rectangle(canvas, (1, 1), (full - 2, full - 2), (180, 180, 180), 1)
    label = f"ArUco 4x4  ID={marker_id}   {size_mm:.0f}x{size_mm:.0f} mm"
    cv2.putText(
        canvas,
        label,
        (quiet, full + cap_h - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        max(0.4, glyph_px / 700.0),
        (0, 0, 0),
        max(1, glyph_px // 300),
        cv2.LINE_AA,
    )
    return canvas


class ArucoDetector:
    """Detects ArUco markers in a camera frame and optionally estimates pose."""

    def __init__(
        self,
        camera_matrix: Optional[np.ndarray] = None,
        dist_coeffs: Optional[np.ndarray] = None,
        marker_size_m: float = 0.15,
    ):
        self.camera_matrix = camera_matrix
        self.dist_coeffs = dist_coeffs if dist_coeffs is not None else np.zeros(5)
        self.marker_size_m = marker_size_m
        self.available = _ARUCO_OK

    def detect(self, frame: np.ndarray) -> List[DetectedMarker]:
        if not self.available or frame is None:
            return []
        from utils.cuda import bgr2gray

        gray = bgr2gray(frame)
        if _NEW_API:
            corners, ids, _ = _DETECTOR.detectMarkers(gray)
        else:
            corners, ids, _ = cv2.aruco.detectMarkers(gray, _DICT, parameters=_PARAMS)
        if ids is None:
            return []

        results: List[DetectedMarker] = []
        for i, mid in enumerate(ids.flatten()):
            c = corners[i][0]
            cx = int(c[:, 0].mean())
            cy = int(c[:, 1].mean())
            dm = DetectedMarker(marker_id=int(mid), corners=c, center=(cx, cy))
            if self.camera_matrix is not None:
                try:
                    rvec, tvec, _ = cv2.aruco.estimatePoseSingleMarkers(
                        corners[i],
                        self.marker_size_m,
                        self.camera_matrix,
                        self.dist_coeffs,
                    )
                    dm.rvec = rvec[0][0]
                    dm.tvec = tvec[0][0]
                    dm.distance = float(np.linalg.norm(tvec[0][0]))
                except Exception:
                    # Pose is optional — keep the 2-D detection without it.
                    pass
            results.append(dm)
        return results

    def draw_markers(
        self, frame: np.ndarray, detected: List[DetectedMarker]
    ) -> np.ndarray:
        if not detected:
            return frame
        out = frame.copy()
        for dm in detected:
            pts = dm.corners.reshape((-1, 1, 2)).astype(int)
            cv2.polylines(out, [pts], True, (0, 255, 0), 2)
            cv2.circle(out, dm.center, 4, (0, 255, 0), -1)
            label = f"ID:{dm.marker_id}"
            if dm.distance is not None:
                label += f"  {dm.distance:.2f}m"
            cv2.putText(
                out,
                label,
                (dm.center[0] + 6, dm.center[1] - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                2,
            )
        return out
