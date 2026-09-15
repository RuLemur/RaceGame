import neat

from car_racer.cars.physic_car import PhyCar
from car_racer.constants import TIMEOUT, MAX_TIMEOUT, TICK_RATE


class GameEnvironment:
    def __init__(self, genome, config, genome_id, screen, visible, space=None):
        self.screen = screen

        self.genome = genome
        self.network = neat.nn.FeedForwardNetwork.create(genome, config)
        self.car = PhyCar(screen, visible, car_size=(15, 35), space=space)

        self.genome_id = genome_id
        self.ticks_elapsed = 0
        self.timeout_ticks = TIMEOUT * TICK_RATE
        self.max_timeout_ticks = MAX_TIMEOUT * TICK_RATE
        self.active = True

    def decide(self):
        """Считать сенсоры, прогнать сеть, применить газ/руль. Физику не
        шагает - для группы это делает один общий pymunk.Space снаружи, один
        раз на весь тик (см. car_racer/neat_runner/main.py: decide() для всех
        машин -> space.step() -> resolve() для всех машин)."""
        if not self.active:
            return
        if self.ticks_elapsed >= self.timeout_ticks or self.ticks_elapsed >= self.max_timeout_ticks:
            # Та же "утешительная" премия за пройденную дистанцию, что и при
            # столкновении со стеной (см. PhyCar.add_distance_consolation_fitness)
            # - раньше эпизод, закончившийся по таймауту (а не аварией),
            # вообще не получал этот бонус, хотя мог пройти ту же дистанцию:
            # эволюция не отличала "долго аккуратно ехал, но не успел" от
            # "стоял на месте всю дорогу".
            self.car.add_distance_consolation_fitness()
            self.active = False
            return

        inputs = self.car.get_inputs_for_network()
        output = self.network.activate(inputs)
        self.car.throttle(output[0])
        self.car.turn(output[1])

    def resolve(self):
        """Вызывать после шага общего Space: обновить состояние машины и
        проверить столкновения/чекпоинты/фитнес за этот тик."""
        if not self.active:
            return
        self.ticks_elapsed += 1
        self.car.update()

        if self.car.check_collision_with_track():
            self.car.cl_count = 0
            self.active = False
        if self.car.check_collision_with_checkpoint():
            self.car.add_fitness(1)
            self.timeout_ticks += 10 * TICK_RATE
        if self.car.check_collision_with_start():
            self.car.add_fitness(5)
            if self.car.get_lap_time() > 0:
                self.car.add_fitness(20 / self.car.get_lap_time())

    def update(self):
        """decide() + resolve() одним вызовом - для одиночного использования
        без общего Space (тогда car.update() сам шагнёт свою физику)."""
        self.decide()
        self.resolve()

    def render(self):
        self.car.draw()
