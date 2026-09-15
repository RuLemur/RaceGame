import os
import re
import sys
import time

import neat
import pygame
import pymunk

from car_racer.cars import physic_car
import car_racer.dashboard as dashboard
from car_racer.constants import MAX_TIMEOUT, TICK_RATE, PX_PER_METER
from car_racer.file_manager.file_worker import save_checkpoint, CHECKPOINT_DIR, load_checkpoint, get_neat_config
from car_racer.file_manager.settings_store import load_settings, save_settings
from car_racer.neat_runner.game_instatnse import GameEnvironment
from car_racer.screen.camera import MIN_ZOOM, MAX_ZOOM
from car_racer.screen.screen import Screen, BEST_PATH_COLOR
from car_racer.trajectory import optimal_line

GROUP_SIZE = 30
MAX_VISIBLE = 10
FPS = 60

# "Turbo + Camera Follow" ("фоновый расчёт"): когда включены ОБА -
# unlimited_fps (турбо, обычно полностью пропускает отрисовку) И
# camera_follow (камера следует за живым лидером группы, group_best_env) -
# вместо полностью пропущенного
# кадра изредка (не чаще BACKGROUND_RENDER_FPS раз/сек РЕАЛЬНОГО времени)
# рисуется дешёвый кадр вида камеры на лидере, чтобы экран не был чёрным.
BACKGROUND_RENDER_FPS = 15

# Интервал обновления "живого" снимка для браузерной панели (см.
# car_racer/dashboard) - обновляем не каждый тик, а раз в секунду реального
# времени, чтобы не тратить время на сериализацию в турбо-режиме.
DASHBOARD_SYNC_INTERVAL = 1.0

generation = 1
max_fitness: int = 0
max_cl = 0
max_laps = 0
best_lap_time = MAX_TIMEOUT
max_distance = 0

# --- Настройки, управляемые из БРАУЗЕРНОЙ панели (см. car_racer/dashboard) --
# Раньше жили в pygame-панели (ui_panel.py); теперь вся панель управления
# вынесена в браузер, а в окне игры оставлены только тогглы сенсоров/генома.
# Эти модульные глобали читаются/пишутся eval_genomes'ом и
# _handle_dashboard_commands'ом, персистятся в user_settings.json.
paused = False
unlimited_fps = False
camera_follow = False
zoom = 1.0            # актуальный зум; пересчитывается под трассу при загрузке
show_track_lines = True

# Флаг перезапуска текущей группы, поднятый из браузера.
_pending_restart_group = False

# Выбранный на данный момент файл трассы (переключается из браузерной панели).
current_track_file = "points.txt"

# Окно и панель создаются один раз и переиспользуются между поколениями:
# быстрее (не пересоздаём pygame-окно на каждое поколение) и не сбрасывает
# состояние панели (пауза, Unlimited FPS) между поколениями.
screen = None

# Ручное панорамирование камеры (drag ЛКМ по игровому полю, см. обработку
# событий в eval_genomes ниже). Camera Follow (автослежка за лидером) - отдельно,
# включается из браузерной панели (см. camera_follow).
# _camera_drag_active - True всё время, пока зажата ЛКМ и драг был начат на
# игровом поле.
# _camera_manual_pan - True после хотя бы одного драга (не сбрасывается по
# отпусканию ЛКМ) - подавляет автоматическое center_on_field(), иначе ручной
# пан отменялся бы на следующем же отрисованном кадре. Сбрасывается при смене
# трассы.
_camera_drag_active = False
_camera_drag_last_pos = None
_camera_manual_pan = False

# Сохранённые настройки предыдущего запуска (см.
# car_racer/file_manager/settings_store.py) - __main__ заполняет их ДО первого
# вызова eval_genomes, который использует их как стартовые значения при лениво
# создании screen/panel (см. initial_real_size у Screen() и
# sync_initial_values у panel ниже). initial_settings - словарь "как есть" из
# файла (может отсутствовать/быть пустым при первом запуске), initial_real_size
# - отдельно вынесенный (ширина, высота) реального окна или None.
initial_settings = {}
initial_real_size = None

# Последний ЗАПИСАННЫЙ на диск снимок настроек - см. _maybe_save_settings.
# None до первого вызова - гарантирует, что первая проверка либо совпадёт с
# initial_settings (ничего не пишем зря сразу после старта), либо запишет
# файл, если тот отсутствовал вовсе.
_last_saved_settings = None
_last_dashboard_sync = 0.0


