"""ROS connection settings, diagnostics and help dialog."""
from __future__ import annotations
import os
import re
import subprocess
import threading

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                              QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QTabWidget, QTextEdit,
                              QVBoxLayout, QWidget)

from drone.controller import RosState, run_ros_diagnostics, _ROSPY_OK, _CLOVER_OK
from gui.debug_widget import DebugWidget
from utils.debug_log import log


# ═══════════════════════════════ Guide texts ══════════════════════════════════
_GUIDE_QUICK = """\
╔══════════════════════════════════════════════════════╗
║      БЫСТРЫЙ СТАРТ — подключение к Clover 4          ║
╚══════════════════════════════════════════════════════╝

[1] Убедитесь что дрон включён и светодиод мигает.

[2] Подключитесь к WiFi дрона:
    SSID:   clover-XXXX
    Пароль: cloverwifi

[3] Проверьте что ROS Noetic установлен:
    which roscore   →  должен вывести путь

[4] Проверьте что пакет clover установлен:
    python3 -c "from clover import srv; print('OK')"

[5] Задайте переменные (один раз, добавьте в ~/.bashrc):
    export ROS_MASTER_URI=http://192.168.11.1:11311
    export ROS_IP=$(ip route get 192.168.11.1 | grep -oP 'src \\K[0-9.]+')
    source ~/.bashrc

[6] Проверьте связь:
    ping 192.168.11.1                     ← должен пинговаться
    nc -zv 192.168.11.1 11311             ← порт открыт?
    rosservice list | grep clover         ← сервисы видны?

[7] Запустите приложение:
    ./run.sh

══ Если ping есть, но сервисы не видны ══
    ssh pi@192.168.11.1
    sudo systemctl status clover
    sudo systemctl restart clover
"""

_GUIDE_INSTALL = """\
╔══════════════════════════════════════════════════════╗
║      УСТАНОВКА ROS NOETIC + clover (Ubuntu 20.04)    ║
╚══════════════════════════════════════════════════════╝

── A. ROS Noetic ───────────────────────────────────────
    sudo sh -c 'echo "deb http://packages.ros.org/ros/ubuntu focal main" \\
      > /etc/apt/sources.list.d/ros-latest.list'
    curl -s https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc \\
      | sudo apt-key add -
    sudo apt update
    sudo apt install ros-noetic-desktop python3-rospy

    # Добавить в ~/.bashrc:
    source /opt/ros/noetic/setup.bash

── B. Пакет clover (из исходников) ─────────────────────
    sudo apt install python3-catkin-tools python3-pip -y
    mkdir -p ~/catkin_ws/src && cd ~/catkin_ws/src
    git clone --depth 1 https://github.com/clover-robotics/clover.git

    cd ~/catkin_ws
    catkin_make
    # или: catkin build

    # Добавить в ~/.bashrc:
    source ~/catkin_ws/devel/setup.bash

── C. Переменные окружения ──────────────────────────────
    # Добавить в ~/.bashrc:
    export ROS_MASTER_URI=http://192.168.11.1:11311
    export ROS_IP=$(ip route get 192.168.11.1 | grep -oP 'src \\K[0-9.]+')

── D. Проверка ──────────────────────────────────────────
    source ~/.bashrc
    python3 -c "import rospy; from clover import srv; print('ROS OK')"
    rosservice list | grep clover
"""

