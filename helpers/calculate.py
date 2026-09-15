import math

import numpy as np


# Функция для вычисления конечной точки
def calculate_end_pos(start_pos, angle_degrees, length):
    angle_radians = math.radians(angle_degrees)
    end_x = start_pos[0] + length * math.cos(angle_radians)
    end_y = start_pos[1] - length * math.sin(angle_radians)  # Минус, потому что ось Y направлена вниз
    return int(end_x), int(end_y)


# Функция для вычисления середины отрезка
def get_midpoint(sl):
    x1, y1 = sl[0]
    x2, y2 = sl[1]
    return (x1 + x2) / 2, (y1 + y2) / 2


def build_track_segments(track_outer, track_inner):
    """Собирает границы трассы в пару numpy-массивов (starts, ends) формы (N, 2)
    для быстрого векторизованного пересечения лучей-сенсоров (см. cast_ray) И
    проверки столкновения со стенами (min_distance_to_segments).

    ВАЖНО: контур ЗАМЫКАЕТСЯ - последняя точка соединяется с первой
    (`(i + 1) % n`). Раньше диапазон был `range(len(line) - 1)`, т.е. сегмент
    последняя->первая НЕ создавался: у трасс, где эти точки не совпадают
    вплотную (например оцифрованные из реальных схем - у points_monza.txt
    разрыв ~128px, у points.txt ~10px), в стене оставалась ДЫРА на стыке, и
    машина вылетала за трассу именно через неё (столкновение там не
    детектировалось - сегмента-то нет).

    Нужно пересчитывать заново каждый раз, когда меняются track_outer/track_inner
    (например при переключении трассы) - см. Screen.load_track."""
    starts = []
    ends = []
    for line in (track_outer, track_inner):
        n = len(line)
        for i in range(n):
            starts.append(line[i])
            ends.append(line[(i + 1) % n])
    return np.asarray(starts, dtype=float), np.asarray(ends, dtype=float)


def min_distance_to_segments(point, seg_starts, seg_ends):
    """Кратчайшее расстояние от точки до множества отрезков разом
    (векторизовано через numpy). Используется для проверки столкновения со
    стенами трассы вместо поштучного pygame.Rect.clipline() по каждому
    сегменту в Python-цикле - профилирование показало, что именно это было
    самым дорогим местом в тике после того, как сенсоры уже перевели на
    cast_ray (~74% времени тика на group.resolve(), в основном на повторные
    обращения к body.position внутри цикла по сегментам)."""
    px, py = point
    ax, ay = seg_starts[:, 0], seg_starts[:, 1]
    bx, by = seg_ends[:, 0], seg_ends[:, 1]
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy

    with np.errstate(divide="ignore", invalid="ignore"):
        t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t = np.where(seg_len_sq > 0, np.clip(t, 0.0, 1.0), 0.0)

    closest_x = ax + t * dx
    closest_y = ay + t * dy
    dist_sq = (px - closest_x) ** 2 + (py - closest_y) ** 2
    return float(np.sqrt(np.min(dist_sq)))


def cast_ray(origin, direction_degrees, max_length, seg_starts, seg_ends):
    """
    Быстрое пересечение одного луча со всеми сегментами трассы разом
    (векторизовано через numpy, без shapely/GEOS - в разы дешевле на тик,
    т.к. не создаёт Python-объекты геометрии на каждый сегмент).

    origin - (x, y) начало луча. direction_degrees - направление в тех же
    градусах, что использует calculate_end_pos (0 = вдоль +x, положительный
    угол - против часовой стрелки в системе координат экрана, где ось Y
    направлена вниз). seg_starts/seg_ends - numpy-массивы (N, 2) от
    build_track_segments.

    Возвращает (distance, hit_point): distance - расстояние вдоль луча до
    ближайшего пересечения, либо max_length, если пересечений нет; hit_point -
    координаты точки пересечения (для отладочной отрисовки) или None.
    """
    angle_radians = math.radians(direction_degrees)
    dx, dy = math.cos(angle_radians), -math.sin(angle_radians)  # см. calculate_end_pos

    ox, oy = origin
    qpx = seg_starts[:, 0] - ox
    qpy = seg_starts[:, 1] - oy
    rsx = seg_ends[:, 0] - seg_starts[:, 0]
    rsy = seg_ends[:, 1] - seg_starts[:, 1]

    # Стандартная формула пересечения луча (O + t*D) с отрезком (Q + u*S)
    # через векторные произведения: t = cross(Q-O, S) / cross(D, S),
    # u = cross(Q-O, D) / cross(D, S).
    denom = dx * rsy - dy * rsx
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (qpx * rsy - qpy * rsx) / denom
        u = (qpx * dy - qpy * dx) / denom

    valid = (denom != 0) & (t >= 0) & (t <= max_length) & (u >= 0) & (u <= 1)
    if not np.any(valid):
        return float(max_length), None

    distance = float(np.min(t[valid]))
    hit_point = (ox + dx * distance, oy + dy * distance)
    return distance, hit_point
