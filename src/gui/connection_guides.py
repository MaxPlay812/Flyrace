"""Static guide texts for the connection dialog."""

GUIDE_QUICK = """\
╔══════════════════════════════════════════════════════╗
║      БЫСТРЫЙ СТАРТ — подключение к Clover 4          ║
╚══════════════════════════════════════════════════════╝

[1] Убедитесь что дрон включён и светодиод мигает.

[2] Подключитесь к WiFi дрона:
    SSID:   clover-XXXX
    Пароль: cloverwifi

[3] Проверьте что ROS Noetic установлен:
    which roscore   →  должен вывести путь

[4] Проверьте что пакет clover установлен:
    python3 -c "from clover import srv; print('OK')"

[5] Задайте переменные (один раз, добавьте в ~/.bashrc):
    export ROS_MASTER_URI=http://192.168.11.1:11311
    export ROS_IP=$(ip route get 192.168.11.1 | grep -oP 'src \\K[0-9.]+')
    source ~/.bashrc

[6] Проверьте связь:
    ping 192.168.11.1                     ← должен пинговаться
    nc -zv 192.168.11.1 11311             ← порт открыт?
    rosservice list | grep clover         ← сервисы видны?

[7] Запустите приложение:
    ./run.sh

══ Если ping есть, но сервисы не видны ══
    ssh pi@192.168.11.1
    sudo systemctl status clover
    sudo systemctl restart clover
"""

GUIDE_INSTALL = """\
╔══════════════════════════════════════════════════════╗
║      УСТАНОВКА ROS NOETIC + clover (Ubuntu 20.04)    ║
╚══════════════════════════════════════════════════════╝

── A. ROS Noetic ───────────────────────────────────────
    sudo sh -c 'echo "deb http://packages.ros.org/ros/ubuntu focal main" \\
      > /etc/apt/sources.list.d/ros-latest.list'
    curl -s https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc \\
      | sudo apt-key add -
    sudo apt update
    sudo apt install ros-noetic-desktop python3-rospy

    # Добавить в ~/.bashrc:
    source /opt/ros/noetic/setup.bash

── B. Пакет clover (из исходников) ─────────────────────
    sudo apt install python3-catkin-tools python3-pip -y
    mkdir -p ~/catkin_ws/src && cd ~/catkin_ws/src
    git clone --depth 1 https://github.com/clover-robotics/clover.git

    cd ~/catkin_ws
    catkin_make
    # или: catkin build

    # Добавить в ~/.bashrc:
    source ~/catkin_ws/devel/setup.bash

── C. Переменные окружения ──────────────────────────────
    # Добавить в ~/.bashrc:
    export ROS_MASTER_URI=http://192.168.11.1:11311
    export ROS_IP=$(ip route get 192.168.11.1 | grep -oP 'src \\K[0-9.]+')

── D. Проверка ──────────────────────────────────────────
    source ~/.bashrc
    python3 -c "import rospy; from clover import srv; print('ROS OK')"
    rosservice list | grep clover
"""

GUIDE_TROUBLESHOOT = """\
╔══════════════════════════════════════════════════════╗
║      ДИАГНОСТИКА ПРОБЛЕМ                             ║
╚══════════════════════════════════════════════════════╝

СИМПТОМ: кнопка «ROS: симуляция» не меняется
─────────────────────────────────────────────────────
• rospy не установлен:
    sudo apt install ros-noetic-desktop
• clover пакет отсутствует:
    python3 -c "from clover import srv"
    → ошибка? Установите (шаг B в Установка)

СИМПТОМ: «ROS: нет пакета clover»
─────────────────────────────────────────────────────
• Соберите clover и source-уйте workspace:
    source ~/catkin_ws/devel/setup.bash
    python3 -c "from clover import srv; print('OK')"

СИМПТОМ: ping работает, но порт 11311 закрыт
─────────────────────────────────────────────────────
• rosmaster не запущен на дроне:
    ssh pi@192.168.11.1 'rosnode list'
• Перезапустить clover:
    ssh pi@192.168.11.1 'sudo systemctl restart clover'
    ssh pi@192.168.11.1 'sudo systemctl status clover'

СИМПТОМ: порт 11311 открыт, но сервис get_telemetry не появляется
─────────────────────────────────────────────────────
• clover-узел запустился не полностью:
    ssh pi@192.168.11.1 'rosservice list 2>&1 | grep clover'
    ssh pi@192.168.11.1 'sudo journalctl -u clover -n 50'
• Перезагрузить дрон:
    ssh pi@192.168.11.1 'sudo reboot'

СИМПТОМ: ping не проходит
─────────────────────────────────────────────────────
• Проверьте подключение к WiFi дрона:
    ip addr show
    nmcli connection show --active
• Иногда нужно:
    nmcli device wifi connect clover-XXXX password cloverwifi

СИМПТОМ: «ROS_IP не задан»
─────────────────────────────────────────────────────
• Без ROS_IP дрон не может вызывать обратно наш узел!
• Задайте вручную:
    export ROS_IP=$(ip route get 192.168.11.1 | grep -oP 'src \\K[0-9.]+')
• Или воспользуйтесь кнопкой «Автодетект ROS_IP»

ПОЛНАЯ ДИАГНОСТИКА В ОДНУ КОМАНДУ:
─────────────────────────────────────────────────────
    ping -c1 192.168.11.1           # сеть
    nc -zv 192.168.11.1 11311       # rosmaster TCP
    rosservice list 2>&1            # clover сервисы
    python3 -c "from clover import srv; print('OK')"
"""

GUIDE_CMDS = """\
╔══════════════════════════════════════════════════════╗
║      ПОЛЕЗНЫЕ КОМАНДЫ                                ║
╚══════════════════════════════════════════════════════╝

── Сеть ────────────────────────────────────────────────
    ip addr show
    ip route get 192.168.11.1
    ping -c3 192.168.11.1
    nc -zv 192.168.11.1 11311

── ROS ─────────────────────────────────────────────────
    rosnode list
    rosservice list | grep clover
    rosservice call /clover/get_telemetry "frame_id: 'map'"
    rostopic list
    rostopic echo /main_camera/image_raw -n1

── SSH на дрон ─────────────────────────────────────────
    ssh pi@192.168.11.1           # пароль: raspberry
    sudo systemctl status clover
    sudo systemctl restart clover
    sudo journalctl -u clover -n 100
    rosnode list                  # на борту дрона

── Python проверки ─────────────────────────────────────
    python3 -c "import rospy; print(rospy.__file__)"
    python3 -c "from clover import srv; print('clover OK')"
    echo $ROS_MASTER_URI
    echo $ROS_IP

── WiFi ────────────────────────────────────────────────
    nmcli device wifi list
    nmcli device wifi connect clover-XXXX password cloverwifi
    nmcli connection show --active
"""
