import json
from dataclasses import dataclass
from enum import Enum


class ZoneType(str, Enum):
    NORMAL = "normal"
    ACCELERATE = "accelerate"
    DECELERATE = "decelerate"
    WAYPOINT = "waypoint"
    START = "start"

    def label(self) -> str:
        return {
            ZoneType.NORMAL: "Нейтральная",
            ZoneType.ACCELERATE: "Ускорение",
            ZoneType.DECELERATE: "Замедление",
            ZoneType.WAYPOINT: "Маршрутная точка",
            ZoneType.START: "Старт / Финиш",
        }[self]


@dataclass
class ArucoMarker:
    marker_id: int
    x: float  # mm on field (from bottom-left)
    y: float  # mm on field
    size: float  # mm physical size
    zone_type: ZoneType = ZoneType.NORMAL
    speed_value: float = 0.5  # m/s target speed when zone active
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.marker_id,
            "x": self.x,
            "y": self.y,
            "size": self.size,
            "zone_type": self.zone_type.value,
            "speed_value": self.speed_value,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ArucoMarker":
        return cls(
            marker_id=d["id"],
            x=float(d["x"]),
            y=float(d["y"]),
            size=float(d.get("size", 150)),
            zone_type=ZoneType(d.get("zone_type", "normal")),
            speed_value=float(d.get("speed_value", 0.5)),
            label=str(d.get("label", "")),
        )


def load_markers(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [ArucoMarker.from_dict(d) for d in data]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def save_markers(path: str, markers: list):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([m.to_dict() for m in markers], f, indent=2, ensure_ascii=False)
