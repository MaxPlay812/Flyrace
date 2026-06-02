"""Clover 4 drone controller.

Connection states:
  FULL  — rospy + clover.srv available AND drone services reachable
  ROSPY — rospy available but clover package missing on this machine
  SIM   — simulation fallback (no ROS, or ROS not yet connected)

Startup flow:
  1. Simulation starts immediately (non-blocking, UI stays responsive)
  2. If clover package present, a background thread attempts ROS every 10 s
  3. Once ROS connects, _poll_ros() takes over telemetry; sim pauses
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

# ------------------------------------------------------------------ imports
try:
    import rospy
    _ROSPY_OK = True
except ImportError:
    _ROSPY_OK = False

_CLOVER_OK = False
_clover_srv = None
if _ROSPY_OK:
    try:
        from clover import srv as _clover_srv   # type: ignore
        from std_srvs.srv import Trigger as _Trigger
        _CLOVER_OK = True
    except ImportError:
        pass


class RosState(Enum):
    FULL  = auto()
    ROSPY = auto()   # rospy present, clover package missing
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


def _tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Quick TCP probe — much faster than rospy.wait_for_service."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class CloverController:
    """Interface to Clover 4 drone via ROS (with auto-retry) or simulation."""

    _RETRY_INTERVAL = 10.0   # seconds between ROS reconnect attempts

    def __init__(self):
        self._telemetry = Telemetry()
        self._lock = threading.Lock()
        self._callbacks: List[Callable] = []
        self._running = True
        self._speed = 0.5
        self._ros_state = RosState.SIM
        self._ros_connected = False   # True only when _poll_ros is running

        # Simulation always starts immediately so the UI is responsive
        self._sim_t = 0.0
        self._sim_paused = True
        threading.Thread(target=self._run_sim, daemon=True).start()

        if not _ROSPY_OK:
            self._ros_state = RosState.SIM
        elif not _CLOVER_OK:
            self._ros_state = RosState.ROSPY
            with self._lock:
                self._telemetry.ros_state = RosState.ROSPY
                self._telemetry.error_msg = (
                    "rospy найден, но пакет 'clover' не установлен.\n"
                    "Инструкция: docs/ROS_UBUNTU.md"
                )
        else:
            # Try connecting in background; retry until successful
            threading.Thread(target=self._connect_loop, daemon=True).start()

    # ------------------------------------------------------------------ props
    @property
    def ros_state(self) -> RosState:
        return self._ros_state

    @property
    def ros_available(self) -> bool:
        return self._ros_connected

    # -------------------------------------------------------------- ROS loop
    def _connect_loop(self):
        """Background thread: attempt ROS connection every _RETRY_INTERVAL s."""
        while self._running:
            if not self._ros_connected:
                self._try_connect()
            time.sleep(self._RETRY_INTERVAL)

    def _try_connect(self):
        import os as _os
        from config import ROS_NS
        master_uri = _os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
        ros_ip     = _os.environ.get("ROS_IP", "(не задан)")
        host       = master_uri.split("//")[-1].split(":")[0]
        port       = int(master_uri.split(":")[-1])

        print(f"[ROS] попытка подключения → {master_uri}  (local IP: {ros_ip})")

        # Step 1: TCP probe — fast check before involving rospy
        if not _tcp_reachable(host, port):
            msg = f"rosmaster недоступен: {host}:{port} (нет TCP-соединения)"
            print(f"[ROS] {msg}")
            self._set_error(msg)
            return

        print(f"[ROS] порт {port} доступен, инициализируем rospy...")
        try:
            if not rospy.core.is_initialized():
                rospy.init_node("clover_gui", anonymous=True, disable_signals=True)

            ns = f"/{ROS_NS}"
            print(f"[ROS] ожидание сервиса {ns}/get_telemetry ...")
            try:
                rospy.wait_for_service(f"{ns}/get_telemetry", timeout=6.0)
            except rospy.ROSException:
                msg = (
                    f"rosmaster доступен ({host}:{port}), но сервис "
                    f"{ns}/get_telemetry не отвечает.\n"
                    "Возможно, clover-узел на дроне не запущен.\n"
                    "Проверьте: ssh pi@192.168.11.1 'sudo systemctl status clover'"
                )
                print(f"[ROS] {msg}")
                self._set_error(msg)
                return

            self._svc_telem = rospy.ServiceProxy(
                f"{ns}/get_telemetry", _clover_srv.GetTelemetry)
            self._svc_nav   = rospy.ServiceProxy(
                f"{ns}/navigate", _clover_srv.Navigate)
            self._svc_vel   = rospy.ServiceProxy(
                f"{ns}/set_velocity", _clover_srv.SetVelocity)
            self._svc_land  = rospy.ServiceProxy(f"{ns}/land", _Trigger)

            self._ros_state    = RosState.FULL
            self._ros_connected = True
            with self._lock:
                self._telemetry.ros_state  = RosState.FULL
                self._telemetry.error_msg  = ""
            print("[ROS] подключён успешно!")

            # Hand off to polling loop
            self._poll_ros()   # blocks until connection drops

        except Exception as exc:
            msg = str(exc)
            print(f"[ROS] ошибка: {msg}")
            self._set_error(msg)

        # If we get here, poll loop exited (connection dropped)
        self._ros_connected = False
        self._ros_state = RosState.FULL   # keep FULL state, will retry
        print("[ROS] соединение потеряно, повтор через "
              f"{self._RETRY_INTERVAL:.0f} с...")

    def _set_error(self, msg: str):
        with self._lock:
            self._telemetry.connected  = False
            self._telemetry.error_msg  = msg

    # -------------------------------------------------------------- poll ROS
    def _poll_ros(self):
        from config import TELEMETRY_HZ
        rate = 1.0 / TELEMETRY_HZ
        fail_count = 0
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
                fail_count = 0
            except Exception as exc:
                fail_count += 1
                with self._lock:
                    self._telemetry.connected = False
                    self._telemetry.error_msg = str(exc)
                if fail_count >= 5:
                    # 5 consecutive failures → declare disconnected, exit loop
                    break
            self._notify()
            time.sleep(rate)

    # ----------------------------------------------------------- simulation
    def _run_sim(self):
        from config import POLE_1, POLE_2, TRACK_RADIUS, FLIGHT_ALT
        cx1, cy1 = POLE_1[0] / 1000.0, POLE_1[1] / 1000.0
        cx2, cy2 = POLE_2[0] / 1000.0, POLE_2[1] / 1000.0
        r  = TRACK_RADIUS / 1000.0
        dt = 0.05
        while self._running:
            # Pause sim output whenever drone is live
            if not self._sim_paused and not self._ros_connected:
                period = 2 * math.pi
                cycle  = self._sim_t % (2 * period)
                if cycle < period:
                    ang = cycle
                    x, y = cx1 + r * math.cos(ang + math.pi), cy1 + r * math.sin(ang + math.pi)
                    yaw  = ang + math.pi / 2
                else:
                    ang = cycle - period
                    x, y = cx2 + r * math.cos(ang), cy2 + r * math.sin(ang)
                    yaw  = ang + math.pi / 2
                with self._lock:
                    self._telemetry.x        = x
                    self._telemetry.y        = y
                    self._telemetry.z        = FLIGHT_ALT
                    self._telemetry.yaw      = yaw
                    self._telemetry.armed    = True
                    self._telemetry.connected = True
                    self._telemetry.mode     = "SIM"
                    self._telemetry.of_active = True
                    self._telemetry.battery  = max(0.0, 100.0 - self._sim_t * 0.2)
                self._sim_t += dt * self._speed * 2.5
            self._notify()
            time.sleep(dt)

    # ------------------------------------------------------- public interface
    def get_telemetry(self) -> Telemetry:
        with self._lock:
            return copy.copy(self._telemetry)

    def add_telemetry_callback(self, cb: Callable):
        self._callbacks.append(cb)

    def remove_telemetry_callback(self, cb: Callable):
        self._callbacks = [c for c in self._callbacks if c is not cb]

    def reconnect(self):
        """Force an immediate reconnect attempt (e.g. after env vars updated)."""
        if not _CLOVER_OK:
            return
        self._ros_connected = False
        threading.Thread(target=self._try_connect, daemon=True).start()

    def takeoff(self, altitude: Optional[float] = None):
        from config import FLIGHT_ALT
        alt = altitude or FLIGHT_ALT
        if self.ros_available:
            try:
                self._svc_nav(x=0, y=0, z=alt, frame_id="body", auto_arm=True)
            except Exception as e:
                print(f"[ROS] takeoff error: {e}")
        else:
            self._sim_paused = False
            with self._lock:
                self._telemetry.armed = True
                self._telemetry.z     = alt

    def land(self):
        if self.ros_available:
            try:
                self._svc_land()
            except Exception as e:
                print(f"[ROS] land error: {e}")
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
        self._running = False

    def _notify(self):
        t = self.get_telemetry()
        for cb in list(self._callbacks):
            try:
                cb(t)
            except Exception:
                pass


# ------------------------------------------------------------------ diagnostics
def run_ros_diagnostics(master_uri: str = "") -> dict:
    uri  = master_uri or os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
    host = uri.split("//")[-1].split(":")[0]
    port = int(uri.split(":")[-1]) if ":" in uri.split("//")[-1] else 11311
    items = []

    items.append(("rospy установлен",
                  "Да" if _ROSPY_OK else "НЕТ — установите ROS Noetic",
                  _ROSPY_OK))
    items.append(("clover пакет",
                  "Да" if _CLOVER_OK else "НЕТ — нет типов сервисов",
                  _CLOVER_OK))

    env_uri = os.environ.get("ROS_MASTER_URI", "")
    items.append(("ROS_MASTER_URI", env_uri or "(не задан)", bool(env_uri)))

    env_ip = os.environ.get("ROS_IP", os.environ.get("ROS_HOSTNAME", ""))
    items.append(("ROS_IP", env_ip or "(не задан — скорее всего нужен)", bool(env_ip)))

    # TCP probe on rosmaster port
    tcp_ok = _tcp_reachable(host, port, timeout=2.0)
    items.append((f"TCP {host}:{port}",
                  "Доступен" if tcp_ok else "Недоступен",
                  tcp_ok))

    # Ping
    try:
        ping_ok = subprocess.run(
            ["ping", "-c", "1", "-W", "1", host],
            capture_output=True, timeout=3
        ).returncode == 0
    except Exception:
        ping_ok = False
    items.append((f"Ping {host}", "Доступен" if ping_ok else "Недоступен", ping_ok))

    # xmlrpc rosmaster check
    master_ok = False
    if _ROSPY_OK and tcp_ok:
        try:
            import xmlrpc.client
            code, _, _ = xmlrpc.client.ServerProxy(uri).getSystemState("/diag")
            master_ok = (code == 1)
        except Exception:
            pass
    items.append(("rosmaster (xmlrpc)", "Отвечает" if master_ok else "Не отвечает", master_ok))

    overall = _ROSPY_OK and _CLOVER_OK and master_ok
    return {"ok": overall, "items": items, "host": host}
