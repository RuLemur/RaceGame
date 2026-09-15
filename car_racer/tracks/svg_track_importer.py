"""
Оцифровка реальной схемы трассы из SVG в формат, который понимает
`car_racer.file_manager.file_worker.parse_track`.

Источник: векторная схема реальной картинг-трассы (SVG, `viewBox="0 0 1437.8
766.9"`). Известные реальные параметры (даны пользователем, не выводятся из
файла): длина трассы 1250 м, ширина полотна 9-12 м, покрытие асфальт.

## Метод извлечения геометрии

Прямой парсинг векторных `<path>` через `svgpathtools` (pure Python, не
требует cairo/GTK, что важно на Windows) — растеризация не понадобилась.
В файле всего 13 `<path>`, а не "лес" декоративных мелких путей; слой с
классом `.st7` (`fill: #cadbe6`, светлый асфальт — см. заметку пользователя)
встречается дважды, и ровно один из них состоит из 2 замкнутых подпутей —
обычный признак "кольца с дыркой" (донат через nonzero fill-rule), то есть
полотна трассы: внешняя граница + внутренняя граница-дырка. Второй `.st7`
путь — одиночный сплошной контур (декоративное пятно фона, не полотно) и
отброшен. Красный путь `.st6` (1386 подпутей, ~86 тыс. символов в `d`) — это
не центральная линия, а пунктирная разметка/поребрик, собранный как сотни
отдельных прямоугольников-штрихов; для геометрии полотна не нужен.

Из выбранного пути извлекаются два подпути; тот, что охватывает большую
площадь (формула площади многоугольника, shoelace) — внешняя граница, второй
— внутренняя (дырка). Оба подпути дискретизируются с мелким шагом по длине
дуги (`Path.ilength`/`Path.point` из svgpathtools).

## Соответствие точек outer[i] <-> inner[i]

Внешняя граница пересэмплируется равномерно по длине дуги до `N_POINTS`
точек. Для каждой такой точки методом ближайшей точки (перебор по всем точкам
мелкой дискретизации внутренней границы) находится соответствующая точка на
внутренней границе. Проверено отдельно (см. отчёт агента, здесь не
пересчитывается): получившаяся последовательность внутренних индексов
монотонна (движется в одном направлении с редким дребезгом в 1-2 точки,
максимум 21 из ~1900 — нормальный шум в тесных углах), то есть пары
действительно идут "поперёк" полотна, а не скачут хаотично. Обе границы на
этом этапе остаются буквально частями настоящих контуров SVG (просто
пересэмплированными), поэтому сохраняют исходную топологию (не
самопересекаются).

## Калибровка масштаба

Длина не берётся из SVG "на глаз" — считается длина центральной линии
(среднее между outer[i] и соответствующим inner[i], слегка сглаженное) в
SVG-единицах, затем `метров_на_svg_единицу = 1250 / длина_в_svg_единицах`
(~0.222 м/единица). Проверка на здравый смысл: подставив этот коэффициент в
ширину полотна, измеренную из тех же путей (37.5-50.7 SVG-единиц), получаем
реальную ширину ~8.3-11.2 м — совпадает с заявленными пользователем 9-12 м,
хотя ширина в самой калибровке не участвовала (она пришла только из длины
1250 м). Это независимое подтверждение, что найденный `.st7` путь — это
действительно полотно, а не что-то ещё.

## Масштаб — теперь напрямую из PX_PER_METER, а не из целевого bbox экрана

`draw_scale` (множитель SVG-единица -> игровой px) раньше подбирался так,
чтобы bounding box поместился в целевой размер экрана (`TARGET_BBOX_PX`,
~1650x850) — это было НЕ калибровкой, а просто "влезть в окно", единственная
причина была в том, что `PhyCar.check_collision_with_track` сравнивал позицию
машины с `screen.screen_width/screen.screen_height` (2000x1200), и трасса
крупнее этого окна ложно считалась бы выездом за пределы.

Эта причина больше не существует — граница выхода за пределы трассы теперь
считается из bounding box САМОЙ трассы (`Screen.world_bounds`, см.
`car_racer/screen/screen.py` и CLAUDE.md), а не из фиксированного размера
окна рендера, так что trace может быть сколь угодно больше рендер-канваса
(~2000x1200, не меняется) — `Camera` (пан+зум) показывает произвольно
большой мир на канвасе фиксированного размера ровно для этого.

Поэтому масштаб теперь считается ПРАВИЛЬНО, а не "чтобы влезло": напрямую из
единственной реальной калибровки px->метры в проекте, `PX_PER_METER`
(`car_racer/constants.py`, привязана к спрайту тренировочной машины) —
`draw_scale` подбирается так, чтобы `meters_per_unit * draw_scale ==
PX_PER_METER`, т.е. 1 реальный метр этой трассы = ровно столько же px, сколько
у любой другой трассы в игре. При реальной длине трассы 1250 м и
PX_PER_METER=20 это даёт ~25000px по центральной линии — заметно больше, чем
раньше, и ЭТО ОЖИДАЕМО (весь смысл задачи была в этом), а не повод уменьшать
масштаб обратно.

## Уширение полотна (не связано с масштабом выше)

Реальная форма трассы включает техничную секцию слева — несколько тугих
поворотов подряд ("шпилька"). Радиус кривизны там (по факту, а не на
глаз) — около 26-36 SVG-единиц на внешней границе и 27-34 на внутренней
(т.е. считанные метры в реальности). Если бы ширину полотна задавали
привычным для `track_builder.build_track` способом — офсетом
ФИКСИРОВАННОЙ полуширины от синтетической центральной линии, — на этой
шпильке почти наверняка получилось бы самопересечение (обычная ширина в
track_builder — 140 px, это намного больше самого узкого радиуса
поворота этой трассы).

Поэтому вместо этого используется двухшаговая схема:
   - Обе границы сначала масштабируются напрямую (см. выше) — это сохраняет
     подлинную, гарантированно непересекающуюся форму и подлинное
     (изменяющееся) соотношение ширины по всей трассе.
   - Затем к ним добавляется ДОПОЛНИТЕЛЬНОЕ уширение (`_extra_half_width`) —
     каждая точка внешней/внутренней границы сдвигается ещё немного наружу/
     внутрь вдоль направления "центр полотна -> эта точка", а не вдоль
     касательной к границе (это устраняет неоднозначность знака нормали и
     совпадает с интуитивным "раздвинуть трассу поперёк"). Величина сдвига
     не берётся "с потолка": для каждой границы отдельно считается локальный
     радиус кривизны (после лёгкого сглаживания, чтобы не словить шум
     оцифровки) и берётся `0.5 * min(радиус)` — с запасом вдвое от
     теоретического порога самопересечения. Итоговая проверка на
     самопересечение (полный перебор рёбер) выполняется по факту после
     сдвига — если бы она сработала, дальнейшая генерация трассы
     остановилась бы с исключением.

   Из-за этого итоговая игровая ширина полотна (~75-90 px, см. вывод скрипта)
   заметно меньше "стандартных" 130-140 px в `points_oval.txt`/
   `points_stadium_chicane.txt` — это осознанный компромисс в пользу точной
   формы шпильки, а не недосмотр. Подробнее — в отчёте агента.

## Использование

    python -m car_racer.tracks.svg_track_importer

Создаёт `car_racer/tracks/points_xti_winter.txt`. Требует пакет
`svgpathtools` (добавлен в requirements.txt/pyproject.toml специально ради
этого скрипта — используется только при импорте трассы, в игровом рантайме
не участвует).
"""
import math
import xml.etree.ElementTree as ET

