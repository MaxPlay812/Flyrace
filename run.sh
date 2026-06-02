#!/usr/bin/env bash
# Launch the Clover 4 Race GUI on Linux / macOS
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Virtual environment (uncomment if you use one) ────────────────────
# source venv/bin/activate

# ── ROS Noetic setup ──────────────────────────────────────────────────
ROS_SETUP=/opt/ros/noetic/setup.bash
CATKIN_SETUP="$HOME/catkin_ws/devel/setup.bash"

if [ -f "$ROS_SETUP" ]; then
    source "$ROS_SETUP"
    echo "[run.sh] sourced $ROS_SETUP"
else
    echo "[run.sh] ВНИМАНИЕ: ROS Noetic не найден ($ROS_SETUP отсутствует)"
fi

if [ -f "$CATKIN_SETUP" ]; then
    source "$CATKIN_SETUP"
    echo "[run.sh] sourced $CATKIN_SETUP"
fi

# ── ROS_MASTER_URI ────────────────────────────────────────────────────
if [ -z "${ROS_MASTER_URI:-}" ]; then
    export ROS_MASTER_URI=http://192.168.11.1:11311
    echo "[run.sh] ROS_MASTER_URI задан автоматически: $ROS_MASTER_URI"
else
    echo "[run.sh] ROS_MASTER_URI=$ROS_MASTER_URI"
fi

# ── ROS_IP: автодетект по маршруту к дрону ───────────────────────────
# ROS требует явного IP локальной машины, иначе дрон не может
# обратно подключиться к нашему узлу (двунаправленный TCP).
DRONE_IP=$(echo "$ROS_MASTER_URI" | sed 's|http://||' | cut -d':' -f1)

if [ -z "${ROS_IP:-}" ]; then
    # Определяем IP нашего интерфейса на пути к дрону
    DETECTED_IP=$(ip route get "$DRONE_IP" 2>/dev/null \
                  | grep -oP 'src \K[0-9.]+' | head -1)
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

# ── Проверка clover пакета ────────────────────────────────────────────
if python3 -c "from clover import srv" 2>/dev/null; then
    echo "[run.sh] clover пакет: OK"
else
    echo "[run.sh] ВНИМАНИЕ: пакет 'clover' не найден — режим симуляции."
    echo "         Инструкция: docs/ROS_UBUNTU.md"
fi

echo ""
python3 src/main.py "$@"
