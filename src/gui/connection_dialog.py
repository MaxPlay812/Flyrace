"""ROS connection settings and diagnostics dialog."""
from __future__ import annotations
import os
import threading

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                              QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QScrollArea, QTextEdit,
                              QVBoxLayout, QWidget)

from drone.controller import RosState, run_ros_diagnostics, _ROSPY_OK, _CLOVER_OK


_INSTALL_GUIDE = """\
═══ КАК ПОДКЛЮЧИТЬ ВНЕШНИЙ UBUNTU-ПК К CLOVER 4 ═══

1. Установите ROS Noetic (если ещё нет):
   https://wiki.ros.org/noetic/Installation/Ubuntu

2. Установите пакет clover одним из способов:

   А) Бинарник (рекомендуется):
      sudo apt install ros-noetic-clover
      — или —
      pip install clover  # если есть PyPI-пакет

   Б) Из исходников:
      mkdir -p ~/catkin_ws/src && cd ~/catkin_ws/src
      git clone https://github.com/clover-robotics/clover.git
      cd ~/catkin_ws && catkin_make
      source ~/catkin_ws/devel/setup.bash

3. Добавьте в ~/.bashrc (или ~/.zshrc):
      source /opt/ros/noetic/setup.bash
      source ~/catkin_ws/devel/setup.bash   # если собирали из исходников
      export ROS_MASTER_URI=http://192.168.11.1:11311
      export ROS_IP=$(hostname -I | awk '{print $1}')

4. Подключитесь к WiFi дрона:
      SSID:  clover-XXXX
      пароль: cloverwifi

5. Перезапустите приложение.
"""


class DiagRow(QWidget):
    def __init__(self, label: str, value: str, ok: bool, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        indicator = QLabel("✓" if ok else "✗")
        indicator.setStyleSheet(
            f"color: {'#6f6' if ok else '#f66'}; font-weight: bold; min-width: 16px;")
        lbl = QLabel(label)
        lbl.setMinimumWidth(180)
        val = QLabel(value)
        val.setStyleSheet("color: #aaa; font-size: 11px;")
        lay.addWidget(indicator)
        lay.addWidget(lbl)
        lay.addWidget(val, 1)


class ConnectionDialog(QDialog):
    reconnect_requested = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle("Настройки ROS / Подключение к дрону")
        self.setMinimumSize(560, 500)
        self._build_ui()
        self._run_diag()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        # ── Environment settings ──────────────────────────────────────────
        env_gb = QGroupBox("Переменные окружения ROS")
        form = QFormLayout(env_gb)

        self._uri_edit = QLineEdit(
            os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311"))
        self._ip_edit = QLineEdit(
            os.environ.get("ROS_IP", os.environ.get("ROS_HOSTNAME", "")))
        self._ip_edit.setPlaceholderText("Ваш IP на WiFi дрона (напр. 192.168.11.100)")

        form.addRow("ROS_MASTER_URI:", self._uri_edit)
        form.addRow("ROS_IP:", self._ip_edit)

        apply_btn = QPushButton("Применить и переподключить")
        apply_btn.clicked.connect(self._on_apply)
        form.addRow("", apply_btn)
        lay.addWidget(env_gb)

        # ── Diagnostics ───────────────────────────────────────────────────
        diag_gb = QGroupBox("Диагностика")
        self._diag_lay = QVBoxLayout(diag_gb)
        self._diag_lay.setSpacing(2)
        self._diag_msg = QLabel("Проверка…")
        self._diag_msg.setStyleSheet("color: #aaa; font-size: 11px;")
        self._diag_lay.addWidget(self._diag_msg)
        self._diag_area = QWidget()
        self._diag_area_lay = QVBoxLayout(self._diag_area)
        self._diag_area_lay.setContentsMargins(0, 0, 0, 0)
        self._diag_area_lay.setSpacing(2)
        self._diag_lay.addWidget(self._diag_area)

        recheck_btn = QPushButton("Проверить снова")
        recheck_btn.clicked.connect(self._run_diag)
        self._diag_lay.addWidget(recheck_btn, alignment=Qt.AlignLeft)
        lay.addWidget(diag_gb)

        # ── Install guide ─────────────────────────────────────────────────
        guide_gb = QGroupBox("Инструкция по установке")
        gl = QVBoxLayout(guide_gb)
        guide_txt = QTextEdit()
        guide_txt.setReadOnly(True)
        guide_txt.setPlainText(_INSTALL_GUIDE)
        guide_txt.setStyleSheet(
            "background:#1a1a1a; color:#bbb; font-family:monospace; font-size:11px;")
        guide_txt.setMaximumHeight(160)
        gl.addWidget(guide_txt)
        lay.addWidget(guide_gb)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.accept)
        lay.addWidget(btns)

    # ---------------------------------------------------------------- diag
    def _run_diag(self):
        self._diag_msg.setText("Проверка…")
        uri = self._uri_edit.text().strip()
        threading.Thread(target=self._diag_thread, args=(uri,), daemon=True).start()

    def _diag_thread(self, uri: str):
        result = run_ros_diagnostics(uri)
        # schedule UI update in main thread
        QTimer.singleShot(0, lambda: self._update_diag(result))

    def _update_diag(self, result: dict):
        # Clear old rows
        while self._diag_area_lay.count():
            item = self._diag_area_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for label, value, ok in result["items"]:
            self._diag_area_lay.addWidget(DiagRow(label, value, ok))

        if result["ok"]:
            self._diag_msg.setText("Всё готово — можно подключаться.")
            self._diag_msg.setStyleSheet("color:#6f6; font-size:12px; font-weight:bold;")
        else:
            self._diag_msg.setText("Обнаружены проблемы — см. строки ✗ ниже.")
            self._diag_msg.setStyleSheet("color:#f96; font-size:12px; font-weight:bold;")

    # ---------------------------------------------------------------- apply
    def _on_apply(self):
        uri = self._uri_edit.text().strip()
        ip = self._ip_edit.text().strip()
        if uri:
            os.environ["ROS_MASTER_URI"] = uri
        if ip:
            os.environ["ROS_IP"] = ip
            os.environ["ROS_HOSTNAME"] = ip
        self._controller.reconnect()
        self.reconnect_requested.emit()
        self._run_diag()