import numpy as np
from svgpathtools import parse_path

from car_racer.constants import PX_PER_METER
from car_racer.file_manager.file_worker import POINTS_DIR
from car_racer.tracks.track_builder import save_track_file, fit_to_screen

SVG_FILE = "X-Ti_track_winter_LE.svg"
REAL_LENGTH_M = 1250.0        # реальная длина трассы, дана пользователем
N_POINTS = 300                # точек во внешней границе (и, соответственно, во внутренней)
# Шаг чекпоинтов вдоль центральной линии, px (после масштабирования). Раньше
# был 300 (22 чекпоинта на круг) - на прямых достаточно, но на тесной
# "шпильке" слева разрыв между двумя такими чекпоинтами оказался БОЛЬШЕ, чем
# порог MAX_CHECKPOINT_GAP в file_worker.parse_track, и автоматическое
# "уплотнение" там (линейная интерполяция между двумя соседними чекпоинтами)
# резало напрямую через несколько витков спирали по диагонали - геометрически
# бессмысленные чекпоинты, не поперёк полотна. Здесь, в отличие от
# file_worker, есть настоящее соответствие outer[i]/inner[i] по всей трассе
# (см. build_correspondence), поэтому правильный способ - просто чаще брать
# пары из НЕГО (следует подлинной форме шпильки), а не интерполировать потом.
# 150 даёт ~44 чекпоинта и разрыв везде меньше порога уплотнения - оно
# перестаёт срабатывать на этой трассе вовсе.
CHECKPOINT_SPACING_PX = 150.0
CURVATURE_SAFETY_FACTOR = 0.5  # доп. уширение <= этой доли минимального локального радиуса кривизны
SMOOTH_WINDOW = 7              # окно сглаживания (используется только для оценок длины/кривизны)
STRAIGHT_PERCENTILE = 75       # см. _find_longest_straight_index


