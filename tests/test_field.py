"""Tests for the editable ∞ track geometry and persistence."""

import math

import pytest

from models.field import REG_POLE_1, REG_POLE_2, FieldConfig


def _loop_area_centroid(points, center_x):
    """Area centroid (shoelace) of the loop whose x is past ``center_x``.

    A plain average of boundary points is wrong here — samples are uniform in
    the curve parameter, not in space — so we use the polygon centroid.
    """
    loop = [(x, y) for x, y in points if x >= center_x]
    area = cx = cy = 0.0
    n = len(loop)
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area *= 0.5
    return cx / (6 * area), cy / (6 * area)


def test_default_is_regulation_layout():
    field = FieldConfig()
    assert field.pole1 == REG_POLE_1
    assert field.pole2 == REG_POLE_2
    assert field.loop_scale == 1.0


def test_curve_is_closed_and_dense():
    points = FieldConfig().lemniscate_points(600)
    assert len(points) == 601
    # closed: first and last point coincide
    assert points[0] == pytest.approx(points[-1])


def test_poles_sit_at_loop_centroids():
    """At scale 1.0 each pole must lie at the area centroid of its loop."""
    field = FieldConfig()
    center_x = field.center[0]
    cx_right, cy_right = _loop_area_centroid(field.lemniscate_points(4000), center_x)
    assert cx_right == pytest.approx(field.pole2_x, abs=5.0)
    assert cy_right == pytest.approx(field.pole2_y, abs=5.0)


def test_tip_distance_matches_parameter():
    field = FieldConfig()
    cx, cy = field.center
    tx, ty = field.tip_point()
    assert math.hypot(tx - cx, ty - cy) == pytest.approx(field.param_a * math.sqrt(2.0))


def test_loop_scale_is_clamped():
    field = FieldConfig()
    field.set_loop_scale(99.0)
    assert field.loop_scale == 3.0
    field.set_loop_scale(0.0)
    assert field.loop_scale == 0.3


def test_set_tip_distance_round_trips():
    field = FieldConfig()
    field.set_tip_distance(2000.0)
    cx, cy = field.center
    tx, ty = field.tip_point()
    assert math.hypot(tx - cx, ty - cy) == pytest.approx(2000.0, abs=1.0)


def test_curve_follows_rotated_poles():
    """A vertical pole layout must yield a vertical ∞."""
    field = FieldConfig(pole1_x=2500, pole1_y=1000, pole2_x=2500, pole2_y=2000)
    points = field.lemniscate_points(400)
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    # vertical orientation: y spread larger than x spread
    assert (max(ys) - min(ys)) > (max(xs) - min(xs))


def test_set_pole_rejects_bad_index():
    with pytest.raises(ValueError):
        FieldConfig().set_pole(2, 0, 0)


def test_reset_restores_regulation():
    field = FieldConfig(pole1_x=0, pole1_y=0, pole2_x=10, pole2_y=10, loop_scale=2.0)
    field.reset()
    assert field.pole1 == REG_POLE_1
    assert field.pole2 == REG_POLE_2
    assert field.loop_scale == 1.0


def test_save_and_load_round_trip(tmp_path):
    path = str(tmp_path / "field.json")
    original = FieldConfig(
        pole1_x=1200, pole1_y=1300, pole2_x=3600, pole2_y=1400, loop_scale=1.25
    )
    original.save(path)
    loaded = FieldConfig.load(path)
    assert loaded == original


def test_load_missing_file_returns_default():
    loaded = FieldConfig.load("/nonexistent/field.json")
    assert loaded == FieldConfig()


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "field.json"
    path.write_text('{"pole1_x": 1000, "garbage": 5}')
    loaded = FieldConfig.load(str(path))
    assert loaded.pole1_x == 1000


def test_degenerate_poles_produce_no_curve():
    """Coincident poles must not crash — just yield an empty curve."""
    field = FieldConfig(pole1_x=2500, pole1_y=1500, pole2_x=2500, pole2_y=1500)
    assert field.lemniscate_points() == []
