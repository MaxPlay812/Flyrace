# PROJECT MEMORY — Clover 4 Воздушные гонки

Знания проекта: решённые проблемы, архитектурные решения, рабочие конфигурации.
Обновляется по мере развития проекта.

---

## Рабочая конфигурация (проверено)

**Машина оператора:**
- ОС: Ubuntu 20.04 (user@user-Legion-R7000-AHP9)
- ROS: Noetic
- catkin_ws: `~/catkin_ws/devel/setup.bash`
- PYTHONPATH: `/home/user/catkin_ws/devel/lib/python3/dist-packages:/opt/ros/noetic/lib/python3/dist-packages`

**Дрон:**
- Clover 4, IP: `192.168.11.1`
- SSH: `pi@192.168.11.1`, пароль: `raspberry`
- WiFi: `clover-XXXX`, пароль: `cloverwifi`
- ROS: запущен rosmaster на 192.168.11.1:11311
- **Неймспейс clover: `/` (корневой!)** — не `/clover`, а `/get_telemetry` напрямую

**Переменные окружения (рабочие):**
```bash
ROS_MASTER_URI=http://192.168.11.1:11311
ROS_IP=192.168.11.200        # IP ноутбука в сети дрона
ROS_DISTRO=noetic
```

---

## Ключевые проблемы и решения

### 1. Неймспейс дрона `/` вместо `/clover`

**Симптом:** шаги 1-4 проходят, шаг 5 (`/clover/get_telemetry`) зависает 8 с.  
**Причина:** clover на этом конкретном дроне зарегистрировал сервисы в корневом неймспейсе. `get_telemetry` находится по пути `/get_telemetry`, а не `/clover/get_telemetry`.

**Решение (автоматическое с v1.1.0):**
- После неудачи шага 5 контроллер запускает XML-RPC discovery
- Находит реальный неймспейс через поиск сервисов с суффиксом `/get_telemetry`
- Автоматически переподключается с правильным путём
- `_svc_path(ns, name)` корректно строит путь: `('/', 'get_telemetry')` → `/get_telemetry`

**Для постоянной настройки:**
```bash
export CLOVER_NS=    # пустой = корневой неймспейс
# или
export CLOVER_NS=/
```

### 2. ROS_IP не задан → дрон не может подключиться обратно

**Симптом:** шаги 1-3 проходят, шаг 4 (rospy.init_node) зависает или телеметрия не приходит.  
**Причина:** ROS требует двустороннего TCP-соединения. Без `ROS_IP` дрон не знает куда подключаться к GUI.

**Решение:**
- `run.sh` автоопределяет `ROS_IP` через `ip route get 192.168.11.1`
- Контроллер дополнительно использует `socket.connect()` trick как fallback

### 3. SSH без ключей / без sshpass

**Симптом:** SSH-авто-настройка не работает (таймаут).  
**Причина:** `BatchMode=no` без sshpass не может ввести пароль в subprocess.

**Решение:**
```bash
sudo apt install sshpass
```
`DroneAutoSetup` автоматически использует `sshpass -p raspberry` если доступен.

### 4. AttributeError: reconnect_requested

**Симптом:** диалог подключения падал при каждом открытии.  
**Причина:** `main_window.py` пытался подключиться к несуществующему сигналу `reconnect_requested` у `ConnectionDialog`.  
**Решение:** строка удалена. ROS-кнопка обновляется через 100-мс таймер телеметрии.

### 5. NameError: controller in _build_ui

**Симптом:** вкладка «Авто-настройка» не отображалась.  
**Причина:** в методе `_build_ui` использовалась переменная `controller` вместо `self._controller`.  
**Решение:** исправлено на `self._controller`.

---

## Архитектурные решения

### Неблокирующий запуск ROS
- Симуляция стартует немедленно при запуске
- Подключение к ROS идёт в фоне (`_connect_loop`), повторяя попытки каждые 10 с
- Qt-поток никогда не блокируется

### Автообнаружение неймспейса
```python
def _svc_path(ns: str, name: str) -> str:
    ns = ns.rstrip("/")
    return f"{ns}/{name}" if ns else f"/{name}"
```
Если шаг 5 провалился → XML-RPC query → поиск `*get_telemetry` → retry с найденным ns.

### SSH-безопасность
- Хост валидируется regex `^[a-zA-Z0-9._-]+$` (no shell injection)
- subprocess вызывается в list-форме (shell=False)
- Перед перезапуском clover: проверка `armed=True` → блок если вооружён
- sshpass пароль передаётся как аргумент, не через shell

### Discovery (XML-RPC)
```python
code, msg, state = xmlrpc.client.ServerProxy(uri).getSystemState("/disco")
publishers, subscribers, services = state
```
Работает без rospy, через стандартный Python `xmlrpc.client`.

---

## Структура файлов (v1.1.0)

```
src/drone/
  controller.py    — ROS/sim, 5-шаговое подключение, авто-ns
  ssh_setup.py     — DroneAutoSetup (6 шагов, все случаи ошибок)
  discovery.py     — XML-RPC discovery, format_ros_report

src/gui/
  connection_dialog.py   — 8 вкладок, SSH-ремонт
  connection_guides.py   — тексты справочников (отдельный файл)
  autosetup_widget.py    — вкладка авто-настройки + discovery
  debug_widget.py        — живой лог, polling 200 мс

src/utils/
  debug_log.py     — thread-safe синглтон-логгер, уровень SUCCESS
```

---

## Обработанные случаи ошибок подключения

| Код случая | Обнаружение | Действие |
|-----------|------------|---------|
| `no_ssh` | `echo SSH_OK` не вернул ответ | Советы по WiFi/sshpass/паролю |
| `crash_loop` | NRestarts > 8 | Показать журнал, не перезапускать |
| `not_started` | not active за 13 с | Полный журнал journalctl |
| `no_services` | rosservice list пуст | Ждать 15 с, проверить ROS_MASTER_URI |
| `wrong_ns` | get_telemetry не в /clover | Авто-подключение + совет CLOVER_NS |
| ping fail | returncode != 0 | Проверить WiFi |
| TCP закрыт | socket timeout | rosmaster не запущен |
| xmlrpc fail | xmlrpc exception | rosmaster сломан |
| rospy init fail | exception | Проверить ROS_IP |
| service timeout | ROSException | Авто-discovery + retry |

---

## Версии

| Версия | Дата | Изменения |
|--------|------|-----------|
| 1.0.0 | 2026-05 | Начальная версия: GUI, камера, карта, ArUco, ROS |
| 1.1.0 | 2026-06 | Авто-настройка SSH, discovery, авто-неймспейс, безопасный restart |
