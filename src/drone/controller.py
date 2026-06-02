"""Clover 4 drone controller.

Connection states:
  FULL  — rospy + clover.srv available AND drone services reachable
  ROSPY — rospy available but clover package missing on this machine
  SIM   — simulation fallback (no ROS, or connecting in background)

Startup: simulation starts immediately (UI stays responsive).
Background thread retries ROS every _RETRY_INTERVAL seconds.
"""
import copy
import math
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, List, Optional

from utils.debug_log import log, success

# ------------------------------------------------------------------ imports
try:
    import rospy
    _ROSPY_OK = True
    log.info("rospy импортирован успешно")
except ImportError as _e:
    _ROSPY_OK = False
    log.warning(f"rospy недоступен: {_e}")

_CLOVER_OK = False
_clover_srv = None
if _ROSPY_OK:
    try:
        from clover import srv as _clover_srv   # type: ignore
        from std_srvs.srv import Trigger as _Trigger
        _CLOVER_OK = True
        log.info("clover.srv импортирован успешно")
    except ImportError as _e:
        log.warning(f"clover.srv недоступен: {_e}")
        log.warning("Для установки: docs/ROS_UBUNTU.md")


class RosState(Enum):
    FULL  = auto()
    ROSPY = auto()
    SIM   = auto()


@dataclass
class Telemetry:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    yaw: float = 0.0
    battery: float = 100.0
    armed: bool = False
    connected: bool = False
    mode: str = "SIM"
    of_active: bool = False
    ros_state: RosState = RosState.SIM
    error_msg: str = ""


