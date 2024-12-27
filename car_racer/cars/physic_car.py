import math

import pygame
import pymunk

import pymunk.pygame_util
from shapely.geometry.linestring import LineString

from car_racer.constants import GRAY
from car_racer.screen.screen import Screen
from helpers.calculate import calculate_end_pos, get_midpoint

CAR_HEIGHT = 80
CAR_WIDTH = 50
VELOCITY_EPSILON = 0.1
ROTATE_POWER = 5  # Сила тяги
THROTTLE_POWER = 25  # Сила тяги


# Загрузка изображений


class PhyCar:
    def __init__(self, screen: Screen, car_size):
        car_image = pygame.image.load("./assets/car.png")
        car_image = pygame.transform.scale(car_image, car_size)
        car_image = pygame.transform.rotate(car_image, -90)
        self.car_image = car_image

        self.cl_count = 0
        self.fitness = 0
        self.lap_count = 0
        self.already_crossed = []
        self.mass = 1000
        self.car_size = car_size

        self.damping = 0.95  # Коэффициент гашения скорости

        self.moment = pymunk.moment_for_box(self.mass, self.car_size)

        body = pymunk.Body(self.mass, self.moment)
        body.position = get_midpoint(screen.start_line)
        shape = pymunk.Poly.create_box(body, self.car_size)
        width, height = car_size
        # vertices = [(10, -height / 2), (-width, -height / 2), (-width, height / 2), (10, height / 2)]
        # shape = pymunk.Poly(body, vertices)

        self.car_rect = car_image.get_rect(center=body.position)

        shape.friction = 0.01

        self.screen = screen

        self.space = pymunk.Space()
        self.space.gravity = (0, 0)  # Отсутствие гравитации в игре с видом сверху
        self.space.add(body, shape)

        self.body = body
        self.draw_options = pymunk.pygame_util.DrawOptions(self.screen.get_window())
        self.draw_speed_vectore = True
        self.body.angle = -1.5708

    def get_car(self):
        return self.body

    def throttle(self, throttle_power):
        if throttle_power > 0:
            direction = pymunk.Vec2d(1, 0).rotated(self.body.angle)
            force_vector = direction * throttle_power * THROTTLE_POWER
            self.body.velocity = force_vector  # Сброс скорости и применение новой силы
        elif throttle_power < 0:
            direction = pymunk.Vec2d(1, 0).rotated(self.body.angle)
            force_vector = direction * throttle_power * THROTTLE_POWER
            self.body.velocity = force_vector  # Сброс скорости и применение новой силы

    def turn(self, turn_power):
        if turn_power > 0:
            if abs(self._get_max_velocity()) >= VELOCITY_EPSILON:
                self.body.angular_velocity = min(self.body.angular_velocity + turn_power * ROTATE_POWER,
                                                 ROTATE_POWER)

        elif turn_power < 0:
            if abs(self._get_max_velocity()) >= VELOCITY_EPSILON:
                self.body.angular_velocity = max(self.body.angular_velocity + turn_power * ROTATE_POWER,
                                                 -ROTATE_POWER)

    def update(self):
        print(self.body.angle)

        self.space.step(1 / 60)

    def draw(self):
        rotated_image = pygame.transform.rotate(self.car_image, -math.degrees(self.body.angle))
        self.car_rect = rotated_image.get_rect(center=self.body.position)
        if self.draw_speed_vectore:
            self.space.debug_draw(self.draw_options)

            # Отрисовка вектора силы
            if self.body.velocity.length > 0:
                end_pos_velocity = self.body.position + self.body.velocity.normalized() * 50
                pygame.draw.line(self.screen.get_window(), (0, 0, 255), self.body.position, end_pos_velocity, 3)
        self.screen.get_window().blit(rotated_image, self.car_rect.topleft)

    def get_car_rect(self):
        rect = pygame.Rect(self.body.position.x - CAR_WIDTH // 3, self.body.position.y - CAR_WIDTH // 3,
                           CAR_WIDTH, CAR_WIDTH)
        # pygame.draw.rect(self.window, WHITE, rect, 3)
        return rect

    def _get_max_velocity(self):
        return max(self.body.velocity.x, self.body.velocity.y)

    def _get_min_velocity(self):
        return min(self.body.velocity.x, self.body.velocity.y)

    def get_fitness(self):
        return self.fitness

    def get_cl(self):
        return self.crossed_lines

    def get_laps(self):
        return self.laps

    def get_postion(self) -> (int, int):
        return self.body.position.x, self.body.position.x

    def set_postion(self, x: int, y: int):
        self.body.position.x, self.body.position.x = x, y

    def get_speed(self) -> float:
        return self._get_max_velocity()

    def draw_line(self, angle: int):
        car_position = self.get_postion()
        line_end_pos = calculate_end_pos(car_position, -self.body.angle + angle, 500)
        pygame.draw.line(self.screen.get_window(), GRAY, car_position, line_end_pos, 1)
        m_line = LineString([car_position, line_end_pos])
        return m_line

    def check_collision_with_track(self):
        for track_lines in [self.screen.track_inner, self.screen.track_outer]:
            for i in range(len(track_lines) - 1):
                line_start = track_lines[i]
                line_end = track_lines[i + 1]

                if (self.car_rect.clipline(line_start, line_end) or
                        (self.body.position.x <= 0 or self.body.position.x >= self.screen.screen_height
                         or self.body.position.y <= 0 or self.body.position.y >= self.screen.screen_height)):
                    return True
        return False

    def check_collision_with_checkpoint(self):
        for line in self.screen.checkpoints_lines:
            line_start, line_end = line
            if self.car_rect.clipline(line_start, line_end) and (
                    line_start, line_end) not in self.already_crossed:
                self.already_crossed.append((line_start, line_end))
                self.cl_count += 1
                return True
        line_start, line_end = self.screen.start_line
        if (self.car_rect.clipline(line_start, line_end) and (line_start, line_end) and
                len(self.already_crossed) == self.screen.checkpoints_lines):
            self.already_crossed = []
            self.lap_count += 1
            return True
        return False
