import json
import math
import os

import numpy as np
import pygame

from car_racer.constants import PX_PER_METER
from car_racer.file_manager.file_worker import parse_track, POINTS_DIR
from car_racer.screen.camera import Camera, MIN_ZOOM, MAX_ZOOM
from car_racer.screen.ui_panel import UIPanel, PANEL_WIDTH
from helpers.calculate import build_track_segments

BLACK = (0, 0, 0)
RED = (255, 0, 0)
CHECKPOINT_COLOR = (15, 128, 0)
WHITE = (255, 255, 255)
GRAY = (104, 104, 104)
DARK_GRAY = (70, 70, 70)
IDEAL_LINE_COLOR = (255, 215, 0)  # "идеальная" траектория от офлайн-оптимизатора
BEST_PATH_COLOR = (0, 220, 255)  # путь лучшего генома текущего поколения

TRACK_COLOR = (150, 150, 150)
SCREEN_WIDTH, SCREEN_HEIGHT = 2000, 1200

# --- Фон/полотно трассы (см. draw_track/_build_grass_texture) --------------
# Раньше вне трассы был плоский self.win.fill(BLACK), а полотно вообще не
# заливалось - только контурные polyline outer/inner на чёрном фоне, отчего
# экран выглядел пустым/безжизненным (особенно на крупных реальных трассах,
# где внутри контура было ничего). GRASS_GREEN - фон "за пределами трассы"
# (заливается текстурой, см. ниже, но это её базовый цвет), ASPHALT_COLOR -
# заливка самого полотна (тёмно-серый, не чёрный - чтобы отличаться от
# фона/чёрных областей letterbox в present()).
GRASS_GREEN = (36, 94, 46)
ASPHALT_COLOR = (58, 58, 63)

# Шум травы генерируется ОДИН РАЗ (см. _build_grass_texture, кэшируется в
# self._grass_texture) на пониженном разрешении - по блокам GRASS_NOISE_SCALE
# px, а не по каждому пикселю: даёт то же ощущение "мятой" травы, но
# генерация (единственный раз, не каждый кадр) на порядок дешевле, а сама
# заливка кадра - обычный blit готовой Surface, независимо от размера трассы
# (важно для крупных трасс типа points_monza.txt, где рендер и так недёшев).
GRASS_NOISE_SCALE = 5
GRASS_NOISE_AMPLITUDE = 14  # +/- отклонение яркости блока от базового GRASS_GREEN

# Максимальная сторона (px) кэшированной растровой текстуры полотна трассы
# (см. Screen._build_track_fill_texture) - трасса заливается ОДИН РАЗ в
# эту текстуру (в её собственном, уменьшенном относительно мировых px,
# разрешении), а не через pygame.draw.polygon по полным outer/inner каждый
# кадр (дорого на трассах с большим числом точек полотна, см. докстринг
# _build_track_fill_texture). 2048 - с запасом достаточно, чтобы кольцо
# полотна не выглядело "лестницей" даже при сильном приближении камерой
# (asphalt/grass - плоские цвета без резких деталей, лёгкая пикселизация на
# границе почти не заметна и в любом случае перекрывается чёткой контурной
# линией outer/inner, рисуемой отдельно по полным координатам).
TRACK_FILL_CACHE_MAX_DIM = 2048

# --- "Шашечки" на стартовой линии (см. _draw_start_checkers) ---------------
# Чисто декоративный чек-паттерн поперёк стартовой линии - НЕ зависит от
# общего числа точек трассы (в отличие от контуров outer/inner), поэтому
# дешёв даже на points_monza.txt (~9700 точек полотна): считается по
# start_line (всегда 2 точки) на каждый кадр, а не по всей границе трассы.
CHECKER_SQUARE_WORLD = 10.0  # размер одной "шашечки" в мировых px
CHECKER_ROWS = 2


def _polygon_area(points):
    """Площадь простого замкнутого полигона (формула площади Гаусса/шоеласа),
    без знака (нам важна только величина, не ориентация обхода) - используется
    ТОЛЬКО Screen._build_track_fill_texture, чтобы определить, какой из двух
    контуров трассы (track_outer/track_inner) геометрически больше и должен
    заливаться асфальтом первым (см. комментарий там же про то, что имя поля
    "outer" не гарантирует, что контур больше)."""
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0

VIS_WIDTH, VIS_HEIGHT = 700, 350
VIS_X, VIS_Y = 20, 830
NEURON_RADIUS = 5

WORLD_BOUNDS_MARGIN = 200.0  # запас (px) от bounding box трассы до "границы
                              # мира" - см. Screen._recompute_world_bounds

# --- Масштабная линейка (см. Screen.draw_scale_bar) -------------------------
SCALE_BAR_NICE_METERS = [1, 2, 5, 10, 20, 50, 100, 200, 500,
                          1000, 2000, 5000, 10000, 20000, 50000, 100000]
SCALE_BAR_TARGET_PX = 110  # желаемая длина бруска на экране, px - из этого
                            # ряда выбирается "круглое" значение метров, чьи
                            # реальные PX_PER_METER*zoom пикселей ближе всего
SCALE_BAR_MARGIN = 24
SCALE_BAR_TICK_H = 7
SCALE_BAR_COLOR = (240, 240, 240)