_GUIDE_TROUBLESHOOT = """\
╔══════════════════════════════════════════════════════╗
║      ДИАГНОСТИКА ПРОБЛЕМ                             ║
╚══════════════════════════════════════════════════════╝

СИМПТОМ: кнопка «ROS: симуляция» не меняется
─────────────────────────────────────────────────────
• rospy не установлен:
    sudo apt install ros-noetic-desktop
• clover пакет отсутствует:
    python3 -c "from clover import srv"
    → ошибка? Установите (шаг B в Установка)

СИМПТОМ: «ROS: нет пакета clover»
─────────────────────────────────────────────────────
• Соберите clover и source-уйте workspace:
    source ~/catkin_ws/devel/setup.bash
    python3 -c "from clover import srv; print('OK')"

СИМПТОМ: ping работает, но порт 11311 закрыт
─────────────────────────────────────────────────────
• rosmaster не запущен на дроне:
    ssh pi@192.168.11.1 'rosnode list'
• Перезапустить clover:
    ssh pi@192.168.11.1 'sudo systemctl restart clover'
    ssh pi@192.168.11.1 'sudo systemctl status clover'

СИМПТОМ: порт 11311 открыт, но сервис get_telemetry не появляется
─────────────────────────────────────────────────────
• clover-узел запустился не полностью:
    ssh pi@192.168.11.1 'rosservice list 2>&1 | grep clover'
    ssh pi@192.168.11.1 'sudo journalctl -u clover -n 50'
• Перезагрузить дрон:
    ssh pi@192.168.11.1 'sudo reboot'

СИМПТОМ: ping не проходит
─────────────────────────────────────────────────────
• Проверьте подключение к WiFi дрона:
    ip addr show
    nmcli connection show --active
• Иногда нужно:
    nmcli device wifi connect clover-XXXX password cloverwifi

СИМПТОМ: «ROS_IP не задан»
─────────────────────────────────────────────────────
• Без ROS_IP дрон не может вызывать обратно наш узел!
• Задайте вручную:
    export ROS_IP=$(ip route get 192.168.11.1 | grep -oP 'src \\K[0-9.]+')
• Или воспользуйтесь кнопкой «Автодетект ROS_IP»

ПОЛНАЯ ДИАГНОСТИКА В ОДНУ КОМАНДУ:
─────────────────────────────────────────────────────
    ping -c1 192.168.11.1           # сеть
    nc -zv 192.168.11.1 11311       # rosmaster TCP
    rosservice list 2>&1            # clover сервисы
    python3 -c "from clover import srv; print('OK')"
"""

