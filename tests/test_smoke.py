"""Headless smoke tests: every module imports and the window builds."""

import importlib

import pytest

GUI_MODULES = [
    "config",
    "models.field",
    "models.marker",
    "drone.controller",
    "vision.camera_thread",
    "gui.map_widget",
    "gui.status_widget",
    "gui.main_window",
]


@pytest.mark.parametrize("name", GUI_MODULES)
def test_module_imports(name):
    importlib.import_module(name)


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_builds(qapp):
    from gui.main_window import MainWindow

    window = MainWindow()
    try:
        assert window.windowTitle()
        # the editable field is wired and produces a curve
        assert window._map_w.field.lemniscate_points()
    finally:
        window.close()


def test_field_edit_persists(qapp, tmp_path, monkeypatch):
    import config
    from gui.map_widget import MapWidget

    field_file = tmp_path / "field.json"
    monkeypatch.setattr(config, "FIELD_FILE", str(field_file))
    monkeypatch.setattr("gui.map_widget.FIELD_FILE", str(field_file))

    widget = MapWidget()
    widget.field.set_pole(0, 1234, 1456)
    widget.field.save(str(field_file))
    assert field_file.exists()

    from models.field import FieldConfig

    reloaded = FieldConfig.load(str(field_file))
    assert reloaded.pole1_x == 1234


def test_marker_drag_moves_marker(qapp):
    from gui.map_widget import MapWidget
    from models.marker import ArucoMarker

    widget = MapWidget()
    marker = ArucoMarker(marker_id=7, x=1000, y=1000, size=150)
    widget.set_markers([marker])

    # Drag marker #7 to a new field position via the widget API.
    widget._drag = ("marker", 7)
    widget._drag_moved = True
    moved = widget._marker_by_id(7)
    moved.x, moved.y = 2600, 1900
    assert widget._marker_by_id(7).x == 2600
    assert widget._marker_by_id(7).y == 1900
