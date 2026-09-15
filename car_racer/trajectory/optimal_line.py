"""
car_racer.trajectory.optimal_line
==================================

Классический (НЕ через обучение/NEAT) расчёт "идеальной" гоночной траектории
для трассы — используется как эталон/потолок производительности, с которым
позже можно сравнивать то, чему научится NEAT-агент через сенсоры. Ничего
здесь не трогает `car_racer/cars/*.py` и не участвует в самом обучении —
это отдельный офлайн-инструмент, который считает JSON один раз и кладёт его
рядом с файлом трассы; `car_racer/screen/screen.py::_load_ideal_line()` уже
умеет подхватывать и рисовать результат (см. `IDEAL_LINE_COLOR` там же).

Алгоритм состоит из трёх стандартных для автоспорта шагов:

1. **Извлечение "ворот" поперёк трассы** (`extract_gates`) — каждая "ворота"
   это пара точек (outer, inner), гоночная линия параметризуется одним
   числом `t в [0, 1]` на каждые ворота (0 = у внешней границы, 1 = у
   внутренней).

   Есть два пути:

   - **Индексное соответствие** (`_extract_gates_indexed`) — если
     `len(track_outer) == len(track_inner)`, ворота это просто
     `zip(track_outer, track_inner)`. Это точный и надёжный случай для
     треков, сгенерированных `car_racer/tracks/track_builder.py`
     (`points_oval.txt`, `points_stadium_chicane.txt`) — там обе границы
     получены смещением (`offset_polyline`) одной и той же центральной линии
     в разные стороны на одинаковое число точек, так что `outer[i]`/`inner[i]`
     всегда лежат на одном перпендикуляре к центральной линии.

   - **Общий (geometric) случай** (`_extract_gates_general`) — используется
     как fallback, когда длины границ не совпадают (треки, нарисованные
     мышью через `helpers/draw_track.py`: `points.txt`, `points_reserve.txt`,
     `points_reserve2.txt` — у них outer/inner нарисованы независимо и НЕ
     соответствуют друг другу по индексу). Алгоритм: внешнюю границу
     передискретизируют на `num_gates` точек с равным шагом по длине дуги,
     в каждой точке считают локальную касательную (по соседним точкам) и
     бросают перпендикулярный луч в обе стороны до пересечения с внутренней
     границей (векторизованное numpy-пересечение луча с ломаной, тот же
     принцип, что и `helpers.calculate.cast_ray`, но переиспользовать сам
     `cast_ray` неудобно из-за его API в градусах/экранных координатах —
     здесь используется локальный аналог на векторах). Это OK-эвристика для
     не самопересекающихся трасс разумной формы, но не гарантирована для
     произвольных нарисованных мышью контуров (острые изломы, места, где
     трасса "складывается" сама на себя, узкие шпильки и т.п.) — это
     ограничение v1, не баг. На практике при отсутствии пересечения ворота
     просто пропускаются.

2. **Собственно траектория** (`compute_racing_line`) — итеративная
   geometric-релаксация, минимизирующая кривизну ломаной: на каждой
   итерации для каждых ворот текущая точка линии сдвигается на небольшой шаг
   в сторону середины отрезка между соседними (уже актуальными — это
   Gauss-Seidel, не Jacobi, сходится быстрее) точками линии — это и есть
   локальное "выпрямление" траектории, классический некалиброванный (не
   через QP/выпуклую оптимизацию) подход к racing line, которого достаточно
   для v1. После сдвига точка проецируется обратно на отрезок ворот
   (outer->inner) и обрезается в `[margin, 1-margin]`, чтобы линия не
   вылезала физически за пределы трассы (небольшой отступ `margin` от стен
   — гонщики тоже не едут впритык к бордюру).

3. **Профиль скорости и время круга** (`compute_speed_profile`,
   `estimate_lap_time`) — машина моделируется материальной точкой с "кругом
   трения": максимальное ЛАТЕРАЛЬНОЕ ускорение ограничивает скорость в
   повороте по формуле `v_max = sqrt(a_lat_max / curvature)` (кривизна —
   через дискретную формулу Менгера по трём соседним точкам, `4*Area/(abc)`).
   Считается по СГЛАЖЕННОЙ копии точек линии (`_smooth_closed_points`,
   `_smoothing_window`), не по самой линии — формула Менгера очень
   чувствительна к мелкому дребезгу после релаксации (см. п.2), который
   иначе давал кривизну в разы выше настоящей и заниженное время круга
   (см. `compute_optimal_line`).
   Отдельно есть предел скорости по прямой (`MAX_SPEED_PX_S`) и раздельные
   пределы разгона/торможения. Скорость в каждой точке — это минимум трёх
   ограничений, посчитанный через forward-pass (ограничение по разгону от
   предыдущей точки, `v[i] <= sqrt(v[i-1]^2 + 2*a_accel*ds)`) и
   backward-pass (то же самое от следующей точки в обратном порядке —
   "тормозить нужно заранее"), взятый как поточечный минимум. Так как трасса
   — замкнутый контур, оба прохода гоняются несколько "кругов"
   (`SPEED_PASS_LAPS`) подряд, чтобы условие на стыке конец->начало круга
   сошлось (v в начале и в конце согласованы). Время круга — интеграл
   `ds / v_avg` по всем сегментам (средняя скорость на сегменте — среднее
   арифметическое скоростей по его концам, что чуть точнее, чем брать только
   скорость в начале сегмента).

Единицы измерения (важно!)
---------------------------
Координаты трассы в проекте — "игровые пиксели", в проекте нет и не было
калибровки px -> метры (см. CLAUDE.md). Здесь используются **px и px/с**
(не px/тик) для скорости и ускорений — по той же логике, что и уже
существующий `PhyCar` (`car_racer/cars/physic_car.py`): его
`pymunk.Body.velocity` тоже в px/с, потому что `pymunk.Space.step(1/TICK_RATE)`
с `TICK_RATE=30` физических шагов в секунду — то есть один шаг физики это
`1/30` секунды симулированного времени, а не "один тик = одна единица
времени". `estimated_lap_time` в итоговом JSON — в секундах.

Константы машины ниже (`MAX_SPEED_PX_S`, `MAX_LATERAL_ACCEL_PX_S2`,
`MAX_ACCEL_PX_S2`, `MAX_BRAKE_PX_S2`) подобраны "на глаз", чтобы быть того
же порядка величины, что уже существующие числа `PhyCar`, а не выдуманы из
воздуха:
  - `MAX_SPEED_PX_S = 400` — совпадает с `PhyCar.MAX_SPEED` (400, тоже px/с
    по построению pymunk), чтобы верхняя скорость на прямых была
    сопоставима с тем, что физически может ехать машина в игре.
  - `MAX_BRAKE_PX_S2 = 450` — выведено из `PhyCar`: `BRAKE_RATE = 15`
    px/тик * `TICK_RATE` (30 тиков/с) = 450 px/с^2 — торможение здесь того
    же порядка, что и явное `BRAKE_RATE` в физической машине.
  - `MAX_ACCEL_PX_S2 = 250` — разгон обычно медленнее торможения (типично и
    для настоящих гоночных машин, и с запасом меньше, чем `MAX_BRAKE_PX_S2`,
    чтобы профиль скорости не был "торможение = разгон", что визуально
    неправдоподобно).
  - `MAX_LATERAL_ACCEL_PX_S2 = 350` — того же порядка, что продольные
    ускорения (типичное отношение для "круга трения": боковое ускорение
    сопоставимо с продольным, не на порядок больше/меньше).

Это ЗАВЕДОМО не калибровка под реальный картинг/болид — абсолютное значение
`estimated_lap_time` условное число, а не физически точная секунда. Это
нормально и ожидаемо для v1: настоящая физика машины (`PhyCar`) в этой
задаче намеренно не трогается, калибровка px->метры — отдельная будущая
работа. Цель этого модуля — дать внутренне непротиворечивый (быстрее в
широких поворотах, медленнее в узких, быстрее по прямым) ориентир для
сравнения с NEAT-агентом, а не абсолютную истину.

CLI
---
    python -m car_racer.trajectory.optimal_line <имя_файла_трассы.txt>

Читает трассу через `car_racer.file_manager.file_worker.parse_track`, считает
траекторию и сохраняет `<имя_без_.txt>.ideal_line.json` рядом с файлом трассы
(`car_racer.file_manager.file_worker.POINTS_DIR`).
"""
import argparse
import json
import math
import os

