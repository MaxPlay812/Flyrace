import copy
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

try:
    import rospy
    from clover import srv as clover_srv
    from std_srvs.srv import Trigger
    _ROS_AVAILABLE = True
except ImportError:
    _ROS_AVAILABLE = False


@dataclass
class Telemetry:
    x: float = 0.0       # m, field origin
    y: float = 0.0       # m
    z: float = 0.0       # m altitude
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    yaw: float = 0.0     # radians
    battery: float = 100.0  # %
    armed: bool = False
    connected: bool = False
    mode: str = "MANUAL"
    of_active: bool = False  # optical flow active


class CloverController:
    """Interface to Clover 4 drone via ROS or simulation fallback."""

    def __init__(self):
        self._telemetry = Telemetry()
        self._lock = threading.Lock()
        self._callbacks: List[Callable] = []
        self._running = False
        self._speed = 0.5
        self.ros_available = _ROS_AVAILABLE

        if _ROS_AVAILABLE:
            self._init_ros()
        else:
            self._init_sim()

    # ------------------------------------------------------------------ setup
    def _init_ros(self):
        from config import ROS_NS, TELEMETRY_HZ
        try:
            rospy.init_node("clover_gui", anonymous=True, disable_signals=True)
            ns = f"/{ROS_NS}"
            self._svc_telem = rospy.ServiceProxy(f"{ns}/get_telemetry", clover_srv.GetTelemetry)
            self._svc_nav = rospy.ServiceProxy(f"{ns}/navigate", clover_srv.Navigate)
            self._svc_vel = rospy.ServiceProxy(f"{ns}/set_velocity", clover_srv.SetVelocity)
            self._svc_land = rospy.ServiceProxy(f"{ns}/land", Trigger)
            self._running = True
            t = threading.Thread(target=self._poll_ros, daemon=True)
            t.start()
        except Exception as exc:
            print(f"[Controller] ROS init failed ({exc}), using simulation")
            self.ros_available = False
            self._init_sim()

    def _init_sim(self):
        self._sim_t = 0.0
        self._sim_paused = True
        self._running = True
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
                    v = getattr(t, "voltage", 8.4)
                    self._telemetry.battery = min(100, v / 8.4 * 100)
            except Exception:
                with self._lock:
                    self._telemetry.connected = False
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
                    self._telemetry.mode = "AUTO"
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

    # ---------------------------------------------------------------- private
    def _notify(self):
        t = self.get_telemetry()
        for cb in list(self._callbacks):
            try:
                cb(t)
            except Exception:
                pass