class RestartTrainingRequested(Exception):
    """Поднимается из eval_genomes, когда пользователь подтвердил кнопку
    "Restart Training" в UI-панели. Ловится в __main__, где заново создаётся
    neat.Population и обучение запускается с нуля. Окно/панель при этом не
    трогаем - пересоздаётся только состояние NEAT."""
    pass


def _format_best_lap(value):
    return f"{value:.2f}" if value < MAX_TIMEOUT else "-"


def _settings_snapshot(screen, panel, cfg):
    """Текущие настройки в виде, готовом для settings_store.save_settings -
    используется и для сравнения "изменилось ли что-то с прошлого раза", и
    как есть для записи в файл. Округление float-полей - не косметика: без
    него на каждом тике снимок отличался бы от предыдущего на ничтожную
    величину (float-шум) и автосохранение писало бы файл на диск каждый
    кадр вместо реальных изменений."""
    win_w, win_h = screen.real_window.get_size()
    return {
        "track_file": screen.track_file,
        "max_visible": MAX_VISIBLE,
        "group_size": GROUP_SIZE,
        "pop_size": cfg.pop_size,
        "render_fps": FPS,
        "grip_g": round(physic_car.GRIP_ACCEL / physic_car.GRIP_ACCEL_PER_G, 3),
        "mass_kg": round(physic_car.CAR_MASS * physic_car.REFERENCE_MASS_KG, 3),
        "power_hp": round(physic_car.ENGINE_POWER_HP, 3),
        "zoom": round(zoom, 4),
        "camera_follow": camera_follow,
        "show_genome": panel.show_genome,
        "unlimited_fps": unlimited_fps,
        "show_sensors": panel.show_sensors,
        "show_track_lines": show_track_lines,
        "window_width": win_w,
        "window_height": win_h,
    }


def _maybe_save_settings(screen, panel, cfg):
    """Автосохранение настроек - НЕ по кнопке: сравнивает текущий снимок с
    последним записанным на диск и пишет файл только если что-то реально
    изменилось (переключили трассу/камеру/поля, изменили размер окна и т.п.)
    - вызывается каждый тик игрового цикла, но реальная запись на диск
    происходит только при изменении, а не каждый кадр."""
    global _last_saved_settings
    snapshot = _settings_snapshot(screen, panel, cfg)
    if snapshot != _last_saved_settings:
        save_settings(snapshot)
        _last_saved_settings = snapshot


