import signal
import sys

import pygame
import math
from shapely.geometry import LineString
import neat
import os
from shapely.geometry import LineString
import time
import pickle

from pygame import Surface
from shapely.geometry.base import BaseGeometry

CHECKPOINT_DIR = 'checkpoints'

# Инициализация Pygame
pygame.init()

# трасса
TRACK_COLOR = (50, 50, 50)
TRACK = [[95, 114], [237, 64], [385, 48], [532, 86], [613, 100], [756, 85], [891, 75], [1081, 51], [1141, 144],
         [1134, 237], [1089, 315], [1035, 400], [967, 409], [871, 430], [819, 457], [869, 533], [938, 622], [918, 694],
         [722, 740], [556, 742], [450, 748], [421, 654], [331, 623], [215, 618], [172, 665], [97, 683], [57, 572],
         [79, 390], [63, 300], [47, 222], [96, 114]]
TRACK2 = [[298, 190], [408, 197], [486, 249], [570, 287], [692, 254], [849, 222], [920, 226], [924, 243], [892, 303],
          [808, 330], [737, 358], [714, 401], [667, 440], [669, 506], [689, 559], [746, 601], [635, 619], [565, 600],
          [497, 551], [473, 502], [389, 478], [284, 477], [229, 481], [179, 415], [202, 312], [201, 215]]

START_LINE = ([45, 456], [226, 456])

CHECKPOINTS = [([95, 83], [246, 231]), ([513, 64], [464, 272]), ([829, 83], [843, 243]), ([879, 278], [1027, 416]),
               ([919, 545], [688, 584]), ([603, 585], [544, 774])]

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
RED = (200, 0, 0)
TIMEOUT = 10

# Настройка окна
win = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Car Racing")

# Загрузка изображений
car_image = pygame.image.load("./assets/car.png")
car_image = pygame.transform.scale(car_image, (CAR_WIDTH, CAR_HEIGHT))

font = pygame.font.Font('freesansbold.ttf', 20)


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


def check_collision_by_line(car_rect, track_lines, already_crossed):
    for line in track_lines:
        line_start, line_end = line
        if car_rect.clipline(line_start, line_end) and (line_start, line_end) not in already_crossed:
            already_crossed.append((line_start, line_end))
            return True
    return False


def draw_line(car, angle: int):
    car_position = (car.x, car.y)
    line_end_pos = calculate_end_pos(car_position, -car.angle + angle, 500)
    pygame.draw.line(win, WHITE, car_position, line_end_pos, 1)
    m_line = LineString([car_position, line_end_pos])
    return m_line


def draw_intersaction(m_line, inters, y_text_pos):
    if not inters.is_empty:
        # Вычисляем расстояние до точки пересечения от начала основной линии
        distance = m_line.project(inters)
        d_text = font.render(f"{distance:.2f}", True, WHITE, BLACK)
        win.blit(d_text, (10, y_text_pos))
        pygame.draw.circle(win, WHITE, inters.coords[0], 5)


generation: int = 1


def eval_genomes(genomes, config):
    global generation
    for genome_id, genome in genomes:
        net = neat.nn.FeedForwardNetwork.create(genome, config)
        genome.fitness = run_game_with_network(net, generation, genome_id)
        print(f"Generation {generation}. Genome {genome_id} fitness: {genome.fitness:.2f}")
    save_checkpoint(p, generation)
    generation += 1
    print(f"Generation {generation} complete.")


max_fitness = 0
max_crossed_lines = 0