import numpy as np

from car_racer.file_manager.file_worker import POINTS_DIR, parse_track

# --- Константы модели машины (px, px/с, px/с^2 — см. docstring выше) -------

MAX_SPEED_PX_S = 400.0          # предел скорости по прямой
MAX_LATERAL_ACCEL_PX_S2 = 350.0  # ограничивает скорость в повороте по кривизне
MAX_ACCEL_PX_S2 = 250.0          # разгон
MAX_BRAKE_PX_S2 = 450.0          # торможение


def vehicle_params_from_physic_car():
    """Пересчитывает константы модели машины выше из ТЕКУЩИХ настроек
    car_racer.cars.physic_car (сцепление/масса/мощность - настраиваются в
    UI-панели, см. car_racer/screen/ui_panel.py) вместо фиксированных
    дефолтов, подобранных "на глаз". Так "идеальное" время круга реально
    зависит от характеристик машины, а не только от формы трассы - иначе
    сравнение с результатом NEAT-агента (который эти настройки чувствует
    через физику) было бы нечестным.

    Не импортируется на уровне модуля (см. верх файла) - physic_car, в свою
    очередь, не импортирует car_racer.trajectory ни для чего, но лучше не
    создавать связь между "офлайн-математикой" и "живой физикой" сильнее,
    чем нужно: только этой одной функцией, вызываемой по требованию."""
    from car_racer.cars import physic_car
    from car_racer.constants import TICK_RATE

    max_speed = physic_car.MAX_SPEED
    # Круг трения PhyCar: одно общее сцепление на поворот И торможение
    # (a=μg не зависит от массы - см. комментарий в physic_car.py про
    # GRIP_ACCEL). Торможение дополнительно не может быть быстрее
    # фиксированного BRAKE_RATE самой машины (тормоза, а не только шины).
    max_lateral_accel = physic_car.GRIP_ACCEL
    max_brake = min(physic_car.GRIP_ACCEL, physic_car.BRAKE_RATE * TICK_RATE)

    # Разгон под тягой у PhyCar - экспоненциальный "подход" к целевой
    # скорости (ACCELERATION_RATE), а не константное ускорение - берём его
    # пиковое (при максимальном рассогласовании скоростей, т.е. с места)
    # значение, масштабированное текущими мощностью/массой, и заодно
    # ограничиваем тем же кругом сцепления - именно так ведёт себя реальная
    # машина в PhyCar (см. _apply_controls/_desired_speed).
    power_ratio = physic_car.ENGINE_POWER_HP / physic_car.REFERENCE_POWER_HP
    mass_ratio = physic_car.REFERENCE_MASS / physic_car.CAR_MASS
    peak_accel = max_speed * physic_car.ACCELERATION_RATE * TICK_RATE * power_ratio * mass_ratio
    max_accel = min(peak_accel, physic_car.GRIP_ACCEL)

    return {
        "max_speed": max_speed,
        "max_lateral_accel": max_lateral_accel,
        "max_accel": max_accel,
        "max_brake": max_brake,
    }

