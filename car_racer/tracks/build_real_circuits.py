"""
Импорт реальных гоночных трасс (Монца, Имола) из настоящих схем, а не по
описанию последовательности поворотов (см. предыдущую версию в git-истории,
`build_famous_circuits.py` - удалена, форма получалась слишком приближённой).

Источники (положены пользователем в корень репозитория):
- `RaceCircuitAutodromaDiMonza.svg` - НАСТОЯЩИЙ векторный SVG, один замкнутый
  `<path>` - это ЦЕНТРАЛЬНАЯ ЛИНИЯ трассы (не пара outer/inner, как у
  `points_xti_winter.txt`/`svg_track_importer.py`), поэтому ширина полотна
  здесь получается смещением (`track_builder.offset_polyline`) этой одной
  линии в обе стороны на половину реальной ширины - а не из двух независимых
  контуров SVG.
- `Imola_2009.svg.webp` - РАСТРОВОЕ изображение (несмотря на имя - это
  сохранённый с Wikipedia PNG/WEBP рендер, не сам векторный SVG), схематичная
  чёрная линия на белом фоне с подписями поворотов. Векторных данных тут нет
  - центральная линия извлекается оцифровкой: бинаризация (чёрные пиксели),
  скелетизация (`skimage.morphology.skeletonize` - сводит толстую линию до
  толщины 1px) и трассировка скелета в упорядоченную последовательность точек
  (обход по соседним пикселям скелета). Кружки-номера поворотов и подписи на
  картинке - отдельные, не связанные с основной линией компоненты (после
  бинаризации превращаются в отдельные "острова"), отбрасываются как шум по
  размеру/форме компонента связности.

Реальные длина/ширина (найдены в интернете, не выдуманы):
- Монца: 5793 м, ширина полотна 10-12 м (используется среднее, 11 м).
- Имола: 4909 м (современная конфигурация), ширина полотна 14 м.

Единицы/масштаб - тот же принцип, что и в svg_track_importer.py: считаем
всё в "единицах исходного изображения", калибруем `метров_на_единицу =
REAL_LENGTH_M / длина_центральной_линии_в_этих_единицах`, переводим в игровые
px через ЕДИНУЮ калибровку проекta `PX_PER_METER` (car_racer/constants.py) -
`draw_scale = PX_PER_METER * метров_на_единицу`.

Старт-финиш ставится на середину самого длинного прямого участка
(`svg_track_importer._find_longest_straight_index` - переиспользуется как
есть, просто вызывается с одним и тем же массивом в роли и "outer", и
"inner", тогда её внутреннее `(outer+inner)/2` возвращает саму центральную
линию) - как и у `points_xti_winter.txt`, а не там, где случайно начинается
путь в исходном файле.

Запуск:
    python -m car_racer.tracks.build_real_circuits
"""
import math
import os
import xml.etree.ElementTree as ET

import numpy as np
from svgpathtools import parse_path

from car_racer.constants import PX_PER_METER
from car_racer.file_manager.file_worker import POINTS_DIR
from car_racer.tracks.track_builder import offset_polyline, fit_to_screen, save_track_file
from car_racer.tracks.svg_track_importer import (
    _smooth_closed, _radius_of_curvature, _find_longest_straight_index,
    build_checkpoints, count_self_intersections,
)

MONZA_SVG = "RaceCircuitAutodromaDiMonza.svg"
MONZA_REAL_LENGTH_M = 5793.0
MONZA_WIDTH_M = 11.0

IMOLA_IMAGE = "Imola_2009.svg.webp"
IMOLA_REAL_LENGTH_M = 4909.0
IMOLA_WIDTH_M = 14.0

N_POINTS = 900              # точек центральной линии после передискретизации
CHECKPOINT_SPACING_M = 60.0  # чекпоинт примерно каждые 60м реальной трассы
CURVATURE_SAFETY_FACTOR = 0.5  # см. svg_track_importer.widen_boundaries


def _project_root_path(filename):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), filename)


def _discretize_svg_path(svg_file, n=N_POINTS):
    """Читает единственный <path> из svg_file и передискретизирует его на n
    точек с равным шагом по длине дуги (svgpathtools.ilength/point)."""
    ns = {"svg": "http://www.w3.org/2000/svg"}
    tree = ET.parse(_project_root_path(svg_file))
    root = tree.getroot()
    paths = root.findall(".//svg:path", ns)
    if not paths:
        raise RuntimeError(f"В {svg_file} не найден <path>")
    path = parse_path(paths[0].get("d"))
    total_len = path.length()
    pts = np.zeros((n, 2))
    for i in range(n):
        t = path.ilength(total_len * i / n, s_tol=1e-4)
        p = path.point(t)
        pts[i] = (p.real, p.imag)
    return pts, total_len


def _closed_length(pts):
    return float(np.sum(np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)))