def run_game_with_network(network, generation_id, genome_id):
    # Создание машины
    crossed_lines = 0
    already_crossed = []

    car = Car(130, 500)
    fitness = 0
    clock = pygame.time.Clock()
    running = True
    start_time = time.time()

    while running:
        global max_fitness, max_crossed_lines
        max_fitness = max_fitness if max_fitness > fitness else fitness
        max_crossed_lines = max_crossed_lines if max_crossed_lines > crossed_lines else crossed_lines

        fitness -= 0.001
        clock.tick(FPS)
        win.fill(BLACK)

        # Проверка на тайм-аут
        elapsed_time = time.time() - start_time
        if elapsed_time > TIMEOUT:
            print(f"Timeout reached: {elapsed_time:.2f} seconds")
            break

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.MOUSEBUTTONDOWN:
                x, y = pygame.mouse.get_pos()
                print(x, y)

        # Получение входных данных для нейросети
        inputs = get_inputs_for_network(car)

        # Получение выходных данных от нейросети
        output = network.activate(inputs)

        # Используем выходы сети для управления автомобилем
        if output[0] > 0.5:
            car.angle -= 5 * (1 - GRIP * car.speed / car.mass)
        if output[1] > 0.5:
            car.angle += 5 * (1 - GRIP * car.speed / car.mass)
        if output[2] > 0.5:
            car.speed += FORCE / car.mass
        elif output[3] > 0.5:
            car.speed -= FORCE / car.mass
        else:
            if car.speed > 0:
                car.speed -= DECELERATION / car.mass
            elif car.speed < 0:
                car.speed += DECELERATION / car.mass

        # Обновление машины
        car.update()

        pygame.draw.lines(win, TRACK_COLOR, True, TRACK, 3)
        pygame.draw.lines(win, TRACK_COLOR, True, TRACK2, 3)

        for start_ch_line, end_ch_line in CHECKPOINTS:
            pygame.draw.line(win, RED, start_ch_line, end_ch_line, 3)
        pygame.draw.line(win, (255, 255, 255), START_LINE[0], START_LINE[1], 5)

        d_text = font.render(f"{fitness:.2f}", True, WHITE, BLACK)
        win.blit(d_text, (10, 10))

        d_text = font.render(f"Max CL: {max_crossed_lines}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 170))
        d_text = font.render(f"Max fitness: {max_fitness:.2f}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 130))
        d_text = font.render(f"Crossed lines: {crossed_lines}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 90))
        d_text = font.render(f"Generation: {generation_id}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 50))
        d_text = font.render(f"Genome: {genome_id}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 10))

        # Проверка столкновений
        car_rect = pygame.Rect(car.x - CAR_WIDTH // 2, car.y - CAR_HEIGHT // 2, CAR_WIDTH, CAR_HEIGHT)
        if check_collision(car_rect, TRACK) or check_collision(car_rect, TRACK2):
            print(f"Collision at position: ({car.x}, {car.y})")
            crossed_lines = 0
            fitness -= 100
            running = False
        if check_collision_by_line(car_rect, CHECKPOINTS, already_crossed):
            print(f"Reached checkpoints: ({car.x}, {car.y})")
            crossed_lines += 1
            fitness += 1000
        if check_collision_by_line(car_rect, [START_LINE],
                                   already_crossed) and crossed_lines > 0 and crossed_lines % len(CHECKPOINTS) == 0:
            print(f"Reached START LINE: ({car.x}, {car.y})")
            fitness += 5000

        car.draw(win)
        pygame.display.flip()
        # Увеличение фитнесс-функции за каждую пройденную дистанцию
        fitness += car.speed * 0.05

    return fitness


def get_inputs_for_network(car):
    # Пример: используем расстояния до ближайших препятствий как входы
    distances = []
    for angle in [0, 30, -30, 90, -90, 140, -140]:
        main_line = draw_line(car, angle)
        distance = float('inf')
        for line in [TRACK, TRACK2]:
            for i in range(len(line) - 1):
                checked_line = LineString([line[i], line[i + 1]])
                intersection = main_line.intersection(checked_line)
                if not intersection.is_empty:
                    distance = min(distance, main_line.project(intersection))
                    pygame.draw.circle(win, WHITE, intersection.coords[0], 5)
        distances.append(distance)

        distance = float('inf')
        for line in CHECKPOINTS:
            l_start, l_end = line
            checked_line = LineString([l_start, l_end])
            intersection = main_line.intersection(checked_line)
            if not intersection.is_empty:
                distance = min(distance, main_line.project(intersection))
                pygame.draw.circle(win, RED, intersection.coords[0], 5)

    return distances


def save_checkpoint(population, generation):
    filename = os.path.join(CHECKPOINT_DIR, f'neat-checkpoint-gen-{generation}.pkl')
    with open(filename, 'wb') as f:
        pickle.dump(population, f)
    print(f"Checkpoint saved to {filename}")


def load_checkpoint(filename):
    with open(filename, 'rb') as f:
        population = pickle.load(f)
    print(f"Checkpoint loaded from {filename}")
    return population


def signal_handler(sig, frame):
    print('Interrupt received, saving latest checkpoint...')
    save_checkpoint(p, str(generation))
    sys.exit(0)


if __name__ == "__main__":
    if not os.path.exists(CHECKPOINT_DIR):
        os.makedirs(CHECKPOINT_DIR)

    signal.signal(signal.SIGINT, signal_handler)

    config_path = os.path.join(os.path.dirname(__file__), "config-feedforward.txt")
    config = neat.config.Config(neat.DefaultGenome, neat.DefaultReproduction,
                                neat.DefaultSpeciesSet, neat.DefaultStagnation,
                                config_path)

    # Пытаемся загрузить последнюю контрольную точку
    latest_checkpoint = None
    if os.path.exists(CHECKPOINT_DIR):
        checkpoints = [f for f in os.listdir(CHECKPOINT_DIR) if f.endswith('.pkl')]
        if checkpoints:
            latest_checkpoint = max(checkpoints, key=lambda f: int(f.split('-')[3].split('.')[0]))
            generation = int(latest_checkpoint.split('-')[3].split('.')[0])

    p = load_checkpoint(os.path.join(CHECKPOINT_DIR, latest_checkpoint)) if latest_checkpoint else neat.Population(
        config)

    # Добавление репортеров
    p.add_reporter(neat.StdOutReporter(True))
    stats = neat.StatisticsReporter()
    p.add_reporter(stats)

    # Запуск обучения
    try:
        winner = p.run(eval_genomes, 1000)
    except Exception as e:
        print(f"An error occurred: {e}")
        save_checkpoint(p, 'error')
        raise
