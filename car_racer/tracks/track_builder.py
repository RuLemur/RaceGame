"""
Конструктор трасс "по схеме" — трасса описывается списком сегментов
(прямая / поворот) вместо рисования мышью. Из схемы генерируется
центральная линия, затем строится внешняя/внутренняя граница нужной
ширины, чекпоинты и линия старта, и всё сохраняется в формате,
который понимает car_racer.file_manager.file_worker.parse_track.

Формат схемы — список словарей:
    {"type": "straight", "length": 300}
    {"type": "turn", "angle": 90, "radius": 150}

Угол поворота в градусах: положительный — налево (против часовой),
отрицательный — направо. Чтобы получить замкнутую трассу, сумма углов
поворотов должна давать 360 (или -360), а форма должна визуально
сходиться в начальную точку (проще всего строить из симметричных
прямых/поворотов, как в примерах ниже).

Запуск файла как скрипта создаёт несколько примеров треков в
car_racer/tracks/.
"""
import math
import os

from car_racer.file_manager.file_worker import POINTS_DIR

STEP = 12.0  # шаг сэмплирования центральной линии, px


def build_centerline(schema, start=(0.0, 0.0), start_heading=0.0, step=STEP):
    """Строит список точек (x, y) центральной линии трассы по схеме сегментов."""
    points = [start]
    x, y = start
    heading = start_heading

    for segment in schema:
        seg_type = segment["type"]

        if seg_type == "straight":
            length = segment["length"]
            steps = max(1, round(length / step))
            seg_step = length / steps
            dx, dy = math.cos(heading), math.sin(heading)
            for _ in range(steps):
                x += dx * seg_step
                y += dy * seg_step
                points.append((x, y))

        elif seg_type == "turn":
            radius = segment["radius"]
            angle_rad = math.radians(segment["angle"])
            arc_length = abs(radius * angle_rad)
            steps = max(1, round(arc_length / step))
            d_theta = angle_rad / steps
            seg_step = arc_length / steps
            for _ in range(steps):
                # полушаг до и после смены курса — сглаживает дугу
                heading += d_theta / 2
                x += math.cos(heading) * seg_step
                y += math.sin(heading) * seg_step
                heading += d_theta / 2
                points.append((x, y))

        else:
            raise ValueError(f"Неизвестный тип сегмента: {seg_type!r}")

    return points, heading


def offset_polyline(points, distance):
    """Сдвигает ломаную на `distance` по нормали (положительное значение — влево по ходу)."""
    offset_points = []
    n = len(points)
    for i in range(n):
        if i == 0:
            dx = points[1][0] - points[0][0]
            dy = points[1][1] - points[0][1]
        elif i == n - 1:
            dx = points[i][0] - points[i - 1][0]
            dy = points[i][1] - points[i - 1][1]
        else:
            dx = points[i + 1][0] - points[i - 1][0]
            dy = points[i + 1][1] - points[i - 1][1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        offset_points.append((points[i][0] + nx * distance, points[i][1] + ny * distance))
    return offset_points


def build_track(schema, width=140.0, checkpoint_spacing=250.0,
                 start=(0.0, 0.0), start_heading=0.0):
    """
    Возвращает (outer, inner, checkpoints, start_line) в том же формате,
    что и file_worker.parse_track: outer/inner — списки [x, y],
    checkpoints — список пар точек, start_line — пара точек.
    """
    centerline, _ = build_centerline(schema, start=start, start_heading=start_heading, step=STEP)

    half_width = width / 2
    outer = offset_polyline(centerline, half_width)
    inner = offset_polyline(centerline, -half_width)

    # Чекпоинты — перпендикулярные отрезки поперёк трассы через равные
    # промежутки по длине центральной линии (кроме самого начала — там старт).
    checkpoints = []
    dist_since_last = 0.0
    for i in range(1, len(centerline) - 1):
        dist_since_last += math.dist(centerline[i - 1], centerline[i])
        if dist_since_last >= checkpoint_spacing:
            checkpoints.append((outer[i], inner[i]))
            dist_since_last = 0.0

    start_line = (outer[0], inner[0])

    return outer, inner, checkpoints, start_line


def fit_to_screen(outer, inner, checkpoints, start_line, margin=100.0):
    """Сдвигает всю трассу так, чтобы её левый верхний угол был на `margin`
    от края экрана (координаты схемы не привязаны к экрану и могут уйти в минус)."""
    xs = [p[0] for p in outer + inner]
    ys = [p[1] for p in outer + inner]
    dx, dy = margin - min(xs), margin - min(ys)

    def shift(p):
        return (p[0] + dx, p[1] + dy)

    outer = [shift(p) for p in outer]
    inner = [shift(p) for p in inner]
    checkpoints = [(shift(a), shift(b)) for a, b in checkpoints]
    start_line = (shift(start_line[0]), shift(start_line[1]))
    return outer, inner, checkpoints, start_line


def save_track_file(filename, outer, inner, checkpoints, start_line, directory=POINTS_DIR):
    """Сохраняет трассу в текстовый файл формата car_racer/tracks/*.txt."""

    def fmt_point(p):
        return f"[{round(p[0])}, {round(p[1])}]"

    def fmt_line(a, b):
        return f"[{fmt_point(a)},{fmt_point(b)}]"

    path = os.path.join(directory, filename)
    with open(path, "w") as f:
        f.write("[" + ",".join(fmt_point(p) for p in outer) + "]\n")
        f.write("[" + ",".join(fmt_point(p) for p in inner) + "]\n")
        for a, b in checkpoints:
            f.write(fmt_line(a, b) + "\n")
        f.write(fmt_line(*start_line) + "\n")
    print(f"Трасса сохранена: {path}")
    return path


# --- Примеры схем (только как справка по формату - НЕ используются для
# генерации актуальных файлов трасс; points_oval_half_mile.txt/
# points_stadium_chicane.txt, которые раньше делались отсюда, либо пересобраны
# отдельно под реальные метры (овал), либо удалены как неудачные (стадион) -
# см. CLAUDE.md) -----------------------------------------------------

OVAL_SCHEMA = [
    {"type": "straight", "length": 500},
    {"type": "turn", "angle": 180, "radius": 200},
    {"type": "straight", "length": 500},
    {"type": "turn", "angle": 180, "radius": 200},
]

STADIUM_WITH_CHICANE_SCHEMA = [
    {"type": "straight", "length": 300},
    {"type": "turn", "angle": -30, "radius": 120},
    {"type": "straight", "length": 80},
    {"type": "turn", "angle": 30, "radius": 120},
    {"type": "straight", "length": 250},
    {"type": "turn", "angle": 180, "radius": 180},
    {"type": "straight", "length": 630},
    {"type": "turn", "angle": 180, "radius": 180},

]
