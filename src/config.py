import os as _os

FIELD_W = 5000  # mm  — wider so figure-eight circles fit with margin
FIELD_H = 3000  # mm

POLE_1 = (1500, 1500)  # (x, y) mm from bottom-left
POLE_2 = (3500, 1500)
POLE_DIAMETER = 110  # mm
TRACK_RADIUS = 500  # mm — drone flight circle radius around each pole
TRACK_LINE_W = 50  # mm
DASH_LEN = 300  # mm
GAP_LEN = 100  # mm

DEFAULT_SPEED = 0.5  # m/s
MAX_SPEED = 2.5
MIN_SPEED = 0.1
FLIGHT_ALT = 1.5  # m

ARUCO_DICT_NAME = "DICT_4X4_50"
DEFAULT_MARKER_SIZE = 150  # mm physical

ROS_NS = "clover"
CAMERA_TOPIC = "/main_camera/image_raw"
TELEMETRY_HZ = 10

MARKERS_FILE = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "markers.json"
)
APP_TITLE = "Clover 4 — Воздушные гонки"
APP_VERSION = "1.1.0"