def _svg_namespace_paths(svg_path):
    ns = {"svg": "http://www.w3.org/2000/svg"}
    tree = ET.parse(svg_path)
    root = tree.getroot()
    return root.findall(".//svg:path", ns)


def _discretize(subpath, step=3.0):
    """Дискретизирует один непрерывный подпуть svgpathtools равномерно по длине дуги."""
    total_len = subpath.length()
    n = max(50, int(total_len / step))
    pts = np.zeros((n, 2))
    for i, frac in enumerate(np.linspace(0, 1, n, endpoint=False)):
        t = subpath.ilength(frac * total_len, s_tol=1e-3)
        p = subpath.point(t)
        pts[i] = (p.real, p.imag)
    return pts, total_len


def _shoelace_area(pts):
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)


def _resample_closed(pts, n):
    """Равномерная передискретизация замкнутой ломаной по длине дуги до n точек."""
    seg = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    targets = np.linspace(0, total, n, endpoint=False)
    out = np.zeros((n, 2))
    m = len(pts)
    j = 0
    for i, t in enumerate(targets):
        while j < m - 1 and cum[j + 1] < t:
            j += 1
        t0 = cum[j]
        t1 = cum[j + 1] if j + 1 < len(cum) else total
        p0, p1 = pts[j], pts[(j + 1) % m]
        frac = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
        out[i] = p0 + frac * (p1 - p0)
    return out


def _smooth_closed(pts, window=SMOOTH_WINDOW):
    n = len(pts)
    k = window // 2
    out = np.zeros_like(pts)
    for i in range(n):
        idxs = [(i + o) % n for o in range(-k, k + 1)]
        out[i] = pts[idxs].mean(axis=0)
    return out


def _closed_length(pts):
    return float(np.sum(np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)))


def _nearest_indices(a, b):
    """Для каждой точки в a - индекс ближайшей точки в b (полный перебор, векторизовано)."""
    d2 = ((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2)
    idx = np.argmin(d2, axis=1)
    return idx, np.sqrt(d2[np.arange(len(a)), idx])


def _radius_of_curvature(pts):
    """Локальный радиус окружности, проведённой через 3 соседние точки замкнутой
    ломаной, в каждой вершине (стандартная оценка радиуса кривизны дискретной кривой)."""
    n = len(pts)
    R = np.full(n, np.inf)
    for i in range(n):
        p0, p1, p2 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        a = np.linalg.norm(p1 - p0)
        b = np.linalg.norm(p2 - p1)
        c = np.linalg.norm(p2 - p0)
        area2 = abs((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1]))
        if area2 > 1e-9:
            R[i] = (a * b * c) / (2 * area2)
    return R


def _segments_intersect(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)


