"""Thread-safe debug logger for ROS connection diagnostics.

Usage (any module):
    from utils.debug_log import log
    log.debug("message")
    log.info("message")
    log.warning("message")
    log.error("message")

The GUI debug widget polls get_new_lines() via QTimer.
"""

import logging
import queue
import threading
from datetime import datetime

_queue: queue.Queue = queue.Queue()
_history: list = []
_history_lock = threading.Lock()
_MAX_HISTORY = 2000

_LEVEL_COLOR = {
    "DEBUG": "#888",
    "INFO": "#8cf",
    "WARNING": "#fa0",
    "ERROR": "#f55",
    "SUCCESS": "#6f6",
}


class _QueueHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        lvl = record.levelname
        line = {
            "ts": ts,
            "level": lvl,
            "text": record.getMessage(),
            "full": f"[{ts}] [{lvl:7s}] {record.getMessage()}",
        }
        with _history_lock:
            _history.append(line)
            if len(_history) > _MAX_HISTORY:
                _history.pop(0)
        _queue.put(line)


_handler = _QueueHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))

log = logging.getLogger("clover_gui")
log.setLevel(logging.DEBUG)
log.addHandler(_handler)
log.propagate = False  # don't double-print to root logger

# convenience: success level
logging.SUCCESS = 25
logging.addLevelName(logging.SUCCESS, "SUCCESS")


def success(msg: str, *args):
    log.log(logging.SUCCESS, msg, *args)


def get_new_lines() -> list:
    """Drain queue; returns list of line dicts."""
    lines = []
    while True:
        try:
            lines.append(_queue.get_nowait())
        except queue.Empty:
            break
    return lines


def get_history() -> list:
    with _history_lock:
        return list(_history)


def get_level_color(level: str) -> str:
    return _LEVEL_COLOR.get(level, "#ddd")
