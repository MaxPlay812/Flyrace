# Деплой на Raspberry Pi (Clover 4)

Этот файл описывает настройку дрона Clover 4 для работы с приложением.

## На борту дрона (RPi)

### 1. Прошивка и ROS

Clover 4 поставляется с предустановленным образом [Clover](https://clover.coex.tech/).  
ROS Noetic и пакет `clover` уже включены в образ.

Проверьте, что rosmaster запущен:
```bash
ssh pi@192.168.11.1
rosnode list
```

### 2. Включить optical flow

В файле `/home/pi/catkin_ws/src/clover/clover/launch/clover.launch`:
```xml
<arg name="optical_flow" default="true"/>
```

Перезапустите сервис:
```bash
sudo systemctl restart clover
```

### 3. Настройка камеры

Основная камера должна публиковать топик `/main_camera/image_raw`.  
Проверьте:
```bash
rostopic list | grep camera
```

### 4. ArUco навигация (опционально)

Для позиционирования по маркерам добавьте в launch-файл:
```xml
<arg name="aruco" default="true"/>
```

## На наземной станции (ноутбук)

### 1. Подключение к WiFi дрона

```bash
# macOS
networksetup -setairportnetwork en0 clover-XXXX cloverwifi

# Linux
nmcli device wifi connect clover-XXXX password cloverwifi
```

### 2. Переменные окружения ROS

```bash
export ROS_MASTER_URI=http://192.168.11.1:11311
export ROS_IP=$(ipconfig getifaddr en0)   # macOS
# или
export ROS_IP=$(hostname -I | awk '{print $1}')  # Linux
```

Для постоянной настройки добавьте в `~/.bashrc` или `~/.zshrc`.

### 3. Установка зависимостей Python

```bash
pip install -r requirements.txt
```

Для полной ROS-интеграции также нужен `rospy` (входит в `ros-noetic-desktop`).

### 4. Запуск

```bash
cd /path/to/Flyrace
python src/main.py
```

## Проверка связи

```bash
# Пинг дрона
ping 192.168.11.1

# Список ROS топиков
rostopic list

# Телеметрия дрона
rostopic echo /clover/get_telemetry

# Видео с камеры
rosrun rqt_image_view rqt_image_view /main_camera/image_raw
```

## Маркеры ArUco

Маркеры из словаря `4X4_50` (ID 0–49) распечатайте на бумаге нужного размера.  
Размер маркера по умолчанию: **150 мм × 150 мм**.

Рекомендуемое размещение:
| ID | Позиция | Зона |
|----|---------|------|
| 0 | Старт/финиш (2000, 200) | Старт |
| 1 | Зона разгона (500, 1500) | Ускорение |
| 2 | Зона торможения (1500, 1500) | Замедление |
| 3 | Поворот (3500, 1500) | Ускорение |

Маркеры можно распечатать прямо из приложения: вкладка **ArUco маркеры** → выбрать → **Показать маркер**.

## Параметры Clover 4

| Параметр | Значение |
|----------|---------|
| IP дрона | 192.168.11.1 |
| SSH логин | pi / raspberry |
| WiFi | clover-XXXX / cloverwifi |
| ROS namespace | /clover |
| Камера | /main_camera/image_raw |
| Optical flow | /optical_flow/twist |
