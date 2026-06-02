"""Auto-setup + ROS topic discovery widget (used as a dialog tab)."""
from __future__ import annotations
import os

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                              QLineEdit, QPushButton, QTextEdit, QVBoxLayout,
                              QWidget)

from drone.ssh_setup import DroneAutoSetup, CASE_WRONG_NS
from drone.discovery import discover_ros_info, format_ros_report
from utils.debug_log import log

_MONO = ("font-family:'Menlo','Consolas','DejaVu Sans Mono',monospace; "
         "font-size:11px;")
_BTN  = "border:1px solid {c}; border-radius:3px; padding:4px 10px; color:{c};"


class AutoSetupWidget(QWidget):
    """Tab that auto-fixes clover via SSH and discovers ROS topology."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._ctrl = controller
        self._setup: DroneAutoSetup | None = None
        self._build_ui()

    # ----------------------------------------------------------------- build
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # SSH credentials
        gb = QGroupBox("SSH-доступ к дрону")
        form = QFormLayout(gb)
        uri = os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
        self._host = QLineEdit(uri.split("//")[-1].split(":")[0])
        self._user = QLineEdit("pi")
        self._pwd  = QLineEdit("raspberry")
        self._pwd.setEchoMode(QLineEdit.Password)
        form.addRow("Хост дрона:",    self._host)
        form.addRow("Пользователь:",  self._user)
        form.addRow("Пароль SSH:",    self._pwd)
        lay.addWidget(gb)

        # Action buttons
        row = QHBoxLayout()
        self._btn_fix = QPushButton("▶  Авто-настройка — починить clover")
        self._btn_fix.setStyleSheet(_BTN.format(c="#4f4"))
        self._btn_fix.clicked.connect(self._start_setup)

        self._btn_disco = QPushButton("🔍  Найти ROS-топики")
        self._btn_disco.setStyleSheet(_BTN.format(c="#8cf"))
        self._btn_disco.clicked.connect(self._discover)

        self._btn_ssh_status = QPushButton("SSH: статус clover")
        self._btn_ssh_status.clicked.connect(
            lambda: self._quick_ssh("sudo systemctl status clover --no-pager -l"))
        self._btn_ssh_journal = QPushButton("Журнал clover")
        self._btn_ssh_journal.clicked.connect(
            lambda: self._quick_ssh(
                "sudo journalctl -u clover -n 40 --no-pager 2>&1"))

        for btn in (self._btn_fix, self._btn_disco,
                    self._btn_ssh_status, self._btn_ssh_journal):
            row.addWidget(btn)
        lay.addLayout(row)

        # Output log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            f"background:#0a0a0a; color:#ccc; {_MONO} border:1px solid #333;")
        lay.addWidget(self._log, 1)

        # Status label
        self._status = QLabel("Готов к работе.")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#888; font-size:11px;")
        lay.addWidget(self._status)

    # ---------------------------------------------------------------- helpers
    def _write(self, text: str, color: str = "#ccc"):
        html = (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("\n", "<br>"))
        self._log.append(f'<span style="color:{color}; {_MONO}">{html}</span>')
        self._log.moveCursor(self._log.textCursor().End)

    def _set_buttons(self, enabled: bool):
        for b in (self._btn_fix, self._btn_disco,
                  self._btn_ssh_status, self._btn_ssh_journal):
            b.setEnabled(enabled)

    # --------------------------------------------------------------- auto-setup
    def _start_setup(self):
        host = self._host.text().strip() or "192.168.11.1"
        self._log.clear()
        self._write(f"Авто-настройка → pi@{host}\n", "#8cf")
        self._status.setText("Работает…")
        self._set_buttons(False)

        self._setup = DroneAutoSetup(
            host=host,
            password=self._pwd.text(),
            user=self._user.text().strip() or "pi",
            progress_cb=lambda n, t, m, ok: QTimer.singleShot(
                0, lambda n=n, t=t, m=m, ok=ok:
                self._on_prog(n, t, m, ok)),
            done_cb=lambda ok, msg: QTimer.singleShot(
                0, lambda ok=ok, msg=msg: self._on_done(ok, msg)),
        )
        self._setup.run_async()

    def _on_prog(self, step: int, total: int, msg: str, ok: bool):
        icon  = "✓" if ok else "✗"
        color = "#6f6" if ok else "#f55"
        self._write(f"[{step}/{total}] {icon} {msg}", color)

    def _on_done(self, ok: bool, message: str):
        self._set_buttons(True)
        color = "#6f6" if ok else "#f88"
        self._write("─" * 52, "#444")
        self._write(message, color)
        self._status.setText("✓ Успешно" if ok else "✗ Требуется вмешательство")
        self._status.setStyleSheet(f"color:{color}; font-weight:bold; font-size:11px;")
        if ok:
            QTimer.singleShot(1000, self._ctrl.reconnect)
            self._write("\nПереподключение GUI…", "#8cf")
        elif (self._setup and self._setup.case == CASE_WRONG_NS
              and self._setup.found_ns):
            self._write(
                f"\nУстановите переменную и перезапустите:\n"
                f"  export CLOVER_NS={self._setup.found_ns.lstrip('/')}\n"
                f"  ./run.sh", "#fa0")

    # -------------------------------------------------------------- discovery
    def _discover(self):
        uri = os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
        self._log.clear()
        self._write(f"Опрос rosmaster: {uri}\n", "#8cf")
        self._set_buttons(False)
        import threading
        threading.Thread(target=self._disco_thread, args=(uri,),
                         daemon=True).start()

    def _disco_thread(self, uri: str):
        info   = discover_ros_info(uri)
        report = format_ros_report(info)
        QTimer.singleShot(0, lambda: self._on_disco(info, report))

    def _on_disco(self, info: dict, report: str):
        self._set_buttons(True)
        color = "#8cf" if info["ok"] else "#f55"
        self._write(report, color)
        ns = info.get("clover_ns")
        if ns and ns != "/clover":
            self._write(
                f"\n⚠ Неймспейс {ns!r} ≠ /clover!\n"
                f"  export CLOVER_NS={ns.lstrip('/')}  →  ./run.sh", "#fa0")

    # --------------------------------------------------- quick SSH one-liners
    def _quick_ssh(self, cmd: str):
        from drone.ssh_setup import ssh_exec
        host = self._host.text().strip() or "192.168.11.1"
        self._write(f"\n$ {cmd}", "#888")
        self._set_buttons(False)
        import threading
        threading.Thread(target=self._ssh_thread,
                         args=(host, cmd), daemon=True).start()

    def _ssh_thread(self, host: str, cmd: str):
        from drone.ssh_setup import ssh_exec
        _, out = ssh_exec(host, cmd,
                          user=self._user.text().strip() or "pi",
                          password=self._pwd.text())
        QTimer.singleShot(0, lambda: (
            self._write(out, "#aaa"),
            self._set_buttons(True),
        ))
