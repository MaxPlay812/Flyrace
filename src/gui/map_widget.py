from __future__ import annotations
import math
from typing import List, Optional

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QAction, QMenu, QWidget

from config import FIELD_H, FIELD_W, POLE_1, POLE_2, POLE_DIAMETER
from models.marker import ArucoMarker, ZoneType
from utils.compat import mono_font, sans_font

_ZONE_COLOR = {
    ZoneType.NORMAL: QColor(80, 130, 255, 200),
    ZoneType.ACCELERATE: QColor(50, 220, 50, 210),
    ZoneType.DECELERATE: QColor(240, 60, 60, 210),
    ZoneType.WAYPOINT: QColor(240, 190, 40, 210),
    ZoneType.START: QColor(190, 50, 200, 210),
}
_MARGIN = 24


class MapWidget(QWidget):
    """Top-down 2-D field map with drone position and ArUco markers."""

    marker_add_requested = pyqtSignal(float, float)  # field x, y [mm]
    marker_selected = pyqtSignal(int)  # marker_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self._markers: List[ArucoMarker] = []
        self._drone_x: Optional[float] = None  # mm
        self._drone_y: Optional[float] = None
        self._drone_yaw: float = 0.0
        self._selected_id: Optional[int] = None
        self._add_mode: bool = False
        self._lap_path: List[QPointF] = []
        self._trail: List[QPointF] = []
        self._max_trail = 300

    # --------------------------------------------------- public setters
    def set_markers(self, markers: List[ArucoMarker]):
        self._markers = markers
        self.update()

    def set_drone_position(self, x_m: float, y_m: float, yaw: float = 0.0):
        self._drone_x = x_m * 1000.0
        self._drone_y = y_m * 1000.0
        self._drone_yaw = yaw
        pt = self._f2w(self._drone_x, self._drone_y)
        self._trail.append(pt)
        if len(self._trail) > self._max_trail:
            self._trail.pop(0)
        self.update()

    def clear_trail(self):
        self._trail.clear()
        self.update()

    def set_add_mode(self, enabled: bool):
        self._add_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    # ------------------------------------------- coordinate conversion
    def _transform(self):
        """Returns (scale, ox, oy): field_mm * scale + offset = widget_px."""
        aw = self.width() - 2 * _MARGIN
        ah = self.height() - 2 * _MARGIN
        scale = min(aw / FIELD_W, ah / FIELD_H)
        ox = _MARGIN + (aw - FIELD_W * scale) / 2.0
        oy = _MARGIN + (ah - FIELD_H * scale) / 2.0
        return scale, ox, oy

    def _f2w(self, fx: float, fy: float) -> QPointF:
        s, ox, oy = self._transform()
        return QPointF(ox + fx * s, oy + (FIELD_H - fy) * s)

    def _w2f(self, wx: float, wy: float) -> tuple:
        s, ox, oy = self._transform()
        return (wx - ox) / s, FIELD_H - (wy - oy) / s

    # --------------------------------------------------- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint_field(p)
        self._paint_track(p)
        self._paint_poles(p)
        self._paint_trail(p)
        self._paint_markers(p)
        self._paint_drone(p)
        self._paint_legend(p)
        p.end()

    def _paint_field(self, p: QPainter):
        tl = self._f2w(0, FIELD_H)
        br = self._f2w(FIELD_W, 0)
        rect = QRectF(tl, br)
        p.fillRect(rect, QColor(28, 38, 28))
        # Grid 500 mm
        p.setPen(QPen(QColor(50, 65, 50), 1, Qt.DotLine))
        for gx in range(0, FIELD_W + 1, 500):
            p.drawLine(self._f2w(gx, 0), self._f2w(gx, FIELD_H))
        for gy in range(0, FIELD_H + 1, 500):
            p.drawLine(self._f2w(0, gy), self._f2w(FIELD_W, gy))
        # Border
        p.setPen(QPen(QColor(100, 140, 100), 2))
        p.drawRect(rect)
        # Axis labels
        p.setPen(QColor(90, 110, 90))
        p.setFont(mono_font(7))
        for gx in range(0, FIELD_W + 1, 500):
            pt = self._f2w(gx, 0)
            p.drawText(QPointF(pt.x() - 10, pt.y() + 14), f"{gx}")
        for gy in range(0, FIELD_H + 1, 500):
            pt = self._f2w(0, gy)
            p.drawText(QPointF(pt.x() - 36, pt.y() + 4), f"{gy}")

    def _paint_track(self, p: QPainter):
        """Lemniscate of Bernoulli centred between the poles.

        Parametric form: x = a√2·cos(t)/(sin²t+1),  y = a√2·cos(t)sin(t)/(sin²t+1)
        Each loop's centroid lies at distance a·π/4 from the centre, so
        a = half·4/π makes the loop centres coincide exactly with the poles
        ("столбы в центрах окружностей").
        """
        s, _, _ = self._transform()

        cx   = (POLE_1[0] + POLE_2[0]) / 2.0
        cy   = (POLE_1[1] + POLE_2[1]) / 2.0
        half = (POLE_2[0] - POLE_1[0]) / 2.0       # pole offset from centre
        a    = half * 4.0 / math.pi                # loop centroids ↔ poles

        N = 600
        path = QPainterPath()
        for i in range(N + 1):
            t     = 2.0 * math.pi * i / N
            denom = math.sin(t) ** 2 + 1.0
            x_mm  = cx + a * math.sqrt(2) * math.cos(t) / denom
            y_mm  = cy + a * math.sqrt(2) * math.cos(t) * math.sin(t) / denom
            pt = self._f2w(x_mm, y_mm)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()

        dash_px = max(1.0, 300 * s)
        gap_px  = max(1.0, 100 * s)
        line_w  = max(1.0,  50 * s)
        pen = QPen(QColor(230, 220, 70, 200), line_w)
        pen.setDashPattern([dash_px / line_w, gap_px / line_w])
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _paint_poles(self, p: QPainter):
        s, _, _ = self._transform()
        r = max(4.0, POLE_DIAMETER / 2 * s)
        p.setPen(QPen(QColor(200, 200, 200), 1))
        p.setBrush(QBrush(QColor(160, 160, 160)))
        for px, py in (POLE_1, POLE_2):
            c = self._f2w(px, py)
            p.drawEllipse(c, r, r)
        p.setPen(QColor(220, 220, 220))
        p.setFont(sans_font(7))
        for i, (px, py) in enumerate((POLE_1, POLE_2), 1):
            c = self._f2w(px, py)
            p.drawText(c + QPointF(-6, -r - 3), f"P{i}")

    def _paint_trail(self, p: QPainter):
        if len(self._trail) < 2:
            return
        p.setPen(QPen(QColor(60, 130, 220, 100), 1))
        for i in range(1, len(self._trail)):
            p.drawLine(self._trail[i - 1], self._trail[i])

    def _paint_markers(self, p: QPainter):
        s, _, _ = self._transform()
        font = sans_font(max(7, int(8 * s * 3)))
        p.setFont(font)
        for m in self._markers:
            c = self._f2w(m.x, m.y)
            r = max(7.0, m.size * s * 0.35)
            color = _ZONE_COLOR.get(m.zone_type, QColor(80, 130, 255))
            is_sel = m.marker_id == self._selected_id
            pen_color = Qt.white if is_sel else QColor(180, 180, 180)
            p.setPen(QPen(pen_color, 2 if is_sel else 1))
            p.setBrush(QBrush(color))
            p.drawRect(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
            p.setPen(QPen(Qt.white, 1))
            p.drawText(
                c + QPointF(-r + 2, r - 3),
                f"#{m.marker_id}" + (f" {m.label}" if m.label else ""),
            )
            p.setPen(QPen(QColor(200, 200, 100), 1))
            p.drawText(c + QPointF(-r + 2, r + 12), m.zone_type.label())

    def _paint_drone(self, p: QPainter):
        if self._drone_x is None:
            return
        s, _, _ = self._transform()
        c = self._f2w(self._drone_x, self._drone_y)
        r = max(6.0, 160 * s)
        # Shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 80)))
        p.drawEllipse(c + QPointF(2, 2), r, r)
        # Body
        p.setPen(QPen(Qt.white, 1))
        p.setBrush(QBrush(QColor(50, 160, 255, 230)))
        p.drawEllipse(c, r, r)
        # Direction arrow
        yaw = self._drone_yaw
        tip = c + QPointF(math.sin(yaw) * r * 1.7, -math.cos(yaw) * r * 1.7)
        p.setPen(QPen(QColor(255, 240, 50), 2))
        p.drawLine(c, tip)

    def _paint_legend(self, p: QPainter):
        items = [(c, zt.label()) for zt, c in _ZONE_COLOR.items()]
        x0, y0 = 6, 6
        p.setFont(sans_font(8))
        for i, (color, lbl) in enumerate(items):
            y = y0 + i * 16
            p.fillRect(QRectF(x0, y, 12, 11), color)
            p.setPen(QColor(200, 200, 200))
            p.drawText(x0 + 15, y + 10, lbl)

    # --------------------------------------------------- mouse events
    def mousePressEvent(self, event):
        fx, fy = self._w2f(event.x(), event.y())
        if event.button() == Qt.LeftButton:
            if self._add_mode and 0 <= fx <= FIELD_W and 0 <= fy <= FIELD_H:
                self.marker_add_requested.emit(fx, fy)
                return
            for m in self._markers:
                c = self._f2w(m.x, m.y)
                if math.hypot(event.x() - c.x(), event.y() - c.y()) < 18:
                    self._selected_id = m.marker_id
                    self.marker_selected.emit(m.marker_id)
                    self.update()
                    return
            self._selected_id = None
            self.update()

    def contextMenuEvent(self, event):
        fx, fy = self._w2f(event.x(), event.y())
        menu = QMenu(self)
        add_act = QAction(f"Добавить маркер ({int(fx)}, {int(fy)} мм)", self)
        add_act.triggered.connect(lambda: self.marker_add_requested.emit(fx, fy))
        menu.addAction(add_act)
        menu.addSeparator()
        clear_act = QAction("Очистить след", self)
        clear_act.triggered.connect(self.clear_trail)
        menu.addAction(clear_act)
        menu.exec_(event.globalPos())
