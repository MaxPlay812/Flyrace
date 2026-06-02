# Сборка и запуск

## Требования

| Компонент | Версия |
|-----------|--------|
| Python | 3.10+ |
| PyQt5 | 5.15+ |
| opencv-contrib-python | 4.8+ |
| numpy | 1.24+ |
| ROS Noetic *(опционально)* | для реального дрона |

## Установка зависимостей

```bash
pip install -r requirements.txt
```

> **Примечание**: `opencv-contrib-python` необходим для модуля ArUco.  
> Не устанавливайте одновременно `opencv-python` и `opencv-contrib-python`.

## Запуск

### Режим симуляции (без дрона)

```bash
python src/main.py
```

Приложение запустится в режиме симуляции: дрон автоматически летит по маршруту «восьмёрка», камера показывает тестовый паттерн.

### Режим реального дрона (Clover 4 + ROS)

1. Подключитесь к WiFi дрона (SSID: `clover-XXXX`, пароль: `cloverwifi`).
2. Убедитесь, что `ROS_MASTER_URI` указывает на дрон:
   ```bash
   export ROS_MASTER_URI=http://192.168.11.1:11311
   export ROS_IP=<ваш_IP>
   ```
3. Запустите приложение:
   ```bash
   python src/main.py
   ```

Приложение автоматически определит наличие ROS и переключится в режим реального управления.

## Структура проекта

```
Flyrace/
├── src/
│   ├── main.py              # Точка входа
│   ├── config.py            # Константы (поле, скорость, ROS)
│   ├── models/
│   │   └── marker.py        # Модель ArUco маркера
│   ├── drone/
│   │   └── controller.py    # Интерфейс дрона (ROS / симуляция)
│   ├── vision/
│   │   ├── aruco_detector.py # Детектор маркеров ArUco
│   │   └── camera_thread.py  # Захват видео (ROS / OpenCV)
│   └── gui/
│       ├── main_window.py    # Главное окно
│       ├── control_panel.py  # Панель управления полётом
│       ├── camera_widget.py  # Виджет камеры с наложением
│       ├── map_widget.py     # Карта поля
│       ├── status_widget.py  # Статус системы
│       └── marker_dialog.py  # Менеджер ArUco маркеров
├── docs/
│   ├── BUILD.md             # Этот файл
│   └── DEPLOY.md            # Деплой на Raspberry Pi
├── markers.json             # Сохранённые маркеры (создаётся автоматически)
└── requirements.txt
```

## Конфигурация поля

Параметры полигона задаются в `src/config.py`:

```python
FIELD_W = 4000   # ширина поля, мм
FIELD_H = 3000   # высота поля, мм
POLE_1  = (1000, 1500)   # позиция столба 1
POLE_2  = (3000, 1500)   # позиция столба 2
TRACK_RADIUS = 500       # радиус трека, мм
```

## CUDA-ускорение (Windows / Linux)

Стандартный `opencv-contrib-python` из pip не включает CUDA.  
Для GPU-ускорения optical flow и обработки кадров нужна сборка OpenCV с флагом `WITH_CUDA=ON`.

### Проверка CUDA

```bash
python -c "import cv2; print(cv2.cuda.getCudaEnabledDeviceCount())"
# 0 — CUDA не найдена, >0 — GPU готов
```

### Сборка OpenCV с CUDA (Ubuntu 20.04+)

```bash
sudo apt install -y libopencv-dev cmake build-essential
git clone https://github.com/opencv/opencv.git
git clone https://github.com/opencv/opencv_contrib.git

mkdir opencv/build && cd opencv/build
cmake .. \
  -DOPENCV_EXTRA_MODULES_PATH=../../opencv_contrib/modules \
  -DWITH_CUDA=ON \
  -DCUDA_ARCH_BIN="8.6"   \
  -DBUILD_opencv_python3=ON \
  -DPYTHON3_EXECUTABLE=$(which python3) \
  -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
sudo make install
```

> Замените `8.6` на вычислительную способность вашей GPU  
> (RTX 30xx = 8.6, RTX 20xx = 7.5, GTX 10xx = 6.1).

### Готовые сборки (Windows)

Бинарные пакеты OpenCV с CUDA для Windows:  
https://github.com/cudawarped/opencv-python-cuda-wheels/releases

```bash
pip uninstall opencv-contrib-python
pip install opencv-contrib-python-cuda-*.whl
```

Приложение автоматически обнаружит CUDA и покажет **[CUDA]** рядом с кнопкой Optical flow.

## Тестирование

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from config import *
from models.marker import ArucoMarker, ZoneType
from drone.controller import CloverController
from vision.aruco_detector import ArucoDetector
from utils.cuda import cuda_available, cuda_info
print('OK, CUDA:', cuda_available())
print(cuda_info())
"
```
