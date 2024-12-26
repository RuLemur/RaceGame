import math
import time

import neat
import pygame
from shapely.geometry.linestring import LineString

from mygame.car import Car
from mygame.constants import WHITE, TIMEOUT, DECELERATION, FORCE, CAR_WIDTH, GRIP, RED, BLACK, GRAY


def out_of_screen(car):
    return car.x <= 0 or car.y <= 0


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


def check_collision(car_rect, track_lines):
    for i in range(len(track_lines) - 1):
        line_start = track_lines[i]
        line_end = track_lines[i + 1]
        if car_rect.clipline(line_start, line_end):
            return True
    return False


def check_collision_by_line(car_rect, track_lines, already_crossed):
    for line in track_lines:
        line_start, line_end = line
        if car_rect.clipline(line_start, line_end) and (line_start, line_end) not in already_crossed:
            already_crossed.append((line_start, line_end))
            return True
    return False


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
        car_rect = pygame.Rect(self.car.x - CAR_WIDTH // 2, self.car.y - CAR_WIDTH // 2, CAR_WIDTH // 2, CAR_WIDTH // 2)
        if check_collision(car_rect, self.track_outer) or check_collision(car_rect, self.track_inner) or out_of_screen(
                self.car):
            self.crossed_lines = 0
            self.active = False
        if check_collision_by_line(car_rect, self.checkpoints_lines, self.already_crossed):
            self.crossed_lines += 1
            self.fitness += 1000 * self.crossed_lines
            self.timeout += 10
        if (check_collision_by_line(car_rect, [self.start_line], self.already_crossed)
                and self.crossed_lines > 0
                and self.crossed_lines % len(self.checkpoints_lines) == 0):
            self.fitness += 5000 * self.crossed_lines

        self.fitness += self.car.speed * 0.15

    def render(self):
        self.car.draw(self.window)

    def get_fitness(self):
        return self.fitness

    def get_cl(self):
        return self.crossed_lines

    def draw_line(self, angle: int):
        car_position = (self.car.x, self.car.y)
        line_end_pos = calculate_end_pos(car_position, -self.car.angle + angle, 500)
        pygame.draw.line(self.window, GRAY, car_position, line_end_pos, 1)
        m_line = LineString([car_position, line_end_pos])
        return m_line

    def print_x(self, coords):
        cross_length = 20

        pos_x, pos_y = coords
        # Координаты концов линий крестика
        left_top = (pos_x - cross_length, pos_y - cross_length)
        right_bottom = (pos_x + cross_length, pos_y + cross_length)
        right_top = (pos_x + cross_length, pos_y - cross_length)
        left_bottom = (pos_x - cross_length, pos_y + cross_length)

        # Рисование линий крестика
        pygame.draw.line(self.window, RED, left_top, right_bottom, 5)
        pygame.draw.line(self.window, RED, right_top, left_bottom, 5)

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
                        pygame.draw.circle(self.window, WHITE, intersection.coords[0], 5)
            inputs.append(distance)

        return inputs

    def draw_intersaction(self, m_line, inters, y_text_pos):
        if not inters.is_empty:
            # Вычисляем расстояние до точки пересечения от начала основной линии
            pygame.draw.circle(self.window, WHITE, inters.coords[0], 5)
