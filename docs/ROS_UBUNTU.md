# Подключение внешнего Ubuntu-ПК к Clover 4

## Схема соединения

```
Ноутбук (Ubuntu) ←── WiFi ──→ Clover 4 (RPi)
  python src/main.py              rosmaster
  rospy client                    clover ROS nodes
```

## 1. Установка ROS Noetic

```bash
sudo sh -c 'echo "deb http://packages.ros.org/ros/ubuntu focal main" \
  > /etc/apt/sources.list.d/ros-latest.list'
curl -s https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc | sudo apt-key add -
sudo apt update
sudo apt install ros-noetic-desktop
```

Добавьте в `~/.bashrc`:
```bash
source /opt/ros/noetic/setup.bash
```

## 2. Установка пакета clover (типы сервисов)

Без этого пакета приложение работает в **режиме симуляции** — управление дроном недоступно.

### Вариант А: из исходников (рекомендуется)

```bash
mkdir -p ~/catkin_ws/src
cd ~/catkin_ws/src
git clone --depth 1 https://github.com/clover-robotics/clover.git

cd ~/catkin_ws
catkin_make

# Добавить в ~/.bashrc
echo "source ~/catkin_ws/devel/setup.bash" >> ~/.bashrc
source ~/.bashrc
```

### Вариант Б: только сервисные типы (минимальный)

Если нет нужды собирать весь Clover, достаточно модулей сообщений:

```bash
cd ~/catkin_ws/src
git clone --depth 1 --no-single-branch \
  --filter=blob:none --sparse \
  https://github.com/clover-robotics/clover.git
cd clover
git sparse-checkout init --cone
git sparse-checkout set clover
cd ~/catkin_ws && catkin_make --pkg clover
source ~/catkin_ws/devel/setup.bash
```

## 3. Настройка ROS сети

```bash
# Подключитесь к WiFi дрона
# SSID: clover-XXXX, пароль: cloverwifi

# Узнайте свой IP на сети дрона
ip addr show   # ищите адрес 192.168.11.xxx

# Задайте переменные (замените xxx на ваш IP)
export ROS_MASTER_URI=http://192.168.11.1:11311
export ROS_IP=192.168.11.xxx

# Постоянно: добавьте в ~/.bashrc
echo 'export ROS_MASTER_URI=http://192.168.11.1:11311' >> ~/.bashrc
echo 'export ROS_IP=$(hostname -I | awk "{print \$1}")' >> ~/.bashrc
```

## 4. Проверка соединения

```bash
# Пинг дрона
ping 192.168.11.1

# Список ROS узлов (должен ответить быстро)
rosnode list

# Проверка сервиса телеметрии
rosservice call /clover/get_telemetry "frame_id: 'map'"

# Проверка что clover установлен
python3 -c "from clover import srv; print('clover OK')"
```

## 5. Запуск приложения

```bash
cd ~/Flyrace
./run.sh
```

Или с явным указанием переменных:
```bash
ROS_MASTER_URI=http://192.168.11.1:11311 \
ROS_IP=192.168.11.100 \
python3 src/main.py
```

## Диагностика в приложении

Нажмите кнопку **«ROS: ...»** в панели инструментов — откроется диалог с:
- Проверкой всех зависимостей (rospy, clover, ping, rosmaster)
- Полем для ввода `ROS_MASTER_URI` и `ROS_IP`
- Кнопкой переподключения без перезапуска

## Частые проблемы

| Симптом | Причина | Решение |
|---------|---------|---------|
| Приложение в симуляции, нет ROS | rospy не установлен | `sudo apt install ros-noetic-desktop` |
| «нет пакета clover» в кнопке ROS | clover не собран | Вариант А или Б выше |
| clover есть, но нет ответа | Не задан ROS_MASTER_URI или WiFi | Шаг 3 выше |
| ping проходит, rosmaster не отвечает | ROS_MASTER_URI неверный | Проверьте IP 192.168.11.1 |
| Ответ rosmaster есть, сервис нет | Clover не запущен на дроне | `ssh pi@192.168.11.1 "sudo systemctl restart clover"` |
