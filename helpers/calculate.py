import math


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
