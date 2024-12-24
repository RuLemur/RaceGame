import pygame
import math

# Инициализация Pygame
pygame.init()

# Задаем размеры окна
width, height = 800, 600
screen = pygame.display.set_mode((width, height))
pygame.display.set_caption("Line Intersection with Multiple Segments")

# Цвета
black = (0, 0, 0)
white = (255, 255, 255)
red = (255, 0, 0)

# Основная линия (задана начальной и конечной точками)
start_pos_main = (100, 100)
end_pos_main = (400, 400)

# Дополнительные линии (каждая линия задана последовательностью точек)
lines = [
    [(300, 200), (350, 250), (500, 300)],
    [(400, 100), (400, 500)],
    [(200, 300), (250, 350), (600, 300)]
]


# Функция для нахождения ориентации
def orientation(p, q, r):
    """ Возвращает:
    0 -> p, q и r коллинеарны
    1 -> по часовой стрелке
    2 -> против часовой стрелки
    """
    val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
    if val == 0:
        return 0
    elif val > 0:
        return 1
    else:
        return 2


# Функция для проверки пересечения отрезков
def do_intersect(p1, q1, p2, q2):
    # Найти четыре ориентации, необходимые для общего и специального случая
    o1 = orientation(p1, q1, p2)
    o2 = orientation(p1, q1, q2)
    o3 = orientation(p2, q2, p1)
    o4 = orientation(p2, q2, q1)

    # Общий случай
    if o1 != o2 and o3 != o4:
        return True

    # Специальные случаи
    # p1, q1 и p2 коллинеарны и p2 лежит на отрезке p1q1
    if o1 == 0 and on_segment(p1, p2, q1):
        return True

    # p1, q1 и p2 коллинеарны и q2 лежит на отрезке p1q1
    if o2 == 0 and on_segment(p1, q2, q1):
        return True

    # p2, q2 и p1 коллинеарны и p1 лежит на отрезке p2q2
    if o3 == 0 and on_segment(p2, p1, q2):
        return True

    # p2, q2 и q1 коллинеарны и q1 лежит на отрезке p2q2
    if o4 == 0 and on_segment(p2, q1, q2):
        return True

    return False


# Функция для проверки, лежит ли точка q на отрезке pr
def on_segment(p, q, r):
    if (min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and
            min(p[1], r[1]) <= q[1] <= max(p[1], r[1])):
        return True
    return False


def find_intersection(p1, p2, q1, q2):
    if do_intersect(p1, p2, q1, q2):
        # Вычисляем пересечение
        A1 = p2[1] - p1[1]
        B1 = p1[0] - p2[0]
        C1 = A1 * p1[0] + B1 * p1[1]

        A2 = q2[1] - q1[1]
        B2 = q1[0] - q2[0]
        C2 = A2 * q1[0] + B2 * q1[1]

        det = A1 * B2 - A2 * B1

        if det == 0:
            return None  # Линии параллельны, в теории невозможный случай после do_intersect

        x = (B2 * C1 - B1 * C2) / det
        y = (A1 * C2 - A2 * C1) / det
        return (x, y)
    return None


# Главный цикл программы
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Заполняем экран белым цветом
    screen.fill(white)

    # Рисуем основную линию
    pygame.draw.line(screen, (0,255,0), start_pos_main, end_pos_main, 2)

    # Обработка пересечений
    nearest_distance = float('inf')
    nearest_intersection = None

    for line in lines:
        # Рисуем линию
        pygame.draw.lines(screen, black, False, line, 2)

        # Проходим по сегментам линии
        for i in range(len(line) - 1):
            start_pos = line[i]
            end_pos = line[i + 1]

            # Находим точку пересечения
            intersection = find_intersection(start_pos_main, end_pos_main, start_pos, end_pos)

            if intersection:
                ix, iy = intersection
                # Вычисляем расстояние
                distance = math.sqrt((ix - start_pos_main[0]) ** 2 + (iy - start_pos_main[1]) ** 2)
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_intersection = intersection

    # Рисуем ближайшую точку пересечения
    if nearest_intersection:
        pygame.draw.circle(screen, red, (int(nearest_intersection[0]), int(nearest_intersection[1])), 5)

    # Обновляем экран
    pygame.display.flip()

pygame.quit()

# Печатаем ближайшее расстояние
if nearest_distance != float('inf'):
    print(f"Ближайшее расстояние от начала основной линии до пересечения: {nearest_distance:.2f}")
else:
    print("Пересечений не найдено.")
