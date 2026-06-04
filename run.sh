#!/usr/bin/env bash
# Launch the Clover 4 Race GUI on Linux (with ROS) or macOS (dev, no ROS).
#
# Two modes, chosen automatically:
#   * ROS present  (/opt/ros/noetic) → use the SYSTEM python so rospy / clover
#     from the ROS install and the catkin workspace are importable.
#   * ROS absent   (macOS dev)       → use an isolated .venv so PyQt5 does not
#     clash with a system PyQt6 (the macOS Qt5/Qt6 segfault).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ROS_SETUP=/opt/ros/noetic/setup.bash
CATKIN_SETUP="$HOME/catkin_ws/devel/setup.bash"
PY=python3

# ── ROS Noetic setup ──────────────────────────────────────────────────
if [ -f "$ROS_SETUP" ]; then
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    echo "[run.sh] sourced $ROS_SETUP"
    if [ -f "$CATKIN_SETUP" ]; then
        # shellcheck disable=SC1090
        source "$CATKIN_SETUP"
        echo "[run.sh] sourced $CATKIN_SETUP"
    fi
else
    echo "[run.sh] ВНИМАНИЕ: ROS Noetic не найден ($ROS_SETUP отсутствует)"
    # ── No ROS → isolated venv to avoid the macOS PyQt5/PyQt6 clash ──
    VENV="$SCRIPT_DIR/.venv"
    if [ ! -d "$VENV" ]; then
        echo "[run.sh] создаю изолированное окружение: $VENV"
        python3 -m venv "$VENV"
    fi
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
    PY="$VENV/bin/python"
    echo "[run.sh] venv активирован: $VENV"
    # Install/refresh dependencies only when something is missing.
    if ! "$PY" -c "import PyQt5, cv2, numpy" >/dev/null 2>&1; then
        echo "[run.sh] устанавливаю зависимости в venv…"
        "$PY" -m pip install --quiet --upgrade pip
        "$PY" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
    fi
fi

# ── ROS_MASTER_URI ────────────────────────────────────────────────────
if [ -z "${ROS_MASTER_URI:-}" ]; then
    export ROS_MASTER_URI=http://192.168.11.1:11311
    echo "[run.sh] ROS_MASTER_URI задан автоматически: $ROS_MASTER_URI"
else
    echo "[run.sh] ROS_MASTER_URI=$ROS_MASTER_URI"
fi

# ── ROS_IP: автодетект по маршруту к дрону (Linux only) ───────────────
DRONE_IP=$(echo "$ROS_MASTER_URI" | sed 's|http://||' | cut -d':' -f1)
if [ -z "${ROS_IP:-}" ]; then
    DETECTED_IP=""
    if command -v ip >/dev/null 2>&1; then
        DETECTED_IP=$(ip route get "$DRONE_IP" 2>/dev/null \
                      | sed -n 's/.*src \([0-9.]*\).*/\1/p' | head -1)
    fi
    if [ -n "$DETECTED_IP" ]; then
        export ROS_IP="$DETECTED_IP"
        echo "[run.sh] ROS_IP автодетект:  $ROS_IP  (через маршрут к $DRONE_IP)"
    else
        echo "[run.sh] ВНИМАНИЕ: не удалось определить ROS_IP автоматически."
        echo "         Задайте вручную: export ROS_IP=192.168.11.XXX"
    fi
else
    echo "[run.sh] ROS_IP=$ROS_IP"
fi

# ── clover пакет ──────────────────────────────────────────────────────
if "$PY" -c "from clover import srv" 2>/dev/null; then
    echo "[run.sh] clover пакет: OK"
else
    echo "[run.sh] ВНИМАНИЕ: пакет 'clover' не найден — режим симуляции."
    echo "         Инструкция: docs/ROS_UBUNTU.md"
fi

# ── Preflight self-test (packages, geometry, imports) ─────────────────
echo ""
if ! "$PY" "$SCRIPT_DIR/scripts/preflight.py"; then
    echo "[run.sh] Запуск отменён: preflight нашёл проблемы (см. выше)."
    exit 1
fi

echo ""
exec "$PY" src/main.py "$@"
