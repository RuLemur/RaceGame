import math
import os
import pickle

import neat

CHECKPOINT_DIR = 'car_racer/checkpoints/checkpoints'
POINTS_DIR = 'car_racer/tracks/'
CONFIG_DIR = 'car_racer/config/'

# Максимальный разрыв (px) между серединами соседних чекпоинтов - на
# нарисованных мышью трассах (например points.txt) пара чекпоинтов может
# оказаться в разы дальше друг от друга, чем остальные (см. CLAUDE.md про
# checkpoints_lines): между ними машина не получает вообще никакого
# фитнес-сигнала за большой отрезок трассы, что душит обучение (сравнимо
# хорошие и случайные геномы неотличимы, если оба не дотягивают до
# следующего чекпоинта). _densify_checkpoints ниже вставляет линейно
# интерполированные промежуточные чекпоинты, чтобы разрыв не превышал этот
# порог - это геометрическое приближение (линия между двумя соседними
# воротами не обязана точно повторять кривизну трассы), но чекпоинт чуть в
# стороне от идеальной линии всё равно куда полезнее, чем разрыв в 600+ px
# без единого промежуточного сигнала.
#
# Было 500.0, поднято до 2200.0 по явному запросу пользователя - "снизить
# количество чекпоинтов на всех трассах раза в 3-4" (после того как компас,
# см. PhyCar._heading_error_to_next_checkpoint, стал давать сглаженный
# направляющий сигнал ПОСТОЯННО, а не только "от чекпоинта к чекпоинту" -
# необходимость в очень частых чекпоинтах для фитнес-сигнала стала меньше,
# чем когда порог только вводился). Раньше при 500.0 порог был МЕНЬШЕ, чем
# намеренный шаг генерации чекпоинтов у points_monza.txt/points_imola.txt
# (~1200px = 60м, см. build_real_circuits.py) - парадоксальный эффект: чем
# ГУЩЕ трасса генерировалась изначально, тем СИЛЬНЕЕ автоуплотнение потом
# добавляло сверху (267/227 итоговых чекпоинтов вместо задуманных 89/68) -
# 2200 выше и этого намеренного шага, и максимального разрыва после ручного
# прореживания (см. ниже) остальных трасс - автоуплотнение теперь НЕ
# добавляет чекпоинты ни на одной из текущих трасс, только страхует от
# гипотетического будущего разрыва больше 2200px.
#
# points.txt/points_oval_half_mile.txt/points_xti_winter.txt прорежены
# ВРУЧНУЮ (оставлен каждый 4-й чекпоинт из сохранённого файла, всегда с
# сохранением последнего перед финишем) - у них, в отличие от Монцы/Имолы,
# чекпоинты генерировались С ШАГОМ УЖЕ МЕНЬШЕ старого порога 500, так что
# поднять порог было недостаточно - разрежение самого файла было нужно
# отдельно. points_xti_winter.txt масштабирован через реальную длину 1250 м
# и сознательно не учтён в множителе PX_PER_METER/SENSOR_RANGE - см.
# комментарий у SENSOR_RANGE.
MAX_CHECKPOINT_GAP = 2200.0


def _densify_checkpoints(checkpoints, start_line, max_gap=MAX_CHECKPOINT_GAP):
    def midpoint(line):
        (x1, y1), (x2, y2) = line
        return (x1 + x2) / 2, (y1 + y2) / 2

    def lerp_line(a, b, t):
        (a1, a2), (b1, b2) = a, b
        return (
            (a1[0] + (b1[0] - a1[0]) * t, a1[1] + (b1[1] - a1[1]) * t),
            (a2[0] + (b2[0] - a2[0]) * t, a2[1] + (b2[1] - a2[1]) * t),
        )

    prev_line = start_line
    densified = []
    for line in checkpoints:
        prev_mid = midpoint(prev_line)
        mid = midpoint(line)
        gap = math.hypot(mid[0] - prev_mid[0], mid[1] - prev_mid[1])
        num_segments = max(1, math.ceil(gap / max_gap))
        for i in range(1, num_segments):
            densified.append(lerp_line(prev_line, line, i / num_segments))
        densified.append(line)
        prev_line = line
    return densified


def parse_track(filename):
    with open(POINTS_DIR + filename, 'r') as file:
        lines = file.readlines()

        # Удаляем символы новой строки и пробелы
    lines = [line.strip() for line in lines if line.strip()]

    # Остальные строки
    other_lines = []
    for line in lines[2:]:
        # Преобразуем строку в список кортежей
        points = eval(line)
        tuple_points = (points[0], points[1])
        other_lines.append(tuple_points)

    checkpoints, start_line = other_lines[:-1], other_lines[len(other_lines) - 1]
    checkpoints = _densify_checkpoints(checkpoints, start_line)
    return eval(lines[0]), eval(lines[1]), checkpoints, start_line


def save_checkpoint(population, generation):
    filename = os.path.join(CHECKPOINT_DIR, f'neat-checkpoint-gen-{generation}.pkl')
    with open(filename, 'wb') as f:
        pickle.dump(population, f)
    print(f"Checkpoint saved to {filename}")


def load_checkpoint(filename):
    with open(filename, 'rb') as f:
        population = pickle.load(f)
    print(f"Checkpoint loaded from {filename}")
    return population


def get_neat_config():
    config_path = os.path.join(CONFIG_DIR + "config-feedforward.txt")
    config = neat.config.Config(neat.DefaultGenome, neat.DefaultReproduction,
                                neat.DefaultSpeciesSet, neat.DefaultStagnation,
                                config_path)
    return config
