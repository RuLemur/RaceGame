import pygame
import pymunk
import pymunk.pygame_util
import math

from mygame.physic_car import PhyCar, THROTTLE_POWER, ROTATE_POWER
#
# # Инициализация Pygame
# pygame.init()
# WIDTH, HEIGHT = 800, 600
# window = pygame.display.set_mode((WIDTH, HEIGHT))
# clock = pygame.time.Clock()
#
# # Инициализация Pymunk
# space = pymunk.Space()
# space.gravity = (0, 0)  # Отсутствие гравитации в игре с видом сверху
#
# # Утилита для отрисовки
# draw_options = pymunk.pygame_util.DrawOptions(window)
#
# # Создание машины
# car_body = PhyCar(space, (WIDTH // 2, HEIGHT // 2), (50, 30), False, draw_options)
#
# running = True
# while running:
#     for event in pygame.event.get():
#         if event.type == pygame.QUIT:
#             running = False
#
#     keys = pygame.key.get_pressed()
#
#     if keys[pygame.K_UP]:
#         car_body.throttle_power = 1.0
#     if keys[pygame.K_DOWN]:
#         car_body.throttle_power = -1.0
#
#     if keys[pygame.K_RIGHT]:
#         car_body.turn_power = 1.0
#     if keys[pygame.K_LEFT]:
#         car_body.turn_power = -1.0
#
#     car_body.car_update()
#     space.step(1 / 60)
#
#     # Проверка столкновений с краями экрана
#     x, y = car_body.get_car().position
#     vx, vy = car_body.get_car().velocity
#
#     if x <= 0 or x >= WIDTH or y <= 0 or y >= HEIGHT:
#         car_body.get_car().position = (WIDTH // 2, HEIGHT // 2)
#
#     # Отрисовка
#     window.fill((255, 255, 255))
#     space.debug_draw(draw_options)
#
#     # Отрисовка вектора силы
#     start_pos = car_body.get_car().position
#
#     velocity_vector = car_body.get_car().velocity
#     if velocity_vector.length > 0:
#         end_pos_velocity = start_pos + velocity_vector.normalized() * 50
#         pygame.draw.line(window, (0, 0, 255), start_pos, end_pos_velocity, 3)
#
#     pygame.display.flip()
#     clock.tick(60)
#
# pygame.quit()