class Screen:
    def __init__(self, window_size=(SCREEN_WIDTH, SCREEN_HEIGHT), track_file="points.txt", with_panel=True,
                 initial_real_size=None):
        pygame.init()
        self.font = pygame.font.Font(None, 25)

        # Настройка окна.
        # self.screen_width/self.screen_height — размер ВИДИМОГО игрового поля
        # (виджет Camera, см. ниже) — НЕ используются машинами для проверки
        # выхода за границы (та проверка теперь идёт по world_bounds —
        # bounding box самой трассы, см. _recompute_world_bounds ниже; трасса
        # может быть физически намного больше этих чисел, см. CLAUDE.md про
        # PX_PER_METER/points_xti_winter.txt). Панель UI пристёгивается справа
        # и добавляется только к физическому размеру логического холста, не к
        # игровому полю.
        #
        # Окно можно менять по размеру (pygame.RESIZABLE), но вся трасса,
        # физика, сенсоры и UI-панель по-прежнему рисуются в self.win —
        # логический холст ФИКСИРОВАННОГО размера (logical_width x
        # logical_height), как будто размер окна никогда не меняется. Перед
        # показом кадра этот холст масштабируется под реальный размер окна
        # (с сохранением пропорций, letterbox) в present() и блитится в
        # self.real_window - реальную поверхность экрана. Так ресайз окна не
        # требует ни малейших изменений в координатах трассы/физики.
        pygame.display.set_caption("Car Racing")
        self.screen_width, self.screen_height = window_size
        self.panel_width = PANEL_WIDTH if with_panel else 0
        self.logical_width = self.screen_width + self.panel_width
        self.logical_height = self.screen_height

        # Реальное (первое) окно подбирается не больше, чем видит текущий
        # монитор (pygame.display.Info()) - логический холст при этом не
        # меняется, letterbox-масштабирование в present() уже умеет вписывать
        # его в окно любого размера. Раньше окно всегда создавалось РОВНО
        # logical_width x logical_height, и на мониторе с меньшей высотой,
        # чем это, оно не помещалось на экран, пока пользователь не уменьшал
        # его руками. Если размер монитора узнать не удалось (например,
        # headless SDL_VIDEODRIVER=dummy) - ведём себя как раньше (scale=1).
        try:
            display_info = pygame.display.Info()
            monitor_w, monitor_h = display_info.current_w, display_info.current_h
        except pygame.error:
            monitor_w = monitor_h = 0
        margin = 80  # запас под рамки окна/панель задач ОС

        if initial_real_size is not None:
            # Размер окна, сохранённый в прошлый раз (см.
            # car_racer/file_manager/settings_store.py) - используем его
            # вместо auto-fit ниже, но всё равно подрезаем под ТЕКУЩИЙ
            # монитор (мог оказаться другим/меньше того, где сохраняли),
            # чтобы окно не вылезло за экран.
            initial_width, initial_height = initial_real_size
            if monitor_w > 0 and monitor_h > 0:
                initial_width = min(initial_width, max(320, monitor_w - margin))
                initial_height = min(initial_height, max(240, monitor_h - margin))
            initial_width = max(320, round(initial_width))
            initial_height = max(240, round(initial_height))
        else:
            initial_scale = 1.0
            if monitor_w > 0 and monitor_h > 0:
                available_w = max(320, monitor_w - margin)
                available_h = max(240, monitor_h - margin)
                initial_scale = min(1.0, available_w / self.logical_width, available_h / self.logical_height)
            initial_width = max(320, round(self.logical_width * initial_scale))
            initial_height = max(240, round(self.logical_height * initial_scale))

        self.real_window = pygame.display.set_mode(
            (initial_width, initial_height),
            pygame.HWSURFACE | pygame.DOUBLEBUF | pygame.RESIZABLE)
        self.win = pygame.Surface((self.logical_width, self.logical_height))

        # Камера игрового поля (пан + зум) - см. car_racer/screen/camera.py.
        # Отдельно от letterbox-масштабирования выше: та часть вписывает ВЕСЬ
        # логический холст в окно, эта - решает, какой кусок МИРА рисуется НА
        # холсте. При zoom=1 и центре по умолчанию преобразование тождественно
        # (воспроизводит поведение без камеры).
        self.camera = Camera(self.screen_width, self.screen_height)

        self.track_file = track_file
        self.track_outer, self.track_inner, self.checkpoints_lines, self.start_line = parse_track(track_file)
        self._rebuild_track_segments()
        self._recompute_world_bounds()
        self._load_ideal_line()

        self.texts: dict[str, tuple[str, tuple[int, int]]] = {}

        # Гейты видимости, читаемые PhyCar (через self.screen) и
        # draw_track() - см. CLAUDE.md про "Show sensor rays"/"Show track
        # lines" в UI-панели. Живут на Screen (а не только на panel), чтобы
        # машины могли проверять их даже если бы панели не было (with_panel=
        # False) - main.py синхронизирует их с panel.show_sensors/
        # panel.show_track_lines каждый тик. По умолчанию True - совпадает
        # с поведением до появления этих тоглов (лучи и чекпоинты рисовались
        # всегда).
        self.show_sensors = True
        self.show_track_lines = True

        # Текстура травы кэшируется лениво при первом draw_track() (а не в
        # __init__) - строится один раз на self.screen_width x
        # self.screen_height (логический размер игрового поля не меняется
        # за время жизни Screen, см. комментарий выше про letterbox) и
        # переиспользуется во всех последующих кадрах без перегенерации.
        self._grass_texture = None

        # Кэш растровой текстуры полотна трассы (см.
        # _build_track_fill_texture/_draw_track_fill) - тоже лениво строится
        # при первом draw_track(), но, в отличие от _grass_texture, зависит
        # от track_outer/track_inner ТЕКУЩЕЙ трассы - инвалидируется (сбросом
        # в None) в load_track() при переключении трассы.
        self._track_fill_texture = None

        self.panel = UIPanel(self.screen_width, self.screen_height,
                              panel_width=self.panel_width, initial_track=track_file) if with_panel else None

    def handle_resize(self, event):
        """Скармливать сюда события pygame.VIDEORESIZE (обычно из общего цикла
        обработки событий, рядом с QUIT). Логический холст (self.win) при этом
        не меняется - меняется только реальная поверхность экрана."""
        if event.type == pygame.VIDEORESIZE:
            self.real_window = pygame.display.set_mode(
                (event.w, event.h), pygame.HWSURFACE | pygame.DOUBLEBUF | pygame.RESIZABLE)

    def _viewport(self):
        """(scale, ширина/высота вписанного изображения, отступы letterbox)
        для текущего реального размера окна относительно логического холста."""
        win_w, win_h = self.real_window.get_size()
        scale = min(win_w / self.logical_width, win_h / self.logical_height)
        scaled_w = max(1, round(self.logical_width * scale))
        scaled_h = max(1, round(self.logical_height * scale))
        offset_x = (win_w - scaled_w) // 2
        offset_y = (win_h - scaled_h) // 2
        return scale, scaled_w, scaled_h, offset_x, offset_y

    def present(self):
        """Масштабирует логический холст под текущий размер окна (пропорции
        сохраняются, лишнее место - чёрные полосы) и показывает кадр.
        Вызывать вместо pygame.display.flip() в конце кадра."""
        scale, scaled_w, scaled_h, offset_x, offset_y = self._viewport()
        self.real_window.fill(BLACK)
        if (scaled_w, scaled_h) == (self.logical_width, self.logical_height):
            surface_to_blit = self.win
        else:
            surface_to_blit = pygame.transform.smoothscale(self.win, (scaled_w, scaled_h))
        self.real_window.blit(surface_to_blit, (offset_x, offset_y))
        pygame.display.flip()

    def window_to_logical(self, pos):
        """Переводит координаты мыши из пикселей реального (возможно,
        ресайзнутого) окна в логические координаты холста self.win, в которых
        заданы кнопки панели и трасса."""
        scale, scaled_w, scaled_h, offset_x, offset_y = self._viewport()
        x, y = pos
        return (x - offset_x) / scale, (y - offset_y) / scale

    def _rebuild_track_segments(self):
        # Кэш границ трассы как numpy-массивов для быстрого (без shapely)
        # рейкастинга сенсоров машин - см. helpers.calculate.cast_ray.
        # Пересчитывается здесь и в load_track(), т.к. зависит от
        # track_outer/track_inner.
        self.track_segments_start, self.track_segments_end = build_track_segments(
            self.track_outer, self.track_inner)

    def load_track(self, filename):
        """Перезагружает трассу "на лету" без пересоздания окна/Screen —
        используется UI-панелью при переключении трассы и при рестарте группы
        на новой трассе."""
        self.track_outer, self.track_inner, self.checkpoints_lines, self.start_line = parse_track(filename)
        self.track_file = filename
        self._rebuild_track_segments()
        self._recompute_world_bounds()
        self._load_ideal_line()
        # Кэш заливки полотна (см. _build_track_fill_texture) построен под
        # СТАРЫЙ track_outer/track_inner - обязательно инвалидировать здесь,
        # иначе после переключения трассы рисовалось бы полотно предыдущей.
        self._track_fill_texture = None

    def _recompute_world_bounds(self, margin=WORLD_BOUNDS_MARGIN):
        """Прямоугольник "мира" (min_x, min_y, max_x, max_y) — bounding box
        ЭТОЙ трассы (track_outer + track_inner) плюс запас `margin` со всех
        сторон. Это ВТОРОЙ, грубый backstop-барьер выхода за пределы
        (см. PhyCar.check_collision_with_track) — основная проверка
        "разбился о стену" (min_distance_to_segments, расстояние до реального
        полотна) не связана с этим прямоугольником и не отменяется им; этот
        прямоугольник нужен только чтобы отловить машину, которая каким-то
        образом оказалась ДАЛЕКО за пределами всей трассы (а не просто рядом
        со стеной), а не как основной детектор столкновения.

        Раньше границей были фиксированные screen.screen_width/screen_height
        (2000x1200) — не годится, когда трасса физически больше этого окна
        (см. points_xti_winter.txt после переезда на PX_PER_METER: реальная
        длина круга 1250 м * PX_PER_METER=20 = 25000px по центральной линии,
        на порядок больше 2000x1200). world_bounds — ЧИСТО числовой
        прямоугольник (4 float на сравнение позиции), НЕ связан с размером
        self.win/Camera-viewport — рендер-канвас (~2000x1200) не меняется и
        не должен меняться вместе с размером мира, вся суть Camera (pan+zoom)
        в том, что она показывает произвольно большой мир на канвасе
        фиксированного модального размера.

        Пересчитывается здесь и в load_track() — зависит от track_outer/
        track_inner, которые меняются при переключении трассы. Заодно считает
        self.track_center (центр того же bbox, БЕЗ отступа) — нужен камере
        для режима "показать весь трек целиком" (Camera.center_on_field),
        см. car_racer/neat_runner/main.py: раньше center_on_field() центровала
        камеру на (viewport_width/2, viewport_height/2), что совпадало с
        реальным центром трассы только потому, что трассы были нарисованы
        внутри той же коробки 2000x1200 — для трасс крупнее viewport'а это
        совпадение больше не работает."""
        pts = self.track_outer + self.track_inner
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        self.world_bounds = (min_x - margin, min_y - margin, max_x + margin, max_y + margin)
        self.track_center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
        self._track_bbox_size = (max_x - min_x, max_y - min_y)

    def compute_fit_zoom(self, fill_fraction=0.92):
        """Зум, при котором ВСЯ трасса (bounding box track_outer+track_inner,
        см. _recompute_world_bounds) целиком помещается в игровое поле
        (screen_width x screen_height - именно то, что видит Camera, панель
        справа сюда не входит) - используется, чтобы при открытии окна/смене
        трассы карта сразу заполняла собой доступное пространство, а не
        показывала маленький кусок при zoom=1 (было особенно заметно на
        крупных трассах после перехода на PX_PER_METER, см. CLAUDE.md).

        `fill_fraction` - доля игрового поля, которую должен занимать bbox
        трассы (не 1.0 - небольшой отступ по краям, чтобы трасса не
        обрезалась вплотную к границе экрана). Результат зажат в
        [MIN_ZOOM, MAX_ZOOM] (те же границы, что у слайдера Zoom в панели) -
        на очень маленькой трассе не даёт zoom уйти выше разумного предела."""
        bbox_w, bbox_h = self._track_bbox_size
        if bbox_w <= 0 or bbox_h <= 0:
            return 1.0
        zoom = min(self.screen_width / bbox_w, self.screen_height / bbox_h) * fill_fraction
        return max(MIN_ZOOM, min(MAX_ZOOM, zoom))

    def _load_ideal_line(self):
        """Ищет рядом с файлом трассы <имя_трассы>.ideal_line.json (формат см.
        car_racer/trajectory/optimal_line.py) и, если найден, подгружает
        точки "идеальной" траектории для отрисовки поверх трассы. Файл
        необязателен - для трасс, для которых его ещё не считали, тут просто
        остаётся None, и оверлей не рисуется."""
        base_name = os.path.splitext(self.track_file)[0]
        ideal_line_path = os.path.join(POINTS_DIR, base_name + ".ideal_line.json")
        self.ideal_line_points = None
        self.ideal_line_lap_time = None
        try:
            with open(ideal_line_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            points = data.get("points")
            if points and len(points) >= 2:
                self.ideal_line_points = [(p[0], p[1]) for p in points]
                self.ideal_line_lap_time = data.get("estimated_lap_time")
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, KeyError, IndexError):
            pass

    def get_window(self):
        return self.win

    def draw_scale_bar(self):
        """Масштабная линейка "гугл-картовского" вида в левом нижнем углу
        ИГРОВОГО ПОЛЯ (не в UI-панели справа - это свойство карты/камеры, а
        не панели управления): короткий горизонтальный брусок с засечками на
        концах + подпись реальной дистанции ("50 m"/"1 km"), которую этот
        брусок представляет на экране ПРИ ТЕКУЩЕМ zoom камеры. Вызывать
        каждый кадр (как screen.draw_track()) - значение живо пересчитывается
        от screen.camera.zoom, поэтому обновляется вслед за слайдером Zoom
        без каких-либо доп. действий.

        Подбор "круглого" значения метров (см. SCALE_BAR_NICE_METERS) - как в
        картах: из ряда 1/2/5/10/20/50 м... берём то, чья экранная длина при
        текущем zoom ближе всего к SCALE_BAR_TARGET_PX (не любая длина
        выглядела бы естественно - хотим брусок разумного размера, а не то
        220px, то 3px). Перевод "метры -> экранные px" идёт через ДВА шага,
        по конвенции проекта: метры -> МИРОВЫЕ px (умножение на
        PX_PER_METER, константа car_racer/constants.py, единственная
        калибровка px->метры в проекте) -> экранные px (camera.scale_length,
        учитывает zoom) - тот же путь, что и вся остальная отрисовка
        (см. car_racer/screen/camera.py: камера ничего не знает про метры,
        только про мировые px)."""
        cam = self.camera
        best_meters = SCALE_BAR_NICE_METERS[0]
        best_diff = float("inf")
        for meters in SCALE_BAR_NICE_METERS:
            screen_px = cam.scale_length(meters * PX_PER_METER)
            diff = abs(screen_px - SCALE_BAR_TARGET_PX)
            if diff < best_diff:
                best_diff = diff
                best_meters = meters

        bar_px = cam.scale_length(best_meters * PX_PER_METER)
        x0 = SCALE_BAR_MARGIN
        y0 = self.screen_height - SCALE_BAR_MARGIN
        x1 = x0 + bar_px

        pygame.draw.line(self.win, SCALE_BAR_COLOR, (x0, y0), (x1, y0), 2)
        pygame.draw.line(self.win, SCALE_BAR_COLOR, (x0, y0 - SCALE_BAR_TICK_H), (x0, y0 + SCALE_BAR_TICK_H), 2)
        pygame.draw.line(self.win, SCALE_BAR_COLOR, (x1, y0 - SCALE_BAR_TICK_H), (x1, y0 + SCALE_BAR_TICK_H), 2)

        label = f"{best_meters} m" if best_meters < 1000 else f"{best_meters // 1000} km"
        label_surf = self.font.render(label, True, SCALE_BAR_COLOR, BLACK)
        label_rect = label_surf.get_rect(midbottom=((x0 + x1) / 2, y0 - SCALE_BAR_TICK_H - 4))
        self.win.blit(label_surf, label_rect)

    def _build_grass_texture(self):
        """Строит и кэширует (см. self._grass_texture) слегка "мятую" зелёную
        текстуру фона размером с игровое поле (self.screen_width x
        self.screen_height) - вызывается один раз лениво из draw_track(),
        а не в __init__ (не задерживает конструктор Screen без явной нужды)
        и не каждый кадр (см. GRASS_NOISE_SCALE выше про то, почему это
        важно для перформанса на крупных трассах).

        Шум строится через numpy на пониженном разрешении (блоки
        GRASS_NOISE_SCALE px) и растягивается smoothscale до полного
        размера - честный per-pixel шум на 2000x1200 (2.4M пикселей) даёт
        визуально то же самое "мятое" ощущение, но генерируется заметно
        дольше; блочный шум с последующим сглаживанием дешевле и всё равно
        убирает эффект плоской чёрной/однотонной заливки."""
        w, h = self.screen_width, self.screen_height
        small_w = max(1, w // GRASS_NOISE_SCALE)
        small_h = max(1, h // GRASS_NOISE_SCALE)

        rng = np.random.default_rng(1234)  # фиксированный сид - текстура
                                            # детерминирована между запусками
                                            # и не "мерцает" от кадра к кадру
        noise = rng.integers(-GRASS_NOISE_AMPLITUDE, GRASS_NOISE_AMPLITUDE + 1,
                              size=(small_w, small_h))

        arr = np.empty((small_w, small_h, 3), dtype=np.uint8)
        for channel, base_value in enumerate(GRASS_GREEN):
            arr[:, :, channel] = np.clip(base_value + noise, 0, 255)

        small_surf = pygame.surfarray.make_surface(arr)
        return pygame.transform.smoothscale(small_surf, (w, h))

    def _build_track_fill_texture(self):
        """Строит и кэширует (self._track_fill_texture/_origin/_scale) растровую
        текстуру полотна трассы (асфальт-кольцо между outer/inner) В МИРОВЫХ
        координатах (с понижением разрешения, см. TRACK_FILL_CACHE_MAX_DIM) -
        один раз на трассу, а НЕ каждый кадр через pygame.draw.polygon по
        полным outer/inner.

        Почему: первая версия просто заливала pygame.draw.polygon(...) по
        outer/inner КАЖДЫЙ кадр в экранных координатах после камеры - на
        points_monza.txt (~9700 точек полотна) это ~18ms/кадр (профилировано,
        см. car_racer/screen/screen.py в истории правок) - заливка полигона в
        pygame стоит от числа вершин, а не от видимой площади, и с камерой,
        которая пересчитывает экранные координаты каждый кадр, кэшировать
        готовые ЭКРАННЫЕ точки нельзя (они меняются с zoom/pan). Вместо этого
        полигон заливается ОДИН РАЗ в СВОИХ, не зависящих от камеры, мировых
        координатах (пересчитанных в пиксели текстуры через `_scale`), а
        каждый кадр эта готовая растровая Surface просто масштабируется
        (pygame.transform.scale, дешёвая операция) под текущий cam.zoom и
        блитится в точку cam.world_to_screen(origin) - тот же принцип, что и
        _grass_texture выше, но привязанный к МИРОВЫМ координатам (a не
        экранным), т.к. полотно должно панорамироваться/зумиться вместе с
        трассой, а не оставаться неподвижным фоном экрана.

        Аффинность камеры (world_to_screen - чистый scale+translate, без
        поворота, см. car_racer/screen/camera.py) - именно то, что позволяет
        заменить "перерисовать полигон под новую camera" на "перемасштабировать
        готовую картинку" без искажений: линейное преобразование мировых
        координат в текстурные (при постройке текстуры) плюс линейное
        world_to_screen (при показе) композируются в одно линейное
        преобразование текстура -> экран.

        Кэш инвалидируется в load_track() (новая трасса - новый bbox/полигон).

        ВАЖНО про порядок заливки: нельзя считать, что track_outer -
        геометрически БОЛЬШИЙ контур, а track_inner - МЕНЬШИЙ ("дырка") -
        имена полей об этом ничего не гарантируют (см. parse_track/
        file_worker.py: это просто "первая строка файла"/"вторая строка
        файла"). На практике на большинстве трасс outer действительно
        больше, но на points_oval_half_mile.txt наоборот - inner больше
        outer (проверено площадью через _polygon_area ниже: если залить
        "outer первым, inner вторым" не глядя, второй проход просто
        закрашивает ВСЮ асфальтовую заливку цветом фона - полотно становится
        полностью невидимым, что и произошло при первой версии этого кода).
        Поэтому здесь явно сравниваются площади (shoelace) и большей заливкой
        всегда идёт первым (асфальт), меньшей - вторым (дырка), вне
        зависимости от того, как называется поле в этой конкретной трассе."""
        pts = self.track_outer + self.track_inner
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        bbox_w, bbox_h = max_x - min_x, max_y - min_y
        if bbox_w <= 0 or bbox_h <= 0:
            return None

        scale = min(TRACK_FILL_CACHE_MAX_DIM / bbox_w, TRACK_FILL_CACHE_MAX_DIM / bbox_h)
        tex_w = max(1, round(bbox_w * scale))
        tex_h = max(1, round(bbox_h * scale))

        surf = pygame.Surface((tex_w, tex_h))
        surf.fill(GRASS_GREEN)  # база текстуры = фон (без шума - см. draw_track
                                 # про то, что "дырка" внутреннего контура и так
                                 # заливается однотонным цветом, не текстурой)

        def to_tex(p):
            return ((p[0] - min_x) * scale, (p[1] - min_y) * scale)

        outer_tex = [to_tex(p) for p in self.track_outer]
        inner_tex = [to_tex(p) for p in self.track_inner]

        if _polygon_area(outer_tex) < _polygon_area(inner_tex):
            outer_tex, inner_tex = inner_tex, outer_tex

        if len(outer_tex) >= 3:
            pygame.draw.polygon(surf, ASPHALT_COLOR, outer_tex)
        if len(inner_tex) >= 3:
            pygame.draw.polygon(surf, GRASS_GREEN, inner_tex)

        return surf, (min_x, min_y), scale

    def _draw_track_fill(self, cam):
        """Кадрирует под видимую область экрана и масштабирует закэшированную
        текстуру полотна (см. _build_track_fill_texture) под текущую камеру -
        см. пояснение там же про то, почему масштабирование готовой картинки
        эквивалентно перерисовке полигона под новую камеру для афинных
        преобразований.

        ВАЖНО (вылет при близком зуме, был реальным багом): раньше под
        cam.zoom масштабировалась ВСЯ текстура целиком, независимо от того,
        видна ли вся трасса на экране. Текстура снижена до
        TRACK_FILL_CACHE_MAX_DIM=2048px по большей стороне (см.
        _build_track_fill_texture), но у огромных трасс (points_monza.txt/
        points_imola.txt, bbox ~29000x33000/~36600x19300px) даже
        умеренное приближение камеры требовало результирующей Surface на
        ДЕСЯТКИ ТЫСЯЧ пикселей по стороне: для Монцы у MAX_ZOOM=2.5 -
        около 72000x82000px, это ~24 ГБ на один RGB-кадр (32-бит) - гарантированный
        вылет (MemoryError/SDL out of memory) при попытке приблизить камеру
        именно на этих трассах (на маленьких трассах текстура и так меньше
        экрана, поэтому баг не проявлялся). Экран физически не может
        показать больше пикселей, чем в самом игровом поле
        (screen_width x screen_height) - масштабировать нужно ТОЛЬКО ту
        часть текстуры, которая реально попадает в кадр, а не текстуру
        целиком. `cam.screen_to_world` переводит углы видимой области в
        мировые координаты, дальше та же линейная калибровка, что и при
        постройке текстуры (`(мировая_точка - origin) * cache_scale`),
        переводит их в пиксели текстуры - обрезаем текстуру по этому
        прямоугольнику (`Surface.subsurface`, дешёвая view без копирования)
        ДО масштабирования. Результат масштабирования теперь всегда
        ограничен размером игрового поля независимо от zoom и размера
        трассы - кэш РЕЗУЛЬТАТА по zoom (был раньше) больше не нужен: сама
        операция уже ограничена по стоимости размером экрана на каждый
        кадр (тот же порядок величины, что у _grass_texture ниже, который
        и так блитится каждый кадр без кэша результата)."""
        if self._track_fill_texture is None:
            self._track_fill_texture = self._build_track_fill_texture()
        if self._track_fill_texture is None:
            return
        texture, (origin_x, origin_y), cache_scale = self._track_fill_texture
        tex_w, tex_h = texture.get_size()

        world_top_left = cam.screen_to_world((0, 0))
        world_bottom_right = cam.screen_to_world((self.screen_width, self.screen_height))
        tex_x0 = (world_top_left[0] - origin_x) * cache_scale
        tex_y0 = (world_top_left[1] - origin_y) * cache_scale
        tex_x1 = (world_bottom_right[0] - origin_x) * cache_scale
        tex_y1 = (world_bottom_right[1] - origin_y) * cache_scale

        crop_x0 = max(0, math.floor(min(tex_x0, tex_x1)))
        crop_y0 = max(0, math.floor(min(tex_y0, tex_y1)))
        crop_x1 = min(tex_w, math.ceil(max(tex_x0, tex_x1)))
        crop_y1 = min(tex_h, math.ceil(max(tex_y0, tex_y1)))
        crop_w = crop_x1 - crop_x0
        crop_h = crop_y1 - crop_y0
        if crop_w <= 0 or crop_h <= 0:
            return  # видимая область экрана не пересекается с текстурой трассы вообще

        cropped = texture.subsurface((crop_x0, crop_y0, crop_w, crop_h))

        draw_scale = cam.zoom / cache_scale
        scaled_w = max(1, round(crop_w * draw_scale))
        scaled_h = max(1, round(crop_h * draw_scale))
        scaled_texture = pygame.transform.scale(cropped, (scaled_w, scaled_h))

        crop_world_origin = (origin_x + crop_x0 / cache_scale, origin_y + crop_y0 / cache_scale)
        top_left = cam.world_to_screen(crop_world_origin)
        self.win.blit(scaled_texture, top_left)

    def _draw_start_checkers(self, cam):
        """Декоративный чек-паттерн (белый/красный) поперёк стартовой линии
        - см. CHECKER_SQUARE_WORLD/CHECKER_ROWS выше про то, почему это
        дёшево даже на огромных трассах (не зависит от числа точек полотна,
        только от длины ОДНОЙ линии - start_line)."""
        (x1, y1), (x2, y2) = self.start_line
        lat_dx, lat_dy = x2 - x1, y2 - y1
        lat_len = math.hypot(lat_dx, lat_dy)
        if lat_len < 1e-6:
            return
        lat_dx, lat_dy = lat_dx / lat_len, lat_dy / lat_len
        # Перпендикуляр к направлению линии - ось "вдоль трассы", вдоль
        # которой откладываются CHECKER_ROWS рядов шашечек.
        fwd_dx, fwd_dy = -lat_dy, lat_dx

        square = CHECKER_SQUARE_WORLD
        num_squares = max(1, round(lat_len / square))
        for row in range(CHECKER_ROWS):
            # Ряды центрируются на самой линии (одна половина рядов - по
            # одну сторону, другая - по другую), а не полностью в одну
            # сторону от неё - так паттерн выглядит как "лежащий на" линии
            # старта, а не сдвинутый вбок от неё.
            row_offset = (row - (CHECKER_ROWS - 1) / 2.0) * square
            for i in range(num_squares):
                # Чередование по (row + i) - соседние по обеим осям клетки
                # разного цвета, как и положено шашечкам.
                color = WHITE if (row + i) % 2 == 0 else RED
                base_lat = i * square
                corners_world = [
                    (x1 + lat_dx * base_lat + fwd_dx * row_offset,
                     y1 + lat_dy * base_lat + fwd_dy * row_offset),
                    (x1 + lat_dx * (base_lat + square) + fwd_dx * row_offset,
                     y1 + lat_dy * (base_lat + square) + fwd_dy * row_offset),
                    (x1 + lat_dx * (base_lat + square) + fwd_dx * (row_offset + square),
                     y1 + lat_dy * (base_lat + square) + fwd_dy * (row_offset + square)),
                    (x1 + lat_dx * base_lat + fwd_dx * (row_offset + square),
                     y1 + lat_dy * base_lat + fwd_dy * (row_offset + square)),
                ]
                pygame.draw.polygon(self.win, color, cam.world_to_screen_many(corners_world))

    def draw_track(self):
        # Фон "за пределами трассы" - текстурированная трава вместо плоского
        # чёрного (см. GRASS_GREEN/_build_grass_texture выше) - раньше
        # экран вне контура outer/inner был буквально пуст. Текстура кэшируется
        # один раз и просто блитится каждый кадр - НЕ пересчитывается под
        # камеру (это фон игрового поля в экранных, не мировых координатах;
        # при панорамировании/зуме "трава не едет вместе с миром" - осознанный
        # компромисс простоты/производительности, см. задачу).
        if self._grass_texture is None:
            self._grass_texture = self._build_grass_texture()
        self.win.fill(BLACK)
        self.win.blit(self._grass_texture, (0, 0))

        # Все точки трассы - мировые координаты; переводим их в координаты
        # логического холста через камеру (см. car_racer/screen/camera.py)
        # непосредственно перед pygame.draw.* - сама трасса (track_outer/
        # track_inner/checkpoints_lines/start_line/ideal_line_points) в
        # мировых координатах не меняется.
        cam = self.camera
        outer_screen = cam.world_to_screen_many(self.track_outer)
        inner_screen = cam.world_to_screen_many(self.track_inner)

        # Полотно трассы - тёмно-серая заливка вместо пустого чёрного/травы
        # между контурами, из закэшированной растровой текстуры (см.
        # _build_track_fill_texture/_draw_track_fill выше) - НЕ через
        # pygame.draw.polygon по полным outer/inner каждый кадр (было ~18ms/
        # кадр на points_monza.txt, ~9700 точек полотна - заливка полигона в
        # pygame стоит от числа вершин; см. подробное объяснение в докстринге
        # _build_track_fill_texture). pygame не умеет "polygon с дырой"
        # напрямую - текстура строится тем же приёмом в два прохода (залить
        # внешний контур асфальтом, затем внутренний - цветом фона), но
        # ОДНОКРАТНО, в мировых координатах текстуры, а не каждый кадр в
        # экранных.
        self._draw_track_fill(cam)

        pygame.draw.lines(self.win, TRACK_COLOR, True, outer_screen, cam.scale_length(2))
        pygame.draw.lines(self.win, TRACK_COLOR, True, inner_screen, cam.scale_length(2))

        # Линии чекпоинтов - скрываются тоглом "Show track lines" (см.
        # self.show_track_lines/CLAUDE.md), контур трассы и стартовая линия
        # ниже ОСТАЮТСЯ видимыми всегда - без них трасса вообще нечитаема.
        if self.show_track_lines:
            for start_ch_line, end_ch_line in self.checkpoints_lines:
                pygame.draw.line(self.win, CHECKPOINT_COLOR, cam.world_to_screen(start_ch_line),
                                  cam.world_to_screen(end_ch_line), cam.scale_length(3))

        self._draw_start_checkers(cam)
        pygame.draw.line(self.win, (255, 255, 255), cam.world_to_screen(self.start_line[0]),
                          cam.world_to_screen(self.start_line[1]), cam.scale_length(5))
        if self.ideal_line_points:
            pygame.draw.lines(self.win, IDEAL_LINE_COLOR, True,
                               cam.world_to_screen_many(self.ideal_line_points), cam.scale_length(2))

    def draw_path(self, points, color, width=2, closed=False):
        """Рисует произвольную ломаную поверх трассы - используется для
        траектории лучшего генома текущего поколения (см. neat_runner/main.py).
        `points` - мировые координаты (car.position_history), переводятся в
        координаты холста через камеру, как и сама трасса."""
        if points and len(points) >= 2:
            cam = self.camera
            pygame.draw.lines(self.win, color, closed, cam.world_to_screen_many(points), cam.scale_length(width))

    def get_track(self):
        return self.track_outer, self.track_inner

    def draw_all(self, values: [tuple[str, tuple[int, int]]]):
        for text, position in values:
            d_text = self.font.render(text, True, WHITE, BLACK)
            self.win.blit(d_text, position)

    def draw_network(self, genome, config):
        # Очистка области визуализации
        transparent_surface = pygame.Surface((VIS_WIDTH, VIS_HEIGHT), pygame.SRCALPHA)

        # Установите шрифт для отображения текста
        font = pygame.font.SysFont('Arial', 17, bold=False, italic=False)

        # Задайте координаты для слоев
        # layer_positions = []
        node_positions = {}
        input_nodes = config.genome_config.input_keys
        output_nodes = config.genome_config.output_keys
        hidden_nodes = list(set(genome.nodes.keys()) - set(input_nodes) - set(output_nodes))

        # Метки для входных и выходных нейронов
        input_labels = ["angle", "speed", "compass", "-150", "-90", "-45", "0", "45", "90", "150"]
        output_labels = ["throttle", "turn"]

        # Вычисление позиций для входного и выходного слоев
        input_positions = [(VIS_X + 50, VIS_Y + VIS_HEIGHT // (len(input_nodes) + 1) * (i + 1)) for i in
                           range(len(input_nodes))]
        output_positions = [(VIS_X + VIS_WIDTH - 50, VIS_Y + VIS_HEIGHT // (len(output_nodes) + 1) * (i + 1)) for i in
                            range(len(output_nodes))]
        #
        # layer_positions.append(input_positions)
        # layer_positions.append(output_positions)

        # Map input and output nodes to their positions
        for i, node in enumerate(input_nodes):
            node_positions[node] = input_positions[i]
        for i, node in enumerate(output_nodes):
            node_positions[node] = output_positions[i]

        # Проверка на наличие скрытых нейронов
        if hidden_nodes:
            # Создаем словарь для хранения уровней для каждого нейрона
            node_levels = {node: 0 for node in hidden_nodes}

            # Обновляем уровни на основе соединений
            for conn_key, conn in genome.connections.items():
                if conn.enabled:
                    in_node, out_node = conn_key
                    if in_node in hidden_nodes and out_node in hidden_nodes:
                        node_levels[out_node] = max(node_levels[out_node], node_levels[in_node] + 1)

            # Сортируем скрытые нейроны по уровню
            max_level = max(node_levels.values())
            hidden_layer_positions = []
            for level in range(max_level + 1):
                level_nodes = [node for node, lvl in node_levels.items() if lvl == level]
                positions = [(VIS_X + (VIS_WIDTH // (2 + max_level)) * (level + 1),
                              VIS_Y + VIS_HEIGHT // (len(level_nodes) + 1) * (i + 1)) for i in range(len(level_nodes))]
                hidden_layer_positions.append(positions)
                for i, node in enumerate(level_nodes):
                    node_positions[node] = positions[i]

            # layer_positions = [layer_positions[0]] + hidden_layer_positions + [layer_positions[1]]

        self.win.blit(transparent_surface, (VIS_X, VIS_Y))

        # Отображение соединений
        for conn_key, conn in genome.connections.items():
            if conn.enabled:
                in_node, out_node = conn_key
                start_pos = node_positions[in_node]
                end_pos = node_positions[out_node]
                pygame.draw.line(self.win, DARK_GRAY if conn.weight < 0 else GRAY, start_pos, end_pos, 1)

        # Отображение нейронов и меток
        for i, node in enumerate(input_nodes):
            pos = node_positions[node]
            pygame.draw.circle(self.win, (0, 255, 0), pos, NEURON_RADIUS)
            # input_labels собран под текущие 10 входов (num_inputs в
            # config-feedforward.txt) - сопоставление по индексу остаётся
            # корректным и при меньшем num_inputs (просто не все подписи
            # используются), но при БОЛЬШЕМ num_inputs input_labels[i] упал
            # бы с IndexError - вместо падения или молчаливого расхождения
            # подписей показываем сам индекс входа, которому не хватило
            # именованной метки.
            label = input_labels[i] if i < len(input_labels) else f"in{i}"
            label_surface = font.render(label, True, WHITE)
            self.win.blit(label_surface, (pos[0] - 60, pos[1] - 10))

        for i, node in enumerate(output_nodes):
            pos = node_positions[node]
            pygame.draw.circle(self.win, (0, 255, 0), pos, NEURON_RADIUS)
            label_surface = font.render(output_labels[i], True, WHITE)
            self.win.blit(label_surface, (pos[0] + 15, pos[1] - 10))

        # Отображение скрытых нейронов
        for node in hidden_nodes:
            pos = node_positions[node]
            pygame.draw.circle(self.win, (0, 255, 0), pos, NEURON_RADIUS)
