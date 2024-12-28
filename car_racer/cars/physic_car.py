import math
import time

import pygame
import pymunk

import pymunk.pygame_util
from shapely.geometry.linestring import LineString

from car_racer.cars.abs_car import Car
from car_racer.constants import GRAY, WHITE
from car_racer.screen.screen import Screen
from helpers.calculate import calculate_end_pos, get_midpoint

CAR_HEIGHT = 80
CAR_WIDTH = 50
VELOCITY_EPSILON = 0.1
ROTATE_POWER = 3.5  # Сила поворота
THROTTLE_POWER = 200  # Сила тяги
MAX_SPEED = 600  # Установи подходящее значение
SPEED_EFFECT = 0.3  # Чем больше значение, тем меньше поворот на высокой скорости
ACCELERATION_RATE = 0.2
BRAKE_RATE = 15


class PhyCar(Car):
    def __init__(self, screen: Screen, car_size):
        car_image = pygame.image.load("./assets/car.png")
        car_image = pygame.transform.scale(car_image, car_size)
        car_image = pygame.transform.rotate(car_image, -90)
        self.car_image = car_image

        self.lap_start_time = time.time()
        self.best_lap_time = 0
        self.cl_count = 0
        self.fitness = 0
        self.lap_count = 0
        self.already_crossed = []
        self.mass = 1
        self.car_size = car_size

        self.damping_rate = 0.93  # Коэффициент гашения скорости

        self.moment = pymunk.moment_for_box(self.mass, self.car_size)

        body = pymunk.Body(self.mass, self.moment)
        body.position = get_midpoint(screen.start_line)
        shape = pymunk.Poly.create_box(body, self.car_size)

        self.car_rect = car_image.get_rect(center=body.position)

        shape.friction = 0.11

        self.screen = screen

        self.space = pymunk.Space()
        self.space.gravity = (0, 0)  # Отсутствие гравитации в игре с видом сверху
        self.space.add(body, shape)

        self.body = body
        self.draw_options = pymunk.pygame_util.DrawOptions(self.screen.get_window())
        self.draw_speed_vectore = True
        self.x, self.y = self.car_size
        self.collistion_rect = pygame.Rect(self.body.position.x - self.x // 3,
                                           self.body.position.y - self.x // 3,
                                           self.x, self.x)
        self.perpendicular_angle(self.screen.start_line)


    def throttle(self, throttle_power):
        if throttle_power != 0:
            # Ограничиваем throttle_power в пределах от 0 до 1
            throttle_power = max(0, min(1, throttle_power))

            target_speed = throttle_power * MAX_SPEED
            current_speed = self.body.velocity.length

            if throttle_power > 0:
                # Если throttle_power больше 0, разгоняемся
                new_speed = current_speed + (target_speed - current_speed) * ACCELERATION_RATE
            else:
                # Если throttle_power равно 0, замедляемся
                new_speed = current_speed - BRAKE_RATE
                if new_speed < 0:
                    new_speed = 0

                # Обновляем вектор скорости
            if new_speed > MAX_SPEED:
                new_speed = MAX_SPEED

            direction = pymunk.Vec2d(1, 0).rotated(self.body.angle)
            self.body.velocity = direction.normalized() * new_speed

    def turn(self, turn_power):
        # Чем выше скорость, тем хуже управляемость
        current_speed = self.body.velocity.length

        if current_speed < VELOCITY_EPSILON:
            return

        # Уменьшаем поворотное усилие при увеличении скорости
        turn_effectiveness = max(0.05, 1 - SPEED_EFFECT * (current_speed / MAX_SPEED))
        if turn_power != 0:
            angular_change = turn_power * ROTATE_POWER * turn_effectiveness
            self.body.angular_velocity += angular_change

            # Ограничиваем максимальную угловую скорость
            self.body.angular_velocity = max(min(self.body.angular_velocity, ROTATE_POWER), -ROTATE_POWER)

    def update(self):
        self.space.step(1 / 60)
        self.collistion_rect = pygame.Rect(self.body.position.x - self.x // 3,
                                           self.body.position.y - self.x // 3,
                                           self.x, self.x)

    def damping(self, throttle: bool, turning: bool):
        if throttle:
            self.body.velocity *= self.damping_rate
        if turning:
            self.body.angular_velocity *= self.damping_rate
        self.body.velocity = pymunk.Vec2d(1, 0).rotated(self.body.angle) * self.get_speed()

    def draw(self):
        #     for a in [-140, -90, -30, 0, 30, 90, 140]:
        #         self.draw_line(a)

        rotated_image = pygame.transform.rotate(self.car_image, -math.degrees(self.body.angle))
        self.car_rect = rotated_image.get_rect(center=self.body.position)
        if self.draw_speed_vectore:
            # self.space.debug_draw(self.draw_options)

            # Отрисовка вектора силы
            if self.body.velocity.length > 0:
                end_pos_velocity = self.body.position + self.body.velocity.normalized() * self.get_speed()
                pygame.draw.line(self.screen.get_window(), (0, 0, 255), self.body.position, end_pos_velocity, 3)

        self.screen.get_window().blit(rotated_image, self.car_rect.topleft)
        pygame.draw.rect(self.screen.get_window(), (255, 255, 255), self.collistion_rect)

    def _get_max_velocity(self):
        return max(self.body.velocity.x, self.body.velocity.y)

    def _get_min_velocity(self):
        return min(self.body.velocity.x, self.body.velocity.y)

    def get_lap_time(self):
        return self.best_lap_time

    def get_fitness(self):
        return self.fitness

    def get_cl(self):
        return self.cl_count

    def add_fitness(self, fitness):
        self.fitness += fitness

    def get_laps(self):
        return self.lap_count

    def get_postion(self) -> (int, int):
        return self.body.position.x, self.body.position.y

    def get_speed(self) -> float:
        return self.body.velocity.length

    def draw_line(self, angle: int):
        car_position = self.get_postion()
        line_end_pos = calculate_end_pos(car_position, -math.degrees(self.body.angle) + angle, 500)
        pygame.draw.line(self.screen.get_window(), GRAY, car_position, line_end_pos, 1)
        m_line = LineString([car_position, line_end_pos])
        return m_line

    def check_collision_with_track(self):
        for track_lines in [self.screen.track_inner, self.screen.track_outer]:
            for i in range(len(track_lines) - 1):
                line_start = track_lines[i]
                line_end = track_lines[i + 1]

                if (self.collistion_rect.clipline(line_start, line_end) or
                        (self.body.position.x <= 0 or self.body.position.x >= self.screen.screen_width
                         or self.body.position.y <= 0 or self.body.position.y >= self.screen.screen_height)):
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
            self.best_lap_time = time.time() - self.lap_start_time
            self.lap_start_time = time.time()
            return True
        return False

    def get_inputs_for_network(self):
        # Пример: используем расстояния до ближайших препятствий как входы
        inputs = [self.body.angle, self.get_speed()]

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

    def perpendicular_angle(self, line):
        # Создаем вектора из точек
        p1, p2 = line
        vec = pymunk.Vec2d(p2[0] - p1[0], p2[1] - p1[1])

        # Угол вектора относительно оси x
        angle = vec.angle  # Это возвращает угол в радианах относительно оси x

        self.body.angle = angle + math.pi / 2  # 90 градусов в радианах
