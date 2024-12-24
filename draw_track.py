import pygame
import sys

# Инициализация Pygame
pygame.init()

# Установка размеров окна
screen = pygame.display.set_mode((1200, 800))
pygame.display.set_caption("Рисование линий")

# Переменные для отслеживания состояния
drawing = False
last_pos = None

points = []
# Основной цикл программы
while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            print(points)
            pygame.quit()
            sys.exit()
        elif event.type == pygame.MOUSEBUTTONDOWN:
            points.append(event.pos)
            if last_pos is not None:
                pygame.draw.line(screen, (255, 255, 255), last_pos, event.pos, 6)
            last_pos = event.pos

    # Обновление экрана
    pygame.display.flip()