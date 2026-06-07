"""Dashed track-line detection for line-following.

The race track is a bright dashed line (see config DASH_LEN/GAP_LEN). This
module bridges the dashes into a continuous centerline, fits its direction,
and reports the lateral offset and heading error the drone needs to stay on
it — *without* yawing. When two dashes cross near the image centre (an
intersection of the ∞ track) the result is flagged ``crossing`` so the
follower keeps flying straight instead of turning.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

try:
    import cv2

    _CV2_OK = True
except ImportError:
    _CV2_OK = False


@dataclass
class LineResult:
    found: bool = False
    offset_norm: float = 0.0  # lateral offset of line at image bottom, -1..1
    angle_deg: float = 0.0  # heading error vs. straight-up, +right
    crossing: bool = False  # two dashes intersect near centre → go straight
    centerline: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None
    mask_contours: List[np.ndarray] = field(default_factory=list)


class LineDetector:
    """Detects the dashed centerline and the lateral/heading error to it."""

    def __init__(self, dark_line: bool = False):
        # dark_line=True for a dark line on a light floor; False for a bright
        # line on a dark floor (the default field rendering).
        self.dark_line = dark_line
        self.available = _CV2_OK

    # ------------------------------------------------------------------ mask
    def _binary_mask(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        ttype = cv2.THRESH_BINARY_INV if self.dark_line else cv2.THRESH_BINARY
        _, mask = cv2.threshold(gray, 0, 255, ttype | cv2.THRESH_OTSU)
        # Bridge the gaps between dashes into one continuous line.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        return mask

    # --------------------------------------------------------------- detect
    def detect(self, frame: np.ndarray) -> LineResult:
        if not self.available or frame is None:
            return LineResult()
        h, w = frame.shape[:2]
        mask = self._binary_mask(frame)

        cnts, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        min_area = (h * w) * 0.002
        cnts = [c for c in cnts if cv2.contourArea(c) >= min_area]
        if not cnts:
            return LineResult()

        pts = np.vstack(cnts).reshape(-1, 2).astype(np.float32)
        # Fit the dominant line direction through every line pixel.
        vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01).flatten()
        if abs(vy) < 1e-6:
            vy = 1e-6
        # Point where the centerline crosses the image bottom row.
        t_bot = (h - 1 - y0) / vy
        x_bot = x0 + vx * t_bot
        t_top = (0 - y0) / vy
        x_top = x0 + vx * t_top

        offset_norm = float((x_bot - w / 2.0) / (w / 2.0))
        offset_norm = max(-1.0, min(1.0, offset_norm))
        angle_deg = float(np.degrees(np.arctan2(vx, -vy)))
        if angle_deg > 90:
            angle_deg -= 180
        elif angle_deg < -90:
            angle_deg += 180

        crossing = self._detect_crossing(mask, w, h)

        return LineResult(
            found=True,
            offset_norm=offset_norm,
            angle_deg=angle_deg,
            crossing=crossing,
            centerline=((int(x_top), 0), (int(x_bot), h - 1)),
            mask_contours=cnts,
        )

    def _detect_crossing(self, mask: np.ndarray, w: int, h: int) -> bool:
        """Two dashes cross near the centre when Hough finds two distinct
        line orientations whose angular spread is large."""
        edges = cv2.Canny(mask, 50, 150)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=int(0.4 * min(w, h)))
        if lines is None or len(lines) < 2:
            return False
        thetas = np.array([ln[0][1] for ln in lines])
        spread = thetas.max() - thetas.min()
        # ~> 35° between the two strongest orientations ≈ an X crossing.
        return bool(np.degrees(spread) > 35.0)

    # ---------------------------------------------------------------- draw
    def draw(self, frame: np.ndarray, res: LineResult) -> np.ndarray:
        if not self.available:
            return frame
        out = frame.copy()
        h, w = out.shape[:2]
        cv2.drawContours(out, res.mask_contours, -1, (60, 200, 60), 1)
        # Reference vertical (desired straight-ahead path)
        cv2.line(out, (w // 2, 0), (w // 2, h - 1), (90, 90, 90), 1)
        if res.found and res.centerline:
            (xt, yt), (xb, yb) = res.centerline
            color = (0, 180, 255) if res.crossing else (0, 255, 255)
            cv2.line(out, (xt, yt), (xb, yb), color, 3)
            cv2.circle(out, (xb, yb), 6, (0, 0, 255), -1)
        status = "—"
        if res.found:
            status = "ПРЯМО (перекрёсток)" if res.crossing else "ЛИНИЯ"
        cv2.putText(
            out,
            f"{status}  off={res.offset_norm:+.2f}  ang={res.angle_deg:+.0f}",
            (8, h - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        return out