def build_from_centerline(centerline_units, real_length_m, width_m, out_filename, verbose=True):
    """Общий пайплайн center line (в "единицах исходника", любых - px/svg-unit)
    -> файл трассы: калибровка метров, поиск старт-финиша на самой длинной
    прямой, смещение на ширину полотна (с проверкой на самопересечение,
    уменьшая при необходимости), масштаб в PX_PER_METER, чекпоинты,
    fit_to_screen, сохранение."""
    length_units = _closed_length(centerline_units)
    meters_per_unit = real_length_m / length_units

    start_idx = _find_longest_straight_index(centerline_units, centerline_units)
    centerline_units = np.roll(centerline_units, -start_idx, axis=0)

    half_width_units = (width_m / 2.0) / meters_per_unit
    r = _radius_of_curvature(_smooth_closed(centerline_units, 7))
    min_radius = float(np.min(r[np.isfinite(r)]))
    safe_half_width = CURVATURE_SAFETY_FACTOR * min_radius
    used_half_width = min(half_width_units, safe_half_width)
    if verbose and used_half_width < half_width_units:
        print(f"  ! ширина урезана из-за кривизны: {used_half_width*meters_per_unit*2:.1f}м "
              f"вместо {width_m}м (мин. радиус поворота {min_radius*meters_per_unit:.1f}м)")

    outer_units = np.asarray(offset_polyline(centerline_units.tolist(), used_half_width))
    inner_units = np.asarray(offset_polyline(centerline_units.tolist(), -used_half_width))

    n_x = count_self_intersections(outer_units) + count_self_intersections(inner_units)
    if n_x:
        raise RuntimeError(f"Самопересечение после смещения на ширину ({n_x}) - уменьши width_m/CURVATURE_SAFETY_FACTOR")

    draw_scale = PX_PER_METER * meters_per_unit
    outer_px = outer_units * draw_scale
    inner_px = inner_units * draw_scale

    checkpoint_spacing_px = CHECKPOINT_SPACING_M * PX_PER_METER
    checkpoints = build_checkpoints(outer_px, inner_px, checkpoint_spacing_px)
    start_line = (tuple(outer_px[0]), tuple(inner_px[0]))

    outer_list, inner_list, checkpoints, start_line = fit_to_screen(
        [tuple(p) for p in outer_px], [tuple(p) for p in inner_px], checkpoints, start_line, margin=100.0)

    path = save_track_file(out_filename, outer_list, inner_list, checkpoints, start_line, directory=POINTS_DIR)

    if verbose:
        real_len = length_units * meters_per_unit
        xs = [p[0] for p in outer_list]
        ys = [p[1] for p in outer_list]
        print(f"{out_filename}: длина {real_len:.0f}м (цель {real_length_m:.0f}м), "
              f"ширина {used_half_width*2*meters_per_unit:.1f}м, чекпоинтов {len(checkpoints)}, "
              f"bbox {max(xs)-min(xs):.0f}x{max(ys)-min(ys):.0f}px")
    return path


def build_monza():
    centerline, _ = _discretize_svg_path(MONZA_SVG)
    return build_from_centerline(centerline, MONZA_REAL_LENGTH_M, MONZA_WIDTH_M, "points_monza.txt")