# ------------------------------------------------------------------ helpers
def _tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _local_ip_for(dest: str) -> str:
    """Best-guess local IP on the route to dest."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((dest, 80))
            return s.getsockname()[0]
    except Exception:
        return ""


def _dump_env():
    """Log all ROS-related environment variables."""
    keys = ["ROS_MASTER_URI", "ROS_IP", "ROS_HOSTNAME",
            "ROS_NAMESPACE", "ROS_DISTRO", "PYTHONPATH"]
    log.debug("─── Переменные окружения ───────────────────────────")
    for k in keys:
        v = os.environ.get(k, "(не задан)")
        log.debug(f"  {k} = {v}")
    log.debug("────────────────────────────────────────────────────")


def _dump_interfaces():
    """Log all active network interfaces with IPs."""
    try:
        out = subprocess.run(
            ["ip", "-4", "addr", "show"],
            capture_output=True, text=True, timeout=3
        ).stdout
        log.debug("─── Сетевые интерфейсы ─────────────────────────────")
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") or ("state UP" in line) or line[:1].isdigit():
                log.debug(f"  {line}")
        log.debug("────────────────────────────────────────────────────")
    except Exception as e:
        log.debug(f"ip addr: {e}")


# ------------------------------------------------------------------ controller
class CloverController:
    _RETRY_INTERVAL = 10.0

    def __init__(self):
        self._telemetry = Telemetry()
        self._lock = threading.Lock()
        self._callbacks: List[Callable] = []
        self._running = True
        self._speed = 0.5
        self._ros_state = RosState.SIM
        self._ros_connected = False

        log.info("=== CloverController запускается ===")
        _dump_env()

        # Simulation always starts first
        self._sim_t = 0.0
        self._sim_paused = True
        threading.Thread(target=self._run_sim, daemon=True).start()
        log.info("Симуляция запущена (фон)")

        if not _ROSPY_OK:
            log.warning("ROS не установлен — работаем в режиме симуляции")
            log.warning("Установка: https://wiki.ros.org/noetic/Installation/Ubuntu")
        elif not _CLOVER_OK:
            self._ros_state = RosState.ROSPY
            with self._lock:
                self._telemetry.ros_state = RosState.ROSPY
                self._telemetry.error_msg = (
                    "rospy найден, но пакет 'clover' не установлен.\n"
                    "Инструкция: docs/ROS_UBUNTU.md"
                )
            log.warning("rospy есть, пакет clover отсутствует")
            log.warning("Установка clover: docs/ROS_UBUNTU.md")
        else:
            log.info("rospy + clover.srv доступны — запускаем фоновое подключение")
            threading.Thread(target=self._connect_loop, daemon=True).start()

    # ---------------------------------------------------------------- props
    @property
    def ros_state(self) -> RosState:
        return self._ros_state

    @property
    def ros_available(self) -> bool:
        return self._ros_connected

    # ----------------------------------------------------------- connect loop
    def _connect_loop(self):
        attempt = 0
        while self._running:
            if not self._ros_connected:
                attempt += 1
                log.info(f"─── Попытка подключения #{attempt} ───────────────────────")
                self._try_connect()
            time.sleep(self._RETRY_INTERVAL)

    def _try_connect(self):
        from config import ROS_NS
        master_uri = os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
        ros_ip     = os.environ.get("ROS_IP", "")
        host       = master_uri.split("//")[-1].split(":")[0]
        port_str   = master_uri.split(":")[-1] if master_uri.count(":") >= 2 else "11311"
        port       = int(port_str)

        log.info(f"ROS_MASTER_URI = {master_uri}")
        log.info(f"ROS_IP         = {ros_ip or '(не задан)'}")

        if not ros_ip:
            detected = _local_ip_for(host)
            if detected:
                log.warning(f"ROS_IP не задан! Автодетект: {detected}")
                log.warning("Без ROS_IP дрон не сможет подключиться обратно к вам.")
                log.warning(f"Задайте: export ROS_IP={detected}")
                os.environ["ROS_IP"] = detected
            else:
                log.error("ROS_IP не задан и не удалось определить автоматически.")

        _dump_interfaces()

        # ── Step 1: Ping ──────────────────────────────────────────────────
        log.info(f"[1/5] Ping {host}...")
        try:
            r = subprocess.run(
                ["ping", "-c", "1", "-W", "2", host],
                capture_output=True, timeout=5
            )
            if r.returncode == 0:
                success(f"[1/5] Ping {host}: доступен")
            else:
                log.error(f"[1/5] Ping {host}: НЕДОСТУПЕН")
                log.error("Проверьте: подключены ли к WiFi дрона?")
                log.error(f"SSID: clover-XXXX  пароль: cloverwifi")
                self._set_error(f"Дрон {host} не отвечает на ping")
                return
        except Exception as e:
            log.warning(f"[1/5] ping не выполнен: {e}")

        # ── Step 2: TCP port 11311 ────────────────────────────────────────
        log.info(f"[2/5] TCP {host}:{port} (rosmaster)...")
        if not _tcp_reachable(host, port, timeout=3.0):
            log.error(f"[2/5] Порт {port} ЗАКРЫТ — rosmaster не отвечает")
            log.error("Возможные причины:")
            log.error("  • ROS_MASTER_URI указывает на неверный IP/порт")
            log.error("  • На дроне не запущен rosmaster")
            log.error(f"  Проверьте: ssh pi@{host} 'rosnode list'")
            self._set_error(f"rosmaster не отвечает на {host}:{port}")
            return
        success(f"[2/5] TCP {host}:{port}: доступен")

        # ── Step 3: xmlrpc rosmaster ping ─────────────────────────────────
        log.info("[3/5] xmlrpc rosmaster ping...")
        try:
            import xmlrpc.client
            proxy = xmlrpc.client.ServerProxy(master_uri)
            code, msg, val = proxy.getSystemState("/diag")
            if code == 1:
                success(f"[3/5] rosmaster отвечает (nodes: {len(val[0])})")
            else:
                log.warning(f"[3/5] rosmaster ответил с кодом {code}: {msg}")
        except Exception as e:
            log.error(f"[3/5] xmlrpc ошибка: {e}")
            self._set_error(f"rosmaster xmlrpc: {e}")
            return

        # ── Step 4: rospy init ────────────────────────────────────────────
        log.info("[4/5] rospy.init_node...")
        try:
            if not rospy.core.is_initialized():
                rospy.init_node("clover_gui", anonymous=True, disable_signals=True)
                success("[4/5] rospy узел инициализирован")
            else:
                log.info("[4/5] rospy уже инициализирован")
        except Exception as e:
            log.error(f"[4/5] rospy.init_node: {e}")
            log.error("Убедитесь что ROS_IP задан корректно")
            self._set_error(str(e))
            return

        # ── Step 5: wait_for_service ──────────────────────────────────────
        ns = f"/{ROS_NS}"
        svc = f"{ns}/get_telemetry"
        log.info(f"[5/5] wait_for_service {svc} (до 8 с)...")
        try:
            rospy.wait_for_service(svc, timeout=8.0)
            success(f"[5/5] Сервис {svc}: доступен!")
        except rospy.ROSException:
            log.error(f"[5/5] Сервис {svc} не появился за 8 с")
            log.error("rosmaster работает, но clover-узел на дроне НЕ ЗАПУЩЕН")
            # Try to discover actual namespace — clover might run under different NS
            try:
                from drone.discovery import discover_ros_info
                info = discover_ros_info(master_uri)
                if info["ok"]:
                    if info["clover_ns"]:
                        found = info["clover_ns"]
                        log.warning(f"  ► Найден clover в неймспейсе: {found!r}")
                        if found != f"/{ROS_NS}":
                            log.warning(f"    Ожидался /{ROS_NS}, найден {found}")
                            log.warning(f"    Решение: export CLOVER_NS={found.lstrip('/')}")
                    else:
                        log.warning(f"    rosmaster активен, clover-сервисы отсутствуют "
                                    f"({len(info['services'])} других сервисов)")
            except Exception:
                pass
            log.error(f"Исправление:")
            log.error(f"  1. Вкладка «Авто-настройка» → кнопка «Авто-настройка»")
            log.error(f"  2. Или вручную: ssh pi@{host} 'sudo systemctl restart clover'")
            self._set_error(
                f"rosmaster OK, но {svc} не отвечает.\n"
                f"Используйте вкладку «Авто-настройка» для автоматического исправления."
            )
            return

        # ── Connect service proxies ───────────────────────────────────────
        try:
            self._svc_telem = rospy.ServiceProxy(
                f"{ns}/get_telemetry", _clover_srv.GetTelemetry)
            self._svc_nav   = rospy.ServiceProxy(
                f"{ns}/navigate", _clover_srv.Navigate)
            self._svc_vel   = rospy.ServiceProxy(
                f"{ns}/set_velocity", _clover_srv.SetVelocity)
            self._svc_land  = rospy.ServiceProxy(f"{ns}/land", _Trigger)
        except Exception as e:
            log.error(f"ServiceProxy: {e}")
            self._set_error(str(e))
            return

        # ── First telemetry call ──────────────────────────────────────────
        log.info("Первый запрос телеметрии...")
        try:
            t = self._svc_telem(frame_id="map")
            success(f"Телеметрия: x={t.x:.2f} y={t.y:.2f} z={t.z:.2f} "
                    f"armed={t.armed} mode={t.mode}")
        except Exception as e:
            log.warning(f"Первая телеметрия: {e} (продолжаем)")

        self._ros_state     = RosState.FULL
        self._ros_connected = True
        with self._lock:
            self._telemetry.ros_state  = RosState.FULL
            self._telemetry.error_msg  = ""
        success("=== ROS ПОДКЛЮЧЁН УСПЕШНО ===")

        self._poll_ros()   # blocks until connection drops

        self._ros_connected = False
        log.warning("=== ROS соединение потеряно, повтор через "
                    f"{self._RETRY_INTERVAL:.0f} с ===")

    def _set_error(self, msg: str):
        with self._lock:
            self._telemetry.connected  = False
            self._telemetry.error_msg  = msg

    # --------------------------------------------------------------- poll
    def _poll_ros(self):
        from config import TELEMETRY_HZ
        rate = 1.0 / TELEMETRY_HZ
        fail = 0
        log.info("Polling телеметрии запущен")
        while self._running:
            try:
                t = self._svc_telem(frame_id="map")
                with self._lock:
                    self._telemetry.x         = t.x
                    self._telemetry.y         = t.y
                    self._telemetry.z         = t.z
                    self._telemetry.vx        = t.vx
                    self._telemetry.vy        = t.vy
                    self._telemetry.yaw       = t.yaw
                    self._telemetry.armed     = t.armed
                    self._telemetry.connected = True
                    self._telemetry.mode      = t.mode
                    self._telemetry.ros_state = RosState.FULL
                    self._telemetry.error_msg = ""
                    v = getattr(t, "voltage", 8.4)
                    self._telemetry.battery   = min(100.0, v / 8.4 * 100.0)
                if fail > 0:
                    success(f"Соединение восстановлено (после {fail} ошибок)")
                fail = 0
            except Exception as exc:
                fail += 1
                log.warning(f"Телеметрия #{fail}: {exc}")
                with self._lock:
                    self._telemetry.connected = False
                    self._telemetry.error_msg = str(exc)
                if fail >= 5:
                    log.error("5 подряд ошибок телеметрии — объявляем разрыв")
                    break
            self._notify()
            time.sleep(rate)

    # ---------------------------------------------------------- simulation
    def _run_sim(self):
        from config import POLE_1, POLE_2, TRACK_RADIUS, FLIGHT_ALT
        cx1, cy1 = POLE_1[0] / 1000.0, POLE_1[1] / 1000.0
        cx2, cy2 = POLE_2[0] / 1000.0, POLE_2[1] / 1000.0
        r  = TRACK_RADIUS / 1000.0
        dt = 0.05
        while self._running:
            if not self._sim_paused and not self._ros_connected:
                period = 2 * math.pi
                cycle  = self._sim_t % (2 * period)
                if cycle < period:
                    ang  = cycle
                    x    = cx1 + r * math.cos(ang + math.pi)
                    y    = cy1 + r * math.sin(ang + math.pi)
                    yaw  = ang + math.pi / 2
                else:
                    ang  = cycle - period
                    x    = cx2 + r * math.cos(ang)
                    y    = cy2 + r * math.sin(ang)
                    yaw  = ang + math.pi / 2
                with self._lock:
                    self._telemetry.x         = x
                    self._telemetry.y         = y
                    self._telemetry.z         = FLIGHT_ALT
                    self._telemetry.yaw       = yaw
                    self._telemetry.armed     = True
                    self._telemetry.connected = True
                    self._telemetry.mode      = "SIM"
                    self._telemetry.of_active = True
                    self._telemetry.battery   = max(0.0, 100.0 - self._sim_t * 0.2)
                self._sim_t += dt * self._speed * 2.5
            self._notify()
            time.sleep(dt)

    # ----------------------------------------------------------- public API
    def get_telemetry(self) -> Telemetry:
        with self._lock:
            return copy.copy(self._telemetry)

    def add_telemetry_callback(self, cb: Callable):
        self._callbacks.append(cb)

    def remove_telemetry_callback(self, cb: Callable):
        self._callbacks = [c for c in self._callbacks if c is not cb]

    def reconnect(self):
        if not _CLOVER_OK:
            log.warning("reconnect: clover пакет отсутствует")
            return
        log.info("Принудительное переподключение запрошено")
        self._ros_connected = False
        _dump_env()
        threading.Thread(target=self._try_connect, daemon=True).start()

    def takeoff(self, altitude: Optional[float] = None):
        from config import FLIGHT_ALT
        alt = altitude or FLIGHT_ALT
        log.info(f"takeoff: altitude={alt:.1f}m  ros={self.ros_available}")
        if self.ros_available:
            try:
                self._svc_nav(x=0, y=0, z=alt, frame_id="body", auto_arm=True)
            except Exception as e:
                log.error(f"takeoff ROS: {e}")
        else:
            self._sim_paused = False
            with self._lock:
                self._telemetry.armed = True
                self._telemetry.z     = alt

    def land(self):
        log.info(f"land: ros={self.ros_available}")
        if self.ros_available:
            try:
                self._svc_land()
            except Exception as e:
                log.error(f"land ROS: {e}")
        else:
            self._sim_paused = True
            with self._lock:
                self._telemetry.armed = False
                self._telemetry.z     = 0.0

    def set_speed(self, speed: float):
        from config import MIN_SPEED, MAX_SPEED
        self._speed = max(MIN_SPEED, min(MAX_SPEED, speed))
        if self.ros_available:
            try:
                self._svc_vel(vx=self._speed, vy=0.0, vz=0.0,
                              yaw=float("nan"), frame_id="body")
            except Exception:
                pass

    def emergency_stop(self):
        log.warning(f"АВАРИЙНАЯ ОСТАНОВКА  ros={self.ros_available}")
        if self.ros_available:
            try:
                self._svc_land()
            except Exception:
                pass
        else:
            self._sim_paused = True
            with self._lock:
                self._telemetry.armed = False

    @property
    def speed(self) -> float:
        return self._speed

    def stop(self):
        log.info("CloverController остановлен")
        self._running = False

    def _notify(self):
        t = self.get_telemetry()
        for cb in list(self._callbacks):
            try:
                cb(t)
            except Exception:
                pass


# ---------------------------------------------------------------- diagnostics
def run_ros_diagnostics(master_uri: str = "") -> dict:
    uri  = master_uri or os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
    host = uri.split("//")[-1].split(":")[0]
    port_s = uri.split(":")[-1] if uri.count(":") >= 2 else "11311"
    port = int(port_s)
    items = []

    items.append(("rospy установлен",
                  "Да" if _ROSPY_OK else "НЕТ → apt install ros-noetic-desktop",
                  _ROSPY_OK))
    items.append(("clover.srv пакет",
                  "Да" if _CLOVER_OK else "НЕТ → см. docs/ROS_UBUNTU.md",
                  _CLOVER_OK))

    env_uri = os.environ.get("ROS_MASTER_URI", "")
    items.append(("ROS_MASTER_URI", env_uri or "(не задан)", bool(env_uri)))

    env_ip = os.environ.get("ROS_IP", os.environ.get("ROS_HOSTNAME", ""))
    items.append(("ROS_IP", env_ip or "(не задан — критично!)", bool(env_ip)))

    detected = _local_ip_for(host)
    items.append(("Авто IP до дрона", detected or "не определён", bool(detected)))

    # Ping
    try:
        ping_ok = subprocess.run(
            ["ping", "-c", "1", "-W", "2", host],
            capture_output=True, timeout=4
        ).returncode == 0
    except Exception:
        ping_ok = False
    items.append((f"Ping {host}", "✓ доступен" if ping_ok else "✗ недоступен", ping_ok))

    # TCP rosmaster port
    tcp_ok = _tcp_reachable(host, port, timeout=2.0)
    items.append((f"TCP {host}:{port}",
                  "✓ открыт" if tcp_ok else "✗ закрыт (firewall / rosmaster не запущен)",
                  tcp_ok))

    # xmlrpc
    master_ok = False
    if _ROSPY_OK and tcp_ok:
        try:
            import xmlrpc.client
            code, _, val = xmlrpc.client.ServerProxy(uri).getSystemState("/d")
            master_ok = (code == 1)
            if master_ok:
                n_nodes = len(val[0]) if val else 0
                items.append(("rosmaster xmlrpc",
                               f"✓ отвечает ({n_nodes} nodes)", True))
        except Exception as e:
            items.append(("rosmaster xmlrpc", f"✗ {e}", False))
    else:
        items.append(("rosmaster xmlrpc",
                      "— (пропущен, TCP недоступен)", False))

    overall = _ROSPY_OK and _CLOVER_OK and master_ok
    return {"ok": overall, "items": items, "host": host}
