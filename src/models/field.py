"""Editable field layout for the Воздушные гонки track.

The track is a Bernoulli lemniscate (the ∞ / figure-eight curve). Its shape
is fully determined by three editable values:

  * the two pole positions ``pole1`` / ``pole2`` — the loops are built around
    the line joining them and centred on their midpoint;
  * ``loop_scale`` — a multiplier on the loop size. At ``1.0`` each loop's
    centroid sits exactly on its pole (the РобоФинист regulation layout).

All coordinates are millimetres measured from the bottom-left of the field.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import List, Tuple

Point = Tuple[float, float]

# Regulation default layout (РобоФинист «Воздушные гонки»): poles 2000 mm apart,
# shifted to the loop centroids so they sit centred inside each loop.
REG_POLE_1: Point = (1715.0, 1500.0)
REG_POLE_2: Point = (3285.0, 1500.0)

# Centroid of one lemniscate loop lies at a·π/4 from the centre, so this factor
# turns the half pole-distance into the lemniscate parameter ``a``.
_HALF_TO_A = 4.0 / math.pi


@dataclass
class FieldConfig:
    """Pole positions and loop scale defining the editable ∞ track."""

    pole1_x: float = REG_POLE_1[0]
    pole1_y: float = REG_POLE_1[1]
    pole2_x: float = REG_POLE_2[0]
    pole2_y: float = REG_POLE_2[1]
    loop_scale: float = 1.0

    # -------------------------------------------------- pole accessors
    @property
    def pole1(self) -> Point:
        return (self.pole1_x, self.pole1_y)

    @property
    def pole2(self) -> Point:
        return (self.pole2_x, self.pole2_y)

    def pole(self, index: int) -> Point:
        return self.pole1 if index == 0 else self.pole2

    def set_pole(self, index: int, x: float, y: float) -> None:
        if index == 0:
            self.pole1_x, self.pole1_y = x, y
        elif index == 1:
            self.pole2_x, self.pole2_y = x, y
        else:
            raise ValueError(f"pole index must be 0 or 1, got {index}")

    def set_loop_scale(self, scale: float) -> None:
        # Clamp to a sane range so the curve never collapses or explodes.
        self.loop_scale = max(0.3, min(3.0, scale))

    def set_tip_distance(self, dist_mm: float) -> None:
        """Resize the loops so the outer tip sits ``dist_mm`` from the centre.

        Used by the map's resize handle: the user drags the tip, we back out
        the matching ``loop_scale``.
        """
        base = self.half_span * _HALF_TO_A
        if base <= 0.0:
            return
        a = dist_mm / math.sqrt(2.0)
        self.set_loop_scale(a / base)

    def reset(self) -> None:
        self.pole1_x, self.pole1_y = REG_POLE_1
        self.pole2_x, self.pole2_y = REG_POLE_2
        self.loop_scale = 1.0

    # -------------------------------------------------- derived geometry
    @property
    def center(self) -> Point:
        return (
            (self.pole1_x + self.pole2_x) / 2.0,
            (self.pole1_y + self.pole2_y) / 2.0,
        )

    @property
    def half_span(self) -> float:
        """Half the distance between the two poles, in mm."""
        return (
            math.hypot(self.pole2_x - self.pole1_x, self.pole2_y - self.pole1_y) / 2.0
        )

    @property
    def param_a(self) -> float:
        """Lemniscate parameter ``a`` for the current poles and scale."""
        return self.half_span * _HALF_TO_A * self.loop_scale

    def tip_point(self) -> Point:
        """Outer tip of the pole2-side loop — used as the resize handle."""
        cx, cy = self.center
        tip = self.param_a * math.sqrt(2.0)
        angle = math.atan2(self.pole2_y - self.pole1_y, self.pole2_x - self.pole1_x)
        return (cx + tip * math.cos(angle), cy + tip * math.sin(angle))

    def lemniscate_points(self, samples: int = 600) -> List[Point]:
        """Trace the ∞ curve as a list of (x_mm, y_mm) points.

        The curve is generated in a local frame aligned with the pole axis,
        then rotated and translated, so it follows the poles at any angle.
        """
        a = self.param_a
        if a <= 0.0:
            return []
        cx, cy = self.center
        angle = math.atan2(self.pole2_y - self.pole1_y, self.pole2_x - self.pole1_x)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        scale = a * math.sqrt(2.0)

        points: List[Point] = []
        for i in range(samples + 1):
            t = 2.0 * math.pi * i / samples
            denom = math.sin(t) ** 2 + 1.0
            local_x = scale * math.cos(t) / denom
            local_y = scale * math.cos(t) * math.sin(t) / denom
            x = cx + local_x * cos_a - local_y * sin_a
            y = cy + local_x * sin_a + local_y * cos_a
            points.append((x, y))
        return points

    # -------------------------------------------------- persistence
    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "FieldConfig":
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        fields = set(cls.__dataclass_fields__)
        known = {k: float(v) for k, v in data.items() if k in fields}
        return cls(**known)
