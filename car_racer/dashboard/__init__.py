"""Веб-панель мониторинга/управления обучением NEAT.

Разделяет тренировочный цикл (главный поток, pygame) и браузерную панель
(фоновый HTTP-сервер в отдельном потоке) через два канала:

- ``_current`` / ``_history`` — снимок "сейчас" и история по поколениям.
  Пишутся ГЛАВНЫМ потоком (из car_racer/neat_runner/main.py), читаются
  серверным потоком по HTTP. Всё под ``threading.Lock``.
- ``_commands`` — ``queue.Queue`` команд, которые браузер шлёт в игру
  (POST /api/command). Пишутся серверным потоком, читаются главным потоком
  через ``next_command()``.

Никаких внешних зависимостей — используется только stdlib
(http.server + threading + queue), чтобы не тянуть websocket-библиотеки
в проект, который сознательно избавился от тяжёлых зависимостей (shapely).
"""
import glob
import os
import queue
import threading

DEFAULT_PORT = 8080

_INPUT_LABELS = ["angle", "speed", "compass", "-150", "-90", "-45", "0", "45", "90", "150"]
_OUTPUT_LABELS = ["throttle", "turn"]

_lock = threading.Lock()
_current = {}      # dict: живые поля текущего тика (заменяется целиком)
_history = []      # list[dict]: по одной записи на завершённое поколение
_commands = queue.Queue()


def set_current(snapshot: dict):
    """Записать живой снимок тренировки (заменяет предыдущий). Вызывается из
    главного потока, троттлится в main.py (~раз в секунду)."""
    global _current
    with _lock:
        _current = dict(snapshot)


def record_generation(record: dict):
    """Добавить запись о завершённом поколении в историю. Вызывается из
    главного потока в конце eval_genomes."""
    with _lock:
        _history.append(dict(record))


def reset_history():
    """Очистить историю (например при Restart Training)."""
    global _history
    with _lock:
        _history = []


def snapshot():
    """Полный снимок для /api/stats: копии current и history (чтобы серверный
    поток не видел частично записанные структуры)."""
    with _lock:
        return {"current": dict(_current), "history": list(_history)}


def post_command(command: dict):
    """Положить команду из браузера в очередь для главного потока."""
    _commands.put(command)


def next_command():
    """Забрать одну команду (или None, если очередь пуста). Вызывается главным
    потоком каждый тик."""
    try:
        return _commands.get_nowait()
    except queue.Empty:
        return None


def start_server(port=None):
    """Запустить HTTP-сервер панели в фоновом daemon-потоке. Не блокирует и не
    роняет тренировку, если порт занят. Порт берётся из аргумента, затем из
    переменной окружения RACE_DASHBOARD_PORT, затем DEFAULT_PORT."""
    from car_racer.dashboard import server
    if port is None:
        port = int(os.environ.get("RACE_DASHBOARD_PORT", DEFAULT_PORT))
    server.start(port)


def discover_tracks(points_dir="car_racer/tracks/"):
    """Список файлов трасс (имена, без пути), отсортированный по имени - для
    дропдауна выбора трассы в браузерной панели."""
    files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(points_dir, "points*.txt")))
    return files or ["points.txt"]


def serialize_genome(genome, config):
    """Сериализует геном NEAT в JSON-совместимую структуру для отрисовки сети
    в браузере: список узлов (с нормализованными x/y в [0,1]) и список
    соединений. Раскладка та же слоистая, что у Screen.draw_network: входы
    слева, выходы справа, скрытые - по топологическому уровню."""
    input_keys = list(config.genome_config.input_keys)
    output_keys = list(config.genome_config.output_keys)
    hidden_keys = [k for k in genome.nodes if k not in input_keys and k not in output_keys]

    # Топологический уровень скрытых узлов (по включённым связям скрытый->скрытый)
    levels = {k: 0 for k in hidden_keys}
    for (a, b), conn in genome.connections.items():
        if conn.enabled and a in levels and b in levels:
            levels[b] = max(levels[b], levels[a] + 1)

    by_level = {}
    for k in hidden_keys:
        by_level.setdefault(levels[k], []).append(k)

    nodes = []
    for i, k in enumerate(input_keys):
        nodes.append({"key": k, "type": "input",
                      "x": 0.0, "y": (i + 1) / (len(input_keys) + 1),
                      "label": _INPUT_LABELS[i] if i < len(_INPUT_LABELS) else str(k)})

    max_level = max(levels.values()) if levels else 0
    for lvl in sorted(by_level):
        keys = sorted(by_level[lvl])
        for i, k in enumerate(keys):
            nodes.append({"key": k, "type": "hidden",
                          "x": (lvl + 1) / (max_level + 2), "y": (i + 1) / (len(keys) + 1),
                          "label": str(k)})

    for i, k in enumerate(output_keys):
        nodes.append({"key": k, "type": "output",
                      "x": 1.0, "y": (i + 1) / (len(output_keys) + 1),
                      "label": _OUTPUT_LABELS[i] if i < len(_OUTPUT_LABELS) else str(k)})

    connections = [
        {"from": a, "to": b, "weight": round(conn.weight, 3), "enabled": bool(conn.enabled)}
        for (a, b), conn in genome.connections.items() if conn.enabled
    ]

    return {"nodes": nodes, "connections": connections}
