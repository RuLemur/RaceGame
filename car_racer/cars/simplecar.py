import math
import time

import pygame
from shapely.geometry.linestring import LineString

from car_racer.cars.abs_car import Car
from car_racer.constants import GRAY, WHITE, MAX_TIMEOUT
from car_racer.screen.screen import Screen
from helpers.calculate import calculate_end_pos, get_midpoint

CAR_WIDTH = 30
CAR_HEIGHT = 50
FORCE = 1
DECELERATION = 0.95
MAX_SPEED = 10
MAX_SPEED_REVERS = 0
GRIP = 0.01  # Коэффициент сцепления для дрифта
DRIFT_FACTOR = 0.2  # Коэффициент дрифта
EPSILON = 0.01


# Загрузка изображений


class SimpleCar(Car):

    def __init__(self, screen: Screen, car_size=(CAR_WIDTH, CAR_HEIGHT), mass=1.0):
        car_image = pygame.image.load("./assets/car.png")
        car_image = pygame.transform.scale(car_image, car_size)
        car_image = pygame.transform.rotate(car_image, -90)
        self.car_image = car_image

        self.x, self.y = get_midpoint(screen.start_line)
        self.angle = -90
        self.speed = 0
        self.mass = mass
        self.drift = 0
        self.car_rect = car_image.get_rect(center=(self.x, self.y))
        self.collistion_rect = pygame.Rect(self.x - CAR_WIDTH // 3, self.y - CAR_WIDTH // 3, CAR_WIDTH, CAR_WIDTH)
        self.screen = screen

        self.already_crossed = []
        self.cl_count = 0
        self.lap_count = 0
        self.fitness = 0
        self.lap_start_time = time.time()
        self.lap_time = 0

    def add_fitness(self, fitness):
        self.fitness += fitness

    def get_cl(self):
        return self.cl_count

    def get_laps(self):
        return self.lap_count

    def get_fitness(self):
        return self.fitness

    def get_lap_time(self):
        return self.lap_time

    def draw(self):
        # for a in [-140, -90, -30, 0, 30, 90, 140]:
        #     self.draw_line(a)

        rotated_image = pygame.transform.rotate(self.car_image, -self.angle - self.drift)
        self.car_rect = rotated_image.get_rect(center=(self.x, self.y))
        self.screen.get_window().blit(rotated_image, self.car_rect.topleft)
        self.collistion_rect = pygame.Rect(self.x - (CAR_WIDTH // 4), self.y - (CAR_HEIGHT // 4),
                                           CAR_WIDTH // 2, CAR_WIDTH // 2)
        pygame.draw.rect(self.screen.get_window(), (255, 255, 255), self.collistion_rect)

    def damping(self, throttle: bool, turning: bool):
        if not throttle:
            self.speed = 0 if abs(self.speed) <= EPSILON else self.speed * DECELERATION

    # обновляем положение автомобиля
    def update(self):
        rad = math.radians(self.angle + self.drift)
        self.x += self.speed * math.cos(rad)
        self.y += self.speed * math.sin(rad)

    def get_postion(self) -> (int, int):
        return self.x, self.y

    def get_speed(self) -> int:
        return self.speed

    def throttle(self, power: float):
        speed = power * FORCE + self.speed
        if MAX_SPEED_REVERS <= speed <= MAX_SPEED:
            self.speed = speed

    def turn(self, power: float):
        if self.speed != 0:
            # Увеличиваем дрифт при повороте
            self.angle += 5 * power

    def draw_line(self, angle: int):
        car_position = self.get_postion()
        line_end_pos = calculate_end_pos(car_position, -self.angle + angle, 500)
        pygame.draw.line(self.screen.get_window(), GRAY, car_position, line_end_pos, 1)
        m_line = LineString([car_position, line_end_pos])
        return m_line

    def check_collision_with_track(self):
        for track_lines in [self.screen.track_inner, self.screen.track_outer]:
            for i in range(len(track_lines) - 1):
                line_start = track_lines[i]
                line_end = track_lines[i + 1]
                if (self.collistion_rect.clipline(line_start, line_end) or
                        (self.x <= 0 or self.x >= self.screen.screen_width
                         or self.y <= 0 or self.y >= self.screen.screen_height)):
                    return True
        return False

    def check_collision_with_checkpoint(self):
        for line in self.screen.checkpoints_lines:
            line_start, line_end = line
            if self.collistion_rect.clipline(line_start, line_end) and (
            line_start, line_end) not in self.already_crossed:
                self.already_crossed.append((line_start, line_end))
                self.cl_count += 1
                return True
        return False

    def check_collision_with_start(self):
        line_start, line_end = self.screen.start_line
        if (self.collistion_rect.clipline(line_start, line_end) and
                len(self.already_crossed) == len(self.screen.checkpoints_lines)):
            self.already_crossed = []
            self.lap_count += 1
            self.lap_time = time.time() - self.lap_start_time
            self.lap_start_time = time.time()
            return True
        return False


    def get_inputs_for_network(self):
        # Пример: используем расстояния до ближайших препятствий как входы
        inputs = [self.angle, self.get_speed()]

        for angle in [-150, -90, -45, 0, 45, 90, 150]:
            main_line = self.draw_line(angle)
            distance = float('inf')
            for line in [self.screen.track_outer, self.screen.track_inner]:
                for i in range(len(line) - 1):
                    checked_line = LineString([line[i], line[i + 1]])
                    intersection = main_line.intersection(checked_line)
                    if not intersection.is_empty:
                        distance = min(distance, main_line.project(intersection))
                        pygame.draw.circle(self.screen.get_window(), WHITE, intersection.coords[0], 3)
            inputs.append(distance)

        return inputs