def _trace_imola_centerline():
    """Оцифровывает растровую схему Имолы (см. docstring модуля) в
    упорядоченный центральную линию (замкнутый список (x, y) в пикселях
    изображения)."""
    from PIL import Image
    from skimage.morphology import skeletonize
    from scipy import ndimage

    # Изображение RGBA с прозрачным (не белым!) фоном - альфа=0 у фона имеет
    # RGB=(0,0,0), то есть наивный .convert("L") без композитинга красил бы
    # ВЕСЬ прозрачный фон в чёрный, неотличимо от самой линии трассы (так и
    # произошло при первой попытке - "главный компонент" вышел размером
    # 462467px, ~92% всей картинки). Сначала альфа-композитинг на белый фон.
    img = Image.open(_project_root_path(IMOLA_IMAGE)).convert("RGBA")
    white_bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(white_bg, img).convert("L")
    arr = np.array(composited)
    # Чёрная линия на белом фоне - порог по яркости (не пытаемся отличить
    # линию трассы от подписей/кружков поворотов здесь, это следующий шаг).
    binary = arr < 128

    # Шашечный флаг старт-финиша (значок у "Variante Bassa") нарисован
    # ПРЯМО НА линии трассы, перпендикулярно ей - в отличие от кружков-номеров
    # поворотов и подписей (не касаются линии, отсеиваются ниже как отдельные
    # компоненты связности), этот значок сливается с линией в ОДИН компонент
    # и, будучи сплошным, а не тонкой линией, ломает скелетизацию (толстый
    # блок пикселей вместо простой петли). Точные координаты (в пикселях
    # этого конкретного файла, подобраны визуально) - см. отчёт: закрашиваем
    # белым ДО поиска компонент, чтобы под ним осталась только сама линия
    # трассы (флаг её не замещает, просто перпендикулярно пересекает).
    binary[422:478, 222:243] = False

    # Кружки-номера поворотов, буквы подписей и стрелка компаса - отдельные
    # (не соединённые с основной линией трассы) компоненты связности после
    # бинаризации; сама трасса - ОДНА длинная замкнутая линия, т.е. заведомо
    # самый большой по числу пикселей компонент. Оставляем только его.
    labels, n = ndimage.label(binary, structure=np.ones((3, 3)))
    sizes = ndimage.sum(binary, labels, range(1, n + 1))
    main_label = 1 + int(np.argmax(sizes))
    track_mask = labels == main_label

    # Линия трассы на этой картинке нарисована ДВОЙНОЙ (два очень близких
    # параллельных контура, на глаз - обводка полотна с обеих сторон, а не
    # одна центральная линия) - "голая" skeletonize() двух почти-параллельных
    # линий даёт не простую петлю, а "лестницу" (мелкие прямоугольные циклы
    # между двумя контурами в местах, где skeletonize их случайно не до конца
    # слил) - обрезка тупиков (см. ниже) такое не лечит, у цикла нет тупиков.
    # Замыкание (dilate+erode, "closing") на 5 итераций сливает узкий зазор
    # между двумя контурами в одну сплошную полосу ДО скелетизации - тогда
    # skeleton проходит по её середине, что и есть нужная центральная линия.
    track_mask = ndimage.binary_closing(track_mask, structure=np.ones((3, 3)), iterations=5)
    labels, n = ndimage.label(track_mask, structure=np.ones((3, 3)))
    sizes = ndimage.sum(track_mask, labels, range(1, n + 1))
    main_label = 1 + int(np.argmax(sizes))
    track_mask = labels == main_label

    skeleton = skeletonize(track_mask)
    ys, xs = np.nonzero(skeleton)
    skel_points = set(zip(xs.tolist(), ys.tolist()))

    def _neighbors_of(p, points):
        x, y = p
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                q = (x + dx, y + dy)
                if q in points:
                    yield q

    # Скелет замкнутой петли теоретически состоит только из точек степени 2
    # (ровно 2 соседа), но реальная толстая линия схемы (~4-5px) даёт мелкие
    # "шипы"-ветки при скелетизации (в основном там, где чёрная линия трассы
    # пересекается с шашечным паттерном старт-финиша, реже - шум толщины) -
    # это короткие тупиковые отростки, НЕ отдельные маршруты. Итеративно
    # срезаем тупики (точки степени 1) - у чистого цикла тупиков нет вообще,
    # поэтому обрезка останавливается сама, как только все шипы съедены,
    # не трогая сам цикл.
    for _ in range(100):
        degree = {p: sum(1 for _ in _neighbors_of(p, skel_points)) for p in skel_points}
        dead_ends = [p for p, d in degree.items() if d <= 1]
        if not dead_ends:
            break
        skel_points -= set(dead_ends)

    # Трассировка скелета в порядок обхода: скелет замкнутой петли - это
    # (почти) простой цикл из точек с ровно 2 соседями каждая (8-связность);
    # в изломах/пересечениях подписей возможны редкие точки с 1 или 3+
    # соседями - идём greedy по ближайшему ещё не посещённому соседу, этого
    # достаточно для гладкой петли без веток (главный компонент, см. выше,
    # уже отфильтрован от посторонних веток обводки букв/кружков).
    def neighbors(p):
        return _neighbors_of(p, skel_points)

    start = next(iter(skel_points))
    ordered = [start]
    visited = {start}
    current = start
    while True:
        candidates = [p for p in neighbors(current) if p not in visited]
        if not candidates:
            break
        nxt = min(candidates, key=lambda p: (p[0] - current[0]) ** 2 + (p[1] - current[1]) ** 2)
        ordered.append(nxt)
        visited.add(nxt)
        current = nxt

    if len(visited) < len(skel_points) * 0.9:
        raise RuntimeError(
            f"Трассировка скелета Имолы прервалась рано ({len(visited)}/{len(skel_points)} точек) - "
            "вероятно, скелет не является простой петлёй (лишние ветки от подписей не отфильтровались)")

    return np.array(ordered, dtype=float)


def build_imola():
    raw = _trace_imola_centerline()
    n = len(raw)
    idx = np.linspace(0, n, N_POINTS, endpoint=False).astype(int)
    centerline = raw[idx]
    # Изображение - Y растёт ВНИЗ (как и игровые координаты) - никакой
    # инверсии оси не требуется, в отличие от типичных SVG-курсов рисования.
    return build_from_centerline(centerline, IMOLA_REAL_LENGTH_M, IMOLA_WIDTH_M, "points_imola.txt")


if __name__ == "__main__":
    build_monza()
    build_imola()
