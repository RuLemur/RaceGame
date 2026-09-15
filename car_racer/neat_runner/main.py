import os
import re
import sys
import time

import neat
import pygame
import pymunk

from car_racer.cars import physic_car
from car_racer.constants import MAX_TIMEOUT, TICK_RATE
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
# panel.unlimited_fps (турбо, обычно полностью пропускает отрисовку) И
# panel.camera_follow (камера следует за best_env) - вместо полностью
# пропущенного кадра рисуется редкий "лёгкий" кадр вида камеры на лидере, по
# таймеру реального времени (не чаще BACKGROUND_RENDER_FPS раз/сек), а не на
# каждый тик. Экран остаётся живым (виден лидер + окрестность трассы), а сама
# симуляция по-прежнему не ограничена по FPS - см. подробности у should_render
# ниже в тик-цикле.
BACKGROUND_RENDER_FPS = 15

generation = 1
max_fitness: int = 0
max_cl = 0
max_laps = 0
best_lap_time = MAX_TIMEOUT
max_distance = 0

# Выбранный на данный момент файл трассы (переключается кнопкой в UI-панели).
current_track_file = "points.txt"

# Окно и панель создаются один раз и переиспользуются между поколениями:
# быстрее (не пересоздаём pygame-окно на каждое поколение) и не сбрасывает
# состояние панели (пауза, Unlimited FPS) между поколениями.
screen = None

# Ручное панорамирование камеры (drag ЛКМ по игровому полю, см. обработку
# событий в eval_genomes ниже) - независимо от Camera Follow
# (panel.camera_follow, следует за лидером группы), но координируется с ним:
# _camera_drag_active - True всё время, пока зажата ЛКМ и драг был начат на
# игровом поле (не на панели справа) - пока это так, рендер-блок ниже НЕ
# вызывает screen.camera.follow(...), чтобы драг не перезатирался в тот же
# кадр (драг временно "перекрывает" Camera Follow, а не ломает его - после
# отпускания ЛКМ follow снова начинает центрировать камеру как обычно).
# _camera_manual_pan - True после хотя бы одного драга (не сбрасывается по
# отпусканию ЛКМ, в отличие от _camera_drag_active) - подавляет автоматическое
# center_on_field() в режиме "Camera Follow выключен", иначе ручной пан
# отменялся бы уже на следующем отрисованном кадре. Сбрасывается при смене
# трассы (см. consume_track_change ниже) - координаты новой трассы не связаны
# со старой панорамой.
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
        "zoom": round(panel.zoom, 4),
        "camera_follow": panel.camera_follow,
        "show_genome": panel.show_genome,
        "unlimited_fps": panel.unlimited_fps,
        "show_sensors": panel.show_sensors,
        "show_track_lines": panel.show_track_lines,
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


