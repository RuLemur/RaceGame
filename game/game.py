import pygame
import math
from shapely.geometry import LineString

from pygame import Surface
from shapely.geometry.base import BaseGeometry

# Инициализация Pygame
pygame.init()

# трасса
TRACK_COLOR = (50, 50, 50)
TRACK = [[95, 114], [237, 64], [385, 48], [532, 86], [613, 140], [756, 127], [891, 75], [1081, 51], [1141, 144],
         [1134, 237], [1089, 315], [1035, 400], [967, 409], [871, 430], [819, 457], [869, 533], [938, 622], [918, 694],
         [722, 740], [556, 742], [450, 748], [421, 654], [331, 623], [215, 618], [172, 665], [97, 683], [57, 572],
         [79, 390], [63, 300], [47, 222], [96, 114]]
TRACK2 = [[298, 190], [408, 197], [486, 249], [570, 287], [692, 254], [849, 222], [920, 226], [924, 243], [892, 303],
          [808, 330], [737, 358], [714, 401], [667, 440], [669, 506], [689, 559], [746, 601], [635, 619], [565, 600],
          [497, 551], [473, 502], [389, 478], [284, 477], [229, 481], [179, 415], [202, 312], [201, 215]]

# Константы
FORCE = 0.5  # Сила для ускорения
MAX_SPEED = 9
MAX_SPEED_REVERS = 3
DECELERATION = 0.05
GRIP = 0.01  # Коэффициент сцепления для дрифта
DRIFT_FACTOR = 0.2  # Коэффициент дрифта
BLACK = (0, 0, 0)
SCREEN_WIDTH, SCREEN_HEIGHT = 1200, 800
FPS = 60
CAR_WIDTH, CAR_HEIGHT = 65, 30
WHITE = (255, 255, 255)

# Настройка окна
win = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Car Racing")

# Загрузка изображений
car_image = pygame.image.load("./assets/car.png")
car_image = pygame.transform.scale(car_image, (CAR_WIDTH, CAR_HEIGHT))


# Функция для вычисления конечной точки
def calculate_end_pos(start_pos, angle_degrees, length):
    angle_radians = math.radians(angle_degrees)
    end_x = start_pos[0] + length * math.cos(angle_radians)
    end_y = start_pos[1] - length * math.sin(angle_radians)  # Минус, потому что ось Y направлена вниз
    return int(end_x), int(end_y)


class Car:
    def __init__(self, x, y, mass=1.0):
        self.x = x
        self.y = y
        self.angle = 270
        self.speed = 0
        self.mass = mass
        self.drift = 0

    def draw(self, win):
        # car_position = (self.x, self.y)
        rotated_image = pygame.transform.rotate(car_image, -self.angle - self.drift)
        new_rect = rotated_image.get_rect(center=(self.x, self.y))
        win.blit(rotated_image, new_rect.topleft)

    def update(self):
        rad = math.radians(self.angle + self.drift)
        self.x += self.speed * math.cos(rad)
        self.y += self.speed * math.sin(rad)

        # Плавное возвращение из дрифта
        self.drift *= 0.9

    def handle_keys(self):
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT] and self.speed != 0:
            # Увеличиваем дрифт при повороте
            self.angle -= 5 * (1 - GRIP * self.speed / self.mass)
            # self.drift -= DRIFT_FACTOR * self.speed / MAX_SPEED
        if keys[pygame.K_RIGHT] and self.speed != 0:
            self.angle += 5 * (1 - GRIP * self.speed / self.mass)
            # self.drift += DRIFT_FACTOR * self.speed / MAX_SPEED
        if keys[pygame.K_UP]:
            self.speed += FORCE / self.mass
        elif keys[pygame.K_DOWN]:
            self.speed -= FORCE / self.mass
        else:
            # Замедление, когда нет нажатия клавиш
            if self.speed > 0:
                self.speed -= DECELERATION / self.mass
            elif self.speed < 0:
                self.speed += DECELERATION / self.mass

        # Ограничиваем скорость
        if self.speed > MAX_SPEED:
            self.speed = MAX_SPEED
        elif self.speed < -MAX_SPEED_REVERS:
            self.speed = -MAX_SPEED_REVERS

        # Устанавливаем скорость в 0, если она очень мала
        if abs(self.speed) < DECELERATION / self.mass:            self.speed = 0


def check_collision(car_rect, track_lines):
    for i in range(len(track_lines) - 1):
        line_start = track_lines[i]
        line_end = track_lines[i + 1]
        if car_rect.clipline(line_start, line_end):
            return True
    return False


# Создание машины
car = Car(130, 500)
font = pygame.font.Font('freesansbold.ttf', 32)

# Основной цикл
clock = pygame.time.Clock()
running = True
while running:
    clock.tick(FPS)
    # print(clock.get_fps())
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Обновление машины
    car.handle_keys()
    car.update()

    # Отрисовка трассы
    win.fill(BLACK)
    pygame.draw.lines(win, TRACK_COLOR, True, TRACK, 3)
    pygame.draw.lines(win, TRACK_COLOR, True, TRACK2, 3)

    for line in [TRACK, TRACK2]:
        car_position = (car.x, car.y)
        line_end_pos = calculate_end_pos(car_position, -car.angle, 500)
        pygame.draw.line(win, WHITE, car_position, line_end_pos, 2)

        main_line = LineString([car_position, line_end_pos])

        # Проходим по сегментам линии
        for i in range(len(line) - 1):
            checked_line = LineString([line[i], line[i+1]])

            # Проверяем пересечение
            intersection = main_line.intersection(checked_line)
            # Рисуем ближайшую точку пересечения
            if not intersection.is_empty:
                # Вычисляем расстояние до точки пересечения от начала основной линии
                distance = main_line.project(intersection)
                distanceText = font.render(f"{distance:.2f}", True, WHITE, BLACK)
                win.blit(distanceText, (10, 10))
                pygame.draw.circle(win, WHITE, intersection.coords[0], 5)


    # Проверка на столкновение с трассой
    car_rect = pygame.Rect(car.x - CAR_WIDTH // 2, car.y - CAR_HEIGHT // 2, CAR_WIDTH, CAR_HEIGHT)
    if check_collision(car_rect, TRACK) or check_collision(car_rect, TRACK2):
        # Перезапуск игры
        car = Car(130, 500)  # Сброс машины на начальную позицию

    # Отрисовка машины
    car.draw(win)

    pygame.display.flip()

pygame.quit()