def count_self_intersections(poly):
    """Полный перебор непересекающихся (не смежных) рёбер замкнутого многоугольника.
    O(n^2), но n ~ пара сотен точек и вызывается один раз при импорте - не в игровом цикле."""
    n = len(poly)
    count = 0
    for i in range(n):
        a1, a2 = poly[i], poly[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            b1, b2 = poly[j], poly[(j + 1) % n]
            if _segments_intersect(a1, a2, b1, b2):
                count += 1
    return count


def extract_track_boundaries(svg_path=SVG_FILE):
    """Находит путь-полотно (.st7, 2 замкнутых подпути) и возвращает (outer_raw,
    inner_raw) - мелкую дискретизацию исходных SVG-контуров в SVG-единицах."""
    paths = _svg_namespace_paths(svg_path)
    target = None
    for p in paths:
        if p.get("class") == "st7":
            subs = parse_path(p.get("d")).continuous_subpaths()
            if len(subs) == 2:
                target = subs
                break
    if target is None:
        raise RuntimeError(
            "Не найден путь класса .st7 с 2 замкнутыми подпутями (ожидалось полотно трассы). "
            "Структура SVG могла измениться - см. docstring модуля."
        )

    pts_list = []
    for s in target:
        pts, _ = _discretize(s, step=3.0)
        pts_list.append(pts)

    areas = [abs(_shoelace_area(p)) for p in pts_list]
    outer_i = 0 if areas[0] > areas[1] else 1
    inner_i = 1 - outer_i
    return pts_list[outer_i], pts_list[inner_i]


def build_correspondence(outer_raw, inner_raw, n_points=N_POINTS):
    """Пересэмплирует outer_raw до n_points точек и находит соответствующие точки
    на inner_raw методом ближайшей точки. Возвращает (outer, inner_matched, dist)
    - первые два длиной n_points, в SVG-единицах, с поточечным соответствием
    поперёк полотна; dist - соответствующая ширина полотна в SVG-единицах."""
    outer = _resample_closed(outer_raw, n_points)
    idx, dist = _nearest_indices(outer, inner_raw)
    inner_matched = inner_raw[idx]
    return outer, inner_matched, dist


def calibrate_meters_per_unit(outer, inner_matched, real_length_m=REAL_LENGTH_M):
    centerline = (outer + inner_matched) / 2.0
    cl = _smooth_closed(_resample_closed(centerline, len(centerline)))
    length_svg = _closed_length(cl)
    return real_length_m / length_svg, length_svg


def widen_boundaries(outer, inner, safety_factor=CURVATURE_SAFETY_FACTOR):
    """Дополнительно раздвигает outer/inner поперёк полотна (наружу/внутрь
    соответственно) вдоль направления "центр полотна -> точка границы", на
    величину, безопасную относительно локального радиуса кривизны каждой из
    границ (см. docstring модуля). Возвращает (outer_wide, inner_wide,
    extra_half_width)."""
    centerline = (outer + inner) / 2.0
    dir_out = outer - centerline
    dir_out /= np.linalg.norm(dir_out, axis=1, keepdims=True)
    dir_in = inner - centerline
    dir_in /= np.linalg.norm(dir_in, axis=1, keepdims=True)

    r_outer = _radius_of_curvature(_smooth_closed(outer, 5))
    r_inner = _radius_of_curvature(_smooth_closed(inner, 5))
    extra = safety_factor * min(r_outer.min(), r_inner.min())

    outer_wide = outer + dir_out * extra
    inner_wide = inner + dir_in * extra
    return outer_wide, inner_wide, extra


def _find_longest_straight_index(outer, inner, percentile=STRAIGHT_PERCENTILE):
    """Индекс СЕРЕДИНЫ самого длинного непрерывного "прямого" участка
    центральной линии (топ-перцентиль локального радиуса кривизны, см.
    _radius_of_curvature) - по нему потом ротируются outer/inner (см.
    import_track), чтобы старт-финиш оказался на самой длинной прямой, а не
    там, где случайно начинается путь в исходном SVG (было - на короткой
    прямой у одной из связок поворотов, что и попросили сместить)."""
    centerline = (outer + inner) / 2.0
    n = len(centerline)
    radius = _radius_of_curvature(_smooth_closed(centerline, SMOOTH_WINDOW))
    threshold = np.percentile(radius[np.isfinite(radius)], percentile)
    is_straight = np.concatenate([radius > threshold, radius > threshold])

    best_start, best_len, cur_start, cur_len = 0, 0, None, 0
    for idx in range(2 * n):
        if is_straight[idx]:
            if cur_start is None:
                cur_start = idx
            cur_len += 1
            if cur_len > best_len and cur_len <= n:
                best_start, best_len = cur_start, cur_len
        else:
            cur_start, cur_len = None, 0

    return (best_start + best_len // 2) % n


def build_checkpoints(outer, inner, spacing_px):
    """Чекпоинты - пары (outer[i], inner[i]) через равные промежутки по длине
    центральной линии, по аналогии с track_builder.build_track. Индекс 0
    зарезервирован под линию старта и в чекпоинты не попадает."""
    centerline = (outer + inner) / 2.0
    checkpoints = []
    dist_since_last = 0.0
    n = len(centerline)
    for i in range(1, n):
        dist_since_last += math.dist(centerline[i - 1], centerline[i])
        if dist_since_last >= spacing_px:
            checkpoints.append((tuple(outer[i]), tuple(inner[i])))
            dist_since_last = 0.0
    return checkpoints


def import_track(svg_path=SVG_FILE, out_filename="points_xti_winter.txt", verbose=True):
    outer_raw, inner_raw = extract_track_boundaries(svg_path)
    outer_svg, inner_svg, width_dist = build_correspondence(outer_raw, inner_raw, N_POINTS)

    # Ротируем оба массива так, чтобы индекс 0 (= будущая линия старта, см.
    # ниже) оказался на самой длинной прямой трассы, а не там, где случайно
    # начинается путь в исходном SVG-контуре - индекс/соответствие
    # outer<->inner при этом не меняется, np.roll по обоим на одну величину.
    start_idx = _find_longest_straight_index(outer_svg, inner_svg)
    outer_svg = np.roll(outer_svg, -start_idx, axis=0)
    inner_svg = np.roll(inner_svg, -start_idx, axis=0)
    width_dist = np.roll(width_dist, -start_idx, axis=0)

    meters_per_unit, centerline_len_svg = calibrate_meters_per_unit(outer_svg, inner_svg)

    # draw_scale выбран так, чтобы meters_per_unit * draw_scale == PX_PER_METER
    # - т.е. 1 реальный метр этой трассы превращается ровно в PX_PER_METER
    # игровых px, как и у любой другой трассы (см. docstring модуля выше про
    # то, почему раньше это было "подгонкой под экран", а не калибровкой).
    draw_scale = PX_PER_METER * meters_per_unit

    outer_px = outer_svg * draw_scale
    inner_px = inner_svg * draw_scale

    outer_px, inner_px, extra_half_width = widen_boundaries(outer_px, inner_px)

    n_outer_x = count_self_intersections(outer_px)
    n_inner_x = count_self_intersections(inner_px)
    if n_outer_x or n_inner_x:
        raise RuntimeError(
            f"Самопересечение после уширения границ (outer={n_outer_x}, inner={n_inner_x}) - "
            f"уменьши CURVATURE_SAFETY_FACTOR (сейчас {CURVATURE_SAFETY_FACTOR}) и повтори."
        )

    checkpoints = build_checkpoints(outer_px, inner_px, CHECKPOINT_SPACING_PX)
    start_line = (tuple(outer_px[0]), tuple(inner_px[0]))

    outer_list = [tuple(p) for p in outer_px]
    inner_list = [tuple(p) for p in inner_px]
    outer_list, inner_list, checkpoints, start_line = fit_to_screen(
        outer_list, inner_list, checkpoints, start_line, margin=100.0
    )

    if verbose:
        real_len = centerline_len_svg * meters_per_unit
        real_w_min = width_dist.min() * meters_per_unit
        real_w_max = width_dist.max() * meters_per_unit
        width_px = width_dist * draw_scale + 2 * extra_half_width
        xs = [p[0] for p in outer_list]
        ys = [p[1] for p in outer_list]
        print(f"Калибровка: {meters_per_unit:.4f} м/SVG-единица "
              f"(центральная линия {centerline_len_svg:.0f} SVG-ед. -> {real_len:.0f} м, цель 1250 м)")
        print(f"Реальная ширина полотна (из геометрии, для проверки): "
              f"{real_w_min:.1f}-{real_w_max:.1f} м (ожидалось 9-12 м)")
        print(f"DRAW_SCALE = {draw_scale:.3f}, доп. уширение (безопасно по кривизне) = "
              f"{extra_half_width:.1f} px на сторону")
        print(f"Игровая ширина полотна: {width_px.min():.0f}-{width_px.max():.0f} px "
              f"(среднее {width_px.mean():.0f} px)")
        print(f"Точек outer/inner: {len(outer_list)}, чекпоинтов: {len(checkpoints)}")
        print(f"Bounding box (после fit_to_screen, margin=100): "
              f"{max(xs) - min(xs):.0f} x {max(ys) - min(ys):.0f} px - намного больше "
              f"рендер-канваса 2000x1200 (screen.py), ЭТО ОЖИДАЕМО: Screen.world_bounds "
              f"считается из bbox самой трассы (не привязан к 2000x1200), а Camera "
              f"(пан+зум) показывает произвольно большой мир на канвасе фикс. размера.")
        print(f"Самопересечений после уширения: outer={n_outer_x}, inner={n_inner_x} (должно быть 0)")

    return save_track_file(out_filename, outer_list, inner_list, checkpoints, start_line, directory=POINTS_DIR)


if __name__ == "__main__":
    import_track()