def _handle_dashboard_commands(panel, cfg):
    """Команды из браузерной панели (см. car_racer/dashboard). Применяет их
    напрямую к модульным глобалиам - вся настройка теперь в браузере, а
    pygame-панель оставлена только для тогглов сенсоров/генома. Числовые
    значения зажимаются в те же границы, что были у полей pygame-панели.
    restart_training поднимается сразу (в браузере есть свой confirm())."""
    global paused, unlimited_fps, camera_follow, zoom, show_track_lines
    global MAX_VISIBLE, GROUP_SIZE, FPS, current_track_file
    global _camera_manual_pan, _camera_drag_active, _camera_drag_last_pos
    global _pending_restart_group

    def _clamp_int(value, lo, hi):
        try:
            return max(lo, min(hi, int(float(value))))
        except (TypeError, ValueError):
            return None

    def _clamp_float(value, lo, hi, decimals=1):
        try:
            return round(max(lo, min(hi, float(value))), decimals)
        except (TypeError, ValueError):
            return None

    while True:
        cmd = dashboard.next_command()
        if cmd is None:
            return
        action = cmd.get("action")
        value = cmd.get("value")

        if action == "toggle_pause":
            paused = not paused
        elif action == "set_paused":
            paused = bool(value)
        elif action == "toggle_unlimited_fps":
            unlimited_fps = not unlimited_fps
        elif action == "set_unlimited_fps":
            unlimited_fps = bool(value)
        elif action == "set_camera_follow":
            camera_follow = bool(value)
        elif action == "toggle_camera_follow":
            camera_follow = not camera_follow
        elif action == "set_zoom":
            v = _clamp_float(value, MIN_ZOOM, MAX_ZOOM, 4)
            if v is not None:
                zoom = v
        elif action == "set_show_track_lines":
            show_track_lines = bool(value)
        elif action == "toggle_track_lines":
            show_track_lines = not show_track_lines
        elif action == "set_show_sensors":
            panel.show_sensors = bool(value)
            panel.show_sensors_button.active = not panel.show_sensors
        elif action == "set_show_genome":
            panel.show_genome = bool(value)
            panel.show_genome_button.active = not panel.show_genome
        elif action == "restart_group":
            _pending_restart_group = True
        elif action == "restart_training":
            raise RestartTrainingRequested()
        elif action == "set_track":
            if isinstance(value, str) and value and value != current_track_file:
                if os.path.exists(os.path.join("car_racer", "tracks", value)):
                    current_track_file = value
                    screen.load_track(value)
                    _camera_manual_pan = False
                    _camera_drag_active = False
                    _camera_drag_last_pos = None
                    zoom = screen.compute_fit_zoom()
        elif action == "set_fps":
            v = _clamp_int(value, 1, 240)
            if v is not None:
                FPS = v
        elif action == "set_group_size":
            v = _clamp_int(value, 1, cfg.pop_size)
            if v is not None:
                GROUP_SIZE = v
                if MAX_VISIBLE > v:
                    MAX_VISIBLE = v
        elif action == "set_max_visible":
            v = _clamp_int(value, 1, GROUP_SIZE)
            if v is not None:
                MAX_VISIBLE = v
        elif action == "set_pop_size":
            v = _clamp_int(value, 1, 100000)
            if v is not None:
                cfg.pop_size = v
                if GROUP_SIZE > v:
                    GROUP_SIZE = v
                if MAX_VISIBLE > GROUP_SIZE:
                    MAX_VISIBLE = GROUP_SIZE
        elif action == "set_grip":
            v = _clamp_float(value, 0.5, 3.0)
            if v is not None:
                physic_car.GRIP_ACCEL = v * physic_car.GRIP_ACCEL_PER_G
        elif action == "set_mass":
            v = _clamp_float(value, 50, 300, 0)
            if v is not None:
                physic_car.CAR_MASS = v / physic_car.REFERENCE_MASS_KG
        elif action == "set_power":
            v = _clamp_float(value, 1, 1000, 0)
            if v is not None:
                physic_car.ENGINE_POWER_HP = v
        elif action == "recompute_ideal_line":
            vehicle_params = optimal_line.vehicle_params_from_physic_car()
            ideal_result = optimal_line.compute_optimal_line(
                screen.track_outer, screen.track_inner, vehicle_params=vehicle_params)
            optimal_line.save_ideal_line(screen.track_file, ideal_result)
            screen._load_ideal_line()


