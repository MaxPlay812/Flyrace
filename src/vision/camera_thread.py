from __future__ import annotations
import logging
import threading
import time
from typing import Callable, List, Optional, Union
import numpy as np

_cam_log = logging.getLogger("clover_gui").info

try:
    import cv2

    _CV2_OK = True
except ImportError:
    _CV2_OK = False


class CameraThread(threading.Thread):
    """Captures frames from a camera source in a background thread.

    source: int (device index), str path, or ROS topic string starting with '/'.
    """

    def __init__(self, source: Union[int, str] = 0):
        super().__init__(daemon=True, name="CameraThread")
        self._source = source
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._callbacks: List[Callable] = []
        self._use_ros = isinstance(source, str) and str(source).startswith("/")
        self._cap = None
        self._ros_sub = None

    # ------------------------------------------------------------ public API
    def add_frame_callback(self, cb: Callable[[np.ndarray], None]):
        self._callbacks.append(cb)

    def remove_frame_callback(self, cb: Callable):
        self._callbacks = [c for c in self._callbacks if c is not cb]

    def get_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def start(self):
        self._running = True
        if self._use_ros:
            self._start_ros()
        else:
            super().start()

    def stop(self):
        self._running = False
        if self._cap:
            self._cap.release()
        if self._ros_sub:
            try:
                self._ros_sub.unregister()
            except Exception:
                # Already torn down or ROS shutting down — nothing to recover.
                pass

    # ------------------------------------------------------- ROS path
    def _start_ros(self):
        try:
            import rospy
            from sensor_msgs.msg import Image, CompressedImage
            from cv_bridge import CvBridge

            self._bridge = CvBridge()
            # Prefer compressed topic to reduce WiFi bandwidth and latency
            compressed = self._source + "/compressed"
            try:
                published = dict(rospy.get_published_topics())
                use_compressed = compressed in published
            except Exception:
                use_compressed = False
            if use_compressed:
                self._ros_sub = rospy.Subscriber(
                    compressed,
                    CompressedImage,
                    self._ros_cb_compressed,
                    queue_size=1,
                    buff_size=2**22,
                    tcp_nodelay=True,
                )
                _cam_log(f"[Camera] compressed: {compressed}")
            else:
                self._ros_sub = rospy.Subscriber(
                    self._source,
                    Image,
                    self._ros_cb,
                    queue_size=1,
                    buff_size=2**24,
                    tcp_nodelay=True,
                )
        except Exception as exc:
            _cam_log(
                f"[Camera] ROS subscribe failed ({exc}), falling back to OpenCV device 0"
            )
            self._use_ros = False
            self._source = 0
            threading.Thread.start(self)

    def _ros_cb(self, msg):
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            self._push(frame)
        except Exception:
            # Drop a single malformed frame rather than kill the subscriber.
            pass

    def _ros_cb_compressed(self, msg):
        try:
            nparr = np.frombuffer(msg.data, np.uint8)
            import cv2 as _cv2

            frame = _cv2.imdecode(nparr, _cv2.IMREAD_COLOR)
            if frame is not None:
                self._push(frame)
        except Exception:
            # Drop a single undecodable frame; the next one will arrive.
            pass

    # ------------------------------------------------------- OpenCV path
    def run(self):
        if not _CV2_OK:
            return
        # On Linux prefer V4L2 to avoid GStreamer warnings
        import sys

        backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(self._source, backend)
        if not self._cap.isOpened():
            # Try test pattern if device unavailable
            self._run_test_pattern()
            return
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # minimize capture buffer lag
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            self._push(frame)

    def _run_test_pattern(self):
        """Generate a synthetic camera feed when no device is available."""
        import math

        t = 0.0
        while self._running:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            frame[:] = (30, 30, 30)
            cx = int(320 + 200 * math.sin(t))
            cy = int(240 + 100 * math.cos(t * 0.7))
            cv2.circle(frame, (cx, cy), 30, (0, 200, 100), -1)
            cv2.putText(
                frame,
                "SIM CAM — no device",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (180, 180, 180),
                2,
            )
            self._push(frame)
            t += 0.05
            time.sleep(1 / 15)

    # ---------------------------------------------------------------- private
    def _push(self, frame: np.ndarray):
        with self._lock:
            self._frame = frame
        for cb in list(self._callbacks):
            try:
                cb(frame.copy())
            except Exception:
                # A failing consumer must not stall frame capture.
                pass
