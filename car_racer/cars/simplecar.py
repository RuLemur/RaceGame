import math
import time

import pygame

from car_racer.cars.abs_car import Car
from car_racer.cars.physic_car import CHECKPOINT_LOOKAHEAD_WEIGHT
from car_racer.constants import GRAY, WHITE, MAX_TIMEOUT, SENSOR_RANGE
from car_racer.screen.screen import Screen
from helpers.calculate import calculate_end_pos, get_midpoint, cast_ray, min_distance_to_segments

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

        self.next_checkpoint_index = 0
        self.cl_count = 0
        self.lap_count = 0
        self.fitness = 0
        self.lap_start_time = time.time()
        self.lap_time = 0
        # См. PhyCar._sensor_debug/draw_sensors - тот же кэш-и-рисуй-позже
        # приём, синхронно с PhyCar по конвенции проекта.
        self._sensor_debug = []

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
        # Сенсоры рисуются до спрайта - см. PhyCar.draw/draw_sensors.
        self.draw_sensors()

        # Позиция/спрайт машины проходят через камеру (см.
        # car_racer/screen/camera.py и PhyCar.draw) - rotozoom вместо rotate,
        # чтобы спрайт масштабировался под zoom. Мировые self.x/self.y камера
        # не трогает - только то, что реально передаётся в pygame.draw.*/blit.
        camera = self.screen.camera
        rotated_image = pygame.transform.rotozoom(self.car_image, -self.angle - self.drift, camera.zoom)
        screen_pos = camera.world_to_screen((self.x, self.y))
        self.car_rect = rotated_image.get_rect(center=screen_pos)
        self.screen.get_window().blit(rotated_image, self.car_rect.topleft)
        self.collistion_rect = pygame.Rect(self.x - (CAR_WIDTH // 4), self.y - (CAR_HEIGHT // 4),
                                           CAR_WIDTH // 2, CAR_WIDTH // 2)
        debug_rect = pygame.Rect(0, 0, camera.scale_length(CAR_WIDTH // 2), camera.scale_length(CAR_WIDTH // 2))
        debug_rect.center = camera.world_to_screen(self.collistion_rect.center)
        pygame.draw.rect(self.screen.get_window(), (255, 255, 255), debug_rect)

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
        # ЧИСТАЯ геометрия - см. PhyCar.draw_line/draw_sensors про то, почему
        # отрисовка вынесена в draw_sensors() (вызывается из draw(), после
        # screen.draw_track() в рендер-блоке, а не отсюда).
        direction_deg = -self.angle + angle
        return direction_deg

    def draw_sensors(self):
        """См. PhyCar.draw_sensors - тот же приём, синхронно."""
        if not self.screen.show_sensors:
            return
        camera = self.screen.camera
        for car_position, line_end_pos, hit_point in self._sensor_debug:
            pygame.draw.line(self.screen.get_window(), GRAY,
                             camera.world_to_screen(car_position), camera.world_to_screen(line_end_pos), 1)
            if hit_point is not None:
                pygame.draw.circle(self.screen.get_window(), WHITE,
                                   camera.world_to_screen(hit_point), camera.scale_length(3))

    def check_collision_with_track(self):
        # Барьер "далеко за пределами трассы" - bounding box трассы + отступ
        # (см. Screen._recompute_world_bounds), не фиксированные screen_width/
        # screen_height - см. синхронный комментарий в PhyCar.check_collision_with_track
        # (эти два метода поддерживаются в паре, см. CLAUDE.md).
        min_x, min_y, max_x, max_y = self.screen.world_bounds
        if self.x <= min_x or self.x >= max_x or self.y <= min_y or self.y >= max_y:
            return True
        # Векторизованная (numpy) проверка вместо Python-цикла с
        # pygame.Rect.clipline() по каждому сегменту трассы - см.
        # PhyCar.check_collision_with_track и helpers.calculate.min_distance_to_segments.
        collision_radius = CAR_WIDTH * math.sqrt(2) / 2
        distance = min_distance_to_segments(
            (self.x, self.y), self.screen.track_segments_start, self.screen.track_segments_end)
        return distance <= collision_radius

    def check_collision_with_checkpoint(self):
        if self.next_checkpoint_index >= len(self.screen.checkpoints_lines):
            return False
        line_start, line_end = self.screen.checkpoints_lines[self.next_checkpoint_index]
        if self.collistion_rect.clipline(line_start, line_end):
            self.next_checkpoint_index += 1
            self.cl_count += 1
            return True
        return False

    def check_collision_with_start(self):
        line_start, line_end = self.screen.start_line
        if (self.collistion_rect.clipline(line_start, line_end) and
                self.next_checkpoint_index == len(self.screen.checkpoints_lines)):
            self.next_checkpoint_index = 0
            self.lap_count += 1
            self.lap_time = time.time() - self.lap_start_time
            self.lap_start_time = time.time()
            return True
        return False


    def _gate_midpoint(self, index):
        """См. PhyCar._gate_midpoint - тот же хэлпер, синхронизирован."""
        checkpoints = self.screen.checkpoints_lines
        if index < len(checkpoints):
            p1, p2 = checkpoints[index]
        else:
            p1, p2 = self.screen.start_line
        return get_midpoint((p1, p2))

    def _heading_error_to_next_checkpoint(self):
        """См. PhyCar._heading_error_to_next_checkpoint - тот же сглаженный
        (CHECKPOINT_LOOKAHEAD_WEIGHT) "компас", синхронизирован с PhyCar по
        конвенции сенсоров/чекпоинтов (см. CLAUDE.md)."""
        idx = self.next_checkpoint_index
        target_x, target_y = self._gate_midpoint(idx)
        if idx < len(self.screen.checkpoints_lines):
            look_x, look_y = self._gate_midpoint(idx + 1)
            w = CHECKPOINT_LOOKAHEAD_WEIGHT
            target_x = target_x * w + look_x * (1 - w)
            target_y = target_y * w + look_y * (1 - w)
        car_x, car_y = self.get_postion()
        target_angle = math.atan2(target_y - car_y, target_x - car_x)
        heading_error = target_angle - math.radians(self.angle)
        heading_error = math.atan2(math.sin(heading_error), math.cos(heading_error))
        return heading_error / math.pi

    def get_inputs_for_network(self):
        # Нормализуем угол в [-1, 1] (не накапливается при многократных оборотах)
        normalized_angle = math.atan2(math.sin(math.radians(self.angle)), math.cos(math.radians(self.angle))) / math.pi
        normalized_speed = min(self.get_speed() / MAX_SPEED, 1.0)
        inputs = [normalized_angle, normalized_speed, self._heading_error_to_next_checkpoint()]

        car_position = self.get_postion()
        seg_starts = self.screen.track_segments_start
        seg_ends = self.screen.track_segments_end

        self._sensor_debug = []
        for angle in [-150, -90, -45, 0, 45, 90, 150]:
            direction_deg = self.draw_line(angle)
            distance, hit_point = cast_ray(car_position, direction_deg, SENSOR_RANGE, seg_starts, seg_ends)
            line_end_pos = calculate_end_pos(car_position, direction_deg, SENSOR_RANGE)
            self._sensor_debug.append((car_position, line_end_pos, hit_point))
            inputs.append(distance / SENSOR_RANGE)

        return inputs