def eval_genomes(genomes, cfg):
    global generation, max_fitness, max_cl, max_laps, best_lap_time, max_distance
    global current_track_file, screen, MAX_VISIBLE, GROUP_SIZE, FPS, p
    global _camera_drag_active, _camera_drag_last_pos, _camera_manual_pan

    if screen is None:
        screen = Screen(track_file=current_track_file, initial_real_size=initial_real_size)
        # Панель создаётся раньше, чем сюда приходит cfg - синхронизируем
        # стартовые значения полей вводимых параметров реальными (иначе
        # поле "Pop size" показывало бы дефолт-заглушку виджета, а не
        # актуальный config.pop_size). camera_follow/show_genome/unlimited_fps
        # - из сохранённых настроек прошлого запуска (см. initial_settings/
        # settings_store.py), None если их не было - sync_initial_values
        # тогда просто не трогает эти поля, остаются дефолты виджетов.
        #
        # zoom - НЕ из сохранённых настроек: при открытии окна карта должна
        # сразу заполнять всё доступное пространство (screen.compute_fit_zoom
        # - подбирает zoom под bounding box ИМЕННО этой трассы), а не
        # восстанавливать зум прошлой сессии, который мог быть подобран под
        # совсем другую по размеру трассу (особенно с учётом того, что трассы
        # теперь очень разного реального размера - от короткого овала до
        # многокилометровой xti_winter, см. CLAUDE.md про PX_PER_METER).
        screen.panel.sync_initial_values(
            max_visible=MAX_VISIBLE, group_size=GROUP_SIZE, pop_size=cfg.pop_size, fps=FPS,
            grip_g=physic_car.GRIP_ACCEL / physic_car.GRIP_ACCEL_PER_G,
            mass_kg=physic_car.CAR_MASS * physic_car.REFERENCE_MASS_KG,
            power_hp=physic_car.ENGINE_POWER_HP,
            zoom=screen.compute_fit_zoom(),
            camera_follow=initial_settings.get("camera_follow"),
            show_genome=initial_settings.get("show_genome"),
            unlimited_fps=initial_settings.get("unlimited_fps"),
            show_sensors=initial_settings.get("show_sensors"),
            show_track_lines=initial_settings.get("show_track_lines"))
    panel = screen.panel

    clock = pygame.time.Clock()

    # Разбейте геномы на группы
    num_groups = (len(genomes) + GROUP_SIZE - 1) // GROUP_SIZE  # Округление вверх

    # Для хранения всех сред для последующего отображения
    all_environments = []

    best_genome = None
    best_env = None  # лучший геном за ВСЁ поколение (переживает смену групп) -
                      # используется только для screen.draw_network() ниже.
                      # НЕ годится для камеры/пути/подписи: его машина могла
                      # принадлежать уже завершённой группе и просто не
                      # рендерится в текущей `for env in environments: ...`
                      # (была "машина-призрак" - камера следила за её
                      # застывшей позицией, а сама она не рисовалась - баг).
                      # Для этого ниже отдельно заводится group_best_env.
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

            # Лучший геном/среда В ПРЕДЕЛАХ ТЕКУЩЕЙ группы И СРЕДИ ЕЩЁ
            # АКТИВНЫХ машин (не всего поколения и не "рекорд, который
            # когда-то был поставлен", даже уже разбившейся машиной) - для
            # камеры/пути/подписи: гарантированно ссылается на машину,
            # которая реально рендерится циклом `for env in environments`
            # ниже (см. комментарии у group_best_env ниже по коду).
            group_best_env = None

            # Создайте среду для текущей группы
            environments = []
            for car_index, (genome_id, genome) in enumerate(current_group):
                environments.append(GameEnvironment(genome, cfg, genome_id, screen,
                                                     car_index <= MAX_VISIBLE, space=group_space))

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
                    # полю (event.pos уже в логических координатах холста,
                    # см. выше; сравнение с screen.screen_width отсекает
                    # клики по панели справа). См. комментарий у
                    # _camera_drag_active в начале модуля про то, как это
                    # сочетается с Camera Follow.
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not consumed:
                        if event.pos[0] < screen.screen_width:
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
                        # Зум колесом мыши - event.pos уже в логических
                        # координатах холста (см. rewrite выше), сравнение с
                        # screen_width отсекает скролл над панелью справа
                        # (там своя логика - панель сама не скроллится, но
                        # лучше не трогать zoom, если курсор не над картой).
                        # Мультипликативный шаг (не аддитивный) - одинаково
                        # ощутимый шаг зума и на минимальном, и на
                        # максимальном zoom. event.y > 0 - скролл "от себя"/
                        # вверх - приближение, как в большинстве карт.
                        if event.pos[0] < screen.screen_width:
                            # panel.sync_initial_values сама зажимает
                            # zoom_slider.value в [min,max] слайдера, но НЕ
                            # panel.zoom (простое поле, используется прямо в
                            # screen.camera.zoom = panel.zoom ниже) - зажимаем
                            # явно здесь, иначе многократный скролл в одну
                            # сторону мог бы увести zoom далеко за пределы,
                            # которые слайдер и так не позволяет выставить
                            # мышью.
                            new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, panel.zoom * (1.15 ** event.y)))
                            panel.sync_initial_values(zoom=new_zoom)

                panel.update()

                # Continuous-атрибуты (как panel.paused/panel.camera_follow) -
                # синхронизируем на Screen КАЖДЫЙ тик, а не только в блоке
                # should_render ниже: PhyCar читает screen.show_sensors
                # внутри get_inputs_for_network()/draw_line(), которые
                # вызываются из env.decide() безусловно (каждый тик, не
                # только когда рисуется кадр) - см. CLAUDE.md про то, что это
                # гейт ТОЛЬКО отрисовки, расчёт сенсора (cast_ray) не
                # пропускается независимо от этого флага. show_track_lines
                # читается только внутри screen.draw_track() (вызывается
                # только при should_render), но синхронизировать его здесь же
                # не вредит и проще для понимания, чем разносить по двум местам.
                screen.show_sensors = panel.show_sensors
                screen.show_track_lines = panel.show_track_lines

                if panel.consume_restart_training():
                    raise RestartTrainingRequested()

                new_track = panel.consume_track_change()
                if new_track:
                    current_track_file = new_track
                    screen.load_track(new_track)
                    # Ручной пан (см. _camera_manual_pan выше) относится к
                    # координатам СТАРОЙ трассы - на новой трассе он
                    # бессмыслен и, если не сбросить, до первого нового
                    # драга держал бы камеру в точке, никак не связанной с
                    # новым треком.
                    _camera_manual_pan = False
                    _camera_drag_active = False
                    _camera_drag_last_pos = None
                    # Аналогично зуму при первом открытии окна (см. выше) -
                    # новая трасса может быть совсем другого размера, старый
                    # zoom для неё бессмысленен, пересчитываем под неё же.
                    panel.sync_initial_values(zoom=screen.compute_fit_zoom())

                # MAX_VISIBLE читается только при создании environments для
                # ГРУППЫ (ниже, вне этого тик-цикла) - значит новое значение
                # само подхватится со следующей группы, ничего пересчитывать
                # прямо сейчас не нужно.
                new_max_visible = panel.consume_max_visible_change()
                if new_max_visible is not None:
                    MAX_VISIBLE = new_max_visible

                # GROUP_SIZE используется только для разбиения genomes на
                # группы ДО начала цикла по группам текущего поколения (см.
                # num_groups выше) - менять его тут безопасно: текущее
                # поколение уже разбито и не пересчитывается, эффект будет
                # виден с следующего вызова eval_genomes (следующее поколение).
                new_group_size = panel.consume_group_size_change()
                if new_group_size is not None:
                    GROUP_SIZE = new_group_size

                # pop_size у живого neat.Population на лету не меняется -
                # правим только conf, реальный размер популяции пересоздастся
                # при следующем Restart Training (см. RestartTrainingRequested
                # ниже и __main__).
                new_pop_size = panel.consume_pop_size_change()
                if new_pop_size is not None:
                    cfg.pop_size = new_pop_size

                new_fps = panel.consume_fps_change()
                if new_fps is not None:
                    FPS = new_fps

                # Физика (car_racer/cars/physic_car.py) читает эти модульные
                # переменные при создании КАЖДОЙ машины - меняем их тут же
                # напрямую, эффект будет виден с машин следующей группы (у
                # уже бегущих в этой группе ничего не меняется "на лету").
                # Переводим из наглядных единиц UI (g/кг/л.с.) обратно во
                # внутренние игровые - см. комментарии в physic_car.py.
                new_grip_g = panel.consume_grip_change()
                if new_grip_g is not None:
                    physic_car.GRIP_ACCEL = new_grip_g * physic_car.GRIP_ACCEL_PER_G

                new_mass_kg = panel.consume_mass_change()
                if new_mass_kg is not None:
                    physic_car.CAR_MASS = new_mass_kg / physic_car.REFERENCE_MASS_KG

                new_power_hp = panel.consume_power_change()
                if new_power_hp is not None:
                    physic_car.ENGINE_POWER_HP = new_power_hp

                if panel.consume_recompute_ideal_line():
                    # Синхронный клик (~1с на сложных трассах) - пересчитывает
                    # идеальную траекторию ТЕКУЩЕЙ трассы под ТЕКУЩИЕ
                    # сцепление/массу/мощность (vehicle_params_from_physic_car),
                    # а не под дефолты модуля, сохраняет .ideal_line.json и
                    # сразу перезагружает его в Screen, чтобы оверлей на треке
                    # обновился без перезапуска.
                    vehicle_params = optimal_line.vehicle_params_from_physic_car()
                    ideal_result = optimal_line.compute_optimal_line(
                        screen.track_outer, screen.track_inner, vehicle_params=vehicle_params)
                    optimal_line.save_ideal_line(screen.track_file, ideal_result)
                    screen._load_ideal_line()

                if panel.consume_restart_group():
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

                # "Unlimited FPS" в панели - это не только снятие ограничения
                # кадров/сек, но и (обычно) полный пропуск отрисовки: именно
                # отрисовка (трасса, машины, визуализация сети, панель) и
                # flip() стоят дороже всего за кадр - просто снять лимит FPS
                # почти не ускоряет обучение, если продолжать рисовать каждый
                # кадр.
                #
                # Исключение - "Turbo + Camera Follow" ("фоновый расчёт"):
                # если ОДНОВРЕМЕННО включены Unlimited FPS и Camera Follow (и
                # есть group_best_env, за кем следить - см. комментарий у
                # camera.follow() ниже про то, почему именно group_best_env,
                # а не best_env) - экран не остаётся полностью чёрным/
                # замороженным, а изредка (не чаще BACKGROUND_RENDER_FPS
                # раз/сек РЕАЛЬНОГО времени - НЕ раз в N тиков, т.к. в турбо
                # тики идут гораздо быстрее реального времени) перерисовывается
                # дешёвый кадр: вид камеры, следящей за лидером, + окрестность
                # трассы. Между такими редкими кадрами остальная популяция
                # по-прежнему считается без ограничения FPS - см. clock.tick()
                # ниже, который в любом варианте турбо-режима (обычном и с
                # фоновым рендером лидера) сознательно не вызывается вовсе.
                background_compute = panel.unlimited_fps and panel.camera_follow and group_best_env is not None
                if not panel.unlimited_fps:
                    should_render = True
                elif background_compute:
                    now = time.time()
                    should_render = (now - last_bg_render_time) >= (1.0 / BACKGROUND_RENDER_FPS)
                    if should_render:
                        last_bg_render_time = now
                else:
                    should_render = False

                if not panel.paused:
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
                                best_env = env

                    # group_best_env пересчитывается ЗАНОВО каждый тик среди
                    # ТОЛЬКО ЕЩЁ АКТИВНЫХ машин (не "рекорд, который когда-то
                    # был поставлен") - если лидер группы только что разбился,
                    # он больше не активен и не рендерится циклом `env.render()`
                    # ниже; продолжать следить за ним камерой значило бы снова
                    # словить "машину-призрак" (см. комментарий у camera.follow
                    # ниже), только по другой причине, чем изначальный баг.
                    # Пока этот тик выполняется, хотя бы одна машина группы
                    # ещё активна (иначе внешний while уже бы завершился) -
                    # список никогда не окажется пустым здесь.
                    still_active = [env for env in environments if env.active]
                    if still_active:
                        group_best_env = max(still_active, key=lambda e: e.car.get_fitness())

                if should_render:
                    # Камеру (пан+зум) обновляем ПОСЛЕ шага физики/resolve() -
                    # т.е. используя уже АКТУАЛЬНУЮ на этот тик позицию
                    # лидера. Раньше камера настраивалась ДО физики - если
                    # лидерство переходило к другой машине в этом же тике,
                    # камера оставалась центрирована на устаревшей позиции
                    # СТАРОГО лидера, а машина/путь/подпись рисовались уже
                    # для НОВОГО (баг №1). Следим именно за group_best_env
                    # (лидер ТЕКУЩЕЙ группы), а не best_env (лидер ВСЕГО
                    # поколения) - иначе, если поколенческий лидер был найден
                    # в уже завершённой группе, камера центрировалась бы на
                    # застывшей позиции машины, которая физически не
                    # рендерится циклом ниже (`for env in environments`) -
                    # получалась "машина-призрак": путь/подпись видны
                    # (рисуются по прямой ссылке), а сама трасса вокруг неё
                    # пустая, и ни одна из реально активных машин группы не
                    # видна в кадре (баг №2, воспринимался как "трасса
                    # пропала"). Zoom - из слайдера панели.
                    screen.camera.zoom = panel.zoom
                    if panel.camera_follow and group_best_env is not None:
                        # Пока пользователь тащит камеру мышью (см.
                        # _camera_drag_active), НЕ перезаписываем center
                        # обратно на лидера в этом же кадре - иначе драг был
                        # бы не виден вовсе (follow() выполнялся бы каждый
                        # кадр ПОСЛЕ обработки событий и мгновенно стирал
                        # результат). Как только ЛКМ отпущена - follow как
                        # обычно продолжает центрировать камеру на лидере.
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

                    best_genome_time_str = "-"
                    if group_best_env is not None:
                        screen.draw_path(group_best_env.car.position_history, BEST_PATH_COLOR)
                        best_car = group_best_env.car
                        if best_car.get_lap_time() > 0:
                            best_genome_time_str = f"{best_car.get_lap_time():.2f}s (круг)"
                        else:
                            best_genome_time_str = f"{best_car.tick_count / TICK_RATE:.2f}s (в пути)"
                        # label_pos - мировая позиция машины лидера; в
                        # координаты холста переводим через камеру (как и
                        # саму трассу/путь выше), иначе подпись "уезжала" бы
                        # от машины при включённом Camera Follow/zoom != 1.
                        label_screen_pos = screen.camera.world_to_screen(best_car.get_postion())
                        screen.draw_all([(best_genome_time_str,
                                          (label_screen_pos[0] + 15, label_screen_pos[1] - 15))])

                    stats = {
                        "generation": generation,
                        "genomes_range": f"{start_index + 1}-{end_index}",
                        "left_in_group": left_in_group,
                        "visible_count": visible_count,
                        "hidden_count": hidden_count,
                        "time": time.time() - group_start_time,
                        "fps": fps,
                        "best_lap_time_str": _format_best_lap(best_lap_time),
                        "max_distance": max_distance,
                        "max_cl": max_cl,
                        "max_laps": max_laps,
                        "max_fitness": max_fitness,
                        "best_genome_time_str": best_genome_time_str,
                        "ideal_lap_time_str": (f"{screen.ideal_line_lap_time:.2f}s"
                                                if screen.ideal_line_lap_time else "-"),
                    }
                    panel.draw(screen.win, stats)

                    screen.present()
                    if not panel.unlimited_fps:
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
    generation += 1


if __name__ == "__main__":
    if not os.path.exists(CHECKPOINT_DIR):
        os.makedirs(CHECKPOINT_DIR)

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

                p = neat.Population(config)
                p.add_reporter(neat.StdOutReporter(True))
                stats = neat.StatisticsReporter()
                p.add_reporter(stats)
    except Exception as e:
        print(f"An error occurred: {e}")
        raise
    finally:
        pygame.quit()
