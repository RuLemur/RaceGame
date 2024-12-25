import math
import pygame

from mygame.constants import CAR_WIDTH, CAR_HEIGHT, FORCE, DECELERATION, MAX_SPEED, MAX_SPEED_REVERS

# Загрузка изображений
car_image = pygame.image.load("./assets/car.png")
car_image = pygame.transform.scale(car_image, (CAR_WIDTH, CAR_HEIGHT))
car_image = pygame.transform.rotate(car_image, -90)


class Car:
    def __init__(self, x, y, mass=1.0):
        self.x = x
        self.y = y
        self.angle = -90
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