_GUIDE_CMDS = """\
╔══════════════════════════════════════════════════════╗
║      ПОЛЕЗНЫЕ КОМАНДЫ                                ║
╚══════════════════════════════════════════════════════╝

── Сеть ────────────────────────────────────────────────
    ip addr show
    ip route get 192.168.11.1
    ping -c3 192.168.11.1
    nc -zv 192.168.11.1 11311

── ROS ─────────────────────────────────────────────────
    rosnode list
    rosservice list | grep clover
    rosservice call /clover/get_telemetry "frame_id: 'map'"
    rostopic list
    rostopic echo /main_camera/image_raw -n1

── SSH на дрон ─────────────────────────────────────────
    ssh pi@192.168.11.1           # пароль: raspberry
    sudo systemctl status clover
    sudo systemctl restart clover
    sudo journalctl -u clover -n 100
    rosnode list                  # на борту дрона

── Python проверки ─────────────────────────────────────
    python3 -c "import rospy; print(rospy.__file__)"
    python3 -c "from clover import srv; print('clover OK')"
    echo $ROS_MASTER_URI
    echo $ROS_IP

── WiFi ────────────────────────────────────────────────
    nmcli device wifi list
    nmcli device wifi connect clover-XXXX password cloverwifi
    nmcli connection show --active
"""


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
        # Auto-run diagnostics
        QTimer.singleShot(200, self._run_diag)

    # ------------------------------------------------------------ build
    def _build_ui(self):
        lay = QVBoxLayout(self)

        # Error banner
        self._err_box = QLabel()
        self._err_box.setWordWrap(True)
        self._err_box.setStyleSheet(
            "background:#2a1a1a; color:#f88; border:1px solid #833; "
            "border-radius:4px; padding:6px; font-size:11px;")
        self._err_box.hide()
        lay.addWidget(self._err_box)

        tabs = QTabWidget()
        tabs.addTab(self._tab_connect(), "Подключение")
        tabs.addTab(self._tab_diag(),    "Диагностика")
        tabs.addTab(self._tab_log(),     "Лог подключения")
        tabs.addTab(_make_guide(_GUIDE_QUICK),         "Быстрый старт")
        tabs.addTab(_make_guide(_GUIDE_INSTALL),       "Установка")
        tabs.addTab(_make_guide(_GUIDE_TROUBLESHOOT),  "Решение проблем")
        tabs.addTab(_make_guide(_GUIDE_CMDS),          "Команды")
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
        self._ip_edit  = QLineEdit(
            os.environ.get("ROS_IP", os.environ.get("ROS_HOSTNAME", "")))
        self._ip_edit.setPlaceholderText(
            "Ваш IP на WiFi дрона — нажмите «Автодетект»")

        form.addRow("ROS_MASTER_URI:", self._uri_edit)
        form.addRow("ROS_IP:", self._ip_edit)

        row = QHBoxLayout()
        btn_apply = QPushButton("Применить и переподключить")
        btn_apply.clicked.connect(self._on_apply)
        btn_auto  = QPushButton("Автодетект ROS_IP")
        btn_auto.clicked.connect(self._autodetect_ip)
        row.addWidget(btn_apply)
        row.addWidget(btn_auto)
        form.addRow("", row)
        lay.addWidget(gb)

        ssh_gb = QGroupBox("SSH к дрону")
        sh = QVBoxLayout(ssh_gb)
        self._ssh_host = QLineEdit(
            os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
            .split("//")[-1].split(":")[0])
        self._ssh_out = QTextEdit()
        self._ssh_out.setReadOnly(True)
        self._ssh_out.setMaximumHeight(120)
        self._ssh_out.setStyleSheet(
            "background:#111; color:#8fc; "
            "font-family:monospace; font-size:11px;")
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Хост:"))
        row2.addWidget(self._ssh_host, 1)
        for lbl, cmd in [
            ("Статус clover", "sudo systemctl status clover --no-pager -l"),
            ("Список сервисов", "rosservice list 2>&1 | grep clover"),
            ("Перезапустить clover", "sudo systemctl restart clover"),
        ]:
            btn = QPushButton(lbl)
            btn.clicked.connect(lambda _, c=cmd: self._ssh_run(c))
            row2.addWidget(btn)
        sh.addLayout(row2)
        sh.addWidget(self._ssh_out)
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

    # -------------------------------------------------------- tab: log
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
        threading.Thread(
            target=lambda: QTimer.singleShot(
                0, lambda: self._update_diag(run_ros_diagnostics(uri))
            ),
            daemon=True
        ).start()
        # run in thread, update in main thread
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

    # -------------------------------------------------------- SSH
    def _ssh_run(self, remote_cmd: str):
        host = self._ssh_host.text().strip() or "192.168.11.1"
        cmd  = (f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "
                f"-o BatchMode=no pi@{host} '{remote_cmd}'")
        self._ssh_out.setPlainText(f"$ {remote_cmd}\n\nПодключение…")
        log.info(f"SSH: {cmd}")
        threading.Thread(target=self._ssh_thread, args=(cmd,), daemon=True).start()

    def _ssh_thread(self, cmd: str):
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=12
            )
            out = (r.stdout + r.stderr).strip() or "(нет вывода)"
        except subprocess.TimeoutExpired:
            out = "Таймаут SSH (12 с)"
        except Exception as e:
            out = str(e)
        log.info(f"SSH результат:\n{out}")
        QTimer.singleShot(0, lambda: self._ssh_out.setPlainText(out))

    # -------------------------------------------------------- apply
    def _autodetect_ip(self):
        uri  = self._uri_edit.text().strip() or "http://192.168.11.1:11311"
        host = uri.split("//")[-1].split(":")[0]
        try:
            r = subprocess.run(
                ["ip", "route", "get", host],
                capture_output=True, text=True, timeout=3
            )
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
