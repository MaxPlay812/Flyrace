"""Centralised visual theme for the Clover 4 Race GUI.

A single dark "racing" palette (amber accent) plus the Qt stylesheet that
every widget inherits. Keeping colours and QSS here means the look is tuned
in one place instead of scattered inline styles.

Buttons opt into a role with a dynamic property, e.g.::

    btn.setProperty("role", "primary")   # amber call-to-action
    btn.setProperty("role", "danger")    # destructive / emergency

so the stylesheet can target them without per-widget styling.
"""

from __future__ import annotations

# ---------------------------------------------------------------- palette
BG = "#14161a"  # window background (deep graphite)
SURFACE = "#1c1f26"  # cards / panels
SURFACE_HI = "#242832"  # raised elements, hovered rows
BORDER = "#323844"
TEXT = "#e6e8ec"
TEXT_DIM = "#9aa3ad"

ACCENT = "#f59e0b"  # amber — primary accent
ACCENT_HI = "#fbbf24"  # lighter amber for hover
SUCCESS = "#34d399"
WARNING = "#fbbf24"
DANGER = "#ef4444"
DANGER_HI = "#f87171"
TRACK = "#f5d020"  # ∞ track yellow


def battery_color(percent: float) -> str:
    """Traffic-light colour for a battery level."""
    if percent > 50:
        return SUCCESS
    if percent > 20:
        return WARNING
    return DANGER


STYLESHEET = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 13px;
}}

/* ---- cards / group boxes ---- */
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 10px 10px 8px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: {TEXT_DIM};
}}

/* ---- buttons ---- */
QPushButton {{
    background: {SURFACE_HI};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ background: #2b303b; border-color: #3d4452; }}
QPushButton:pressed {{ background: #181b21; }}
QPushButton:disabled {{ color: #5b626c; background: {SURFACE}; }}

QPushButton[role="primary"] {{
    background: {ACCENT};
    color: #1a1205;
    border: none;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HI}; }}
QPushButton[role="primary"]:pressed {{ background: #d98908; }}

QPushButton[role="danger"] {{
    background: {DANGER};
    color: #fff;
    border: none;
}}
QPushButton[role="danger"]:hover {{ background: {DANGER_HI}; }}

/* mode-switch segmented buttons */
QPushButton[role="mode"] {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 6px 18px;
    color: {TEXT_DIM};
}}
QPushButton[role="mode"]:hover {{ color: {TEXT}; }}
QPushButton[role="mode"]:checked {{
    background: {SURFACE};
    color: {ACCENT};
    border: 1px solid {BORDER};
}}

/* ---- tabs ---- */
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

/* ---- inputs ---- */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {SURFACE_HI};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border-color: {ACCENT};
}}

/* ---- slider ---- */
QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_HI}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -6px 0;
    border-radius: 8px; background: {ACCENT_HI};
}}

/* ---- progress (battery) ---- */
QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 7px;
    height: 16px;
    text-align: center;
    font-size: 11px;
    background: {SURFACE_HI};
}}
QProgressBar::chunk {{ border-radius: 6px; background: {SUCCESS}; }}

/* ---- lists ---- */
QListWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    alternate-background-color: {SURFACE_HI};
}}
QListWidget::item:selected {{ background: {ACCENT}; color: #1a1205; }}

/* ---- misc ---- */
QStatusBar {{ background: {BG}; color: {TEXT_DIM}; border-top: 1px solid {BORDER}; }}
QSplitter::handle {{ background: {BORDER}; }}
QScrollBar:vertical {{ background: {BG}; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #3d4452; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
