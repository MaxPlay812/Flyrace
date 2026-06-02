"""SSH-based automated drone repair and diagnostics."""
from __future__ import annotations
import subprocess
import threading
import time
from typing import Callable, List, Optional, Tuple

from utils.debug_log import log, success

_SSH_OPTS = ["-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=6",
             "-o", "ServerAliveInterval=5",
             "-o", "BatchMode=no"]

# Known connection failure cases
CASE_NO_SSH       = "no_ssh"        # SSH unreachable
CASE_CRASH_LOOP   = "crash_loop"    # service restarting too many times
CASE_NOT_STARTED  = "not_started"   # service never became active
CASE_NO_SERVICES  = "no_services"   # active but ROS services missing
CASE_WRONG_NS     = "wrong_ns"      # running in unexpected namespace
CASE_OK           = "ok"


def _sshpass_ok() -> bool:
    try:
        subprocess.run(["sshpass", "--version"],
                       capture_output=True, timeout=2)
        return True
    except Exception:
        return False


def ssh_exec(host: str, cmd: str, user: str = "pi",
             password: str = "raspberry",
             timeout: int = 15) -> Tuple[int, str]:
    """Run *cmd* on *host* via SSH. Returns (returncode, output)."""
    if password and _sshpass_ok():
        argv = (["sshpass", "-p", password, "ssh"]
                + _SSH_OPTS + [f"{user}@{host}", cmd])
    else:
        argv = ["ssh"] + _SSH_OPTS + [f"{user}@{host}", cmd]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"Таймаут ({timeout} с)"
    except Exception as e:
        return -2, str(e)


