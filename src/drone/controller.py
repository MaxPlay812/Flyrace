"""Clover 4 drone controller.

Detects three connection states:
  FULL  — rospy + clover.srv available, drone reachable
  ROSPY — rospy available but clover package missing on this machine
  SIM   — no ROS at all, pure simulation fallback
"""
import copy
import math
import os
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
    FULL  = auto()   # rospy + clover.srv reachable
    ROSPY = auto()   # rospy present but clover package missing
    SIM   = auto()   # no ROS


@dataclass
class Telemetry:
    x: float = 0.0        # m, field origin
    y: float = 0.0
    z: float = 0.0        # m altitude
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    yaw: float = 0.0      # radians
    battery: float = 100.0
    armed: bool = False
    connected: bool = False
    mode: str = "MANUAL"
    of_active: bool = False
    ros_state: RosState = RosState.SIM
    error_msg: str = ""


class CloverController:
    """Interface to Clover 4 drone via ROS or simulation fallback."""

    def __init__(self):
        self._telemetry = Telemetry()
        self._lock = threading.Lock()
        self._callbacks: List[Callable] = []
        self._running = True
        self._speed = 0.5
        self._ros_state = RosState.SIM

        if not _ROSPY_OK:
            self._ros_state = RosState.SIM
            self._init_sim()
        elif not _CLOVER_OK:
            self._ros_state = RosState.ROSPY
            self._telemetry.ros_state = RosState.ROSPY
            self._telemetry.error_msg = (
                "rospy найден, но пакет 'clover' не установлен на этом ПК.\n"
                "Установите его или соберите catkin-воркспейс с пакетом clover.\n"
                "Нажмите 'Настройки ROS' для инструкций."
            )
            self._init_sim()
        else:
            self._ros_state = RosState.FULL
            self._init_ros()

    # ------------------------------------------------------------------ props
    @property
    def ros_state(self) -> RosState:
        return self._ros_state

    @property
    def ros_available(self) -> bool:
        return self._ros_state == RosState.FULL

    # ------------------------------------------------------------------ setup
    def _init_ros(self):
        from config import ROS_NS
        try:
            if not rospy.core.is_initialized():
                rospy.init_node("clover_gui", anonymous=True, disable_signals=True)
            ns = f"/{ROS_NS}"
            # Wait up to 3 s for telemetry service before declaring connected
            try:
                rospy.wait_for_service(f"{ns}/get_telemetry", timeout=3.0)
            except rospy.ROSException:
                raise ConnectionError(
                    f"Сервис {ns}/get_telemetry недоступен.\n"
                    "Проверьте: ROS_MASTER_URI, WiFi-соединение с дроном."
                )
            self._svc_telem = rospy.ServiceProxy(
                f"{ns}/get_telemetry", _clover_srv.GetTelemetry)
            self._svc_nav = rospy.ServiceProxy(
                f"{ns}/navigate", _clover_srv.Navigate)
            self._svc_vel = rospy.ServiceProxy(
                f"{ns}/set_velocity", _clover_srv.SetVelocity)
            self._svc_land = rospy.ServiceProxy(f"{ns}/land", _Trigger)
            threading.Thread(target=self._poll_ros, daemon=True).start()
        except Exception as exc:
            err = str(exc)
            with self._lock:
                self._telemetry.connected = False
                self._telemetry.error_msg = err
            self._ros_state = RosState.ROSPY if _ROSPY_OK else RosState.SIM
            self._init_sim()

    def _init_sim(self):
        self._sim_t = 0.0
        self._sim_paused = True
        threading.Thread(target=self._run_sim, daemon=True).start()

    # -------------------------------------------------------------- ros loop
    def _poll_ros(self):
        from config import TELEMETRY_HZ
        rate = 1.0 / TELEMETRY_HZ
        while self._running:
            try:
                t = self._svc_telem(frame_id="map")
                with self._lock:
                    self._telemetry.x = t.x
                    self._telemetry.y = t.y
                    self._telemetry.z = t.z
                    self._telemetry.vx = t.vx
                    self._telemetry.vy = t.vy
                    self._telemetry.yaw = t.yaw
                    self._telemetry.armed = t.armed
                    self._telemetry.connected = True
                    self._telemetry.mode = t.mode
                    self._telemetry.ros_state = RosState.FULL
                    self._telemetry.error_msg = ""
                    v = getattr(t, "voltage", 8.4)
                    self._telemetry.battery = min(100.0, v / 8.4 * 100)
            except Exception as exc:
                with self._lock:
                    self._telemetry.connected = False
                    self._telemetry.error_msg = str(exc)
            self._notify()
            time.sleep(rate)

    # ----------------------------------------------------------- simulation
    def _run_sim(self):
        from config import POLE_1, POLE_2, TRACK_RADIUS, FLIGHT_ALT
        cx1, cy1 = POLE_1[0] / 1000.0, POLE_1[1] / 1000.0
        cx2, cy2 = POLE_2[0] / 1000.0, POLE_2[1] / 1000.0
        r = TRACK_RADIUS / 1000.0
        dt = 0.05
        while self._running:
            if not self._sim_paused:
                period = 2 * math.pi
                cycle = self._sim_t % (2 * period)
                if cycle < period:
                    ang = cycle
                    x = cx1 + r * math.cos(ang + math.pi)
                    y = cy1 + r * math.sin(ang + math.pi)
                    yaw = ang + math.pi / 2
                else:
                    ang = cycle - period
                    x = cx2 + r * math.cos(ang)
                    y = cy2 + r * math.sin(ang)
                    yaw = ang + math.pi / 2
                with self._lock:
                    self._telemetry.x = x
                    self._telemetry.y = y
                    self._telemetry.z = FLIGHT_ALT
                    self._telemetry.yaw = yaw
                    self._telemetry.armed = True
                    self._telemetry.connected = True
                    self._telemetry.mode = "SIM"
                    self._telemetry.of_active = True
                    self._telemetry.battery = max(0.0, 100.0 - self._sim_t * 0.2)
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
        """Attempt ROS reconnection in background (e.g. after env vars updated)."""
        if not _CLOVER_OK:
            return
        self._ros_state = RosState.FULL
        threading.Thread(target=self._init_ros, daemon=True).start()

    def takeoff(self, altitude: Optional[float] = None):
        from config import FLIGHT_ALT
        alt = altitude or FLIGHT_ALT
        if self.ros_available:
            try:
                self._svc_nav(x=0, y=0, z=alt, frame_id="body", auto_arm=True)
            except Exception as e:
                print(f"[Controller] takeoff: {e}")
        else:
            self._sim_paused = False
            with self._lock:
                self._telemetry.armed = True
                self._telemetry.z = alt

    def land(self):
        if self.ros_available:
            try:
                self._svc_land()
            except Exception as e:
                print(f"[Controller] land: {e}")
        else:
            self._sim_paused = True
            with self._lock:
                self._telemetry.armed = False
                self._telemetry.z = 0.0

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
    """Check ROS connectivity. Returns dict with keys: ok, items (list of (label, status, ok))."""
    uri = master_uri or os.environ.get("ROS_MASTER_URI", "http://192.168.11.1:11311")
    items = []

    # 1. rospy importable
    items.append(("rospy установлен", "Да" if _ROSPY_OK else "НЕТ — установите ROS Noetic", _ROSPY_OK))

    # 2. clover package importable
    items.append(("clover пакет", "Да" if _CLOVER_OK else "НЕТ — нет типов сервисов", _CLOVER_OK))

    # 3. ROS_MASTER_URI set
    env_uri = os.environ.get("ROS_MASTER_URI", "")
    items.append(("ROS_MASTER_URI", env_uri or "(не задан)", bool(env_uri)))

    # 4. ROS_IP set
    env_ip = os.environ.get("ROS_IP", os.environ.get("ROS_HOSTNAME", ""))
    items.append(("ROS_IP", env_ip or "(не задан — может не работать)", bool(env_ip)))

    # 5. Ping drone IP
    host = uri.split("//")[-1].split(":")[0] if "//" in uri else "192.168.11.1"
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", host],
            capture_output=True, timeout=3
        )
        reachable = result.returncode == 0
    except Exception:
        reachable = False
    items.append((f"Ping {host}", "Доступен" if reachable else "Недоступен", reachable))

    # 6. rosmaster reachable (try xmlrpc)
    master_ok = False
    if _ROSPY_OK:
        try:
            import xmlrpc.client
            proxy = xmlrpc.client.ServerProxy(uri)
            code, _, _ = proxy.getSystemState("/diag")
            master_ok = (code == 1)
        except Exception:
            pass
    items.append(("rosmaster", "Отвечает" if master_ok else "Не отвечает", master_ok))

    overall = _ROSPY_OK and _CLOVER_OK and master_ok
    return {"ok": overall, "items": items, "host": host}
