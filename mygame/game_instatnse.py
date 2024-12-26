import math
import time

import neat
import pygame
from shapely.geometry.linestring import LineString

from mygame.car import Car
from mygame.constants import WHITE, TIMEOUT, DECELERATION, FORCE, CAR_WIDTH, GRIP, RED, BLACK, GRAY, MAX_TIMEOUT


def get_midpoint(sl):
    x1, y1 = sl[0]
    x2, y2 = sl[1]
    return (x1 + x2) / 2, (y1 + y2) / 2


# Функция для вычисления конечной точки
def calculate_end_pos(start_pos, angle_degrees, length):
    angle_radians = math.radians(angle_degrees)
    end_x = start_pos[0] + length * math.cos(angle_radians)
    end_y = start_pos[1] - length * math.sin(angle_radians)  # Минус, потому что ось Y направлена вниз
    return int(end_x), int(end_y)


class GameEnvironment:
    def __init__(self, genome, config, genome_id, window, track_outer, track_inner, checkpoints_lines, start_line):
        start_x, start_y = get_midpoint(start_line)
        self.track_outer = track_outer
        self.track_inner = track_inner
        self.checkpoints_lines = checkpoints_lines
        self.start_line = start_line

        self.genome = genome
        self.network = neat.nn.FeedForwardNetwork.create(genome, config)
        self.car = Car(start_x, start_y)
        self.fitness = 0
        self.crossed_lines = 0
        self.laps = 0
        self.already_crossed = []
        self.genome_id = genome_id
        self.start_time = time.time()
        self.timeout = TIMEOUT
        self.window = window
        self.active = True

    def update(self):
        elapsed_time = self.timeout - (time.time() - self.start_time)
        if elapsed_time <= 0 or not self.active:
            self.active = False
            return
        if time.time() - self.start_time > MAX_TIMEOUT:
            self.active = False
            return

        # Получение входных данных для нейросети
        inputs = self.get_inputs_for_network()

        # Получение выходных данных от нейросети
        output = self.network.activate(inputs)

        # Управление автомобилем на основе выходов сети
        if output[0] > 0.5:
            self.car.angle -= 5 * (1 - GRIP * self.car.speed / self.car.mass)
        if output[0] < -0.5:
            self.car.angle += 5 * (1 - GRIP * self.car.speed / self.car.mass)
        if output[1] > 0.5:
            self.car.speed += FORCE / self.car.mass
        elif output[1] < -0.5:
            if (self.car.speed - FORCE / self.car.mass) > 0:
                self.car.speed -= FORCE / self.car.mass
        else:
            if self.car.speed > 0:
                self.car.speed -= DECELERATION / self.car.mass

        # Обновление машины
        self.car.update()

        # Проверка столкновений и обновление фитнеса
        if self.check_collision(self.track_outer) or self.check_collision(self.track_inner) or self.out_of_screen():
            self.crossed_lines = 0
            self.active = False
        if self.check_collision_by_line(self.checkpoints_lines, False):
            self.crossed_lines += 1
            self.fitness += self.car.speed * (self.laps+1)
            self.timeout += 10
        if (self.check_collision_by_line([self.start_line], True)
                and self.crossed_lines > 0
                and self.crossed_lines % len(self.checkpoints_lines) == 0):
            self.fitness += 10 * self.car.speed * (self.laps+1)
            self.laps += 1
            self.crossed_lines = 0
            self.already_crossed = []
        self.fitness += self.car.speed * 0.05

    def render(self):
        self.car.draw(self.window)

    def get_fitness(self):
        return self.fitness

    def get_cl(self):
        return self.crossed_lines

    def get_laps(self):
        return self.laps

    def draw_line(self, angle: int):
        car_position = (self.car.x, self.car.y)
        line_end_pos = calculate_end_pos(car_position, -self.car.angle + angle, 500)
        pygame.draw.line(self.window, GRAY, car_position, line_end_pos, 1)
        m_line = LineString([car_position, line_end_pos])
        return m_line

    def get_inputs_for_network(self):
        # Пример: используем расстояния до ближайших препятствий как входы
        inputs = [self.car.angle, self.car.speed]

        for angle in [-150, -90, -45, 0, 45, 90, 150]:
            main_line = self.draw_line(angle)
            distance = float('inf')
            for line in [self.track_outer, self.track_inner]:
                for i in range(len(line) - 1):
                    checked_line = LineString([line[i], line[i + 1]])
                    intersection = main_line.intersection(checked_line)
                    if not intersection.is_empty:
                        distance = min(distance, main_line.project(intersection))
                        pygame.draw.circle(self.window, WHITE, intersection.coords[0], 3)
            inputs.append(distance)

        return inputs

    def out_of_screen(self):
        return self.car.x <= 0 or self.car.y <= 0

    def check_collision(self, track_lines):
        car_rect = self.get_rect()
        for i in range(len(track_lines) - 1):
            line_start = track_lines[i]
            line_end = track_lines[i + 1]
            if car_rect.clipline(line_start, line_end):
                return True
        return False

    def get_rect(self):
        rect = pygame.Rect(self.car.x - CAR_WIDTH // 3, self.car.y - CAR_WIDTH // 3, CAR_WIDTH, CAR_WIDTH)
        # pygame.draw.rect(self.window, WHITE, rect, 3)
        return rect

    def check_collision_by_line(self, track_lines, is_start_line):
        car_rect = self.get_rect()
        for line in track_lines:
            line_start, line_end = line
            if car_rect.clipline(line_start, line_end) and (line_start, line_end) not in self.already_crossed:
                if not is_start_line:
                    self.already_crossed.append((line_start, line_end))
                return True
        return False