# --- Параметры алгоритма геометрической релаксации --------------------------

DEFAULT_NUM_GATES = 250      # число ворот для общего (не индексного) случая
RELAXATION_ITERATIONS = 600  # число проходов релаксации кривизны
RELAXATION_STEP = 0.4        # доля сдвига к середине соседей за одну итерацию
EDGE_MARGIN = 0.03           # отступ линии от стен трассы, доля ширины ворот
SPEED_PASS_LAPS = 3          # сколько раз прогонять forward/backward pass по
                              # замкнутому контуру, чтобы сошлось условие на
                              # стыке конец круга -> начало круга
CURVATURE_SMOOTH_FRACTION = 0.05  # см. _smoothing_window/_smooth_closed_points


# --- 1. Извлечение "ворот" --------------------------------------------------

def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _extract_gates_indexed(track_outer, track_inner):
    """Ворота = zip(outer, inner) по индексу — см. docstring модуля, случай
    треков из track_builder.py (offset_polyline от общей центральной линии)."""
    gates = [(tuple(o), tuple(i)) for o, i in zip(track_outer, track_inner)]

    # Трассы из track_builder.py замкнуты "почти в ту же точку" (последняя
    # точка центральной линии близко, но не идентична первой — см.
    # build_centerline), из-за чего ворота[0] и ворота[-1] могут оказаться
    # вырожденно близко друг к другу (намного ближе типичного шага между
    # соседними воротами). Если так — отбрасываем последние ворота-дубликат,
    # чтобы не получить на стыке круга почти нулевой сегмент.
    if len(gates) > 3:
        spacings = [_dist(gates[i][0], gates[i + 1][0]) for i in range(len(gates) - 1)]
        median_spacing = sorted(spacings)[len(spacings) // 2]
        closing_gap = _dist(gates[0][0], gates[-1][0])
        if median_spacing > 1e-6 and closing_gap < median_spacing * 0.5:
            gates = gates[:-1]
    return gates


def _closed_polyline_segments(points):
    """(seg_starts, seg_ends) numpy-массивы для замкнутой ломаной (с сегментом
    последняя точка -> первая точка), для векторизованного пересечения луча."""
    pts = np.asarray(points, dtype=float)
    starts = pts
    ends = np.roll(pts, -1, axis=0)
    return starts, ends


def _cast_ray_to_polyline(origin, direction, seg_starts, seg_ends, max_length):
    """Пересечение луча origin+t*direction (t>=0) с замкнутой ломаной
    (seg_starts/seg_ends из _closed_polyline_segments). Возвращает точку
    ближайшего пересечения или None. Тот же векторный принцип, что
    helpers.calculate.cast_ray, но без перевода в градусы/экранные оси —
    здесь удобнее работать напрямую с вектором нормали."""
    ox, oy = origin
    dx, dy = direction
    qpx = seg_starts[:, 0] - ox
    qpy = seg_starts[:, 1] - oy
    rsx = seg_ends[:, 0] - seg_starts[:, 0]
    rsy = seg_ends[:, 1] - seg_starts[:, 1]

    denom = dx * rsy - dy * rsx
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (qpx * rsy - qpy * rsx) / denom
        u = (qpx * dy - qpy * dx) / denom

    valid = (denom != 0) & (t >= 0) & (t <= max_length) & (u >= 0) & (u <= 1)
    if not np.any(valid):
        return None
    t_masked = np.where(valid, t, np.inf)
    idx = int(np.argmin(t_masked))
    dist = float(t_masked[idx])
    return ox + dx * dist, oy + dy * dist


def _resample_closed_polyline(points, n):
    """Передискретизирует замкнутую ломаную на n точек с равным шагом по длине
    дуги (нужно для общего алгоритма извлечения ворот, где точки исходной
    границы могут идти неравномерно)."""
    pts = np.asarray(points, dtype=float)
    closed = np.vstack([pts, pts[0]])
    seg_vecs = np.diff(closed, axis=0)
    seg_lens = np.hypot(seg_vecs[:, 0], seg_vecs[:, 1])
    cumulative = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total_length = cumulative[-1]
    if total_length < 1e-6:
        return pts[:n] if len(pts) >= n else pts

    targets = np.linspace(0.0, total_length, n, endpoint=False)
    result = np.empty((n, 2), dtype=float)
    seg_idx = 0
    for i, target in enumerate(targets):
        while seg_idx < len(seg_lens) - 1 and cumulative[seg_idx + 1] < target:
            seg_idx += 1
        seg_len = seg_lens[seg_idx]
        local_t = 0.0 if seg_len < 1e-9 else (target - cumulative[seg_idx]) / seg_len
        result[i] = closed[seg_idx] + local_t * seg_vecs[seg_idx]
    return result


def _extract_gates_general(track_outer, track_inner, num_gates=DEFAULT_NUM_GATES):
    """Общий алгоритм извлечения ворот для границ без индексного соответствия
    (например, треков, нарисованных мышью в helpers/draw_track.py) — см.
    docstring модуля. Передискретизирует внешнюю границу на num_gates точек
    и в каждой бросает перпендикулярный луч (в обе стороны) до пересечения
    с внутренней границей. Ворота, для которых пересечение не нашлось,
    пропускаются (например из-за острых изломов нарисованной мышью линии)."""
    resampled_outer = _resample_closed_polyline(track_outer, num_gates)
    inner_starts, inner_ends = _closed_polyline_segments(track_inner)

    outer_arr = np.asarray(track_outer, dtype=float)
    inner_arr = np.asarray(track_inner, dtype=float)
    bbox_pts = np.vstack([outer_arr, inner_arr])
    bbox_diag = float(np.hypot(*(bbox_pts.max(axis=0) - bbox_pts.min(axis=0))))
    max_length = max(bbox_diag, 1.0)

    n = len(resampled_outer)
    gates = []
    for i in range(n):
        prev_pt = resampled_outer[i - 1]
        next_pt = resampled_outer[(i + 1) % n]
        tangent = next_pt - prev_pt
        tangent_norm = float(np.hypot(*tangent))
        if tangent_norm < 1e-9:
            continue
        tangent = tangent / tangent_norm
        normal = np.array([-tangent[1], tangent[0]])

        origin = resampled_outer[i]
        hit_pos = _cast_ray_to_polyline(origin, normal, inner_starts, inner_ends, max_length)
        hit_neg = _cast_ray_to_polyline(origin, -normal, inner_starts, inner_ends, max_length)
        candidates = [h for h in (hit_pos, hit_neg) if h is not None]
        if not candidates:
            continue
        inner_pt = min(candidates, key=lambda h: _dist(h, origin))
        gates.append((tuple(origin), inner_pt))
    return gates


def extract_gates(track_outer, track_inner, num_gates=DEFAULT_NUM_GATES):
    """Извлекает список "ворот" (outer_point, inner_point) вдоль трассы.
    Индексное соответствие, если границы одной длины (см.
    _extract_gates_indexed), иначе общий geometric-алгоритм (см.
    _extract_gates_general)."""
    if len(track_outer) == len(track_inner):
        return _extract_gates_indexed(track_outer, track_inner)
    return _extract_gates_general(track_outer, track_inner, num_gates=num_gates)


# --- 2. Геометрическая релаксация (минимизация кривизны) --------------------

def compute_racing_line(gates, iterations=RELAXATION_ITERATIONS,
                         step=RELAXATION_STEP, margin=EDGE_MARGIN):
    """Возвращает (points, t): points — точки гоночной линии (по одной на
    ворота), t — параметр 0..1 (0=outer, 1=inner) каждой точки в её воротах.
    Итеративная Gauss-Seidel релаксация: каждая точка сдвигается к середине
    соседних точек (уменьшая локальную кривизну), с проекцией обратно на
    отрезок ворот и обрезкой в [margin, 1-margin]."""
    n = len(gates)
    if n < 4:
        raise ValueError(f"Слишком мало ворот для построения траектории: {n}")

    outer = np.array([g[0] for g in gates], dtype=float)
    inner = np.array([g[1] for g in gates], dtype=float)
    seg = inner - outer
    seg_len2 = np.einsum("ij,ij->i", seg, seg)

    t = np.full(n, 0.5, dtype=float)
    points = outer + t[:, None] * seg

    for _ in range(iterations):
        for i in range(n):
            prev_p = points[i - 1]
            next_p = points[(i + 1) % n]
            target = 0.5 * (prev_p + next_p)
            new_p = points[i] + step * (target - points[i])

            if seg_len2[i] < 1e-9:
                continue
            tt = float(np.dot(new_p - outer[i], seg[i]) / seg_len2[i])
            tt = min(max(tt, margin), 1.0 - margin)
            t[i] = tt
            points[i] = outer[i] + tt * seg[i]

    return points, t


# --- 3. Профиль скорости и время круга --------------------------------------

def compute_curvature(points):
    """Дискретная кривизна (формула Менгера через площадь треугольника) в
    каждой точке замкнутой ломаной points: curvature = 2*|cross(b-a,c-a)| /
    (|ab|*|bc|*|ca|). 0, если точки почти совпадают (вырожденный треугольник)."""
    n = len(points)
    curvature = np.zeros(n, dtype=float)
    for i in range(n):
        a = points[i - 1]
        b = points[i]
        c = points[(i + 1) % n]
        ab = _dist(a, b)
        bc = _dist(b, c)
        ca = _dist(c, a)
        if ab < 1e-6 or bc < 1e-6 or ca < 1e-6:
            continue
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        curvature[i] = 2.0 * abs(cross) / (ab * bc * ca)
    return curvature


def _smoothing_window(n, fraction=CURVATURE_SMOOTH_FRACTION):
    w = max(3, round(n * fraction))
    return w if w % 2 == 1 else w + 1


def _smooth_closed_points(points, window):
    """Скользящее усреднение точек по замкнутому контуру (окно `window`,
    нечётное) - см. compute_optimal_line про то, зачем это нужно ИМЕННО для
    оценки кривизны, а не для самой гоночной линии."""
    n = len(points)
    k = window // 2
    offsets = np.arange(-k, k + 1)
    return np.array([points[(i + offsets) % n].mean(axis=0) for i in range(n)])


def compute_speed_profile(points, curvature,
                           max_speed=MAX_SPEED_PX_S,
                           max_lateral_accel=MAX_LATERAL_ACCEL_PX_S2,
                           max_accel=MAX_ACCEL_PX_S2,
                           max_brake=MAX_BRAKE_PX_S2,
                           pass_laps=SPEED_PASS_LAPS):
    """Возвращает (v, seg_len): v — достижимая скорость (px/с) в каждой точке,
    seg_len[i] — длина сегмента от points[i] до points[i+1] (по кругу).
    "Круг трения": v ограничена по кривизне (v_max_curv), затем ограничена
    сверху разгоном (forward pass) и торможением (backward pass), несколько
    "кругов" подряд для сходимости на замкнутом контуре."""
    n = len(points)
    seg_len = np.array([_dist(points[i], points[(i + 1) % n]) for i in range(n)])

    with np.errstate(divide="ignore", invalid="ignore"):
        v_curv = np.sqrt(max_lateral_accel / np.maximum(curvature, 1e-12))
    v_curv = np.minimum(v_curv, max_speed)
    v_curv = np.where(curvature < 1e-9, max_speed, v_curv)

    v = v_curv.copy()

    # forward pass — ограничение по разгону от предыдущей точки
    for _ in range(pass_laps):
        for i in range(n):
            prev_i = i - 1
            v_allowed = math.sqrt(v[prev_i] ** 2 + 2.0 * max_accel * seg_len[prev_i])
            if v_allowed < v[i]:
                v[i] = v_allowed

    # backward pass — ограничение по торможению перед следующей точкой
    for _ in range(pass_laps):
        for i in range(n - 1, -1, -1):
            next_i = (i + 1) % n
            v_allowed = math.sqrt(v[next_i] ** 2 + 2.0 * max_brake * seg_len[i])
            if v_allowed < v[i]:
                v[i] = v_allowed

    return v, seg_len


def estimate_lap_time(v, seg_len):
    """Время круга (с) = сумма ds/v_avg по всем сегментам, где v_avg —
    среднее скоростей на концах сегмента (чуть точнее трапецией, чем
    брать скорость только в начале сегмента)."""
    n = len(v)
    total_time = 0.0
    for i in range(n):
        next_i = (i + 1) % n
        v_avg = 0.5 * (v[i] + v[next_i])
        if v_avg < 1e-6:
            continue
        total_time += seg_len[i] / v_avg
    return total_time


# --- Пайплайн + сохранение/CLI ----------------------------------------------

def compute_optimal_line(track_outer, track_inner, num_gates=DEFAULT_NUM_GATES, vehicle_params=None):
    """Полный пайплайн: ворота -> геометрическая траектория -> профиль
    скорости -> время круга. Возвращает dict с points/speeds/lap_time/gates_t
    (gates_t — параметр t каждой точки в её воротах, для самопроверки).

    `vehicle_params` - необязательный dict с ключами max_speed/max_lateral_accel/
    max_accel/max_brake (см. compute_speed_profile) - передай результат
    vehicle_params_from_physic_car(), чтобы время круга учитывало текущие
    настройки машины (сцепление/масса/мощность), а не дефолты модуля."""
    gates = extract_gates(track_outer, track_inner, num_gates=num_gates)
    points, t = compute_racing_line(gates)

    # Кривизну считаем по СГЛАЖЕННОЙ копии точек, а не по самой гоночной
    # линии - дискретная формула Менгера (compute_curvature) через три
    # соседние точки очень чувствительна к мелкому "дребезгу", который
    # остаётся после релаксации (сама по себе релаксация не гарантирует
    # гладкость, только уменьшает кривизну на каждом шаге - см.
    # compute_racing_line): дребезг, незаметный на глаз и не влияющий на
    # длину пути, давал оценку кривизны в разы выше настоящей, а значит и
    # заниженную v_curv по всей трассе. Так эталонное время круга на овале
    # получалось 7.99с - МЕДЛЕННЕЕ, чем непрерывная езда на максимальной
    # скорости по одной центральной линии (5.64с), что для гоночной линии
    # физически невозможно (она короче центральной и должна быть быстрее).
    # result["points"] (сама линия, для отображения и self_check ниже)
    # остаётся НЕТРОНУТОЙ - усреднять эти точки напрямую нельзя: соседи лежат
    # на РАЗНЫХ, по-разному повёрнутых воротах, и усреднение увело бы точку с
    # отрезка её собственных ворот.
    smoothed = _smooth_closed_points(points, _smoothing_window(len(points)))
    curvature = compute_curvature(smoothed)
    v, seg_len = compute_speed_profile(points, curvature, **(vehicle_params or {}))
    lap_time = estimate_lap_time(v, seg_len)

    return {
        "points": [(float(p[0]), float(p[1])) for p in points],
        "speeds": [float(s) for s in v],
        "estimated_lap_time": float(lap_time),
        "gates": gates,
        "t": [float(x) for x in t],
    }


def save_ideal_line(track_file, result, points_dir=POINTS_DIR):
    """Сохраняет результат compute_optimal_line в
    <points_dir>/<имя_трассы_без_.txt>.ideal_line.json — формат читает
    car_racer/screen/screen.py::_load_ideal_line()."""
    base_name = os.path.splitext(os.path.basename(track_file))[0]
    out_path = os.path.join(points_dir, base_name + ".ideal_line.json")

    payload = {
        "points": [list(p) for p in result["points"]],
        "speeds": result["speeds"],
        "estimated_lap_time": result["estimated_lap_time"],
        "track_file": os.path.basename(track_file),
        "generated_by": "car_racer.trajectory.optimal_line",
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return out_path


def self_check(track_outer, track_inner, result):
    """Headless-проверка корректности результата (нет дисплея в окружении, где
    это разрабатывалось) — используется CLI ниже. Бросает AssertionError с
    понятным сообщением, если что-то не так."""
    gates = result["gates"]
    t = result["t"]
    points = result["points"]
    assert len(gates) == len(points) == len(t), "число ворот/точек/t не совпадает"

    for i, (gate, tt, p) in enumerate(zip(gates, t, points)):
        assert -1e-6 <= tt <= 1.0 + 1e-6, f"ворота {i}: t={tt} вне [0,1]"
        outer, inner = gate
        expected = (outer[0] + tt * (inner[0] - outer[0]),
                    outer[1] + tt * (inner[1] - outer[1]))
        assert _dist(expected, p) < 1e-3, f"ворота {i}: точка не на отрезке ворот"

    lap_time = result["estimated_lap_time"]
    assert math.isfinite(lap_time), "время круга не конечно"
    assert lap_time > 0.0, "время круга должно быть положительным"
    # Разумный порядок величины: не наносекунды и не миллионы (см. docstring
    # модуля про единицы измерения px/с — это условное, не физическое время).
    assert 0.01 < lap_time < 10_000.0, f"время круга неправдоподобного порядка: {lap_time}"

    speeds = result["speeds"]
    assert all(math.isfinite(s) and s >= 0.0 for s in speeds), "скорость должна быть конечной и неотрицательной"
    assert all(s <= MAX_SPEED_PX_S + 1e-6 for s in speeds), "скорость превышает MAX_SPEED_PX_S"

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Расчёт классической 'идеальной' гоночной траектории трассы "
                     "(минимизация кривизны + профиль скорости по кругу трения).")
    parser.add_argument("track_file", help="имя файла трассы в car_racer/tracks/, напр. points_oval.txt")
    parser.add_argument("--num-gates", type=int, default=DEFAULT_NUM_GATES,
                         help="число ворот для общего (не индексного) алгоритма извлечения ворот")
    parser.add_argument("--from-car-settings", action="store_true",
                         help="взять сцепление/массу/мощность из текущих настроек "
                              "car_racer.cars.physic_car вместо дефолтов модуля")
    args = parser.parse_args()

    track_outer, track_inner, _checkpoints, _start_line = parse_track(args.track_file)

    vehicle_params = vehicle_params_from_physic_car() if args.from_car_settings else None
    result = compute_optimal_line(track_outer, track_inner, num_gates=args.num_gates, vehicle_params=vehicle_params)
    self_check(track_outer, track_inner, result)

    out_path = save_ideal_line(args.track_file, result)
    print(f"Ворот: {len(result['gates'])}, время круга (условное, px/с): "
          f"{result['estimated_lap_time']:.2f} с")
    print(f"Сохранено: {out_path}")


if __name__ == "__main__":
    main()
