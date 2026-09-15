"""Автосохранение пользовательских настроек (UI-панель + размер окна) между
запусками - см. car_racer/neat_runner/main.py: загружаются один раз при
старте и применяются как стартовые значения, сохраняются автоматически при
каждом изменении (без отдельной кнопки "Сохранить"). Отдельно от
config-feedforward.txt (топология/мутации NEAT - трогается руками) и от
чекпоинтов обучения (car_racer/checkpoints/ - состояние популяции)."""
import json
import os

SETTINGS_PATH = os.path.join("car_racer", "config", "user_settings.json")


def load_settings() -> dict:
    """Возвращает сохранённые настройки или {} если файла нет / он повреждён
    - в этом случае используются встроенные дефолты, как будто файла никогда
    не было (испорченный вручную json не должен ронять запуск игры)."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict):
    """Атомарная запись (через временный файл + os.replace) - чтобы падение
    ровно в момент записи (или два процесса разом) не оставило битый
    наполовину-записанный json, который потом откатит все настройки на
    дефолты при следующем запуске."""
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    tmp_path = SETTINGS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, SETTINGS_PATH)