def eval_genomes(genomes, cfg):
    global generation, max_fitness, max_cl, max_laps, best_lap_time, max_distance
    global current_track_file, screen, MAX_VISIBLE, GROUP_SIZE, FPS, p
    global paused, unlimited_fps, camera_follow, zoom, show_track_lines, _pending_restart_group
    global _camera_drag_active, _camera_drag_last_pos, _camera_manual_pan
    global _last_dashboard_sync

    if screen is None:
        screen = Screen(track_file=current_track_file, initial_real_size=initial_real_size)
        # Вся настройка теперь в браузере; pygame-панель держит только тогглы
        # сенсоров/генома - проставляем их из сохранённых настроек, а зум
        # считаем под ИМЕННО эту трассу (см. compute_fit_zoom), не из прошлой
        # сессии (трассы теперь очень разного реального размера).
        screen.panel.set_initial(
            show_sensors=initial_settings.get("show_sensors"),
            show_genome=initial_settings.get("show_genome"))
        zoom = screen.compute_fit_zoom()
    panel = screen.panel

    clock = pygame.time.Clock()

    # Разбейте геномы на группы
    num_groups = (len(genomes) + GROUP_SIZE - 1) // GROUP_SIZE  # Округление вверх

    # Для хранения всех сред для последующего отображения
    all_environments = []

    best_genome = None  # Лучший геном за ВСЁ поколение (переживает смену
                        # групп) - используется ТОЛЬКО для screen.draw_network().
                        # Для камеры/пути/подписи НЕ годится: его машина может
                        # принадлежать уже завершённой группе, её тело больше не
                        # шагается и она застывает ("машина-призрак"). Для
                        # камеры/пути/подписи ниже заведён group_best_env -
                        # лидер ЖИВОЙ текущей группы.
    gen_fitness = 0
    quit_requested = False
    gen_start_time = time.time()
    last_bg_render_time = 0.0  # см. BACKGROUND_RENDER_FPS выше

    for group_index in range(num_groups):
        if quit_requested:
            break

        # Определите текущую группу
        start_index = group_index * GROUP_SIZE
        end_index = min(start_index + GROUP_SIZE, len(genomes))
        current_group = genomes[start_index:end_index]

        # Группа может быть перезапущена кнопкой "Restart Group" - тогда она
        # прогоняется заново с нуля (новые GameEnvironment на тех же геномах),
        # а прогресс предыдущей попытки просто отбрасывается.
        redo_group = True
        while redo_group and not quit_requested:
            redo_group = False
            group_start_time = time.time()

            # Общий pymunk.Space на всю группу: один вызов space.step() на тик
            # вместо отдельного Space + step() на каждую машину - дешевле по
            # накладным расходам и позволяет честно шагать физику всей группы
            # одним вызовом. Машины не сталкиваются друг с другом, так что
            # делить один Space между ними безопасно.
            group_space = pymunk.Space()
            group_space.gravity = (0, 0)

            # Создайте среду для текущей группы
            environments = []
            for car_index, (genome_id, genome) in enumerate(current_group):
                environments.append(GameEnvironment(genome, cfg, genome_id, screen,
                                                     car_index <= MAX_VISIBLE, space=group_space))

            # Лидер ТЕКУЩЕЙ группы среди ЕЩЁ АКТИВНЫХ машин - за ним следит
            # камера (Camera Follow) и по нему рисуются путь/подпись. Именно
            # "живая" машина, а НЕ best_env (лучший геном за всё поколение):
            # тот может принадлежать уже завершённой группе, его тело больше не
            # шагается и он "зависает" на месте - камера тогда смотрит на
            # застывшую машину-призрак. Пересчитывается каждый тик ниже.
            group_best_env = None

            # Основной цикл симуляции для текущей группы
            running = True

            while running and any(env.active for env in environments):
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                        quit_requested = True
                    elif event.type == pygame.VIDEORESIZE:
                        screen.handle_resize(event)
                    # Клики мыши приходят в пикселях реального (возможно,
                    # ресайзнутого) окна - панель же расположена в логических
                    # координатах фиксированного холста, поэтому координаты
                    # нужно пересчитать перед тем, как отдавать событие панели.
                    if hasattr(event, "pos"):
                        logical_pos = screen.window_to_logical(event.pos)
                        event = pygame.event.Event(event.type, dict(event.dict, pos=logical_pos))
                    elif event.type == pygame.MOUSEWHEEL:
                        # MOUSEWHEEL не несёт event.pos (см. комментарий в
                        # ui_panel.py) - панель определяет, над ней ли курсор,
                        # через pygame.mouse.get_pos(), который возвращает
                        # пиксели РЕАЛЬНОГО окна, а панель расположена в
                        # логических координатах холста. Без этого пересчёта
                        # (совпадает с веткой выше для событий с .pos)
                        # скролл панели ломался бы на любом окне, отличном по
                        # размеру от логического холста (то есть почти всегда
                        # - см. Screen.initial_scale).
                        logical_pos = screen.window_to_logical(pygame.mouse.get_pos())
                        event = pygame.event.Event(event.type, dict(event.dict, pos=logical_pos))
                    consumed = panel.handle_event(event)

                    # Ручное панорамирование камеры - drag ЛКМ по игровому
                    # полю (event.pos уже в логических координатах холста).
                    # Кнопки-тогглы сами съедают клик (consumed), поэтому над
                    # ними драг не стартует. См. комментарий у
                    # _camera_drag_active в начале модуля про то, как это
                    # сочетается с Camera Follow.
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not consumed:
                        _camera_drag_active = True
                        _camera_drag_last_pos = event.pos
                    elif event.type == pygame.MOUSEMOTION and _camera_drag_active:
                        dx = event.pos[0] - _camera_drag_last_pos[0]
                        dy = event.pos[1] - _camera_drag_last_pos[1]
                        _camera_drag_last_pos = event.pos
                        if dx or dy:
                            cam = screen.camera
                            # Мировая точка под курсором должна остаться под
                            # курсором - центр камеры сдвигается в СЕТЕВОМ
                            # направлении относительно движения мыши, с
                            # поправкой на zoom (world_to_screen умножает на
                            # zoom, здесь - обратное преобразование смещения).
                            cam.center = (cam.center[0] - dx / cam.zoom, cam.center[1] - dy / cam.zoom)
                            _camera_manual_pan = True
                    elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                        _camera_drag_active = False
                        _camera_drag_last_pos = None
                    elif event.type == pygame.MOUSEWHEEL and not consumed:
                        # Зум колесом мыши - мультипликативный шаг (не
                        # аддитивный) - одинаково ощутимый шаг зума и на
                        # минимальном, и на максимальном zoom. event.y > 0 -
                        # скролл "от себя"/вверх - приближение, как в картах.
                        # Явно зажимаем в [MIN_ZOOM, MAX_ZOOM], чтобы
                        # многократный скролл не увёл zoom за пределы.
                        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom * (1.15 ** event.y)))

                _handle_dashboard_commands(panel, cfg)

                # Тогглы pygame-панели (сенсоры/геном) и глобальный
                # show_track_lines читаются КАЖДЫЙ тик: PhyCar читает
                # screen.show_sensors внутри get_inputs_for_network() (вызывается
                # из env.decide() безусловно), поэтому гейт должен быть актуален
                # не только в рендер-кадре.
                screen.show_sensors = panel.show_sensors
                screen.show_track_lines = show_track_lines

                if _pending_restart_group:
                    _pending_restart_group = False
                    redo_group = True
                    running = False
                    continue

                if quit_requested:
                    continue

                # Автосохранение - без кнопки, просто на каждом тике сверяем
                # текущие настройки с последними записанными на диск (см.
                # _maybe_save_settings) и пишем файл, только если что-то
                # реально поменялось - ресайз окна тоже подхватится здесь же
                # (real_window.get_size() входит в снимок), отдельный хук на
                # VIDEORESIZE не нужен.
                _maybe_save_settings(screen, panel, cfg)

                active_envs = [env for env in environments if env.active]
                left_in_group = len(active_envs)
                visible_count = sum(1 for env in active_envs if env.car.visible)
                hidden_count = left_in_group - visible_count
                fps = clock.get_fps()

                if time.time() - _last_dashboard_sync >= DASHBOARD_SYNC_INTERVAL:
                    _last_dashboard_sync = time.time()
                    dashboard.set_current({
                        "generation": generation,
                        "track": current_track_file,
                        "tracks": dashboard.discover_tracks(),
                        "group_size": GROUP_SIZE,
                        "max_visible": MAX_VISIBLE,
                        "pop_size": cfg.pop_size,
                        "render_fps": FPS,
                        "left_in_group": left_in_group,
                        "visible_count": visible_count,
                        "hidden_count": hidden_count,
                        "fps": fps,
                        "group_time_s": round(time.time() - group_start_time, 2),
                        "paused": paused,
                        "unlimited_fps": unlimited_fps,
                        "camera_follow": camera_follow,
                        "zoom": zoom,
                        "show_track_lines": show_track_lines,
                        "best_lap_time": best_lap_time,
                        "max_distance_px": max_distance,
                        "max_cl": max_cl,
                        "max_laps": max_laps,
                        "max_fitness": max_fitness,
                        "grip_g": round(physic_car.GRIP_ACCEL / physic_car.GRIP_ACCEL_PER_G, 3),
                        "mass_kg": round(physic_car.CAR_MASS * physic_car.REFERENCE_MASS_KG, 3),
                        "power_hp": round(physic_car.ENGINE_POWER_HP, 3),
                        "genome": (dashboard.serialize_genome(best_genome, cfg)
                                   if best_genome is not None else None),
                    })

                # "Unlimited FPS" в панели - это не только снятие ограничения
                # кадров/сек, но и (обычно) полный пропуск отрисовки: именно
                # отрисовка (трасса, машины, визуализация сети, панель) и
                # flip() стоят дороже всего за кадр - просто снять лимит FPS
                # почти не ускоряет обучение, если продолжать рисовать каждый
                # кадр. Исключение - "Turbo + Camera Follow" (см.
                # BACKGROUND_RENDER_FPS выше): если включены ОБА - экран не
                # чёрный, а изредка показывает вид камеры на лидере.
                background_compute = unlimited_fps and camera_follow and group_best_env is not None
                if not unlimited_fps:
                    should_render = True
                elif background_compute:
                    now = time.time()
                    should_render = (now - last_bg_render_time) >= (1.0 / BACKGROUND_RENDER_FPS)
                    if should_render:
                        last_bg_render_time = now
                else:
                    should_render = False

                if not paused:
                    for env in environments:
                        if env.active:
                            env.decide()

                    group_space.step(1 / TICK_RATE)

                    for env in environments:
                        if env.active:
                            env.resolve()
                            max_cl = max(max_cl, env.car.get_cl())
                            max_fitness = max(max_fitness, env.car.get_fitness())
                            max_laps = max(max_laps, env.car.get_laps())
                            max_distance = max(max_distance, env.car.get_distance())

                            lap_time = env.car.get_lap_time()
                            if lap_time and lap_time < best_lap_time:
                                best_lap_time = lap_time

                            if env.car.get_fitness() > gen_fitness:
                                gen_fitness = env.car.get_fitness()
                                best_genome = env.genome

                    # Пересчитываем лидера группы заново каждый тик среди
                    # ТОЛЬКО АКТИВНЫХ машин (не "рекорд, который когда-то был
                    # поставлен" уже разбившейся машиной) - гарантирует, что
                    # камера/путь/подпись всегда опираются на реально бегущую
                    # (не застывшую) машину.
                    still_active = [env for env in environments if env.active]
                    if still_active:
                        group_best_env = max(still_active, key=lambda e: e.car.get_fitness())
                        # Лидер (к нему цепляется камера при Camera Follow, и
                        # его путь/подпись рисуются НИЖЕ безусловно, даже без
                        # Camera Follow) должен быть виден всегда - car.visible
                        # иначе выставляется один раз при создании машины по
                        # индексу в группе (car_index <= MAX_VISIBLE, см. выше)
                        # и не связан с тем, кто реально стал лидером сейчас:
                        # без этого лидер за пределами MAX_VISIBLE рисовался бы
                        # как невидимый (PhyCar.draw() выходит по visible=False)
                        # при том, что камера/путь/подпись на него уже указывают.
                        group_best_env.car.visible = True

                if should_render:
                    # Камеру (пан+зум) обновляем ПОСЛЕ шага физики/resolve() -
                    # т.е. используя уже АКТУАЛЬНУЮ на этот тик позицию лидера.
                    # Следим за group_best_env - лидером ЖИВОЙ текущей группы.
                    screen.camera.zoom = zoom
                    if camera_follow and group_best_env is not None:
                        # Пока пользователь тащит камеру мышью, НЕ перезаписываем
                        # center обратно на лидера в этом же кадре.
                        if not _camera_drag_active:
                            screen.camera.follow(group_best_env.car.get_postion())
                    elif not _camera_manual_pan:
                        # screen.track_center (не (viewport/2, viewport/2)) -
                        # центр bounding box САМОЙ трассы, см.
                        # Screen._recompute_world_bounds: для треков крупнее
                        # рендер-канваса (points_xti_winter.txt) это больше
                        # не совпадает с центром игрового поля "случайно",
                        # как было раньше на треках, вписанных в 2000x1200.
                        # Если пользователь уже панорамировал камеру вручную
                        # (_camera_manual_pan) - не сбрасываем её каждый кадр,
                        # иначе ручной пан отменялся бы на следующем же кадре.
                        screen.camera.center_on_field(screen.track_center)
                    screen.draw_track()
                    screen.draw_scale_bar()

                    for env in environments:
                        if env.active:
                            env.render()

                    if best_genome is not None and panel.show_genome:
                        screen.draw_network(best_genome, cfg)

                    if group_best_env is not None:
                        screen.draw_path(group_best_env.car.position_history, BEST_PATH_COLOR)
                        best_car = group_best_env.car
                        # Телеметрия лидера - фиксированный HUD-блок в правом
                        # нижнем углу холста (не подпись рядом с машиной, как
                        # было раньше: машина лидера может оказаться где угодно
                        # на трассе - в стороне, за пределами вида камеры без
                        # Camera Follow и т.п. - фиксированное место читается
                        # всегда, независимо от того, где сейчас лидер).
                        # Дистанция - ОБЩЕЕ пройденное расстояние (в метрах), а
                        # не время круга/в пути (get_distance() копит весь путь
                        # машины за эпизод, см. PhyCar.update). Скорость - км/ч
                        # (наглядная единица для водителя, не м/с) через ту же
                        # калибровку PX_PER_METER, что и дистанция/масштабная
                        # линейка: px/s -> м/с (/ PX_PER_METER) -> км/ч (* 3.6).
                        # Руль/газ - СЫРЫЕ команды сети (throttle/turn, значения,
                        # переданные в последний раз в car.throttle()/car.turn(),
                        # ДО круга трения и ограничений физики) - именно то, что
                        # реально выдаёт сеть на этом тике, а не физически
                        # реализованный руль/скорость машины.
                        speed_kmh = best_car.get_speed() / PX_PER_METER * 3.6
                        hud_lines = [
                            "Лидер группы:",
                            f"Дистанция: {best_car.get_distance() / PX_PER_METER:.1f} м",
                            f"Скорость: {speed_kmh:.1f} км/ч",
                            f"Руль: {best_car._pending_turn_power:.2f}",
                            f"Газ: {best_car._pending_throttle_power:.2f}",
                        ]
                        hud_line_h = 26
                        hud_margin = 16
                        hud_x = screen.logical_width - 300
                        hud_y = screen.logical_height - hud_margin - len(hud_lines) * hud_line_h
                        screen.draw_all([(line, (hud_x, hud_y + i * hud_line_h))
                                          for i, line in enumerate(hud_lines)])

                    panel.draw(screen.win)

                    screen.present()
                    if not unlimited_fps:
                        clock.tick(FPS)
                    # В любом турбо-режиме (Unlimited FPS) clock.tick() не
                    # вызываем вовсе - ни в обычном турбо (should_render тут
                    # всегда False, в этот if вообще не заходим), ни в
                    # "Turbo + Camera Follow" (should_render изредка True по
                    # таймеру реального времени background_compute выше) -
                    # иначе редкие кадры лидер-камеры искусственно тормозили
                    # бы всю группу до FPS, что противоречит смыслу турбо.
                # Если should_render=False (обычный турбо без Camera Follow,
                # либо background_compute ещё не готов рисовать очередной
                # редкий кадр) - гоняем симуляцию так быстро, как может CPU,
                # вообще не рисуя и не показывая кадр.

            if not redo_group:
                all_environments.extend(environments)

    if quit_requested:
        pygame.quit()
        sys.exit(0)

    # Установите оценку для каждого генома
    for env, (genome_id, genome) in zip(all_environments, genomes):
        genome.fitness = env.car.get_fitness()

    save_checkpoint(p, generation)
    elapsed = time.time() - gen_start_time
    print(f"Generation {generation} complete in {elapsed:.2f}s.")

    fits = [genome.fitness for _, genome in genomes]
    if fits:
        species_sizes = sorted((len(s.members) for s in p.species.species.values()), reverse=True)
        dashboard.record_generation({
            "generation": generation,
            "fitness_mean": round(sum(fits) / len(fits), 4),
            "fitness_max": round(max(fits), 4),
            "fitness_min": round(min(fits), 4),
            "species_count": len(species_sizes),
            "species_sizes": species_sizes,
            "best_lap_time": best_lap_time,
            "max_distance_px": max_distance,
            "max_cl": max_cl,
            "max_laps": max_laps,
            "elapsed_s": round(elapsed, 2),
        })

    generation += 1


