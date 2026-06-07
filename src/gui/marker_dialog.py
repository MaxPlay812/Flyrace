from __future__ import annotations
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
import importlib.util

from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from PyQt5.QtWidgets import QFileDialog, QMessageBox

from models.marker import ArucoMarker, ZoneType, save_markers
from vision.aruco_detector import generate_marker_image, generate_printable_marker
from config import DEFAULT_MARKER_SIZE, FIELD_W, FIELD_H, MARKERS_FILE

_CV2_OK = importlib.util.find_spec("cv2") is not None


class MarkerEditDialog(QDialog):
    """Create or edit a single ArUco marker configuration."""

    def __init__(
        self,
        marker: Optional[ArucoMarker] = None,
        x: float = 0.0,
        y: float = 0.0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Маркер ArUco")
        self.setMinimumWidth(340)
        self._result_marker: Optional[ArucoMarker] = None
        self._build_ui(marker, x, y)

    def _build_ui(self, m: Optional[ArucoMarker], x: float, y: float):
        lay = QVBoxLayout(self)

        form = QFormLayout()
        form.setSpacing(6)

        self._spin_id = QSpinBox()
        self._spin_id.setRange(0, 49)
        self._spin_id.setValue(m.marker_id if m else 0)
        form.addRow("ID маркера (0–49):", self._spin_id)

        self._spin_x = QDoubleSpinBox()
        self._spin_x.setRange(0, FIELD_W)
        self._spin_x.setValue(m.x if m else x)
        self._spin_x.setSuffix(" мм")
        form.addRow("X на поле:", self._spin_x)

        self._spin_y = QDoubleSpinBox()
        self._spin_y.setRange(0, FIELD_H)
        self._spin_y.setValue(m.y if m else y)
        self._spin_y.setSuffix(" мм")
        form.addRow("Y на поле:", self._spin_y)

        self._spin_size = QDoubleSpinBox()
        self._spin_size.setRange(30, 500)
        self._spin_size.setValue(m.size if m else DEFAULT_MARKER_SIZE)
        self._spin_size.setSuffix(" мм")
        form.addRow("Физ. размер:", self._spin_size)

        self._combo_zone = QComboBox()
        for zt in ZoneType:
            self._combo_zone.addItem(zt.label(), zt)
        if m:
            idx = list(ZoneType).index(m.zone_type)
            self._combo_zone.setCurrentIndex(idx)
        form.addRow("Тип зоны:", self._combo_zone)

        self._spin_speed = QDoubleSpinBox()
        self._spin_speed.setRange(0.1, 2.5)
        self._spin_speed.setSingleStep(0.1)
        self._spin_speed.setValue(m.speed_value if m else 0.5)
        self._spin_speed.setSuffix(" м/с")
        form.addRow("Скорость в зоне:", self._spin_speed)

        self._edit_label = QLineEdit(m.label if m else "")
        form.addRow("Подпись:", self._edit_label)

        lay.addLayout(form)

        # Marker preview
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setFixedSize(120, 120)
        self._preview_label.setStyleSheet("background:#222;border:1px solid #555")
        lay.addWidget(self._preview_label, alignment=Qt.AlignCenter)
        self._spin_id.valueChanged.connect(self._refresh_preview)
        self._refresh_preview()

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _refresh_preview(self):
        mid = self._spin_id.value()
        img = generate_marker_image(mid, 100)
        if img is not None:
            h, w = img.shape[:2]
            if _CV2_OK:
                import cv2

                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            else:
                rgb = img
            qi = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
            px = QPixmap.fromImage(qi).scaled(110, 110, Qt.KeepAspectRatio)
            self._preview_label.setPixmap(px)

    def _on_accept(self):
        self._result_marker = ArucoMarker(
            marker_id=self._spin_id.value(),
            x=self._spin_x.value(),
            y=self._spin_y.value(),
            size=self._spin_size.value(),
            zone_type=self._combo_zone.currentData(),
            speed_value=self._spin_speed.value(),
            label=self._edit_label.text().strip(),
        )
        self.accept()

    def get_marker(self) -> Optional[ArucoMarker]:
        return self._result_marker


class MarkerManagerWidget(QWidget):
    """Panel to list, add, edit, remove ArUco markers and save to JSON."""

    markers_changed = pyqtSignal(list)  # list[ArucoMarker]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._markers: List[ArucoMarker] = []
        self._build_ui()

    def set_markers(self, markers: List[ArucoMarker]):
        self._markers = list(markers)
        self._refresh_list()
        self.markers_changed.emit(self._markers)

    def add_marker_at(self, x: float, y: float):
        """Open dialog pre-filled with map click position."""
        dlg = MarkerEditDialog(x=x, y=y, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            m = dlg.get_marker()
            if m:
                self._markers = [
                    mk for mk in self._markers if mk.marker_id != m.marker_id
                ]
                self._markers.append(m)
                self._refresh_list()
                self.markers_changed.emit(self._markers)
                save_markers(MARKERS_FILE, self._markers)

    # ---------------------------------------------------------- layout
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._on_edit)
        lay.addWidget(self._list, 1)

        btns = QHBoxLayout()
        btn_add = QPushButton("Добавить")
        btn_add.clicked.connect(self._on_add)
        btn_edit = QPushButton("Изменить")
        btn_edit.clicked.connect(self._on_edit)
        btn_del = QPushButton("Удалить")
        btn_del.clicked.connect(self._on_delete)
        btn_print = QPushButton("Показать маркер")
        btn_print.clicked.connect(self._on_show_marker)
        for b in (btn_add, btn_edit, btn_del, btn_print):
            btns.addWidget(b)
        lay.addLayout(btns)

        save_row = QHBoxLayout()
        btn_save_one = QPushButton("Сохранить для печати…")
        btn_save_one.clicked.connect(self._on_save_marker)
        btn_save_all = QPushButton("Сохранить все…")
        btn_save_all.clicked.connect(self._on_save_all)
        for b in (btn_save_one, btn_save_all):
            save_row.addWidget(b)
        lay.addLayout(save_row)

    def _refresh_list(self):
        self._list.clear()
        for m in sorted(self._markers, key=lambda x: x.marker_id):
            text = (
                f"#{m.marker_id:2d}  [{m.zone_type.label()}]  "
                f"({int(m.x)}, {int(m.y)}) мм  {m.speed_value:.1f} м/с"
                + (f"  «{m.label}»" if m.label else "")
            )
            self._list.addItem(QListWidgetItem(text))

    def _selected_marker(self) -> Optional[ArucoMarker]:
        row = self._list.currentRow()
        if row < 0:
            return None
        sorted_m = sorted(self._markers, key=lambda x: x.marker_id)
        return sorted_m[row] if row < len(sorted_m) else None

    def _on_add(self):
        self.add_marker_at(2000.0, 1500.0)

    def _on_edit(self, *_):
        m = self._selected_marker()
        if not m:
            return
        dlg = MarkerEditDialog(m, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            nm = dlg.get_marker()
            if nm:
                self._markers = [
                    mk for mk in self._markers if mk.marker_id != nm.marker_id
                ]
                self._markers.append(nm)
                self._refresh_list()
                self.markers_changed.emit(self._markers)
                save_markers(MARKERS_FILE, self._markers)

    def _on_delete(self):
        m = self._selected_marker()
        if not m:
            return
        self._markers = [mk for mk in self._markers if mk.marker_id != m.marker_id]
        self._refresh_list()
        self.markers_changed.emit(self._markers)
        save_markers(MARKERS_FILE, self._markers)

    def _on_show_marker(self):
        m = self._selected_marker()
        if not m:
            return
        img = generate_marker_image(m.marker_id, 400)
        if img is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Маркер #{m.marker_id} — {m.size:.0f}мм")
        v = QVBoxLayout(dlg)
        lbl = QLabel()
        if _CV2_OK:
            import cv2

            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            qi = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
            lbl.setPixmap(QPixmap.fromImage(qi))
        v.addWidget(lbl)
        hint = QLabel(f"Распечатайте маркер размером {m.size:.0f}×{m.size:.0f} мм")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)
        dlg.exec_()

    def _on_save_marker(self):
        """Export the selected marker as a print-ready PNG (true to scale)."""
        m = self._selected_marker()
        if not m:
            QMessageBox.information(self, "Печать", "Сначала выберите маркер в списке.")
            return
        if not _CV2_OK:
            QMessageBox.warning(self, "Печать", "OpenCV недоступен.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить маркер", f"aruco_{m.marker_id}.png", "PNG (*.png)"
        )
        if not path:
            return
        img = generate_printable_marker(m.marker_id, m.size)
        import cv2

        if img is None or not cv2.imwrite(path, img):
            QMessageBox.warning(self, "Печать", "Не удалось сохранить изображение.")
            return
        QMessageBox.information(
            self, "Печать", f"Сохранено: {path}\nПечатайте 1:1 без масштабирования."
        )

    def _on_save_all(self):
        """Export every configured marker into a chosen folder."""
        if not self._markers:
            QMessageBox.information(self, "Печать", "Нет маркеров для сохранения.")
            return
        if not _CV2_OK:
            QMessageBox.warning(self, "Печать", "OpenCV недоступен.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Папка для маркеров")
        if not folder:
            return
        import os
        import cv2

        saved = 0
        for m in self._markers:
            img = generate_printable_marker(m.marker_id, m.size)
            if img is None:
                continue
            out = os.path.join(folder, f"aruco_{m.marker_id}_{int(m.size)}mm.png")
            if cv2.imwrite(out, img):
                saved += 1
        QMessageBox.information(
            self, "Печать", f"Сохранено маркеров: {saved} в {folder}"
        )
