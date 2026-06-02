"""ROS connection settings and diagnostics dialog."""
from __future__ import annotations
import os
import subprocess
import threading

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                              QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QTextEdit, QVBoxLayout, QWidget)

from drone.controller import RosState, run_ros_diagnostics, _ROSPY_OK, _CLOVER_OK


_INSTALL_GUIDE = """\
═══ КАК ПОДКЛЮЧИТЬ ВНЕШНИЙ UBUNTU-ПК К CLOVER 4 ═══

1. Установите ROS Noetic (если ещё нет):
   https://wiki.ros.org/noetic/Installation/Ubuntu

2. Установите пакет clover (типы сервисов):

   Из исходников:
     mkdir -p ~/catkin_ws/src && cd ~/catkin_ws/src
     git clone https://github.com/clover-robotics/clover.git
     cd ~/catkin_ws && catkin_make
     echo "source ~/catkin_ws/devel/setup.bash" >> ~/.bashrc
     source ~/.bashrc

3. Задайте переменные ROS (добавьте в ~/.bashrc):
     export ROS_MASTER_URI=http://192.168.11.1:11311
     export ROS_IP=$(ip route get 192.168.11.1 | grep -oP 'src \\K[0-9.]+')

4. Подключитесь к WiFi дрона (clover-XXXX / cloverwifi)

5. Перезапустите приложение или нажмите "Применить".
"""


