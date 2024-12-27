import math
import time

import neat
import pygame
import pymunk
import pymunk.pygame_util
from shapely.geometry.linestring import LineString

from mygame.constants import WHITE, TIMEOUT, GRAY, MAX_TIMEOUT
from mygame.physic_car import PhyCar

from helpers.calculate import get_midpoint

# Инициализация Pymunk
space = pymunk.Space()
space.gravity = (0, 0)  # Отсутствие гравитации в игре с видом сверху



class GameEnvironment:
    def __init__(self, genome, config, genome_id, window, track_outer, track_inner, checkpoints_lines, start_line):
        start_x, start_y = get_midpoint(start_line)
        self.track_outer = track_outer
        self.track_inner = track_inner
        self.checkpoints_lines = checkpoints_lines
        self.start_line = start_line

        self.genome = genome
        self.network = neat.nn.FeedForwardNetwork.create(genome, config)
        self.car = PhyCar(space, (start_x, start_y), (50, 30), False, pymunk.pygame_util.DrawOptions(window))
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
            self.car.turn_power = 1.0
        if output[0] < -0.5:
            self.car.turn_power = 1.0
        if output[1] > 0.5:
            self.car.throttle_power = 1.0
        elif output[1] < -0.5:
            self.car.throttle_power = 1.0

        # Обновление машины
        self.car.car_update()

        # Проверка столкновений и обновление фитнеса
        if self.check_collision(self.track_outer) or self.check_collision(self.track_inner) or self.out_of_screen():
            self.crossed_lines = 0
            self.active = False
        if self.check_collision_by_line(self.checkpoints_lines, False):
            self.crossed_lines += 1
            self.fitness += self.laps + 1
            self.timeout += 10
        if (self.check_collision_by_line([self.start_line], True)
                and self.crossed_lines > 0
                and self.crossed_lines % len(self.checkpoints_lines) == 0):
            self.fitness += 10 * (self.laps + 1)
            self.laps += 1
            self.crossed_lines = 0
            self.already_crossed = []
        # self.fitness += self.car.speed * 0.05

    def render(self):
        self.car.draw(self.window)

    def get_fitness(self):
        return self.fitness

    def get_cl(self):
        return self.crossed_lines

    def get_laps(self):
        return self.laps

    def draw_line(self, angle: int):
        car_position = self.car.get_car_position()
        line_end_pos = calculate_end_pos(car_position, -self.car.body.angle + angle, 500)
        pygame.draw.line(self.window, GRAY, car_position, line_end_pos, 1)
        m_line = LineString([car_position, line_end_pos])
        return m_line

    def get_inputs_for_network(self):
        # Пример: используем расстояния до ближайших препятствий как входы
        inputs = [self.car.body.angle, self.car.get_speed()]

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
        x, y = self.car.get_car_position()
        return x <= 0 or y <= 0

    def check_collision(self, track_lines):
        car_rect = self.car.get_car_rect()
        for i in range(len(track_lines) - 1):
            line_start = track_lines[i]
            line_end = track_lines[i + 1]
            if car_rect.clipline(line_start, line_end):
                return True
        return False

    def check_collision_by_line(self, track_lines, is_start_line):
        car_rect = self.car.get_car_rect()
        for line in track_lines:
            line_start, line_end = line
            if car_rect.clipline(line_start, line_end) and (line_start, line_end) not in self.already_crossed:
                if not is_start_line:
                    self.already_crossed.append((line_start, line_end))
                return True
        return False