class DroneAutoSetup:
    """Multi-step SSH repair that handles every known connection failure case.

    progress_cb(step: int, total: int, msg: str, ok: bool)
    done_cb(success: bool, message: str)
    After completion, `case` and `found_ns` / `found_services` are set.
    """

    TOTAL = 6

    def __init__(self, host: str, password: str = "raspberry",
                 user: str = "pi",
                 progress_cb: Optional[Callable] = None,
                 done_cb: Optional[Callable] = None):
        self.host     = host
        self.password = password
        self.user     = user
        self._on_prog = progress_cb or (lambda *a: None)
        self._on_done = done_cb or (lambda *a: None)
        self.case:            str       = ""
        self.found_ns:        str       = ""
        self.found_services:  List[str] = []

    def run_async(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _ssh(self, cmd: str, timeout: int = 15) -> Tuple[int, str]:
        return ssh_exec(self.host, cmd, self.user, self.password, timeout)

    def _p(self, n: int, msg: str, ok: bool = True):
        self._on_prog(n, self.TOTAL, msg, ok)
        (success if ok else log.error)(f"[AutoSetup {n}/{self.TOTAL}] {msg}")

    # ---------------------------------------------------------------- run
    def _run(self):
        # ── Step 1: SSH reachability ──────────────────────────────────────
        rc, out = self._ssh("echo SSH_OK", timeout=8)
        if "SSH_OK" not in out:
            self.case = CASE_NO_SSH
            self._p(1, f"SSH недоступен: {out}", ok=False)
            self._on_done(False,
                f"SSH к pi@{self.host} не работает.\n\n"
                "Причины и решения:\n"
                "  1. WiFi дрона — подключитесь к сети clover-XXXX\n"
                "  2. Нет sshpass: sudo apt install sshpass\n"
                "  3. Пароль изменён (по умолч.: raspberry)\n"
                "  4. Дрон ещё загружается — подождите 30 с\n\n"
                f"Ручная проверка: ssh pi@{self.host}")
            return
        self._p(1, f"SSH pi@{self.host}: OK")

        # ── Step 2: clover service state + restart count ──────────────────
        _, active  = self._ssh("systemctl is-active clover 2>&1")
        _, nraw    = self._ssh(
            "systemctl show clover --property=NRestarts 2>&1", timeout=5)
        n_restarts = 0
        for line in nraw.splitlines():
            if "NRestarts=" in line:
                try:
                    n_restarts = int(line.split("=")[1])
                except ValueError:
                    pass
        is_active = active.strip() == "active"
        self._p(2, f"clover: {active.strip()}  (перезапусков: {n_restarts})",
                ok=is_active)

        # ── Step 3: crash-loop guard ──────────────────────────────────────
        if n_restarts > 8:
            self.case = CASE_CRASH_LOOP
            self._p(3, f"CRASH LOOP — {n_restarts} сбоев, изучаем журнал", ok=False)
            _, jrn = self._ssh(
                "sudo journalctl -u clover -n 80 --no-pager 2>&1", timeout=15)
            self._on_done(False,
                f"clover в crash-loop ({n_restarts} сбоев)!\n\n"
                "Нужна ручная диагностика:\n"
                f"  ssh pi@{self.host}\n"
                "  sudo journalctl -u clover -n 50\n\n"
                f"Последние записи журнала:\n{jrn[-3000:]}")
            return
        self._p(3, f"Перезапускаю clover (было {n_restarts} сбоев)…")
        self._ssh("sudo systemctl restart clover 2>&1", timeout=20)

        # ── Step 4: wait for clover to become active ──────────────────────
        started = False
        for tick in range(1, 14):
            time.sleep(1)
            self._on_prog(4, self.TOTAL, f"Ожидание clover… {tick}/13 с", True)
            _, s = self._ssh("systemctl is-active clover 2>&1", timeout=4)
            if s.strip() == "active":
                started = True
                break
        if not started:
            self.case = CASE_NOT_STARTED
            self._p(4, "clover не запустился за 13 с", ok=False)
            _, jrn = self._ssh(
                "sudo journalctl -u clover -n 80 --no-pager 2>&1", timeout=15)
            self._on_done(False,
                "clover не запустился.\n\n"
                "Возможные причины:\n"
                "  • Повреждён конфиг roslaunch\n"
                "  • Нет пакета clover в ROS workspace\n"
                "  • Конфликт портов\n\n"
                f"Журнал:\n{jrn[-3000:]}")
            return
        self._p(4, "clover активен")

        # ── Step 5: ROS service discovery on drone ────────────────────────
        _, svc_raw = self._ssh("bash -lc 'rosservice list 2>&1'", timeout=12)
        all_svcs = [s.strip() for s in svc_raw.splitlines()
                    if s.strip().startswith("/")]
        key_svcs = [s for s in all_svcs
                    if any(k in s for k in
                           ("get_telemetry", "navigate", "land",
                            "set_velocity", "set_attitude"))]
        if not key_svcs:
            self.case = CASE_NO_SERVICES
            self._p(5, f"Clover-сервисы не найдены "
                       f"(всего {len(all_svcs)} сервисов в rosmaster)", ok=False)
            self._on_done(False,
                "clover запущен, но ROS-сервисы не зарегистрированы.\n\n"
                "Возможные причины:\n"
                "  • clover ещё инициализируется — повторите через 15 с\n"
                "  • ROS_MASTER_URI на дроне неверный\n"
                "  • Другой rosmaster на сети\n\n"
                f"Все доступные сервисы ({len(all_svcs)}):\n"
                + "\n".join(all_svcs[:50]))
            return

        self.found_services = key_svcs
        for svc in key_svcs:
            if svc.endswith("/get_telemetry"):
                self.found_ns = svc.rsplit("/get_telemetry", 1)[0] or "/"
                break

        if self.found_ns and self.found_ns != "/clover":
            self.case = CASE_WRONG_NS
            self._p(5, f"Найдено {len(key_svcs)} сервисов, "
                       f"неймспейс: {self.found_ns!r} (≠ /clover!)")
        else:
            self._p(5, f"Найдено {len(key_svcs)} clover-сервисов в /clover")

        # ── Step 6: call get_telemetry from drone to verify ───────────────
        telem_svc = next((s for s in key_svcs if s.endswith("/get_telemetry")),
                         None)
        if telem_svc:
            _, traw = self._ssh(
                f"bash -lc \"rosservice call {telem_svc} "
                f"\\\"frame_id: 'map'\\\" 2>&1\"",
                timeout=8)
            armed = "armed: True" in traw
            self._p(6,
                f"Телеметрия с борта: armed={armed}"
                + ("  ⚠ ВООРУЖЁН!" if armed else ""), ok=True)
        else:
            self._p(6, "get_telemetry не найден", ok=False)

        self.case = CASE_OK
        ns_warn = (
            f"\n⚠ Неймспейс {self.found_ns!r} ≠ /clover\n"
            f"  Запустите с: CLOVER_NS={self.found_ns.lstrip('/')} ./run.sh"
            if self.found_ns and self.found_ns != "/clover" else "")
        self._on_done(True,
            f"Авто-настройка успешна!{ns_warn}\n\n"
            f"Активных clover-сервисов: {len(key_svcs)}\n"
            + "\n".join(key_svcs[:15])
            + "\n\nПереподключение GUI запускается автоматически…")
