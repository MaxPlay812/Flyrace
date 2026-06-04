from __future__ import annotations
import math
from typing import List, Optional

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QAction, QMenu, QWidget

from config import FIELD_FILE, FIELD_H, FIELD_W, POLE_DIAMETER
from models.field import FieldConfig
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
_HIT_PX = 14  # click tolerance for grabbing poles / handle


class MapWidget(QWidget):
    """Top-down 2-D field map with drone position and ArUco markers.

    The ∞ track is editable: drag the poles to move the loops, drag the
    orange handle at the loop tip (or use the wheel) to resize them. Changes
    persist to ``field.json``.
    """

    marker_add_requested = pyqtSignal(float, float)  # field x, y [mm]
    marker_selected = pyqtSignal(int)  # marker_id
    field_changed = pyqtSignal()  # poles or loop size edited

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self._field = FieldConfig.load(FIELD_FILE)
        self._markers: List[ArucoMarker] = []
        self._drone_x: Optional[float] = None  # mm
        self._drone_y: Optional[float] = None
        self._drone_yaw: float = 0.0
        self._selected_id: Optional[int] = None
        self._add_mode: bool = False
        self._lap_path: List[QPointF] = []
        self._trail: List[QPointF] = []
        self._max_trail = 300
        # Drag state: None, ("pole", 0|1) or ("handle", None)
        self._drag: Optional[tuple] = None

    @property
    def field(self) -> FieldConfig:
        return self._field

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

    def reset_field(self):
        """Restore the regulation pole layout and loop size, then persist."""
        self._field.reset()
        self._field.save(FIELD_FILE)
        self.field_changed.emit()
        self.update()

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
        """Draw the ∞ track (Bernoulli lemniscate) from the field config."""
        s, _, _ = self._transform()
        pts = self._field.lemniscate_points()
        if not pts:
            return
        path = QPainterPath()
        for i, (x_mm, y_mm) in enumerate(pts):
            wp = self._f2w(x_mm, y_mm)
            if i == 0:
                path.moveTo(wp)
            else:
                path.lineTo(wp)
        path.closeSubpath()

        dash_px = max(1.0, 300 * s)
        gap_px = max(1.0, 100 * s)
        line_w = max(1.0, 50 * s)
        pen = QPen(QColor(230, 220, 70, 200), line_w)
        pen.setDashPattern([dash_px / line_w, gap_px / line_w])
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _paint_poles(self, p: QPainter):
        s, _, _ = self._transform()
        r = max(5.0, POLE_DIAMETER / 2 * s)
        poles = (self._field.pole1, self._field.pole2)
        for i, (px, py) in enumerate(poles):
            c = self._f2w(px, py)
            grabbed = self._drag == ("pole", i)
            p.setPen(QPen(Qt.white if grabbed else QColor(200, 200, 200), 2))
            p.setBrush(
                QBrush(QColor(190, 190, 190) if grabbed else QColor(160, 160, 160))
            )
            p.drawEllipse(c, r, r)
            p.setPen(QColor(225, 225, 225))
            p.setFont(sans_font(7))
            p.drawText(c + QPointF(-6, -r - 3), f"P{i + 1}")

        # Resize handle at the loop tip
        tx, ty = self._field.tip_point()
        hc = self._f2w(tx, ty)
        grabbed = self._drag == ("handle", None)
        p.setPen(QPen(Qt.white if grabbed else QColor(240, 160, 40), 2))
        p.setBrush(QBrush(QColor(240, 160, 40, 200)))
        hr = 6.0
        p.drawEllipse(hc, hr, hr)
        p.setPen(QColor(240, 160, 40))
        p.setFont(sans_font(7))
        p.drawText(hc + QPointF(hr + 2, 3), "R")

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
    def _hit_track_element(self, wx: float, wy: float) -> Optional[tuple]:
        """Return ('handle', None) or ('pole', i) if (wx, wy) grabs it."""
        hc = self._f2w(*self._field.tip_point())
        if math.hypot(wx - hc.x(), wy - hc.y()) <= _HIT_PX:
            return ("handle", None)
        for i, (px, py) in enumerate((self._field.pole1, self._field.pole2)):
            c = self._f2w(px, py)
            if math.hypot(wx - c.x(), wy - c.y()) <= _HIT_PX:
                return ("pole", i)
        return None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        wx, wy = event.x(), event.y()
        fx, fy = self._w2f(wx, wy)

        if self._add_mode and 0 <= fx <= FIELD_W and 0 <= fy <= FIELD_H:
            self.marker_add_requested.emit(fx, fy)
            return

        # Grab a pole or the resize handle for dragging
        hit = self._hit_track_element(wx, wy)
        if hit is not None:
            self._drag = hit
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            return

        for m in self._markers:
            c = self._f2w(m.x, m.y)
            if math.hypot(wx - c.x(), wy - c.y()) < 18:
                self._selected_id = m.marker_id
                self.marker_selected.emit(m.marker_id)
                self.update()
                return
        self._selected_id = None
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        fx, fy = self._w2f(event.x(), event.y())
        kind, idx = self._drag
        if kind == "pole":
            fx = max(0.0, min(float(FIELD_W), fx))
            fy = max(0.0, min(float(FIELD_H), fy))
            self._field.set_pole(idx, fx, fy)
        elif kind == "handle":
            cx, cy = self._field.center
            self._field.set_tip_distance(math.hypot(fx - cx, fy - cy))
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is None:
            return
        self._drag = None
        self.setCursor(Qt.ArrowCursor)
        self._field.save(FIELD_FILE)
        self.field_changed.emit()
        self.update()

    def wheelEvent(self, event):
        """Scroll over the map to resize the loops."""
        step = 1.0 + (0.1 if event.angleDelta().y() > 0 else -0.1)
        self._field.set_loop_scale(self._field.loop_scale * step)
        self._field.save(FIELD_FILE)
        self.field_changed.emit()
        self.update()

    def contextMenuEvent(self, event):
        fx, fy = self._w2f(event.x(), event.y())
        menu = QMenu(self)
        add_act = QAction(f"Добавить маркер ({int(fx)}, {int(fy)} мм)", self)
        add_act.triggered.connect(lambda: self.marker_add_requested.emit(fx, fy))
        menu.addAction(add_act)
        reset_act = QAction("Сбросить поле к регламенту", self)
        reset_act.triggered.connect(self.reset_field)
        menu.addAction(reset_act)
        menu.addSeparator()
        clear_act = QAction("Очистить след", self)
        clear_act.triggered.connect(self.clear_trail)
        menu.addAction(clear_act)
        menu.exec_(event.globalPos())
