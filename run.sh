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
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    echo "[run.sh] sourced $ROS_SETUP"
else
    echo "[run.sh] ВНИМАНИЕ: ROS Noetic не найден ($ROS_SETUP отсутствует)"
    echo "         Для установки: https://wiki.ros.org/noetic/Installation/Ubuntu"
fi

if [ -f "$CATKIN_SETUP" ]; then
    # shellcheck disable=SC1090
    source "$CATKIN_SETUP"
    echo "[run.sh] sourced $CATKIN_SETUP"
fi

# ── ROS network (задайте свои значения) ───────────────────────────────
# Если эти переменные уже заданы в .bashrc — оставьте закомментированными
# export ROS_MASTER_URI=http://192.168.11.1:11311
# export ROS_IP=$(hostname -I | awk '{print $1}')

# Диагностика сети
if [ -n "${ROS_MASTER_URI:-}" ]; then
    echo "[run.sh] ROS_MASTER_URI=$ROS_MASTER_URI"
else
    echo "[run.sh] ВНИМАНИЕ: ROS_MASTER_URI не задан."
    echo "         Добавьте в ~/.bashrc:"
    echo "           export ROS_MASTER_URI=http://192.168.11.1:11311"
    echo "           export ROS_IP=\$(hostname -I | awk '{print \$1}')"
fi

# ── Проверка clover пакета ───────────────────────────────────────────
if python3 -c "from clover import srv" 2>/dev/null; then
    echo "[run.sh] clover пакет: OK"
else
    echo "[run.sh] ВНИМАНИЕ: пакет 'clover' не найден."
    echo "         Приложение запустится в режиме симуляции."
    echo "         Для установки clover см. docs/ROS_UBUNTU.md"
fi

echo ""
python3 src/main.py "$@"
