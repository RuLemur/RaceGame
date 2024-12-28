import time

import neat
import pymunk.pygame_util

from car_racer.cars.physic_car import PhyCar
from car_racer.cars.simplecar import SimpleCar
from car_racer.constants import TIMEOUT, MAX_TIMEOUT

# Инициализация Pymunk
space = pymunk.Space()
space.gravity = (0, 0)  # Отсутствие гравитации в игре с видом сверху


class GameEnvironment:
    def __init__(self, genome, config, genome_id, screen):
        self.screen = screen

        self.genome = genome
        self.network = neat.nn.FeedForwardNetwork.create(genome, config)
        # self.car = SimpleCar(screen, car_size=(35, 75))
        self.car = PhyCar(screen, car_size=(15, 35))

        self.genome_id = genome_id
        self.start_time = time.time()
        self.timeout = TIMEOUT
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
        inputs = self.car.get_inputs_for_network()

        # Получение выходных данных от нейросети
        output = self.network.activate(inputs)

        # Управление автомобилем на основе выходов сети
        if output[0] > 0.5:
            self.car.throttle(output[0])
        if output[0] < -0.5:
            self.car.throttle(output[0])
        if output[1] > 0.5:
            self.car.turn(output[1])
        elif output[1] < -0.5:
            self.car.turn(output[1])

        # Обновление машины
        self.car.update()

        # Проверка столкновений и обновление фитнеса
        if self.car.check_collision_with_track():
            self.car.cl_count = 0
            self.active = False
        if self.car.check_collision_with_checkpoint():
            self.car.add_fitness(1)
            self.timeout += 10
        if self.car.check_collision_with_start():
            self.car.add_fitness(5)
            if self.car.get_lap_time() > 0:
                self.car.add_fitness(20 / self.car.get_lap_time())

    def render(self):
        self.car.draw()