if __name__ == "__main__":
    if not os.path.exists(CHECKPOINT_DIR):
        os.makedirs(CHECKPOINT_DIR)

    # Браузерная панель мониторинга/управления (см. car_racer/dashboard).
    # Запускается в фоновом daemon-потоке, не блокирует обучение и не падает,
    # если порт уже занят.
    dashboard.start_server()

    # Настройки предыдущего запуска (см. car_racer/file_manager/settings_store.py)
    # - {} при первом запуске/битом файле, тогда всё ниже просто остаётся на
    # встроенных дефолтах. current_track_file/MAX_VISIBLE/GROUP_SIZE/FPS -
    # модульные глобали, используемые eval_genomes (см. выше) - здесь мы в
    # области видимости модуля (не внутри функции), поэтому простое
    # присваивание работает без global.
    initial_settings = load_settings()
    # Проверяем, что сохранённый файл трассы всё ещё существует - трассы
    # иногда удаляются/переименовываются (напр. points_reserve*.txt снесены,
    # points_oval.txt переименован в points_oval_half_mile.txt), а
    # user_settings.json мог сохранить старое имя из прошлой сессии -
    # без этой проверки Screen(track_file=...) упал бы с FileNotFoundError
    # прямо на старте, только потому что где-то раньше поменяли набор треков.
    saved_track = initial_settings.get("track_file")
    if saved_track and os.path.exists(os.path.join("car_racer", "tracks", saved_track)):
        current_track_file = saved_track
    if "max_visible" in initial_settings:
        MAX_VISIBLE = initial_settings["max_visible"]
    if "group_size" in initial_settings:
        GROUP_SIZE = initial_settings["group_size"]
    if "render_fps" in initial_settings:
        FPS = initial_settings["render_fps"]
    if "grip_g" in initial_settings:
        physic_car.GRIP_ACCEL = initial_settings["grip_g"] * physic_car.GRIP_ACCEL_PER_G
    if "mass_kg" in initial_settings:
        physic_car.CAR_MASS = initial_settings["mass_kg"] / physic_car.REFERENCE_MASS_KG
    if "power_hp" in initial_settings:
        physic_car.ENGINE_POWER_HP = initial_settings["power_hp"]
    if "unlimited_fps" in initial_settings:
        unlimited_fps = initial_settings["unlimited_fps"]
    if "camera_follow" in initial_settings:
        camera_follow = initial_settings["camera_follow"]
    if "show_track_lines" in initial_settings:
        show_track_lines = initial_settings["show_track_lines"]
    if "window_width" in initial_settings and "window_height" in initial_settings:
        initial_real_size = (initial_settings["window_width"], initial_settings["window_height"])

    config = get_neat_config()
    if "pop_size" in initial_settings:
        config.pop_size = initial_settings["pop_size"]

    # Пытаемся загрузить последнюю контрольную точку. Отбираем строго по
    # имени, которое пишет save_checkpoint() (file_manager/file_worker.py:
    # f'neat-checkpoint-gen-{generation}.pkl') - раньше брался любой *.pkl в
    # папке, и посторонний файл (случайно скопированный, из другого проекта,
    # просто не подходящий под "neat-checkpoint-gen-<N>.pkl") падал с
    # ValueError/IndexError на f.split('-')[3], а не с понятной ошибкой.
    latest_checkpoint = None
    if os.path.exists(CHECKPOINT_DIR):
        checkpoint_pattern = re.compile(r'^neat-checkpoint-gen-(\d+)\.pkl$')
        checkpoints = [f for f in os.listdir(CHECKPOINT_DIR) if checkpoint_pattern.match(f)]
        if checkpoints:
            latest_checkpoint = max(checkpoints, key=lambda f: int(checkpoint_pattern.match(f).group(1)))
            generation = int(checkpoint_pattern.match(latest_checkpoint).group(1))

    p = load_checkpoint(os.path.join(CHECKPOINT_DIR, latest_checkpoint)) \
        if latest_checkpoint else neat.Population(config)
    # load_checkpoint распаковывает ВЕСЬ neat.Population целиком, включая его
    # СОБСТВЕННЫЙ config таким, каким он был на момент pickle.dump - если
    # config-feedforward.txt с тех пор поменялся (например num_inputs), это
    # старое значение молча использовалось бы вместо актуального файла на
    # диске (activate() падал бы с "Expected 9 inputs, got 10" - ровно то,
    # что и произошло). UI-панель и так уже мутирует cfg.pop_size на лету
    # (см. eval_genomes) - конфиг в этом проекте считается живым, актуальным
    # для ТЕКУЩЕГО запуска, а не замороженным на момент чекпоинта.
    p.config = config

    # Добавление репортеров
    p.add_reporter(neat.StdOutReporter(True))
    stats = neat.StatisticsReporter()
    p.add_reporter(stats)

    # Запуск обучения. При запросе "Restart Training" из UI-панели
    # eval_genomes поднимает RestartTrainingRequested - ловим его здесь,
    # создаём свежую популяцию и запускаем обучение заново (окно не трогаем).
    try:
        while True:
            try:
                winner = p.run(eval_genomes, 1000)
                break
            except RestartTrainingRequested:
                print("Restart Training: создаю новую популяцию и начинаю обучение с нуля.")
                generation = 1
                max_fitness = 0
                max_cl = 0
                max_laps = 0
                best_lap_time = MAX_TIMEOUT
                max_distance = 0

                dashboard.reset_history()

                p = neat.Population(config)
                p.add_reporter(neat.StdOutReporter(True))
                stats = neat.StatisticsReporter()
                p.add_reporter(stats)
    except Exception as e:
        import traceback
        print(f"An error occurred: {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            log_path = os.path.join("car_racer", "config", "error.log")
            with open(log_path, "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
            print(f"[полный трейсбек сохранён в {log_path}]")
        except OSError:
            pass
        raise
    finally:
        pygame.quit()
