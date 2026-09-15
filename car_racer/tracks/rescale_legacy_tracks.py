"""
Одноразовый скрипт: масштабирует 5 "легаси" трасс без реальной калибровки
px->метры (нарисованные мышью points.txt/points_reserve.txt/points_reserve2.txt
+ схемные points_oval.txt/points_stadium_chicane.txt) на единый множитель
SCALE_FACTOR, чтобы вместе с PX_PER_METER (car_racer/constants.py) они
представляли правдоподобную длину трассы небольшого/среднего картинг-круга.
points_xti_winter.txt НЕ включена - у неё своя, отдельная калибровка через
реальную длину 1250 м (см. car_racer/tracks/svg_track_importer.py).

Почему SCALE_FACTOR = 2.0
--------------------------
До масштабирования (при PX_PER_METER=20, т.е. без какой-либо перекалибровки
этих 5 трасс) их приблизительная длина центральной линии (среднее периметров
outer/inner - грубая, но достаточная для выбора множителя оценка) была:

    points.txt                  ~241 м
    points_reserve.txt          ~153 м
    points_reserve2.txt         ~170 м
    points_oval.txt             ~113 м
    points_stadium_chicane.txt  ~132 м

Нижняя граница (113 м) заметно короче типичного даже маленького картинг-круга,
верхняя (241 м) - на самой нижней границе "нескольких сотен метров" из
задачи. SCALE_FACTOR=2.0 переносит диапазон в ~226-482 м - устойчиво
"несколько сотен метров" для всех пяти, с запасом не приближаясь к 1 км.

Побочный эффект (осознанный, не устраняется здесь): ширина полотна схемных
трасс (track_builder.py, width=140px = 7 м при PX_PER_METER=20) масштабируется
тем же множителем до ~14 м - шире типичного картинг-полотна (9-12 м у
эталонной points_xti_winter.txt), но задача явно расставляла приоритет на
ДЛИНУ трассы, а не ширину полотна; у чистого геометрического масштабирования
нет отдельной ручки для длины и ширины по отдельности.

MAX_CHECKPOINT_GAP (file_manager/file_worker.py) и SENSOR_RANGE
(car_racer/constants.py) масштабированы этим же множителем ОТДЕЛЬНО (прямо в
тех файлах, не этим скриптом) - см. комментарии там.

Точка отсчёта масштабирования - левый верхний угол bounding box САМОЙ трассы
(min x/y по объединению outer+inner точек), а не центр и не (0,0) - так после
умножения на SCALE_FACTOR результат гарантированно не уходит в отрицательные
координаты (тот же приём, что fit_to_screen в track_builder.py, но здесь это
просто сдвиг к нулю, а не подгонка под margin экрана - x,y-масштаб и форма
трассы не искажаются, меняется только положение).

Результат уже применён и закоммичен - повторный запуск смасштабирует файлы
ЕЩЁ раз (не идемпотентно), поэтому обычно не нужен. Оставлен в репозитории
как документация того, как получены текущие точки (по аналогии с
svg_track_importer.py/track_builder.py - тоже одноразовые генераторы,
хранящиеся в репозитории для воспроизводимости).

Запуск:
    python -m car_racer.tracks.rescale_legacy_tracks
"""
import ast
import os

POINTS_DIR = "car_racer/tracks/"
TRACKS = ["points.txt", "points_reserve.txt", "points_reserve2.txt",
          "points_oval.txt", "points_stadium_chicane.txt"]
SCALE_FACTOR = 2.0


def _load_raw(filename):
    with open(os.path.join(POINTS_DIR, filename), "r") as f:
        lines = [line.strip() for line in f if line.strip()]
    outer = ast.literal_eval(lines[0])
    inner = ast.literal_eval(lines[1])
    other_lines = [ast.literal_eval(line) for line in lines[2:]]
    checkpoints, start_line = other_lines[:-1], other_lines[-1]
    return outer, inner, checkpoints, start_line


def _fmt_point(p):
    return f"[{round(p[0])}, {round(p[1])}]"


def _fmt_line(a, b):
    return f"[{_fmt_point(a)},{_fmt_point(b)}]"


def rescale_track(filename, scale=SCALE_FACTOR, points_dir=POINTS_DIR):
    outer, inner, checkpoints, start_line = _load_raw(filename)
    all_pts = outer + inner
    min_x = min(p[0] for p in all_pts)
    min_y = min(p[1] for p in all_pts)

    def scale_pt(p):
        return ((p[0] - min_x) * scale, (p[1] - min_y) * scale)

    outer_s = [scale_pt(p) for p in outer]
    inner_s = [scale_pt(p) for p in inner]
    checkpoints_s = [(scale_pt(a), scale_pt(b)) for a, b in checkpoints]
    start_line_s = (scale_pt(start_line[0]), scale_pt(start_line[1]))

    path = os.path.join(points_dir, filename)
    with open(path, "w") as f:
        f.write("[" + ",".join(_fmt_point(p) for p in outer_s) + "]\n")
        f.write("[" + ",".join(_fmt_point(p) for p in inner_s) + "]\n")
        for a, b in checkpoints_s:
            f.write(_fmt_line(a, b) + "\n")
        f.write(_fmt_line(*start_line_s) + "\n")
    print(f"Rescaled {filename} by {scale}x -> {path}")
    return path


def main():
    for track_file in TRACKS:
        rescale_track(track_file)


if __name__ == "__main__":
    main()
