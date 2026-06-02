"""ROS connection settings, diagnostics and help dialog."""
from __future__ import annotations
import os
import re
import subprocess
import threading

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                              QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                              QMessageBox, QPushButton, QTabWidget, QTextEdit,
                              QVBoxLayout, QWidget)

from drone.controller import RosState, run_ros_diagnostics, _ROSPY_OK, _CLOVER_OK
from gui.connection_guides import (GUIDE_QUICK, GUIDE_INSTALL,
                                   GUIDE_TROUBLESHOOT, GUIDE_CMDS)
from gui.debug_widget import DebugWidget
from gui.autosetup_widget import AutoSetupWidget
from utils.debug_log import log

_SSH_OPTS = ["-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=5",
             "-o", "BatchMode=no"]


# ═══════════════════════════════ Widgets ══════════════════════════════════════
class DiagRow(QWidget):
    def __init__(self, label: str, value: str, ok: bool, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        ind = QLabel("✓" if ok else "✗")
        ind.setStyleSheet(
            f"color:{'#6f6' if ok else '#f66'}; font-weight:bold; min-width:16px;")
        lbl = QLabel(label)
        lbl.setMinimumWidth(230)
        val = QLabel(value)
        val.setStyleSheet("color:#aaa; font-size:11px;")
        val.setWordWrap(True)
        lay.addWidget(ind)
        lay.addWidget(lbl)
        lay.addWidget(val, 1)


def _make_guide(text: str) -> QTextEdit:
    w = QTextEdit()
    w.setReadOnly(True)
    w.setPlainText(text)
    w.setStyleSheet(
        "background:#0f0f0f; color:#ccc; "
        "font-family:'Menlo','Consolas','DejaVu Sans Mono',monospace; "
        "font-size:11px; border:none;")
    return w


# ═══════════════════════════════ Dialog ═══════════════════════════════════════
class ConnectionDialog(QDialog):

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle("ROS — Подключение к Clover 4")
        self.setMinimumSize(720, 620)
        self._build_ui()
        self._refresh_error()
        QTimer.singleShot(200, self._run_diag)

    # ------------------------------------------------------------ build
    def _build_ui(self):
        lay = QVBoxLayout(self)

        self._err_box = QLabel()
        self._err_box.setWordWrap(True)
        self._err_box.setStyleSheet(
            "background:#2a1a1a; color:#f88; border:1px solid #833; "
            "border-radius:4px; padding:6px; font-size:11px;")
        self._err_box.hide()
        lay.addWidget(self._err_box)

        tabs = QTabWidget()
        tabs.addTab(self._tab_connect(),               "Подключение")
        tabs.addTab(AutoSetupWidget(controller),       "Авто-настройка")
        tabs.addTab(self._tab_diag(),                  "Диагностика")
        tabs.addTab(self._tab_log(),                   "Лог подключения")
        tabs.addTab(_make_guide(GUIDE_QUICK),          "Быстрый старт")
        tabs.addTab(_make_guide(GUIDE_INSTALL),        "Установка")
        tabs.addTab(_make_guide(GUIDE_TROUBLESHOOT),   "Решение проблем")
        tabs.addTab(_make_guide(GUIDE_CMDS),           "Команды")
        lay.addWidget(tabs, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.accept)
        lay.addWidget(btns)

    # -------------------------------------------------------- tab: connect
    def _tab_connect(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        gb = QGroupBox("Переменные окружения ROS")
        form = QFormLayout(gb)
        self._uri_edit = QLineEdit(
            os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311"))
        self._ip_edit = QLineEdit(
            os.environ.get("ROS_IP", os.environ.get("ROS_HOSTNAME", "")))
        self._ip_edit.setPlaceholderText(
            "Ваш IP на WiFi дрона — нажмите «Автодетект»")
        form.addRow("ROS_MASTER_URI:", self._uri_edit)
        form.addRow("ROS_IP:", self._ip_edit)
        row = QHBoxLayout()
        btn_apply = QPushButton("Применить и переподключить")
        btn_apply.clicked.connect(self._on_apply)
        btn_auto = QPushButton("Автодетект ROS_IP")
        btn_auto.clicked.connect(self._autodetect_ip)
        row.addWidget(btn_apply)
        row.addWidget(btn_auto)
        form.addRow("", row)
        lay.addWidget(gb)

        ssh_gb = QGroupBox("SSH к дрону (быстрые команды)")
        sh = QVBoxLayout(ssh_gb)

        # Row 1: host field
        row_host = QHBoxLayout()
        row_host.addWidget(QLabel("Хост:"))
        self._ssh_host = QLineEdit(
            os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
            .split("//")[-1].split(":")[0])
        row_host.addWidget(self._ssh_host, 1)
        sh.addLayout(row_host)

        # Row 2: action buttons
        row_btns = QHBoxLayout()
        for lbl, cmd in [
            ("Статус clover",   "sudo systemctl status clover --no-pager -l"),
            ("Сервисы ROS",     "rosservice list 2>&1 | grep clover"),
            ("Журнал (50 строк)", "sudo journalctl -u clover -n 50 --no-pager"),
        ]:
            btn = QPushButton(lbl)
            btn.clicked.connect(lambda _, c=cmd: self._ssh_run(c))
            row_btns.addWidget(btn)
        btn_restart = QPushButton("Починить clover ▶")
        btn_restart.setStyleSheet(
            "color:#fa0; font-weight:bold; border:1px solid #a70; "
            "border-radius:3px; padding:2px 8px;")
        btn_restart.clicked.connect(self._ssh_safe_restart)
        row_btns.addWidget(btn_restart)
        sh.addLayout(row_btns)

        self._ssh_out = QTextEdit()
        self._ssh_out.setReadOnly(True)
        self._ssh_out.setMaximumHeight(130)
        self._ssh_out.setStyleSheet(
            "background:#111; color:#8fc; "
            "font-family:monospace; font-size:11px;")
        lay.addWidget(ssh_gb)
        lay.addStretch()
        return w

    # -------------------------------------------------------- tab: diag
    def _tab_diag(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self._diag_msg = QLabel("Нажмите «Проверить» для диагностики")
        self._diag_msg.setStyleSheet(
            "color:#aaa; font-size:12px; font-weight:bold;")
        lay.addWidget(self._diag_msg)
        self._diag_area = QWidget()
        self._diag_area_lay = QVBoxLayout(self._diag_area)
        self._diag_area_lay.setContentsMargins(0, 0, 0, 0)
        self._diag_area_lay.setSpacing(3)
        lay.addWidget(self._diag_area, 1)
        btn_row = QHBoxLayout()
        btn_check = QPushButton("Проверить снова")
        btn_check.clicked.connect(self._run_diag)
        btn_row.addWidget(btn_check)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return w

    def _tab_log(self) -> QWidget:
        return DebugWidget()

    # -------------------------------------------------------- error
    def _refresh_error(self):
        t = self._controller.get_telemetry()
        if t.error_msg:
            self._err_box.setText(f"Последняя ошибка: {t.error_msg}")
            self._err_box.show()
        else:
            self._err_box.hide()

    # -------------------------------------------------------- diag
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
            self._diag_msg.setText("Всё готово — подключение должно работать.")
            self._diag_msg.setStyleSheet(
                "color:#6f6; font-size:12px; font-weight:bold;")
        else:
            fail = sum(1 for _, _, ok in result["items"] if not ok)
            self._diag_msg.setText(
                f"Найдено проблем: {fail} — см. ✗ ниже и вкладку «Решение проблем»")
            self._diag_msg.setStyleSheet(
                "color:#f96; font-size:12px; font-weight:bold;")
        self._refresh_error()

    # -------------------------------------------------------- SSH helpers
    def _validate_ssh_host(self, host: str) -> tuple:
        """Returns (ok: bool, error_or_warning: str)."""
        if not host:
            return False, "Хост не задан"
        if not re.match(r'^[a-zA-Z0-9._-]+$', host):
            return False, f"Недопустимые символы в хосте: {host!r}"
        expected = (os.environ.get("ROS_MASTER_URI", "")
                    .split("//")[-1].split(":")[0])
        if expected and host != expected:
            return True, (f"Хост {host} отличается от ROS_MASTER_URI "
                          f"({expected}). Подключаемся к правильному дрону?")
        return True, ""

    def _ssh_run(self, remote_cmd: str):
        host = self._ssh_host.text().strip() or "192.168.11.1"
        ok, warn = self._validate_ssh_host(host)
        if not ok:
            self._ssh_out.setPlainText(f"Ошибка: {warn}")
            return
        cmd = ["ssh"] + _SSH_OPTS + [f"pi@{host}", remote_cmd]
        self._ssh_out.setPlainText(f"$ {remote_cmd}\n\nПодключение…")
        log.info(f"SSH {host}: {remote_cmd}")
        threading.Thread(target=self._ssh_thread, args=(cmd,), daemon=True).start()

    def _ssh_thread(self, cmd: list):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
            out = (r.stdout + r.stderr).strip() or "(нет вывода)"
        except subprocess.TimeoutExpired:
            out = "Таймаут SSH (12 с)"
        except Exception as e:
            out = str(e)
        log.info(f"SSH результат:\n{out}")
        QTimer.singleShot(0, lambda: self._ssh_out.setPlainText(out))

    # -------------------------------------------------------- safe restart
    def _ssh_safe_restart(self):
        host = self._ssh_host.text().strip() or "192.168.11.1"
        ok, warn = self._validate_ssh_host(host)
        if not ok:
            self._ssh_out.setPlainText(f"Ошибка: {warn}")
            return

        dlg = QMessageBox(self)
        dlg.setWindowTitle("Перезапуск clover")
        dlg.setIcon(QMessageBox.Warning)
        dlg.setText(
            f"Перезапустить сервис clover на дроне {host}?\n\n"
            "⚠  Убедитесь что дрон НА ЗЕМЛЕ и НЕ ВООРУЖЁН!\n"
            "Перезапуск сервиса на летящем дроне отключит моторы.")
        if warn:
            dlg.setInformativeText(warn)
        dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dlg.setDefaultButton(QMessageBox.Cancel)
        if dlg.exec_() != QMessageBox.Yes:
            return

        self._ssh_out.setPlainText(f"[1/2] Проверяю armed-статус на {host}…")
        log.info(f"SSH safe-restart: проверка armed на {host}")
        threading.Thread(
            target=self._ssh_restart_thread, args=(host,), daemon=True
        ).start()

    def _ssh_restart_thread(self, host: str):
        # Step 1: check armed status via telemetry service
        check = (
            "rosservice call /clover/get_telemetry \"frame_id: 'map'\" 2>&1 "
            "|| echo SERVICE_UNAVAILABLE"
        )
        cmd1 = ["ssh"] + _SSH_OPTS + [f"pi@{host}", check]
        try:
            r1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=10)
            out1 = r1.stdout + r1.stderr
        except subprocess.TimeoutExpired:
            QTimer.singleShot(0, lambda: self._ssh_out.setPlainText(
                "Таймаут SSH при проверке статуса (10 с)"))
            return
        except Exception as e:
            QTimer.singleShot(0, lambda: self._ssh_out.setPlainText(
                f"SSH ошибка: {e}"))
            return

        if "armed: True" in out1:
            msg = ("🛑 ОТМЕНЕНО: дрон В ВОЗДУХЕ (armed=True)!\n\n"
                   "Перезапуск запрещён — посадите дрон сначала.\n\n"
                   f"Телеметрия:\n{out1.strip()}")
            log.error("SSH restart отменён: дрон вооружён (armed=True)")
            QTimer.singleShot(0, lambda: self._ssh_out.setPlainText(msg))
            return

        # Step 2: restart service
        log.info(f"SSH restart clover на {host}: дрон не вооружён — перезапускаем")
        QTimer.singleShot(0, lambda: self._ssh_out.setPlainText(
            "[2/2] Дрон не вооружён — перезапускаю clover…"))

        restart = ("sudo systemctl restart clover "
                   "&& sleep 3 "
                   "&& sudo systemctl status clover --no-pager -l 2>&1")
        cmd2 = ["ssh"] + _SSH_OPTS + [f"pi@{host}", restart]
        try:
            r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=25)
            out2 = (r2.stdout + r2.stderr).strip() or "(нет вывода)"
        except subprocess.TimeoutExpired:
            out2 = "Таймаут (25 с) — команда могла выполниться, проверьте статус."
        except Exception as e:
            out2 = f"Ошибка: {e}"

        log.info(f"SSH restart результат:\n{out2}")
        QTimer.singleShot(0, lambda: self._ssh_out.setPlainText(
            f"sudo systemctl restart clover\n\n{out2}"))

    # -------------------------------------------------------- apply
    def _autodetect_ip(self):
        uri  = self._uri_edit.text().strip() or "http://192.168.11.1:11311"
        host = uri.split("//")[-1].split(":")[0]
        try:
            r = subprocess.run(
                ["ip", "route", "get", host],
                capture_output=True, text=True, timeout=3)
            m = re.search(r'src\s+([\d.]+)', r.stdout)
            if m:
                self._ip_edit.setText(m.group(1))
                log.info(f"Автодетект ROS_IP: {m.group(1)}")
                return
        except Exception as e:
            log.warning(f"Автодетект ROS_IP: {e}")
        self._ip_edit.setPlaceholderText("Не удалось определить — задайте вручную")

    def _on_apply(self):
        uri = self._uri_edit.text().strip()
        ip  = self._ip_edit.text().strip()
        if uri:
            os.environ["ROS_MASTER_URI"] = uri
            log.info(f"Применено: ROS_MASTER_URI={uri}")
        if not ip:
            self._autodetect_ip()
            ip = self._ip_edit.text().strip()
        if ip:
            os.environ["ROS_IP"]       = ip
            os.environ["ROS_HOSTNAME"] = ip
            log.info(f"Применено: ROS_IP={ip}")
        self._controller.reconnect()
        self._diag_msg.setText("Переподключение запущено — результат через ~10 с…")
        QTimer.singleShot(5000, self._run_diag)