class DiagRow(QWidget):
    def __init__(self, label: str, value: str, ok: bool, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        ind = QLabel("✓" if ok else "✗")
        ind.setStyleSheet(
            f"color:{'#6f6' if ok else '#f66'}; font-weight:bold; min-width:16px;")
        lbl = QLabel(label)
        lbl.setMinimumWidth(200)
        val = QLabel(value)
        val.setStyleSheet("color:#aaa; font-size:11px;")
        val.setWordWrap(True)
        lay.addWidget(ind)
        lay.addWidget(lbl)
        lay.addWidget(val, 1)


class ConnectionDialog(QDialog):
    reconnect_requested = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle("Настройки ROS / Подключение к дрону")
        self.setMinimumSize(600, 560)
        self._build_ui()
        self._refresh_error()
        self._run_diag()

    # ---------------------------------------------------------------- build
    def _build_ui(self):
        lay = QVBoxLayout(self)

        # ── Last error from controller ────────────────────────────────────
        self._err_box = QLabel()
        self._err_box.setWordWrap(True)
        self._err_box.setStyleSheet(
            "background:#2a1a1a; color:#f88; border:1px solid #833; "
            "border-radius:4px; padding:6px; font-size:11px;")
        self._err_box.hide()
        lay.addWidget(self._err_box)

        # ── Environment settings ──────────────────────────────────────────
        env_gb = QGroupBox("Переменные окружения ROS")
        form = QFormLayout(env_gb)

        self._uri_edit = QLineEdit(
            os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311"))
        self._ip_edit = QLineEdit(
            os.environ.get("ROS_IP", os.environ.get("ROS_HOSTNAME", "")))
        self._ip_edit.setPlaceholderText(
            "Ваш IP на WiFi дрона — автодетект если пусто")

        form.addRow("ROS_MASTER_URI:", self._uri_edit)
        form.addRow("ROS_IP:", self._ip_edit)

        hb = QHBoxLayout()
        apply_btn = QPushButton("Применить и переподключить")
        apply_btn.clicked.connect(self._on_apply)
        auto_btn = QPushButton("Автодетект ROS_IP")
        auto_btn.clicked.connect(self._autodetect_ip)
        hb.addWidget(apply_btn)
        hb.addWidget(auto_btn)
        form.addRow("", hb)
        lay.addWidget(env_gb)

        # ── Diagnostics ───────────────────────────────────────────────────
        diag_gb = QGroupBox("Диагностика")
        self._diag_lay = QVBoxLayout(diag_gb)
        self._diag_lay.setSpacing(3)

        self._diag_msg = QLabel("Нажмите «Проверить» для диагностики")
        self._diag_msg.setStyleSheet("color:#aaa; font-size:11px;")
        self._diag_lay.addWidget(self._diag_msg)

        self._diag_area = QWidget()
        self._diag_area_lay = QVBoxLayout(self._diag_area)
        self._diag_area_lay.setContentsMargins(0, 0, 0, 0)
        self._diag_area_lay.setSpacing(2)
        self._diag_lay.addWidget(self._diag_area)

        btn_row = QHBoxLayout()
        recheck_btn = QPushButton("Проверить снова")
        recheck_btn.clicked.connect(self._run_diag)
        ssh_btn = QPushButton("Статус clover (SSH)")
        ssh_btn.clicked.connect(self._ssh_status)
        btn_row.addWidget(recheck_btn)
        btn_row.addWidget(ssh_btn)
        btn_row.addStretch()
        self._diag_lay.addLayout(btn_row)
        lay.addWidget(diag_gb)

        # ── Install guide ─────────────────────────────────────────────────
        guide_gb = QGroupBox("Инструкция по установке")
        gl = QVBoxLayout(guide_gb)
        guide_txt = QTextEdit()
        guide_txt.setReadOnly(True)
        guide_txt.setPlainText(_INSTALL_GUIDE)
        guide_txt.setStyleSheet(
            "background:#1a1a1a; color:#bbb; font-family:monospace; font-size:11px;")
        guide_txt.setMaximumHeight(150)
        gl.addWidget(guide_txt)
        lay.addWidget(guide_gb)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.accept)
        lay.addWidget(btns)

    # ---------------------------------------------------------------- error
    def _refresh_error(self):
        t = self._controller.get_telemetry()
        if t.error_msg:
            self._err_box.setText(f"Последняя ошибка подключения:\n{t.error_msg}")
            self._err_box.show()
        else:
            self._err_box.hide()

    # ---------------------------------------------------------------- diag
    def _run_diag(self):
        self._diag_msg.setText("Проверка…")
        uri = self._uri_edit.text().strip()
        threading.Thread(target=self._diag_thread, args=(uri,), daemon=True).start()

    def _diag_thread(self, uri: str):
        result = run_ros_diagnostics(uri)
        QTimer.singleShot(0, lambda: self._update_diag(result))

    def _update_diag(self, result: dict):
        while self._diag_area_lay.count():
            item = self._diag_area_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for label, value, ok in result["items"]:
            self._diag_area_lay.addWidget(DiagRow(label, value, ok))
        if result["ok"]:
            self._diag_msg.setText("Всё готово.")
            self._diag_msg.setStyleSheet(
                "color:#6f6; font-size:12px; font-weight:bold;")
        else:
            self._diag_msg.setText("Обнаружены проблемы — см. ✗ ниже.")
            self._diag_msg.setStyleSheet(
                "color:#f96; font-size:12px; font-weight:bold;")
        self._refresh_error()

    # ---------------------------------------------------------------- SSH
    def _ssh_status(self):
        host = self._uri_edit.text().split("//")[-1].split(":")[0] or "192.168.11.1"
        cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 pi@{host} " \
              f"'sudo systemctl status clover --no-pager -l'"
        self._ssh_out = QTextEdit()
        self._ssh_out.setReadOnly(True)
        self._ssh_out.setStyleSheet(
            "background:#111; color:#8fc; font-family:monospace; font-size:11px;")
        self._ssh_out.setPlainText(f"$ {cmd}\n\nПодключение…")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"SSH: {host}")
        dlg.resize(640, 340)
        v = QVBoxLayout(dlg)
        v.addWidget(self._ssh_out)
        dlg.show()
        threading.Thread(
            target=self._run_ssh, args=(cmd, dlg), daemon=True
        ).start()

    def _run_ssh(self, cmd: str, dlg):
        try:
            out = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10
            )
            text = (out.stdout or "") + (out.stderr or "")
        except subprocess.TimeoutExpired:
            text = "Таймаут подключения по SSH"
        except Exception as exc:
            text = str(exc)
        QTimer.singleShot(0, lambda: self._ssh_out.setPlainText(text))

    # ---------------------------------------------------------------- apply
    def _autodetect_ip(self):
        uri = self._uri_edit.text().strip() or "http://192.168.11.1:11311"
        drone_ip = uri.split("//")[-1].split(":")[0]
        try:
            result = subprocess.run(
                ["ip", "route", "get", drone_ip],
                capture_output=True, text=True, timeout=3
            )
            import re
            m = re.search(r'src\s+([\d.]+)', result.stdout)
            if m:
                self._ip_edit.setText(m.group(1))
                return
        except Exception:
            pass
        self._ip_edit.setPlaceholderText("Не удалось определить автоматически")

    def _on_apply(self):
        uri = self._uri_edit.text().strip()
        ip  = self._ip_edit.text().strip()
        if uri:
            os.environ["ROS_MASTER_URI"] = uri
        if ip:
            os.environ["ROS_IP"]       = ip
            os.environ["ROS_HOSTNAME"] = ip
        else:
            # Auto-detect if field is empty
            self._autodetect_ip()
            ip = self._ip_edit.text().strip()
            if ip:
                os.environ["ROS_IP"] = ip
        self._controller.reconnect()
        self.reconnect_requested.emit()
        self._diag_msg.setText("Переподключение запущено…")
        QTimer.singleShot(3000, self._run_diag)
