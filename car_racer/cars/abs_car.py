from abc import ABC, abstractmethod


class Car(ABC):
    @abstractmethod
    def throttle(self, throttle_power):
        pass

    @abstractmethod
    def turn(self, turn_power):
        pass

    @abstractmethod
    def update(self):
        pass

    @abstractmethod
    def damping(self, throttle: bool, turning: bool):
        pass

    @abstractmethod
    def draw(self):
        pass

    @abstractmethod
    def add_fitness(self, fitness):
        pass

    @abstractmethod
    def get_fitness(self):
        pass

    @abstractmethod
    def get_cl(self):
        pass

    @abstractmethod
    def get_laps(self):
        pass

    @abstractmethod
    def get_postion(self) -> (int, int):
        pass

    @abstractmethod
    def get_speed(self) -> float:
        pass

    @abstractmethod
    def draw_line(self, angle: int):
        pass

    @abstractmethod
    def check_collision_with_track(self):
        pass

    @abstractmethod
    def check_collision_with_checkpoint(self):
        pass

    @abstractmethod
    def get_inputs_for_network(self):
        pass

    @abstractmethod
    def check_collision_with_start(self):
        pass

    @abstractmethod
    def get_lap_time(self):
        pass
