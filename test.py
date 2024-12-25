import pygame
import math

# Инициализация Pygame
pygame.init()

# Константы и цвета
WIDTH, HEIGHT = 800, 600
WHITE = (255, 255, 255)
RED = (255, 0, 0)

# Установка размеров окна
screen = pygame.display.set_mode((WIDTH, HEIGHT))

# Функция для поворота точки вокруг другой точки
def rotate_point(point, angle, center):
    angle_rad = math.radians(angle)
    x, y = point
    cx, cy = center
    x_new = cx + math.cos(angle_rad) * (x - cx) - math.sin(angle_rad) * (y - cy)
    y_new = cy + math.sin(angle_rad) * (x - cx) + math.cos(angle_rad) * (y - cy)
    return x_new, y_new

# Функция для рисования прямоугольника под углом
def draw_rotated_rect(surface, rect, angle, color):
    # Центр прямоугольника
    center = rect.center

    # Вершины прямоугольника
    corners = [
        rect.topleft,
        rect.topright,
        rect.bottomright,
        rect.bottomleft
    ]

    # Поворот вершин
    rotated_corners = [rotate_point(corner, angle, center) for corner in corners]

    # Отрисовка многоугольника
    pygame.draw.polygon(surface, color, rotated_corners, 2)

# Начальная позиция и размеры прямоугольника
rect = pygame.Rect(300, 200, 200, 100)
angle = 0

# Основной цикл программы
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Очистка экрана
    screen.fill(WHITE)

    # Рисование повернутого прямоугольника
    draw_rotated_rect(screen, rect, angle, RED)

    # Обновление экрана
    pygame.display.flip()

    # Увеличение угла для демонстрации
    angle += 1
    if angle >= 360:
        angle = 0

pygame.quit()
