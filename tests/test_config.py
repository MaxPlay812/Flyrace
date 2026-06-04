"""Sanity checks on the static field configuration constants."""

import config


def test_field_dimensions_positive():
    assert config.FIELD_W > 0
    assert config.FIELD_H > 0


def test_poles_inside_field():
    for pole in (config.POLE_1, config.POLE_2):
        x, y = pole
        assert 0 <= x <= config.FIELD_W
        assert 0 <= y <= config.FIELD_H


def test_speed_bounds_ordered():
    assert config.MIN_SPEED < config.DEFAULT_SPEED < config.MAX_SPEED


def test_camera_topic_is_absolute():
    assert config.CAMERA_TOPIC.startswith("/")


def test_paths_point_into_repo():
    assert config.FIELD_FILE.endswith("field.json")
    assert config.MARKERS_FILE.endswith("markers.json")


def test_version_is_set():
    assert config.APP_VERSION
    assert config.APP_TITLE
